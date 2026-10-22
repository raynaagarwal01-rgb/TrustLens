"""
advanced.py — additional forensic tools for TrustLens.

Techniques follow the tool list of Sherloq (github.com/GuidoBartoli/sherloq) and the forensics
literature cited below. The code here is an independent implementation (Sherloq is GPL).

Tools with a verdict (they emit signals, calibrated on real samples; see tests/test_advanced.py).
median_filtering and contrast_enhance did NOT separate edited from authentic images in calibration,
so run_all reports them as experimental measurements only:
  jpeg_ghost        Farid 2009: a region pasted from a lower-quality JPEG "reappears" when the
                    image is re-saved at that lower quality
  copy_move         cloned areas inside one image, via keypoint self-matching + geometric check
                    (needs OpenCV; skipped without it)
  grid_alignment    blocking artefacts from an earlier JPEG save that don't line up with the
                    current 8x8 grid mean the picture was cropped or shifted, then re-saved
  median_filtering  Kirchner & Fridrich 2010: median filtering leaves runs of equal neighbours
  contrast_enhance  Stamm & Liu 2010: contrast/levels adjustments leave peaks and gaps in the
                    pixel-value histogram (only meaningful on high-quality or lossless files)

Inspection layers (no verdict; for a human or the vision model to look at):
  luminance gradient, edge echo, frequency split, colour PCA, min/max deviation, bit plane,
  noise residual, JPEG ghost map

File-structure tools: jpeg_structure (markers, quantisation tables, encoder hints), histogram,
compare_images (is this a copy / edited copy / different picture?).
"""

import io
import struct

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import forensics as fx

try:
    import cv2
except Exception:  # OpenCV is optional
    cv2 = None


def _signal(check, severity, detail, points_to="none"):
    return fx._signal(check, severity, detail, points_to)


def _gray(img):
    return np.asarray(img.convert("L"), dtype=np.float32)


def _to_img(a: np.ndarray, size=None, colour=True) -> Image.Image:
    """Scale an array to 0..255 (robustly) and render it, optionally with the heatmap palette."""
    if colour:
        return fx._heatmap(a, size or (a.shape[1], a.shape[0]))
    v = a.astype(float)
    lo, hi = np.percentile(v, 0.5), np.percentile(v, 99.5)
    v = np.clip((v - lo) / (hi - lo + 1e-6) * 255, 0, 255).astype(np.uint8)
    im = Image.fromarray(v, "L").convert("RGB")
    return im.resize(size, Image.NEAREST) if size else im

# ---------------------------------------------------------------------------
# JPEG ghost
# ---------------------------------------------------------------------------

GHOST_QUALITIES = list(range(50, 100, 5))


def jpeg_ghost(img: Image.Image, block: int = 16) -> tuple[dict, list[dict], Image.Image]:
    rgb = img.convert("RGB")
    a = np.asarray(rgb, np.float32)
    curves = []
    for q in GHOST_QUALITIES:
        buf = io.BytesIO()
        rgb.save(buf, "JPEG", quality=q)
        r = np.asarray(Image.open(io.BytesIO(buf.getvalue())).convert("RGB"), np.float32)
        curves.append(fx._blocks(((a - r) ** 2).mean(axis=2), block, np.mean))
    D = np.stack(curves)
    qs = np.array(GHOST_QUALITIES)
    Dn = (D - D.min(0)) / (D.max(0) - D.min(0) + 1e-6)
    global_curve = D.mean(axis=(1, 2))
    qg = int(qs[np.argmin(global_curve[:-1])])
    lower = qs < qg - 5
    stats = {"image_best_quality": qg, "region": None}
    if not lower.any():
        return stats, [], _to_img(np.zeros_like(D[0]), rgb.size)
    dip = Dn[qs == qg][0] - Dn[lower].min(0)
    ghost_q = qs[lower][np.argmin(Dn[lower], axis=0)]
    z = fx._box_blur(fx._robust_z(dip), 1)
    region = fx._region(z, block, threshold=2.5, min_frac=0.002)
    stats["region"] = region
    signals = []
    if region:
        x0, y0, x1, y1 = region["box"]
        qmode = int(np.bincount(ghost_q[y0 // block:y1 // block, x0 // block:x1 // block].ravel()).argmax())
        stats["region_quality"] = qmode
        signals.append(_signal("JPEG ghost", "low",
                               f"The area at {region['box']} matches an earlier save at about quality {qmode}, "
                               f"lower than the rest of the image (about {qg}). Content pasted from a lower-quality "
                               "image looks like this. In testing it found every splice from a lower-quality "
                               "source in large photos, and none on authentic photos.", "edited"))
    return stats, signals, _to_img(np.clip(dip, 0, None), rgb.size)

# ---------------------------------------------------------------------------
# Copy-move
# ---------------------------------------------------------------------------

def copy_move(img: Image.Image, max_side: int = 1600) -> tuple[dict, list[dict], Image.Image | None]:
    if cv2 is None:
        return {"status": "skipped", "detail": "OpenCV not installed (pip install opencv-python-headless)"}, [], None
    rgb = img.convert("RGB")
    scale = min(1.0, max_side / max(rgb.size))
    work = rgb.resize((int(rgb.width * scale), int(rgb.height * scale)), Image.LANCZOS) if scale < 1 else rgb
    gray = cv2.cvtColor(np.asarray(work), cv2.COLOR_RGB2GRAY)
    try:
        det = cv2.SIFT_create(nfeatures=4000)
        norm = cv2.NORM_L2
    except Exception:
        det, norm = cv2.ORB_create(nfeatures=4000), cv2.NORM_HAMMING
    kps, desc = det.detectAndCompute(gray, None)
    stats = {"status": "ok", "keypoints": len(kps or []), "matches": 0, "regions": []}
    if desc is None or len(kps) < 30:
        return stats, [], None
    matcher = cv2.BFMatcher(norm)
    knn = matcher.knnMatch(desc, desc, k=4)
    min_dist = 0.04 * max(work.size)
    pairs = []
    for row in knn:
        cand = [m for m in row if m.trainIdx != m.queryIdx]
        # generalised 2NN test (Amerini et al. 2011): keep matches much closer than the next one
        for a_, b_ in zip(cand, cand[1:]):
            if a_.distance < 0.5 * b_.distance:
                p, q = np.array(kps[a_.queryIdx].pt), np.array(kps[a_.trainIdx].pt)
                if np.linalg.norm(p - q) > min_dist:
                    pairs.append((p, q))
            break
    # de-duplicate symmetric pairs
    uniq = {}
    for p, q in pairs:
        key = tuple(np.round(np.concatenate([p, q]) if tuple(p) < tuple(q) else np.concatenate([q, p])).astype(int))
        uniq[key] = (p, q)
    pairs = list(uniq.values())
    stats["matches"] = len(pairs)
    if len(pairs) < 6:
        return stats, [], None
    src = np.float32([p for p, _ in pairs])
    dst = np.float32([q for _, q in pairs])
    M, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=4.0, maxIters=3000)
    n_in = int(inl.sum()) if inl is not None else 0
    if M is None or n_in < 8:
        return stats, [], None
    shift = float(np.hypot(M[0, 2], M[1, 2]))
    if shift < min_dist:
        return stats, [], None
    s_in, d_in = src[inl.ravel() == 1], dst[inl.ravel() == 1]

    def box(pts):
        x0, y0 = pts.min(0) / scale
        x1, y1 = pts.max(0) / scale
        return [int(x0), int(y0), int(x1), int(y1)]
    boxes = [box(s_in), box(d_in)]
    stats.update({"inliers": n_in, "regions": boxes})
    # visual: lines between cloned points on a dimmed copy
    vis = Image.blend(rgb, Image.new("RGB", rgb.size, (0, 0, 0)), 0.45)
    dr = ImageDraw.Draw(vis)
    w = max(2, rgb.width // 500)
    for p, q in zip(s_in, d_in):
        dr.line([tuple(p / scale), tuple(q / scale)], fill=(242, 194, 48), width=w)
    for b in boxes:
        dr.rectangle(b, outline=(0, 230, 255), width=w * 2)
    g = np.asarray(work.convert("L"), np.float32)
    flat_share = float((fx._blocks(np.abs(np.diff(g, axis=1, append=g[:, -1:])), 16, np.mean) < 1.0).mean())
    document_like = flat_share > 0.4
    stats["document_like"] = document_like
    if document_like:  # repeated letters and words in text match each other
        sev, note = "low", (" This image is mostly a plain page, where repeated letters and words also match, "
                            "so treat it as a hint only.")
    else:
        sev, note = ("high" if n_in >= 25 else "medium"), (" Repeating patterns (tiles, windows) can also match, "
                                                           "so check the layer.")
    signals = [_signal("Cloned area (copy-move)", sev,
                       f"{n_in} matching points show the area at {boxes[0]} repeated at {boxes[1]}. Copying part of "
                       "an image over another part is used to hide or duplicate objects." + note, "edited")]
    return stats, signals, vis

# ---------------------------------------------------------------------------
# JPEG grid alignment
# ---------------------------------------------------------------------------

def grid_alignment(img: Image.Image) -> tuple[dict, list[dict]]:
    g = _gray(img)
    if min(g.shape) < 128:
        return {"status": "skipped"}, []
    dx = np.abs(np.diff(g, axis=1))
    dy = np.abs(np.diff(g, axis=0))
    # blockiness at each of the 8 possible grid phases, normalised by the local average difference
    px = np.array([dx[:, o::8].mean() for o in range(8)])
    py = np.array([dy[o::8, :].mean() for o in range(8)])
    rx, ry = px / np.median(px), py / np.median(py)
    # a JPEG boundary between columns 7 and 8 shows up in diff index 7 when the grid is aligned,
    # so the grid offset is (peak index + 1) mod 8; judged separately for each axis
    def axis(r):
        off = (int(np.argmax(r)) + 1) % 8
        return off, float(r.max()), bool(off != 0 and r.max() >= GRID_MIN_STRENGTH)
    ox, sx, fx_ = axis(rx)
    oy, sy, fy_ = axis(ry)
    stats = {"offset": [ox if fx_ else 0, oy if fy_ else 0], "strength": [round(sx, 3), round(sy, 3)],
             "profile_x": [round(v, 3) for v in rx], "profile_y": [round(v, 3) for v in ry]}
    signals = []
    # both axes must agree: single-axis or weak peaks also come from AI upsampling and textures
    if fx_ and fy_:
        where = f"{ox} px across and {oy} px down"
        signals.append(_signal("Shifted JPEG grid", "medium",
                               f"Compression blocks from an earlier save are shifted {where} from where they should "
                               "be. The picture was cropped or shifted after it was first saved, then saved again.",
                               "edited"))
    return stats, signals


GRID_MIN_STRENGTH = 1.10

# ---------------------------------------------------------------------------
# Median filtering
# ---------------------------------------------------------------------------

def median_filtering(img: Image.Image) -> tuple[dict, list[dict]]:
    g = np.asarray(img.convert("L"), dtype=np.int16)
    dx = np.diff(g, axis=1)
    lap = np.abs(np.diff(g, 2, axis=1))
    textured = lap[:, :] > 6
    # share of exactly-equal neighbours, in textured areas only (flat areas are equal anyway)
    eq = (dx[:, 1:] == 0) & textured
    ratio = float(eq.sum() / max(1, textured.sum()))
    stats = {"equal_neighbour_ratio": round(ratio, 4)}
    signals = []
    if ratio > MEDIAN_RATIO:
        signals.append(_signal("Median filtering traces", "low",
                               f"{ratio:.1%} of neighbouring pixels in detailed areas are exactly equal, typical of "
                               "median filtering, which is sometimes used to hide editing or noise traces.", "edited"))
    return stats, signals


MEDIAN_RATIO = 0.12

# ---------------------------------------------------------------------------
# Contrast enhancement
# ---------------------------------------------------------------------------

def contrast_enhancement(img: Image.Image, jpeg_quality: int | None) -> tuple[dict, list[dict]]:
    g = np.asarray(img.convert("L"))
    h = np.bincount(g.ravel(), minlength=256).astype(float)
    inner = h[8:248]
    gaps = int(((inner == 0) & (np.convolve(inner, [1, 0, 1], "same") > 0)).sum())
    spec = np.abs(np.fft.rfft(inner / (inner.sum() + 1e-6)))
    hf = float(spec[len(spec) // 4:].sum() / (spec.sum() + 1e-9))
    stats = {"histogram_gaps": gaps, "high_frequency_energy": round(hf, 3)}
    signals = []
    reliable = jpeg_quality is None or jpeg_quality >= 90
    if reliable and gaps >= CE_MIN_GAPS:
        signals.append(_signal("Contrast or levels adjusted", "low",
                               f"The brightness histogram has {gaps} empty values between used ones, a comb pattern "
                               "left by brightness, contrast or levels adjustments. Common in harmless edits too.",
                               "edited"))
    return stats, signals


CE_MIN_GAPS = 12

# ---------------------------------------------------------------------------
# Inspection layers (no verdict)
# ---------------------------------------------------------------------------

def layer(img: Image.Image, kind: str) -> Image.Image:
    rgb = img.convert("RGB")
    g = _gray(rgb)
    if kind == "gradient":
        gx = np.diff(g, axis=1, append=g[:, -1:])
        gy = np.diff(g, axis=0, append=g[-1:])
        mag = np.hypot(gx, gy)
        ang = (np.arctan2(gy, gx) + np.pi) / (2 * np.pi)
        hsv = np.stack([ang * 255, np.full_like(ang, 200), np.clip(mag / (np.percentile(mag, 99) + 1e-6), 0, 1) * 255], -1)
        return Image.fromarray(hsv.astype(np.uint8), "HSV").convert("RGB")
    if kind == "echo":
        lap = np.abs(np.asarray(rgb.convert("L").filter(ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], 1, 128)),
                                np.float32) - 128)
        return _to_img(lap, colour=False)
    if kind == "frequency":
        low = np.asarray(rgb.convert("L").filter(ImageFilter.GaussianBlur(3)), np.float32)
        return _to_img(np.abs(g - low), colour=False)
    if kind == "pca":
        a = np.asarray(rgb, np.float32).reshape(-1, 3)
        a = a - a.mean(0)
        _, _, vt = np.linalg.svd(a[:: max(1, len(a) // 200000)], full_matrices=False)
        comp = (a @ vt[1]).reshape(rgb.height, rgb.width)  # 2nd component: colour differences, not brightness
        return _to_img(comp, colour=False)
    if kind == "minmax":
        mx = np.asarray(rgb.convert("L").filter(ImageFilter.MaxFilter(3)), np.float32)
        mn = np.asarray(rgb.convert("L").filter(ImageFilter.MinFilter(3)), np.float32)
        dev = np.minimum(np.abs(g - mn), np.abs(mx - g))
        return _to_img(dev, colour=True)
    if kind == "bitplane":
        bp = (np.asarray(rgb.convert("L")) >> 1) & 1
        return Image.fromarray((bp * 255).astype(np.uint8), "L").convert("RGB")
    if kind == "noise":
        med = np.asarray(rgb.convert("L").filter(ImageFilter.MedianFilter(3)), np.float32)
        return _to_img(np.abs(g - med), colour=False)
    raise ValueError(f"unknown layer {kind}")


LAYERS = {
    "gradient": "Luminance gradient: direction (colour) and strength (brightness) of edges; lighting that "
                "doesn't match neighbouring areas stands out",
    "echo": "Edge echo: second-derivative edges; blurred or sharpened pasted areas look different",
    "frequency": "Frequency split: fine detail only; smoothed or AI-generated areas look emptier",
    "pca": "Colour PCA: colour differences the eye can't easily see; pasted objects often separate",
    "minmax": "Min/max deviation: pixels unlike all their neighbours",
    "bitplane": "Bit plane: one bit of brightness; edited areas break the noise texture",
    "noise": "Noise residual: what remains after removing the picture; noise should look uniform",
}

# ---------------------------------------------------------------------------
# JPEG structure, histogram
# ---------------------------------------------------------------------------

MARKERS = {0xC0: "SOF0 baseline", 0xC1: "SOF1 extended", 0xC2: "SOF2 progressive", 0xC4: "DHT Huffman tables",
           0xDB: "DQT quantisation tables", 0xDD: "DRI restart interval", 0xDA: "SOS start of scan",
           0xFE: "COM comment", 0xD8: "SOI start", 0xD9: "EOI end"}


def jpeg_structure(data: bytes) -> dict | None:
    if not data.startswith(b"\xff\xd8"):
        return None
    segs, i, comps = [], 2, []
    while i + 4 <= len(data) and len(segs) < 60:
        if data[i] != 0xFF:
            break
        m = data[i + 1]
        if m == 0xD9:
            segs.append({"marker": "EOI end", "offset": i, "length": 0})
            break
        ln = struct.unpack(">H", data[i + 2:i + 4])[0]
        body = data[i + 4:i + 2 + ln]
        name = MARKERS.get(m, f"APP{m - 0xE0}" if 0xE0 <= m <= 0xEF else f"0x{m:02X}")
        if 0xE0 <= m <= 0xEF:
            ident = body[:12].split(b"\x00")[0].decode("latin-1", "replace")
            name += f" {ident}" if ident.isprintable() and ident else ""
            if m == 0xEB:
                name += " (JUMBF / Content Credentials)"
        if m in (0xC0, 0xC1, 0xC2) and len(body) >= 6:
            n = body[5]
            comps = [{"id": body[6 + 3 * k], "h": body[7 + 3 * k] >> 4, "v": body[7 + 3 * k] & 15} for k in range(n)]
        segs.append({"marker": name, "offset": i, "length": ln})
        if m == 0xDA:  # entropy-coded data follows; jump to end
            end = data.rfind(b"\xff\xd9")
            segs.append({"marker": "compressed image data", "offset": i + 2 + ln, "length": max(0, end - i - 2 - ln)})
            segs.append({"marker": "EOI end", "offset": end, "length": 0})
            trailing = len(data) - end - 2
            if trailing > 16:
                segs.append({"marker": f"{trailing} bytes after end of image", "offset": end + 2, "length": trailing})
            break
        i += 2 + ln
    sub = ""
    if len(comps) == 3:
        y = comps[0]
        sub = {(2, 2): "4:2:0", (2, 1): "4:2:2", (1, 1): "4:4:4"}.get((y["h"], y["v"]), f"{y['h']}x{y['v']}")
    try:
        q = Image.open(io.BytesIO(data)).quantization or {}
    except Exception:
        q = {}
    tables = {str(k): list(v) for k, v in q.items()}
    standard = None
    if "0" in tables and len(tables["0"]) == 64:
        est = fx.jpeg_quality(Image.open(io.BytesIO(data)))
        scale = (5000 / est if est < 50 else 200 - 2 * est) if est else 100
        expect = np.clip(np.floor((fx.STD_LUMA * scale + 50) / 100), 1, 255)
        actual = np.array(tables["0"], float)
        standard = bool(np.mean(np.abs(actual - expect)) < 1.5)
    return {"segments": segs, "subsampling": sub, "progressive": any("SOF2" in s["marker"] for s in segs),
            "quant_tables": tables, "standard_tables": standard,
            "encoder_hint": None if standard is None else (
                "Standard IJG quantisation tables, used by most software and many phones"
                if standard else "Non-standard quantisation tables, as written by many cameras and by Photoshop")}


def histogram(img: Image.Image) -> dict:
    a = np.asarray(img.convert("RGB"))
    lum = np.asarray(img.convert("L"))
    return {c: np.bincount(a[..., i].ravel(), minlength=256).tolist() for i, c in enumerate("rgb")} | {
        "l": np.bincount(lum.ravel(), minlength=256).tolist()}

# ---------------------------------------------------------------------------
# Compare with a suspected original
# ---------------------------------------------------------------------------

def compare_images(a: Image.Image, b: Image.Image) -> tuple[dict, Image.Image]:
    ha, hb = fx.perceptual_hashes(a), fx.perceptual_hashes(b)
    dist = {k: fx.hash_distance(ha[k], hb[k]) for k in ha}
    size = (min(a.width, b.width, 1200), 0)
    size = (size[0], int(size[0] * a.height / a.width))
    ga = np.asarray(a.convert("L").resize(size, Image.LANCZOS).filter(ImageFilter.BoxBlur(1)), np.float32)
    gb = np.asarray(b.convert("L").resize(size, Image.LANCZOS).filter(ImageFilter.BoxBlur(1)), np.float32)
    gb = (gb - gb.mean()) / (gb.std() + 1e-6) * ga.std() + ga.mean()
    diff = np.abs(ga - gb)
    bs = max(8, size[0] // 40)
    blocks = fx._blocks(diff, bs, np.mean)
    changed = blocks > max(25, 4 * np.median(blocks))
    share = float(changed.mean())
    if dist["phash"] > 22:
        verdict = "different"
        text = "These look like different pictures."
    elif share < 0.003:
        verdict = "same"
        text = "Same picture: only re-saving or resizing differences."
    else:
        verdict = "edited"
        text = f"Same picture, but {share:.1%} of it was changed. The changed areas are highlighted."
    region = None
    if changed.any() and verdict == "edited":
        ys, xs = np.nonzero(changed)
        sx = a.width / size[0]
        region = [int(xs.min() * bs * sx), int(ys.min() * bs * sx), int((xs.max() + 1) * bs * sx), int((ys.max() + 1) * bs * sx)]
    return ({"verdict": verdict, "summary": text, "hash_distance": dist, "changed_share": round(share, 4),
             "changed_region": region},
            fx._heatmap(diff, a.size, region))

# ---------------------------------------------------------------------------
# Run everything with a verdict
# ---------------------------------------------------------------------------

def run_all(img: Image.Image, data: bytes, jpeg_quality: int | None,
            raw: Image.Image | None = None) -> tuple[dict, list[dict], dict]:
    """Returns (stats by tool, signals, extra layer images). Each tool is isolated: one failing tool
    never stops the others."""
    stats, signals, images = {}, [], {}
    tools = {
        "ghost": lambda: jpeg_ghost(img),
        "copy_move": lambda: copy_move(img),
        # the JPEG grid lives in the stored orientation, so use the un-rotated image
        "grid": lambda: (*grid_alignment(raw or img), None) if jpeg_quality else ({"status": "not a JPEG"}, [], None),
        "median": lambda: (*median_filtering(img), None),
        "contrast": lambda: (*contrast_enhancement(img, jpeg_quality), None),
    }
    # median and contrast didn't separate edited from authentic images in calibration, so they are
    # reported as measurements only and never feed the verdict
    experimental = {"median", "contrast"}
    for name, fn in tools.items():
        try:
            s, sig, im = fn()
            if name in experimental:
                s = {**s, "experimental": True, "would_flag": bool(sig)}
                sig = []
            stats[name], signals = s, signals + sig
            if im is not None:
                images[name] = im
        except Exception as e:
            stats[name] = {"status": "error", "detail": f"{type(e).__name__}: {str(e)[:120]}"}
    try:
        stats["structure"] = jpeg_structure(data)
    except Exception as e:
        stats["structure"] = {"status": "error", "detail": type(e).__name__}
    return stats, signals, images
