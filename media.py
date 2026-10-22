"""
media.py: tell images, videos and audio apart, find ffmpeg, and read container metadata.

ffmpeg comes from the system (PATH) or from the imageio-ffmpeg pip package, which bundles it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".3gp", ".gif"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".amr", ".wma"}

# Names of AI video / voice tools that may appear in metadata tags or Content Credentials.
AI_TOOLS = ["sora", "veo", "runway", "gen-3", "gen-4", "pika", "kling", "luma", "dream machine", "hailuo", "minimax",
            "synthesia", "heygen", "d-id", "deepfacelab", "faceswap", "facefusion", "roop", "deep-live-cam",
            "sadtalker", "wav2lip", "liveportrait", "elevenlabs", "resemble", "play.ht", "murf", "speechify",
            "tortoise", "bark", "xtts", "coqui", "rvc", "so-vits", "openai tts", "midjourney", "stable video",
            "animatediff", "invideo", "pictory", "vidu", "seedance", "wan2", "hunyuan"]


def kind_of(data: bytes, filename: str = "") -> str:
    """'image' | 'video' | 'audio' | 'unknown', from the file's first bytes, then its extension."""
    head = data[:64]
    if head[:3] == b"\xff\xd8\xff" or head[:8] == b"\x89PNG\r\n\x1a\n" or head[:2] == b"BM" \
            or head[:4] in (b"II*\x00", b"MM\x00*") or (head[:4] == b"RIFF" and head[8:12] == b"WEBP"):
        return "image"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "video"  # animated GIFs are short videos; a still GIF still works as one frame
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio"
    if head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        return "video"
    if head[:3] == b"ID3" or head[:4] in (b"OggS", b"fLaC") or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2") \
            or head[:6] == b"#!AMR\n":
        return "audio"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "video"  # webm / mkv
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"M4A ", b"M4B ", b"M4P "):
            return "audio"
        if brand in (b"heic", b"heix", b"mif1", b"avif"):
            return "image"
        return "video"
    ext = Path(filename).suffix.lower()
    return "image" if ext in IMAGE_EXT else "video" if ext in VIDEO_EXT else "audio" if ext in AUDIO_EXT else "unknown"


def ffmpeg_path() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def probe(path: str) -> dict:
    """Container facts and metadata tags, parsed from `ffmpeg -i` (no ffprobe needed)."""
    exe = ffmpeg_path()
    if not exe:
        return {"available": False}
    try:
        out = subprocess.run([exe, "-hide_banner", "-i", path], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=30).stderr
    except Exception as e:
        return {"available": False, "error": str(e)}
    info: dict = {"available": True, "tags": {}, "streams": []}
    m = re.search(r"Input #0, ([^,]+(?:,[^,]+)*?), from", out)
    info["container"] = m.group(1) if m else ""
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    if m:
        info["duration"] = round(int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)), 2)
    m = re.search(r"bitrate: (\d+) kb/s", out)
    if m:
        info["bitrate_kbps"] = int(m.group(1))
    for line in out.splitlines():
        s = line.strip()
        mt = re.match(r"([A-Za-z0-9_.:\-]+)\s*:\s(.+)$", s)
        if mt and line.startswith("    ") and not s.startswith(("Stream", "Duration", "Metadata", "Input", "Side data")):
            key, val = mt.group(1).strip(), mt.group(2).strip()
            if key not in info["tags"] and len(info["tags"]) < 40:
                info["tags"][key] = val[:200]
        ms = re.match(r"Stream #\d+:\d+.*?: (Video|Audio): (.+)$", s)
        if ms:
            kind, desc = ms.group(1).lower(), ms.group(2)
            st = {"type": kind, "codec": desc.split(",")[0].split(" ")[0], "description": desc[:160]}
            hz = re.search(r"(\d+) Hz", desc)
            if hz:
                st["sample_rate"] = int(hz.group(1))
            ch = re.search(r"Hz, (mono|stereo|[\d.]+ channels|5\.1|7\.1)", desc)
            if ch:
                st["channels"] = ch.group(1)
            fps = re.search(r"([\d.]+) fps", desc)
            if fps:
                st["fps"] = float(fps.group(1))
            size = re.search(r"(\d{2,5})x(\d{2,5})", desc)
            if size and kind == "video":
                st["width"], st["height"] = int(size.group(1)), int(size.group(2))
            info["streams"].append(st)
    return info


def ai_tool_mentions(*texts: str) -> list[str]:
    blob = " ".join(t.lower() for t in texts if t)
    found = []
    for name in AI_TOOLS:
        if re.search(r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])", blob) and name not in found:
            found.append(name)
    return found


def temp_copy(data: bytes, filename: str, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix.lower()
    p = folder / ("input" + (ext if re.fullmatch(r"\.[a-z0-9]{1,5}", ext or "") else ".bin"))
    p.write_bytes(data)
    return p


def safe_remove(path: Path) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
