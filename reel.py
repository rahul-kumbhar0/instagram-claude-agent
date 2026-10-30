"""Join clips into one vertical reel with an optional title over the opening seconds."""
import subprocess, tempfile
from pathlib import Path

W, H, FPS = 720, 1280, 24


def _title_png(text: str, path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    size = 84
    while True:
        font = ImageFont.load_default(size=size)
        box = draw.textbbox((0, 0), text, font=font, stroke_width=6)
        if box[2] - box[0] <= W - 80 or size <= 36:
            break
        size -= 6
    x = 50
    y = int(H * 0.12)
    draw.text((x, y), text, font=font, fill=(255, 214, 10, 255), stroke_width=6, stroke_fill=(20, 20, 20, 255))
    img.save(path)


def join(paths: list[str], out_path: str, title: str | None = None, title_seconds: float = 2.5) -> None:
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    n = len(paths)
    args = [ff, "-y", "-loglevel", "error"]
    for p in paths:
        args += ["-i", p]
    chains = "".join(
        f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"setsar=1,fps={FPS},format=yuv420p[v{i}];" for i in range(n))
    graph = chains + "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[cat]"
    with tempfile.TemporaryDirectory() as tmp:
        last = "[cat]"
        if title:
            png = Path(tmp) / "title.png"
            _title_png(title, png)
            args += ["-loop", "1", "-i", str(png)]
            graph += f";[{n}:v]format=rgba[t];[cat][t]overlay=0:0:enable='lt(t,{title_seconds})':shortest=1[out]"
            last = "[out]"
        args += ["-filter_complex", graph, "-map", last, "-an", "-c:v", "libx264", "-preset", "veryfast",
                 "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path]
        r = subprocess.run(args, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {r.stderr[-1200:]}")
