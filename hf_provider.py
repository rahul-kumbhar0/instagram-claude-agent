"""Free open-source generation through Hugging Face Spaces (ZeroGPU).

Images: FLUX.1-schnell. Videos: Wan 2.2 image-to-video.
Each Space's API is read at runtime, so inputs are matched by name and type rather than
hard-coded positions. Spaces are tried in order until one succeeds.
"""
import os

HF_TOKEN = os.environ.get("HF_TOKEN", "")

def _spaces(var: str, default: str) -> list[str]:
    return [s.strip() for s in os.environ.get(var, default).split(",") if s.strip()]

IMAGE_SPACES = _spaces("HF_IMAGE_SPACES", "black-forest-labs/FLUX.1-schnell")
VIDEO_SPACES = _spaces(
    "HF_VIDEO_SPACES",
    "zerogpu-aoti/wan2-2-fp8da-aoti-faster,r3gm/wan2-2-fp8da-aoti-preview,Wan-AI/Wan-2.2-5B",
)
SIZES = {"9:16": (576, 1024), "16:9": (1024, 576), "1:1": (1024, 1024),
         "4:5": (832, 1024), "3:4": (768, 1024)}
VIDEO_EXTS = (".mp4", ".webm", ".mov", ".mkv")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def _client(space: str):
    from gradio_client import Client
    try:
        return Client(space, token=HF_TOKEN or None, verbose=False)
    except TypeError:
        return Client(space, hf_token=HF_TOKEN or None, verbose=False)


def _comp(p: dict) -> str:
    return str(p.get("component", "")).lower()


def _is_text(p: dict) -> bool:
    return _comp(p) in ("textbox", "text") or "prompt" in (p.get("parameter_name") or "").lower()


def _pick(endpoints: dict, want: str):
    best, best_score = None, -1
    for name, ep in endpoints.items():
        params, rets = ep.get("parameters", []), ep.get("returns", [])
        if not any(_is_text(p) for p in params):
            continue
        has_img = any(_comp(p) == "image" for p in params)
        if want == "video":
            if not any(_comp(r) == "video" for r in rets):
                continue
            score = 2 + (2 if has_img else 0)
        else:
            if not any(_comp(r) in ("image", "gallery") for r in rets):
                continue
            score = 2 - (1 if has_img else 0)
        if any(k in name.lower() for k in ("generate", "infer", "predict", "run")):
            score += 1
        if score > best_score:
            best, best_score = (name, ep), score
    return best


def _fill(ep: dict, prompt: str, image_path: str | None, size: tuple[int, int] | None) -> dict:
    from gradio_client import handle_file
    kw, prompt_set = {}, False
    for p in ep.get("parameters", []):
        n = p.get("parameter_name") or ""
        ln, c, has_default = n.lower(), _comp(p), p.get("parameter_has_default")
        if not n:
            continue
        if c == "image" or ("image" in ln and c in ("", "file", "uploadbutton")):
            if image_path:
                kw[n] = handle_file(image_path)
            elif not has_default:
                kw[n] = None
        elif "negative" in ln:
            if not has_default:
                kw[n] = ""
        elif "prompt" in ln or ln in ("text", "caption", "positive"):
            kw[n] = prompt
            prompt_set = True
        elif "randomize" in ln:
            kw[n] = True
        elif size and ln in ("width", "height"):
            kw[n] = size[0] if ln == "width" else size[1]
        elif not has_default:
            kw[n] = p.get("parameter_default")
    if not prompt_set:
        for p in ep.get("parameters", []):
            if _comp(p) in ("textbox", "text") and "negative" not in (p.get("parameter_name") or "").lower():
                kw[p["parameter_name"]] = prompt
                break
    return kw


def _find_file(res, exts):
    if isinstance(res, str):
        return res if os.path.isfile(res) and res.lower().endswith(exts) else None
    if isinstance(res, dict):
        for v in res.values():
            hit = _find_file(v, exts)
            if hit:
                return hit
    if isinstance(res, (list, tuple)):
        for v in res:
            hit = _find_file(v, exts)
            if hit:
                return hit
    return None


def run(want: str, prompt: str, image_path: str | None = None,
        aspect_ratio: str = "9:16") -> tuple[bytes, str, str]:
    """Generate with the first working Space. Returns (bytes, extension, space_id)."""
    spaces = VIDEO_SPACES if want == "video" else IMAGE_SPACES
    exts = VIDEO_EXTS if want == "video" else IMAGE_EXTS
    size = SIZES.get(aspect_ratio, SIZES["9:16"]) if want == "image" else None
    errors = []
    for space in spaces:
        try:
            client = _client(space)
            api = client.view_api(print_info=False, return_format="dict") or {}
            endpoints = api.get("named_endpoints") or {}
            picked = _pick(endpoints, want)
            if not picked:
                errors.append(f"{space}: no {want} endpoint among {list(endpoints)}")
                continue
            name, ep = picked
            if want == "video" and image_path is None and any(
                    _comp(p) == "image" and not p.get("parameter_has_default")
                    for p in ep.get("parameters", [])):
                errors.append(f"{space}: needs a first-frame image")
                continue
            res = client.predict(api_name=name, **_fill(ep, prompt, image_path, size))
            path = _find_file(res, exts)
            if not path:
                errors.append(f"{space}{name}: no {want} file in result {str(res)[:300]}")
                continue
            with open(path, "rb") as f:
                data = f.read()
            return data, os.path.splitext(path)[1].lstrip(".").lower(), space
        except Exception as e:  # noqa: BLE001
            errors.append(f"{space}: {type(e).__name__}: {str(e)[:400]}")
    raise RuntimeError(f"All Hugging Face {want} Spaces failed: " + " | ".join(errors))
