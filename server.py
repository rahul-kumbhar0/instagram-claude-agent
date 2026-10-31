"""FlowCast MCP: image and video generation as an MCP server for Claude.

PROVIDER=gemini uses Google's Flow models (Gemini Omni video + Nano Banana images).
PROVIDER=hf uses free open-source models on Hugging Face Spaces (Wan 2.2 video + FLUX images).

Tools: create_video, generate_image, start_video, get_video, join_videos, list_files, extend_video.
Generated files are saved on this server and served at /files/<id>.<ext>.
The MCP endpoint is /mcp/<MCP_SECRET>; keep that URL private.
"""
import base64, json, os, secrets, threading, time, uuid, mimetypes
from pathlib import Path

import httpx
import hf_provider
import reel
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

API_KEY = os.environ.get("GEMINI_API_KEY", "")
SECRET = os.environ.get("MCP_SECRET") or secrets.token_urlsafe(24)
PUBLIC_URL = os.environ.get("PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:8000")
VIDEO_MODEL = os.environ.get("VIDEO_MODEL", "gemini-omni-1.1-flash")
IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "gemini-nano-banana-2.1")
PROVIDER = os.environ.get("PROVIDER", "gemini").lower()
BASE = "https://generativelanguage.googleapis.com/v1beta"
DATA = Path(os.environ.get("DATA_DIR", "./data")); DATA.mkdir(parents=True, exist_ok=True)
JOBS: dict[str, dict] = {}
META_FILE = DATA / "meta.json"
META: dict[str, dict] = json.loads(META_FILE.read_text()) if META_FILE.exists() else {}
LOCK = threading.Lock()

mcp = FastMCP(
    "flowcast",
    instructions=(
        "Generate images (Nano Banana) and videos (Gemini Omni, the model behind Google Flow). "
        "Workflow: optionally generate_image to build a first frame from a product photo, then start_video "
        "with image_file_id, then poll get_video every ~20s until status is 'done'. Default aspect is 9:16."
    ),
    host="0.0.0.0",
    port=int(os.environ.get("PORT", 8000)),
    streamable_http_path=f"/mcp/{SECRET}",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

# ---------------- helpers ----------------
def _headers():
    if not API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set on the server.")
    return {"x-goog-api-key": API_KEY, "Content-Type": "application/json"}

def _save(data: bytes, ext: str, kind: str, prompt: str) -> dict:
    fid = uuid.uuid4().hex[:16]
    name = f"{fid}.{ext}"
    (DATA / name).write_bytes(data)
    info = {"file_id": fid, "kind": kind, "filename": name, "url": f"{PUBLIC_URL}/files/{name}",
            "prompt": prompt[:300], "bytes": len(data), "created": int(time.time())}
    with LOCK:
        META[fid] = info
        META_FILE.write_text(json.dumps(META))
    return info

def _image_part(image_url: str | None, image_file_id: str | None) -> dict | None:
    if image_file_id:
        info = META.get(image_file_id)
        if not info:
            raise ValueError(f"Unknown file_id {image_file_id}")
        raw = (DATA / info["filename"]).read_bytes()
        mime = mimetypes.guess_type(info["filename"])[0] or "image/png"
    elif image_url:
        r = httpx.get(image_url, follow_redirects=True, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        raw = r.content
        mime = r.headers.get("content-type", "image/jpeg").split(";")[0]
        if not mime.startswith("image/"):
            mime = "image/jpeg"
    else:
        return None
    return {"type": "image", "data": base64.b64encode(raw).decode(), "mime_type": mime}

def _local_image(image_url: str | None, image_file_id: str | None) -> str | None:
    if image_file_id:
        info = META.get(image_file_id)
        if not info:
            raise ValueError(f"Unknown file_id {image_file_id}")
        return str(DATA / info["filename"])
    if image_url:
        r = httpx.get(image_url, follow_redirects=True, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        ext = (mimetypes.guess_extension(r.headers.get("content-type", "").split(";")[0]) or ".jpg")
        path = DATA / f"in-{uuid.uuid4().hex[:12]}{ext}"
        path.write_bytes(r.content)
        return str(path)
    return None

def _pad_to(path: str, aspect_ratio: str) -> str:
    """Center the photo on a canvas of the target aspect, filled with a blurred copy of itself."""
    from PIL import Image, ImageFilter
    w, h = hf_provider.SIZES.get(aspect_ratio, hf_provider.SIZES["9:16"])
    img = Image.open(path).convert("RGB")
    bg = img.resize((w, h)).filter(ImageFilter.GaussianBlur(40))
    fit = img.copy()
    fit.thumbnail((w, h))
    bg.paste(fit, ((w - fit.width) // 2, (h - fit.height) // 2))
    out = DATA / f"in-{uuid.uuid4().hex[:12]}.png"
    bg.save(out)
    return str(out)

def _find_media(obj, kind: str):
    """Walk an Interactions API response and return the first {'type': kind, data|uri} content item."""
    if isinstance(obj, dict):
        if obj.get("type") == kind and ("data" in obj or "uri" in obj):
            return obj
        for v in obj.values():
            hit = _find_media(v, kind)
            if hit:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = _find_media(v, kind)
            if hit:
                return hit
    return None

def _interact(body: dict, timeout: float) -> dict:
    r = httpx.post(f"{BASE}/interactions", headers=_headers(), json=body, timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError(f"Gemini API error {r.status_code}: {r.text[:800]}")
    return r.json()

def _download_uri(uri: str) -> bytes:
    file_id = uri.rstrip("/").split("/")[-1].split(":")[0]
    for _ in range(180):  # up to ~15 min
        info = httpx.get(f"{BASE}/files/{file_id}", headers=_headers(), timeout=60).json()
        state = (info.get("state") or "").upper()
        if state == "ACTIVE":
            break
        if state == "FAILED":
            raise RuntimeError(f"Video processing failed: {json.dumps(info)[:500]}")
        time.sleep(5)
    r = httpx.get(f"{BASE}/files/{file_id}:download", params={"alt": "media"}, headers=_headers(),
                  timeout=300, follow_redirects=True)
    r.raise_for_status()
    return r.content

def _media_bytes(item: dict) -> bytes:
    if item.get("data"):
        return base64.b64decode(item["data"])
    return _download_uri(item["uri"])

# ---------------- tools ----------------
@mcp.tool()
def generate_image(prompt: str, reference_image_urls: list[str] | None = None,
                   reference_file_ids: list[str] | None = None, aspect_ratio: str = "9:16") -> dict:
    """Create or edit an image with Nano Banana. Pass product photos as reference_image_urls (public URLs)
    or reference_file_ids (files on this server) to keep the exact product design.
    aspect_ratio: '9:16', '16:9', '1:1', '4:5', '3:4'. Returns file_id and public url.
    With the free Hugging Face provider, a reference photo is edited with FLUX.1 Kontext (the first
    reference is used; the product stays the same while the scene changes); without one, FLUX.1-schnell
    draws the image from the prompt."""
    if PROVIDER == "hf":
        ref = (reference_file_ids or [None])[0]
        ref_url = None if ref else (reference_image_urls or [None])[0]
        if ref or ref_url:
            src = _local_image(ref_url, ref)
            data, ext, space = hf_provider.run("edit", prompt, image_path=_pad_to(src, aspect_ratio))
        else:
            data, ext, space = hf_provider.run("image", prompt, aspect_ratio=aspect_ratio)
        info = _save(data, ext, "image", prompt)
        info["model"] = space
        return info
    parts = [{"type": "text", "text": prompt}]
    for u in reference_image_urls or []:
        parts.append(_image_part(u, None))
    for f in reference_file_ids or []:
        parts.append(_image_part(None, f))
    resp = _interact({"model": IMAGE_MODEL, "input": parts,
                      "response_format": {"type": "image", "aspect_ratio": aspect_ratio}}, timeout=240)
    item = _find_media(resp, "image")
    if not item:
        raise RuntimeError(f"No image in response: {json.dumps(resp)[:800]}")
    mime = item.get("mime_type", "image/png")
    return _save(_media_bytes(item), "jpg" if "jpeg" in mime else "png", "image", prompt)

def _run_video(job_id: str, body: dict, prompt: str):
    try:
        resp = _interact(body, timeout=900)
        item = _find_media(resp, "video")
        if not item:
            raise RuntimeError(f"No video in response: {json.dumps(resp)[:800]}")
        info = _save(_media_bytes(item), "mp4", "video", prompt)
        info["interaction_id"] = resp.get("id")
        JOBS[job_id].update(status="done", result=info, finished=int(time.time()))
    except Exception as e:  # noqa: BLE001
        JOBS[job_id].update(status="error", error=str(e)[:1500], finished=int(time.time()))

def _run_fn(job_id: str, fn):
    try:
        JOBS[job_id].update(status="done", result=fn(), finished=int(time.time()))
    except Exception as e:  # noqa: BLE001
        JOBS[job_id].update(status="error", error=str(e)[:1500], finished=int(time.time()))

def _start_fn(fn, prompt: str) -> dict:
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"job_id": job_id, "status": "running", "started": int(time.time()), "prompt": prompt[:300]}
    threading.Thread(target=_run_fn, args=(job_id, fn), daemon=True).start()
    return {"job_id": job_id, "status": "running", "next": "Call get_video(job_id) every ~20 seconds."}

def _hf_video(prompt: str, image_url: str | None, image_file_id: str | None, aspect_ratio: str) -> dict:
    path = _local_image(image_url, image_file_id)
    first_frame = None
    if not path:
        first_frame = generate_image(prompt, aspect_ratio=aspect_ratio)
        path = str(DATA / first_frame["filename"])
    data, ext, space = hf_provider.run("video", prompt, image_path=path)
    info = _save(data, ext or "mp4", "video", prompt)
    info["model"] = space
    if first_frame:
        info["first_frame"] = first_frame
    return info

def _start(body: dict, prompt: str) -> dict:
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"job_id": job_id, "status": "running", "started": int(time.time()), "prompt": prompt[:300]}
    threading.Thread(target=_run_video, args=(job_id, body, prompt), daemon=True).start()
    return {"job_id": job_id, "status": "running", "next": "Call get_video(job_id) every ~20 seconds."}

@mcp.tool()
def start_video(prompt: str, image_url: str | None = None, image_file_id: str | None = None,
                aspect_ratio: str = "9:16", resolution: str = "720p") -> dict:
    """Start generating a video clip (Gemini Omni Flash, the model behind Google Flow).
    Text-to-video by default; pass image_url or image_file_id to animate a first frame (image-to-video).
    aspect_ratio: '9:16' or '16:9'. resolution: '360p', '720p', '1080p', '4k'.
    Returns a job_id. Poll get_video(job_id) until status is 'done'.
    With the free Hugging Face provider (Wan 2.2), a first frame is generated automatically when no image
    is given, and aspect ratio follows the image."""
    if PROVIDER == "hf":
        return _start_fn(lambda: _hf_video(prompt, image_url, image_file_id, aspect_ratio), prompt)
    content = [{"type": "text", "text": prompt}]
    img = _image_part(image_url, image_file_id)
    body = {"model": VIDEO_MODEL, "input": ([img] + content) if img else prompt,
            "response_format": {"type": "video", "aspect_ratio": aspect_ratio,
                                "resolution": resolution, "delivery": "uri"}}
    if img:
        body["generation_config"] = {"video_config": {"task": "image_to_video"}}
    return _start(body, prompt)

@mcp.tool()
def create_video(prompt: str, image_prompt: str | None = None,
                 reference_image_urls: list[str] | None = None,
                 reference_file_ids: list[str] | None = None,
                 aspect_ratio: str = "9:16", resolution: str = "720p",
                 wait_s: int = 420) -> dict:
    """Create a finished video in one call. Optionally pass image_prompt (plus product photos as
    reference_image_urls or reference_file_ids) to first build the opening frame with Nano Banana,
    which is then animated; otherwise the video is generated straight from prompt (text-to-video).
    Waits up to wait_s seconds for the result. If still rendering when time runs out, returns the
    job_id with status 'running' — finish with get_video(job_id). On success result.url is the MP4."""
    first_frame = None
    if image_prompt or ((reference_image_urls or reference_file_ids) and PROVIDER != "hf"):
        first_frame = generate_image(image_prompt or prompt, reference_image_urls,
                                     reference_file_ids, aspect_ratio)
    frame_id = first_frame["file_id"] if first_frame else None
    frame_url = None
    if not first_frame and PROVIDER == "hf":
        frame_id = (reference_file_ids or [None])[0]
        frame_url = None if frame_id else (reference_image_urls or [None])[0]
    job = start_video(prompt, image_url=frame_url, image_file_id=frame_id,
                      aspect_ratio=aspect_ratio, resolution=resolution)
    deadline = time.time() + max(30, min(wait_s, 840))
    while time.time() < deadline:
        state = JOBS.get(job["job_id"], {})
        if state.get("status") in ("done", "error"):
            out = dict(state)
            if first_frame:
                out["first_frame"] = first_frame
            return out
        time.sleep(5)
    out = {"job_id": job["job_id"], "status": "running",
           "next": "Still rendering. Call get_video(job_id) every ~20 seconds."}
    if first_frame:
        out["first_frame"] = first_frame
    return out

@mcp.tool()
def extend_video(previous_file_id: str, prompt: str) -> dict:
    """Continue a previously generated video (3–10 s more) with a new prompt. Returns a job_id."""
    if PROVIDER == "hf":
        raise ValueError("extend_video is only available with PROVIDER=gemini.")
    info = META.get(previous_file_id)
    if not info or not info.get("interaction_id"):
        raise ValueError("previous_file_id must be a video made by start_video on this server.")
    body = {"model": VIDEO_MODEL, "input": prompt, "previous_interaction_id": info["interaction_id"],
            "response_format": {"type": "video", "delivery": "uri"}}
    return _start(body, prompt)

@mcp.tool()
def get_video(job_id: str) -> dict:
    """Check a video job. status is 'running', 'done' (result.url is the MP4) or 'error'."""
    job = JOBS.get(job_id)
    if not job:
        return {"job_id": job_id, "status": "unknown", "hint": "Server may have restarted; start again."}
    out = dict(job)
    if job["status"] == "running":
        out["elapsed_s"] = int(time.time()) - job["started"]
    return out

@mcp.tool()
def list_files(kind: str | None = None) -> list[dict]:
    """List images/videos stored on this server, newest first. kind: 'image', 'video' or None for all."""
    items = [m for m in META.values() if not kind or m["kind"] == kind]
    return sorted(items, key=lambda m: m["created"], reverse=True)[:100]

@mcp.tool()
def join_videos(file_ids: list[str], title: str | None = None, subtitle: str | None = None) -> dict:
    """Join video clips (file_ids, in order) into one 9:16 reel at 720x1280. An optional title types
    in letter by letter in bold yellow over the opening seconds, with an optional small white subtitle
    under it (e.g. 'for you'). Returns the reel's file_id and url."""
    if len(file_ids) < 2:
        raise ValueError("Pass at least two video file_ids.")
    key = f"{','.join(file_ids)}|{title or ''}|{subtitle or ''}"
    with REEL_LOCK:
        cached = META.get(REELS.get(key, ""))
        if cached and (DATA / cached["filename"]).exists():
            return cached
        info = _join_videos(file_ids, title, subtitle)
        REELS[key] = info["file_id"]
        return info

REEL_LOCK = threading.Lock()
REELS: dict[str, str] = {}

def _join_videos(file_ids: list[str], title: str | None, subtitle: str | None = None) -> dict:
    paths = []
    for fid in file_ids:
        info = META.get(fid)
        if not info or info.get("kind") != "video":
            raise ValueError(f"{fid} is not a video on this server.")
        paths.append(str(DATA / info["filename"]))
    out = DATA / f"tmp-reel-{uuid.uuid4().hex[:12]}.mp4"
    try:
        reel.join(paths, str(out), title, subtitle=subtitle)
        info = _save(out.read_bytes(), "mp4", "video", f"reel ({title or 'untitled'}): {', '.join(file_ids)}")
    finally:
        out.unlink(missing_ok=True)
    info["clips"] = file_ids
    with LOCK:
        META[info["file_id"]]["clips"] = file_ids
    return info

# ---------------- plain HTTP routes ----------------
@mcp.custom_route("/", methods=["GET"])
async def health(_: Request):
    return PlainTextResponse("flowcast-mcp ok")

@mcp.custom_route("/files/{name}", methods=["GET"])
async def files(request: Request):
    name = Path(request.path_params["name"]).name
    p = DATA / name
    if not p.exists() or name == "meta.json":
        return PlainTextResponse("not found", status_code=404)
    return FileResponse(p)

@mcp.custom_route(f"/reel/{SECRET}", methods=["GET"])
async def reel_route(request: Request):
    ids = [i.strip() for i in request.query_params.get("ids", "").split(",") if i.strip()]
    try:
        info = await run_in_threadpool(join_videos, ids, request.query_params.get("title"),
                                       request.query_params.get("subtitle"))
    except Exception as e:  # noqa: BLE001
        return PlainTextResponse(f"Could not build reel: {e}", status_code=400)
    return RedirectResponse(info["url"], status_code=302)

def _carry_over_files():
    """On Render, the previous instance keeps serving until this one opens its port, and each
    instance has its own temporary disk. Copy the previous instance's files before starting."""
    if not PUBLIC_URL.startswith("https://"):
        return
    try:
        r = httpx.post(f"{PUBLIC_URL}/mcp/{SECRET}", timeout=15,
                       headers={"Accept": "application/json, text/event-stream"},
                       json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                             "params": {"name": "list_files", "arguments": {}}})
        result = r.json().get("result", {})
        items = (result.get("structuredContent") or {}).get("result")
        if items is None:
            items = []
            for c in result.get("content", []):
                v = json.loads(c.get("text", "null"))
                items.extend(v if isinstance(v, list) else [v])
    except Exception as e:  # noqa: BLE001
        print(f"No previous instance to copy files from ({type(e).__name__}).")
        return
    copied = 0
    for info in items:
        if not isinstance(info, dict) or not info.get("file_id") or not info.get("filename"):
            continue
        name = Path(info["filename"]).name
        if not (DATA / name).exists():
            try:
                f = httpx.get(f"{PUBLIC_URL}/files/{name}", timeout=60)
                f.raise_for_status()
                (DATA / name).write_bytes(f.content)
                copied += 1
            except Exception:  # noqa: BLE001
                continue
        META[info["file_id"]] = info
    META_FILE.write_text(json.dumps(META))
    print(f"Copied {copied} files from the previous instance ({len(items)} listed).")

UPLOAD_PAGE = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>FlowCast upload</title><body style="font-family:system-ui;max-width:520px;margin:40px auto;padding:0 16px">
<h2>Upload product photos</h2><form method=post enctype=multipart/form-data>
<input type=file name=file multiple accept="image/*"><br><br><button>Upload</button></form>
<p>After uploading, tell Claude the file IDs shown (or say "use my latest uploads").</p></body>"""

@mcp.custom_route(f"/upload/{SECRET}", methods=["GET", "POST"])
async def upload(request: Request):
    if request.method == "GET":
        return HTMLResponse(UPLOAD_PAGE)
    form = await request.form()
    saved = []
    for f in form.getlist("file"):
        raw = await f.read()
        ext = (Path(f.filename).suffix.lstrip(".") or "jpg").lower()
        saved.append(_save(raw, ext, "image", f"upload: {f.filename}"))
    return JSONResponse(saved)

if __name__ == "__main__":
    _carry_over_files()
    print(f"MCP endpoint:  {PUBLIC_URL}/mcp/{SECRET}")
    print(f"Upload page:   {PUBLIC_URL}/upload/{SECRET}")
    mcp.run(transport="streamable-http")
