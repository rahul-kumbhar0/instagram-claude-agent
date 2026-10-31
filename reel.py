"""Join clips into one vertical reel with an optional title over the opening seconds.

Clips are normalized one at a time with a fixed thread count and then stitched without
re-encoding, so peak memory stays low enough for a 512 MB instance.
"""
import subprocess, tempfile
from pathlib import Path

W, H, FPS = 720, 1280, 24
ENCODE = ["-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
          "-threads", "1", "-x264-params", "rc-lookahead=10", "-video_track_timescale", "12288"]


def _font(size: int):
    from PIL import ImageFont
    return ImageFont.load_default(size=size)


def _title_frames(title: str, subtitle: str | None, folder: Path, seconds: float) -> None:
    """Write one transparent PNG per frame: the title types in letter by letter, then holds,
    and the subtitle appears once the title is complete."""
    from PIL import Image, ImageDraw
    probe = ImageDraw.Draw(Image.new("RGBA", (W, H)))
    size = 80
    while size > 36 and probe.textbbox((0, 0), title, font=_font(size), stroke_width=3)[2] > W - 70:
        size -= 4
    font, sub_font = _font(size), _font(max(28, size // 2))
    x, y = 36, int(H * 0.11)
    type_frames = max(1, min(int(FPS * 1.2), len(title) * 2))
    cache: dict[tuple[int, bool], Image.Image] = {}
    for f in range(int(seconds * FPS)):
        n = min(len(title), 1 + f * len(title) // type_frames)
        show_sub = bool(subtitle) and n == len(title)
        key = (n, show_sub)
        if key not in cache:
            img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            text = title[:n]
            d.text((x + 4, y + 5), text, font=font, fill=(25, 20, 10, 200), stroke_width=3,
                   stroke_fill=(25, 20, 10, 200))
            d.text((x, y), text, font=font, fill=(255, 221, 0, 255), stroke_width=2,
                   stroke_fill=(255, 221, 0, 255))
            if show_sub:
                full = d.textbbox((x, y), title, font=font, stroke_width=2)
                sw = d.textlength(subtitle, font=sub_font)
                d.text(((full[0] + full[2] - sw) / 2, full[3] + 6), subtitle, font=sub_font,
                       fill=(255, 255, 255, 255), stroke_width=2, stroke_fill=(20, 20, 20, 255))
            cache[key] = img
        cache[key].save(folder / f"t{f:04d}.png")


def _run(args: list[str]) -> None:
    r = subprocess.run(args, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr[-1200:]}")


def join(paths: list[str], out_path: str, title: str | None = None, title_seconds: float = 3.5,
         subtitle: str | None = None) -> None:
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
                frames = Path(tmp) / "title"
                frames.mkdir()
                _title_frames(title, subtitle, frames, title_seconds)
                args += ["-framerate", str(FPS), "-i", str(frames / "t%04d.png"), "-filter_complex",
                         f"[0:v]{norm}[v];[1:v]format=rgba[t];"
                         f"[v][t]overlay=0:0:eof_action=pass[out]",
                         "-map", "[out]"]
            else:
                args += ["-vf", norm]
            _run(args + ["-filter_threads", "1"] + ENCODE + [seg])
            segments.append(seg)
        listing = Path(tmp) / "list.txt"
        listing.write_text("".join(f"file '{s}'\n" for s in segments))
        _run([ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
              "-c", "copy", "-movflags", "+faststart", out_path])
