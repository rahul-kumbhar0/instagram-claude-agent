"""Join clips into one vertical reel with an optional title over the opening seconds.

Clips are normalized one at a time with a fixed thread count and then stitched without
re-encoding, so peak memory stays low enough for a 512 MB instance.
"""
import subprocess, tempfile
from pathlib import Path

W, H, FPS = 720, 1280, 24
ENCODE = ["-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
          "-threads", "1", "-x264-params", "rc-lookahead=10", "-video_track_timescale", "12288"]


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
    draw.text((50, int(H * 0.12)), text, font=font, fill=(255, 214, 10, 255),
              stroke_width=6, stroke_fill=(20, 20, 20, 255))
    img.save(path)


def _run(args: list[str]) -> None:
    r = subprocess.run(args, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr[-1200:]}")


def join(paths: list[str], out_path: str, title: str | None = None, title_seconds: float = 2.5) -> None:
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    norm = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"setsar=1,fps={FPS},format=yuv420p")
    with tempfile.TemporaryDirectory() as tmp:
        segments = []
        for i, src in enumerate(paths):
            seg = str(Path(tmp) / f"seg{i}.mp4")
            args = [ff, "-y", "-loglevel", "error", "-threads", "1", "-i", src]
            if i == 0 and title:
                png = Path(tmp) / "title.png"
                _title_png(title, png)
                args += ["-loop", "1", "-i", str(png), "-filter_complex",
                         f"[0:v]{norm}[v];[1:v]format=rgba[t];"
                         f"[v][t]overlay=0:0:enable='lt(t,{title_seconds})':shortest=1[out]",
                         "-map", "[out]"]
            else:
                args += ["-vf", norm]
            _run(args + ["-filter_threads", "1"] + ENCODE + [seg])
            segments.append(seg)
        listing = Path(tmp) / "list.txt"
        listing.write_text("".join(f"file '{s}'\n" for s in segments))
        _run([ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
              "-c", "copy", "-movflags", "+faststart", out_path])
