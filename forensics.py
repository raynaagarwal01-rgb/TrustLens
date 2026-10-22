"""
forensics.py — classical image forensics for TrustLens (Track 1). Pillow + numpy only.

    from forensics import analyse_image
    result = analyse_image(open("photo.jpg", "rb").read(), "photo.jpg")

Checks:
  integrity   SHA-256 / MD5 hash, size, format, dimensions, analysis time (chain of custody)
  metadata    EXIF camera + editing software + edit dates, PNG text chunks (AI generator
              settings), XMP (IPTC "trainedAlgorithmicMedia" AI marker), C2PA content credentials
  jpeg        estimated JPEG quality from quantization tables
  ela         Error Level Analysis, normalised by local texture so edges don't dominate,
              with the most anomalous region located
  noise       sensor-noise consistency map; pasted or generated regions often have different noise
  agreement   whether ELA and noise point at the same region (much stronger evidence)

Every check returns plain-language "signals" with a severity, used by evidence_analyser.py.
Forensics can show evidence of editing; it can never prove an image is authentic.
"""

import datetime as dt
import hashlib
import io
import re

import numpy as np
from PIL import ExifTags, Image, ImageDraw, ImageOps

Image.MAX_IMAGE_PIXELS = 80_000_000  # refuse decompression bombs above ~80 MP

# Region thresholds on smoothed robust z-scores (tuned on CASIA v2 forgeries vs authentic camera photos)
ELA_THRESHOLD = 2.5
NOISE_THRESHOLD = 2.5

AI_MARKERS = re.compile(
    r"stable[ _-]?diffusion|sdxl|comfyui|automatic1111|invokeai|midjourney|dall[\s·\-]?e|openai|"
    r"firefly|imagen|gemini|novelai|leonardo\.ai|ideogram|flux\.1|runway|"
    r"trainedalgorithmicmedia|compositewithtrainedalgorithmicmedia|made with ai|ai[ -]generated", re.I)
EDITOR_MARKERS = re.compile(
    r"photoshop|gimp|canva|lightroom|snapseed|picsart|pixlr|affinity|paint\.net|photopea|"
    r"facetune|faceapp|meitu|remini|picmonkey|fotor|befunky", re.I)

# libjpeg standard luminance table (quality 50), used to estimate JPEG quality
STD_LUMA = np.array([
    16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69, 56,
    14, 17, 22, 29, 51, 87, 80, 62, 18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92,
    49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99], dtype=float)


def _signal(check, severity, detail, points_to="none"):
    """severity: info | low | medium | high.  points_to: ai | edited | none"""
    return {"check": check, "severity": severity, "detail": detail, "points_to": points_to}

# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------

def integrity(data: bytes, filename: str, img: Image.Image) -> dict:
    return {
        "filename": filename,
        "sha256": hashlib.sha256(data).hexdigest(),
        "md5": hashlib.md5(data).hexdigest(),
        "size_bytes": len(data),
        "format": img.format or "unknown",
        "width": img.width,
        "height": img.height,
        "mode": img.mode,
        "analysed_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }

# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

def _exif(img: Image.Image) -> dict:
    out = {}
    try:
        exif = img.getexif()
    except Exception:
        return out
    for tag, val in exif.items():
        out[ExifTags.TAGS.get(tag, str(tag))] = val
    try:
        for tag, val in exif.get_ifd(0x8769).items():  # Exif sub-IFD: DateTimeOriginal etc.
            out[ExifTags.TAGS.get(tag, str(tag))] = val
    except Exception:
        pass
    clean = {}
    for k, v in out.items():
        if isinstance(v, bytes):
            continue
        s = str(v).strip("\x00 ").strip()
        if s and len(s) < 300:
            clean[k] = s
    return clean


def _xmp(data: bytes) -> str:
    start = data.find(b"<x:xmpmeta")
    if start < 0:
        return ""
    end = data.find(b"</x:xmpmeta>", start)
    return data[start:end + 12 if end > 0 else start + 20000].decode("utf-8", "replace")


def _exif_time(s: str):
    try:
        return dt.datetime.strptime(s[:19], "%Y:%m:%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def metadata(data: bytes, img: Image.Image) -> tuple[dict, list[dict]]:
    exif = _exif(img)
    text_chunks = {k: str(v)[:2000] for k, v in (img.info or {}).items()
                   if isinstance(v, (str, bytes)) and k not in ("icc_profile", "exif", "xmp")}
    text_chunks = {k: (v.decode("utf-8", "replace") if isinstance(v, bytes) else v) for k, v in text_chunks.items()}
    xmp = _xmp(data)
    c2pa = b"c2pa" in data or b"jumb" in data[:200000]
    signals = []

    # AI generator traces anywhere in the metadata
    haystack = " ".join([" ".join(f"{k}={v}" for k, v in exif.items()),
                         " ".join(f"{k}={v}" for k, v in text_chunks.items()), xmp])
    sd_params = any(k.lower() in ("parameters", "prompt", "workflow", "negative_prompt") for k in text_chunks) \
        and re.search(r"steps|sampler|seed|cfg|ksampler|negative", haystack, re.I)
    ai = AI_MARKERS.search(haystack)
    if sd_params or ai:
        what = "image-generator settings (prompt / sampler / seed)" if sd_params else f"'{ai.group(0)}'"
        signals.append(_signal("AI generator trace in metadata", "high",
                               f"The file's metadata contains {what}, which AI image generators write.", "ai"))
    if c2pa:
        signals.append(_signal("Content Credentials (C2PA) present", "info",
                               "The file carries a provenance manifest. TrustLens detects it but cannot verify "
                               "its signature; check it at contentcredentials.org/verify.", "none"))

    software = exif.get("Software", "") + " " + exif.get("ProcessingSoftware", "")
    creator = re.search(r'CreatorTool(?:="|>)([^"<]+)', xmp)
    editor = EDITOR_MARKERS.search(software + " " + (creator.group(1) if creator else "") + " " +
                                   " ".join(text_chunks.values()))
    if editor:
        signals.append(_signal("Editing software recorded", "medium",
                               f"Saved with {editor.group(0)}. Editing isn't proof of deception, "
                               "but the image is not straight from a camera.", "edited"))
    if re.search(r"xmpMM:History|stEvt:action", xmp) and "saved" in xmp.lower():
        signals.append(_signal("Edit history in XMP", "medium",
                               "XMP metadata records save/edit actions.", "edited"))

    taken, modified = _exif_time(exif.get("DateTimeOriginal", "")), _exif_time(exif.get("DateTime", ""))
    if taken and modified and abs((modified - taken).total_seconds()) > 120:
        signals.append(_signal("Modified after capture", "medium",
                               f"Taken {taken:%d %b %Y %H:%M}, last modified {modified:%d %b %Y %H:%M}.", "edited"))

    if exif.get("Make") or exif.get("Model"):
        signals.append(_signal("Camera metadata present", "info",
                               f"Camera: {exif.get('Make', '')} {exif.get('Model', '')}".strip()
                               + (f", taken {taken:%d %b %Y %H:%M}" if taken else "") + ".", "none"))
    elif not sd_params and not ai:
        signals.append(_signal("No camera metadata", "info",
                               "Normal for screenshots and images sent through WhatsApp or social media, "
                               "which strip metadata. Origin can't be confirmed from metadata.", "none"))

    meta = {"exif": exif, "text_chunks": {k: v[:300] for k, v in text_chunks.items()},
            "xmp_present": bool(xmp), "c2pa_present": c2pa}
    return meta, signals

# ---------------------------------------------------------------------------
# JPEG quality
# ---------------------------------------------------------------------------

def jpeg_quality(img: Image.Image) -> int | None:
    q = getattr(img, "quantization", None)
    if not q or 0 not in q:
        return None
    table = np.array(q[0], dtype=float)
    if table.size != 64:
        return None
    scale = float(np.mean(table / STD_LUMA) * 100)
    quality = (200 - scale) / 2 if scale <= 100 else 5000 / scale
    return int(round(min(100, max(1, quality))))

# ---------------------------------------------------------------------------
# Block statistics and region finding
# ---------------------------------------------------------------------------

def _block_size(w, h):
    return int(max(8, min(32, round(min(w, h) / 40))))


def _blocks(arr: np.ndarray, b: int, fn) -> np.ndarray:
    h, w = arr.shape[:2]
    hb, wb = h // b, w // b
    a = arr[:hb * b, :wb * b].reshape(hb, b, wb, b)
    return fn(a, axis=(1, 3))


def _robust_z(x: np.ndarray) -> np.ndarray:
    med = np.median(x)
    mad = np.median(np.abs(x - med)) * 1.4826 + 1e-6
    return (x - med) / mad


def _largest_cluster(mask: np.ndarray):
    """4-connected flood fill on a small block grid; returns (cells, (r0, c0, r1, c1)) or None."""
    seen = np.zeros_like(mask, dtype=bool)
    best = None
    for r, c in zip(*np.nonzero(mask)):
        if seen[r, c]:
            continue
        stack, cells = [(r, c)], []
        seen[r, c] = True
        while stack:
            y, x = stack.pop()
            cells.append((y, x))
            for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= ny < mask.shape[0] and 0 <= nx < mask.shape[1] and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        if best is None or len(cells) > len(best):
            best = cells
    if not best:
        return None
    ys, xs = zip(*best)
    return len(best), (min(ys), min(xs), max(ys) + 1, max(xs) + 1)


def _region(z: np.ndarray, b: int, threshold: float, min_frac=0.004, max_frac=0.4):
    mask = z > threshold
    found = _largest_cluster(mask)
    if not found:
        return None
    cells, (r0, c0, r1, c1) = found
    frac = cells / mask.size
    if frac < min_frac or frac > max_frac or cells < 2:
        return None
    return {"box": [int(c0 * b), int(r0 * b), int(c1 * b), int(r1 * b)],  # x0, y0, x1, y1 in pixels
            "coverage": round(frac, 4),
            "strength": round(float(np.mean(z[r0:r1, c0:c1][mask[r0:r1, c0:c1]])), 1)}


def _heatmap(values: np.ndarray, size, box=None) -> Image.Image:
    v = values.astype(float)
    hi = np.percentile(v, 99.5) or 1.0
    v = np.clip(v / hi, 0, 1)
    stops = np.array([[0, 0, 4], [87, 16, 110], [188, 55, 84], [249, 142, 9], [252, 255, 164]], float)
    idx = v * (len(stops) - 1)
    lo = np.floor(idx).astype(int).clip(0, len(stops) - 2)
    t = (idx - lo)[..., None]
    rgb = (stops[lo] * (1 - t) + stops[lo + 1] * t).astype(np.uint8)
    im = Image.fromarray(rgb, "RGB").resize(size, Image.NEAREST)
    if box:
        ImageDraw.Draw(im).rectangle(box, outline=(0, 255, 255), width=max(2, size[0] // 300))
    return im

# ---------------------------------------------------------------------------
# Error Level Analysis
# ---------------------------------------------------------------------------

def _gray(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("L"), dtype=np.float32)


def _box_blur(a: np.ndarray, r: int = 1) -> np.ndarray:
    p = np.pad(a, r, mode="edge")
    k = 2 * r + 1
    c = np.cumsum(np.cumsum(p, 0), 1)
    c = np.pad(c, ((1, 0), (1, 0)))
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)


def ela(img: Image.Image, quality: int = 90) -> tuple[dict, Image.Image]:
    rgb = img.convert("RGB")
    buf = io.BytesIO()
    rgb.save(buf, "JPEG", quality=quality)
    resaved = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
    diff = np.abs(np.asarray(rgb, np.int16) - np.asarray(resaved, np.int16)).max(axis=2).astype(np.float32)

    b = _block_size(*rgb.size)
    gray = _gray(rgb)
    grad = np.abs(np.diff(gray, axis=0, append=gray[-1:])) + np.abs(np.diff(gray, axis=1, append=gray[:, -1:]))
    ela_b = _blocks(diff, b, np.mean)
    tex_b = _blocks(grad, b, np.mean)
    # normalise by texture: busy areas and edges naturally have higher error levels
    norm = ela_b / (tex_b + np.median(tex_b) + 1e-3)
    # smooth over neighbouring blocks: edited areas are contiguous, noise is scattered
    z = _box_blur(_robust_z(norm), 1)
    region = _region(z, b, threshold=ELA_THRESHOLD, min_frac=0.002)
    stats = {"quality_used": quality, "block": b, "mean_error": round(float(diff.mean()), 2),
             "max_z": round(float(z.max()), 1), "region": region}
    return stats, _heatmap(diff, rgb.size, region["box"] if region else None)

# ---------------------------------------------------------------------------
# Noise consistency
# ---------------------------------------------------------------------------

def noise_map(img: Image.Image) -> tuple[dict, Image.Image]:
    gray = _gray(img)
    residual = gray - _box_blur(gray, 1)
    b = _block_size(*img.size)
    sigma = _blocks(np.abs(residual), b, np.median) / 0.6745  # robust noise level per block
    tex = _blocks(np.abs(gray - _box_blur(gray, 3)), b, np.mean)
    flat = tex < np.percentile(tex, 70)  # judge noise mostly in smoother areas
    z = _robust_z(np.log(sigma + 0.5))
    z_abs = _box_blur(np.where(flat, np.abs(z), np.abs(z) * 0.5), 1)
    region = _region(z_abs, b, threshold=NOISE_THRESHOLD, min_frac=0.002)
    stats = {"block": b, "median_sigma": round(float(np.median(sigma)), 2),
             "max_z": round(float(z_abs.max()), 1), "region": region}
    sigma_img = np.kron(np.abs(z), np.ones((1, 1)))
    return stats, _heatmap(sigma_img, img.size, region["box"] if region else None)


def _iou(a, b):
    if not a or not b:
        return 0.0
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    iw, ih = max(0, min(ax1, bx1) - max(ax0, bx0)), max(0, min(ay1, by1) - max(ay0, by0))
    inter = iw * ih
    union = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return inter / union if union else 0.0


def _overlap(a, b):
    """Share of the smaller box covered by the other (regions are often different sizes)."""
    if not a or not b:
        return 0.0
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    inter = max(0, min(ax1, bx1) - max(ax0, bx0)) * max(0, min(ay1, by1) - max(ay0, by0))
    smaller = min((ax1 - ax0) * (ay1 - ay0), (bx1 - bx0) * (by1 - by0))
    return inter / smaller if smaller else 0.0

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyse_image(data: bytes, filename: str = "upload") -> dict:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:
        raise ValueError(f"Not a readable image: {type(e).__name__}")
    fmt = img.format
    img_oriented = ImageOps.exif_transpose(img) if fmt == "JPEG" else img
    img_oriented.format = fmt

    integ = integrity(data, filename, img)
    meta, signals = metadata(data, img)
    quality = jpeg_quality(img) if fmt == "JPEG" else None

    work = img_oriented.convert("RGB")
    ela_stats, ela_img = ela(work)
    noise_stats, noise_img = noise_map(work)

    lossless = fmt in ("PNG", "BMP", "TIFF", "WEBP") and quality is None
    er, nr = ela_stats["region"], noise_stats["region"]
    agree = _overlap(er["box"] if er else None, nr["box"] if nr else None)

    small = min(work.size) < 400
    if er and nr and agree >= 0.3:
        signals.append(_signal("Two independent tests flag the same region", "medium",
                               f"Error-level and noise analysis both highlight the area at {er['box']} "
                               f"(about {er['coverage']:.1%} of the image). Pasted or regenerated regions "
                               "often look like this; inspect that area closely.", "edited"))
    else:
        if er:
            signals.append(_signal("Compression inconsistency (ELA)", "low",
                                   f"The area at {er['box']} reacts differently to re-compression than its "
                                   "surroundings. This is a hint, not proof: in testing it marked the edited "
                                   "area of every CASIA forgery, but also raises hints on some untouched photos."
                                   + (" ELA is less reliable on lossless images like screenshots." if lossless else ""),
                                   "edited"))
        if nr:
            signals.append(_signal("Noise inconsistency", "low",
                                   f"The area at {nr['box']} has a different noise pattern from the rest of the "
                                   "image. Sky, shadows and blur can also cause this.", "edited"))
    if not er and not nr:
        signals.append(_signal("No localised editing traces", "info",
                               "Error-level and noise patterns are consistent across the image. This lowers "
                               "the chance of a pasted region but doesn't rule out AI generation or "
                               "whole-image edits.", "none"))
    if small:
        signals.append(_signal("Small image", "info",
                               f"At {work.size[0]}x{work.size[1]} px there is little data for pixel-level "
                               "tests; their results are weak evidence either way.", "none"))
    if quality is not None:
        signals.append(_signal("JPEG quality", "info",
                               f"Estimated save quality {quality}." +
                               (" Low quality hides editing traces, so absence of evidence is weaker."
                                if quality < 70 else ""), "none"))

    return {
        "integrity": integ,
        "metadata": meta,
        "jpeg_quality": quality,
        "ela": ela_stats,
        "noise": noise_stats,
        "region_agreement": round(agree, 2),
        "signals": signals,
        "images": {"original": work, "ela": ela_img, "noise": noise_img},
    }
