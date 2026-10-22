"""
TrustLens server: JSON API + the React interface.

    python server.py            # http://127.0.0.1:8000 (opens your browser)
    TRUSTLENS_PORT=9000 python server.py

Cases are kept in ./cases/<case id>/ (original file + results), so the evidence locker survives
restarts. Every action is written to the chain-of-custody log (custody_log.jsonl).
"""

import hashlib
import io
import json
import mimetypes
import os
import shutil
import threading
import time
import webbrowser
from pathlib import Path

import envfile  # loads .env before anything reads the key

import numpy as np
from PIL import Image
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

import advanced
import batch
import campus_check
import custody
import event_check
import evidence_analyser as ea
import faces
import forensics
import media
import screenshot_check
import signing
import summary
import vtop
from report import build_report_html

ROOT = Path(__file__).resolve().parent
CASES = Path(os.getenv("TRUSTLENS_CASES", ROOT / "cases"))
SAMPLES = ROOT / "samples"
WEB = ROOT / "web" / "dist"
MAX_UPLOAD = 300 * 1024 * 1024  # phone 4K clips; only 12 frames are read, so size costs upload time only
MEDIA_TYPES = tuple(media.IMAGE_EXT | media.VIDEO_EXT | media.AUDIO_EXT)
STORED_KINDS = ("video", "audio")   # their analysis images are saved, not re-created

_cache: dict[str, dict] = {}       # case id -> {"result", "images", "data"}
_lock = threading.Lock()

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _json_default(o):
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (set, tuple)):
        return list(o)
    return str(o)


def ok(data, status=200):
    return Response(json.dumps(data, default=_json_default), status_code=status, media_type="application/json")


def err(message, status=400):
    return ok({"error": message}, status)


def case_id(sha: str) -> str:
    return sha[:12]


def _case_dir(cid: str) -> Path:
    if not cid.isalnum() or len(cid) != 12:
        raise KeyError(cid)
    return CASES / cid


def _public(result: dict) -> dict:
    out = {k: v for k, v in result.items() if k != "images"}
    out.setdefault("media_kind", "image")
    out["summary"] = summary.build(out)
    out["headline"] = summary.headline(out)
    return out


def sample_label(name: str) -> tuple[str, str]:
    groups = [("Tp_", "Tampered photo (CASIA dataset)"), ("Au_", "Authentic photo"), ("AI_", "AI-generated image"),
              ("Edited_", "Edited photo"), ("Forged_", "Forged notice"), ("Notice_", "Genuine notice"),
              ("Event_", "Event poster"), ("Video_", "Video"), ("Voice_", "Voice note"), ("Screenshot_", "Screenshot")]
    for prefix, label in groups:
        if name.startswith(prefix):
            return prefix.rstrip("_").lower(), label
    return "other", "Sample"


def analyse_any(data: bytes, name: str, use_llm: bool) -> dict:
    kind = media.kind_of(data, name)
    if kind == "video":
        import video_analyser
        return video_analyser.analyse_video(data, name, use_llm=use_llm)
    if kind == "audio":
        import audio_analyser
        return audio_analyser.analyse_audio(data, name, use_llm=use_llm)
    if kind == "image":
        return ea.analyse(data, name, use_llm=use_llm)
    raise ValueError(f"{name} isn't an image, video or audio file TrustLens can read.")


def _preview(d: Path, kind: str) -> Path | None:
    """Browser-playable copy of a video or voice note, made once per case."""
    out = d / ("preview.mp4" if kind == "video" else "preview.mp3")
    if out.exists() and out.stat().st_size > 0:
        return out
    return out if media.make_preview(str(d / "original.bin"), str(out), kind) else None


def _store_images(d: Path, images: dict):
    """Save analysis images so a case reopens without re-running the tests. The evidence itself stays
    original.bin; these are views of it (the ground-truth mask is re-read from samples/)."""
    folder = d / "images"
    folder.mkdir(exist_ok=True)
    for k, im in images.items():
        if im is None or k in ("ground_truth", "compare_other") or not k.replace("_", "").isalnum():
            continue
        im.convert("RGB").save(folder / f"{k}.jpg", "JPEG", quality=92)


SCREENSHOT_KINDS = ("screenshot", "receipt", "payment", "chat")


NOTICE_KINDS = ("document", "other screenshot")


def auto_checks(data: bytes, result: dict) -> dict:
    """With the AI review on, a payment or chat screenshot gets the screenshot forgery check straight away,
    and a notice or circular is checked against VTOP, so the verdict includes them without a button press."""
    kind = (result.get("image_kind") or "").lower()
    if result.get("media_kind", "image") == "image" and result.get("llm_used") and any(k in kind for k in NOTICE_KINDS):
        try:
            check = campus_check.run_campus_check(data, live=False)
            if check["notice"].get("is_campus_notice") and check["claims"]:
                return campus_check.apply_to_result(result, check)
        except Exception as e:
            result["notice_check_error"] = f"{type(e).__name__}: {str(e)[:160]}"
    if result.get("media_kind", "image") != "image" or not result.get("llm_used") or not any(k in kind for k in SCREENSHOT_KINDS):
        return result
    try:
        check = screenshot_check.run_screenshot_check(data)
        if check.get("kind") in ("payment", "chat"):
            return screenshot_check.apply_to_result(result, check)
    except Exception as e:
        result["screenshot_check_error"] = f"{type(e).__name__}: {str(e)[:160]}"
    return result


def save_case(data: bytes, name: str, use_llm: bool, source: str) -> dict:
    sha = hashlib.sha256(data).hexdigest()
    cid = case_id(sha)
    d = CASES / cid
    d.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in Path(name).name if c.isalnum() or c in "._- ")[:80] or "evidence"
    (d / "original.bin").write_bytes(data)
    result = analyse_any(data, safe, use_llm)
    images = result.pop("images")
    result = auto_checks(data, result)
    gt = SAMPLES / (Path(name).stem + "_gt.png")
    if source == "sample" and gt.exists():
        images["ground_truth"] = Image.open(gt).convert("L")
    _store_images(d, images)
    if result.get("media_kind") in STORED_KINDS:
        # the playable copy takes seconds to minutes: make it in the background, the result shouldn't wait
        threading.Thread(target=_preview, args=(d, result["media_kind"]), daemon=True).start()
    meta = {"id": cid, "sha256": sha, "name": safe, "source": source, "created": time.time(), "use_llm": use_llm,
            "media_kind": result.get("media_kind", "image")}
    result["case"] = meta
    (d / "result.json").write_text(json.dumps(result, default=_json_default), encoding="utf-8")
    with _lock:
        _cache[cid] = {"result": result, "images": images, "data": data}
    custody.record("analysed", sha, {"file": safe, "case": cid, "media": meta["media_kind"], "verdict": result["verdict"],
                                     "score": result["manipulation_score"], "tool": result["tool_version"],
                                     "ai_analysis": result["llm_used"]})
    result["headline"] = summary.headline(result)
    return result


def load_case(cid: str) -> dict:
    with _lock:
        if cid in _cache:
            return _cache[cid]
    d = _case_dir(cid)
    if not (d / "result.json").exists():
        raise KeyError(cid)
    result = json.loads((d / "result.json").read_text(encoding="utf-8"))
    data = (d / "original.bin").read_bytes()
    entry = {"result": result, "images": None, "data": data}
    with _lock:
        _cache[cid] = entry
    return entry


def case_images(cid: str) -> dict:
    """Analysis images: loaded from disk for video/audio, re-created on demand for images."""
    entry = load_case(cid)
    if entry["images"] is None:
        r = entry["result"]
        folder = _case_dir(cid) / "images"
        if folder.exists() and (folder / "original.jpg").exists():
            images = {p.stem: Image.open(p) for p in folder.glob("*.jpg")}
            for im in images.values():
                im.load()
            gt = SAMPLES / (Path(r["case"]["name"]).stem + "_gt.png")
            if r["case"].get("source") == "sample" and gt.exists():
                images["ground_truth"] = Image.open(gt).convert("L")
        else:
            fx = forensics.analyse_image(entry["data"], r["case"]["name"])
            images = fx["images"]
            try:
                raw = Image.open(io.BytesIO(entry["data"])).convert("RGB")
                images.update(advanced.run_all(images["original"], entry["data"], fx["jpeg_quality"], raw)[2])
            except Exception:
                pass
            try:
                fstats, crops, overlay = faces.analyse(images["original"])
                if overlay is not None:
                    images["faces"] = overlay
                for i, c in enumerate(crops):
                    images[f"face_{i + 1}"] = c
            except Exception:
                pass
            gt = SAMPLES / (Path(r["case"]["name"]).stem + "_gt.png")
            if r["case"]["source"] == "sample" and gt.exists():
                images["ground_truth"] = Image.open(gt).convert("L")
        entry["images"] = images
    return entry["images"]


def save_result(cid: str, result: dict):
    (_case_dir(cid) / "result.json").write_text(json.dumps(result, default=_json_default), encoding="utf-8")


def _crash(e: Exception, doing: str):
    """Unexpected error: print the full traceback in the terminal and show the cause on the page."""
    import traceback
    print(f"\n--- TrustLens error while {doing} ---", flush=True)
    traceback.print_exc()
    where = traceback.extract_tb(e.__traceback__)[-1] if e.__traceback__ else None
    loc = f" ({Path(where.filename).name}, line {where.lineno})" if where else ""
    return err(f"TrustLens hit an error while {doing}: {type(e).__name__}: {str(e)[:220]}{loc}. "
               "The full details are in the terminal.", 500)


def _llm_needed(entry, what: str):
    if not envfile.ai_review_status()[0]:
        return err(f"{what} needs the AI review. Add your API key to the .env file and restart TrustLens.", 409)
    return None

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


async def status(request: Request):
    provider = os.getenv("LLM_PROVIDER", "gemini").lower()
    key = envfile.ai_review_status()[0]
    try:
        import c2pa  # noqa: F401
        c2pa_ok = True
    except Exception:
        c2pa_ok = False
    try:
        import reportlab  # noqa: F401
        pdf_ok = True
    except Exception:
        pdf_ok = False
    clitop = shutil.which(os.getenv("CLITOP_PATH", "cli-top")) or (os.path.exists(os.getenv("CLITOP_PATH", "")) or None)
    snaps = sorted(p.stem for p in Path(vtop.SNAPSHOT_DIR).glob("*.txt")) if Path(vtop.SNAPSHOT_DIR).exists() else []
    return ok({
        "llm": {"provider": provider, "configured": bool(key), "model": os.getenv("LLM_MODEL", "")},
        "opencv": advanced.cv2 is not None,
        "faces": faces.available(),
        "ffmpeg": bool(media.ffmpeg_path()),
        "pdf": pdf_ok,
        "signing": signing.signer().mode,
        "c2pa_verification": c2pa_ok,
        "vtop": {"cli_top_found": bool(clitop), "snapshots": snaps},
        "custody": custody.verify(),
        "version": ea.VERSION,
    })


async def samples(request: Request):
    out = []
    for p in sorted(SAMPLES.iterdir()) if SAMPLES.exists() else []:
        if p.suffix.lower() in MEDIA_TYPES and not p.stem.endswith("_gt"):
            group, label = sample_label(p.name)
            out.append({"name": p.name, "group": group, "label": label, "kind": media.kind_of(p.read_bytes()[:64], p.name),
                        "ground_truth": (SAMPLES / (p.stem + "_gt.png")).exists()})
    return ok(out)


def _thumb(p: Path, w: int) -> bytes:
    data = p.read_bytes()
    kind = media.kind_of(data[:64], p.name)
    if kind == "video":
        import cv2
        cap = cv2.VideoCapture(str(p))
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 1)
        cap.set(cv2.CAP_PROP_POS_FRAMES, n // 3)
        good, frame = cap.read()
        cap.release()
        im = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)) if good else Image.new("RGB", (w, w), (43, 48, 54))
    elif kind == "audio":
        import audio_analyser
        x, sr = audio_analyser.decode(str(p))
        im = audio_analyser.waveform(x, 480, 300)
    else:
        im = Image.open(p).convert("RGB")
    im.thumbnail((w, w))
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=85)
    return buf.getvalue()


async def sample_file(request: Request):
    name = request.path_params["name"]
    p = (SAMPLES / name).resolve()
    if p.parent != SAMPLES.resolve() or not p.exists():
        return err("No such sample.", 404)
    w = int(request.query_params.get("w", "0") or 0)
    if w:
        body = await run_in_threadpool(_thumb, p, w)
        return Response(body, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})
    return FileResponse(p)


def _summary_row(r: dict) -> dict:
    c = r.get("case", {})
    pub = {**r, "media_kind": r.get("media_kind", "image")}
    return {**c, "media_kind": pub["media_kind"], "verdict": r.get("verdict"), "verdict_label": r.get("verdict_label"),
            "score": r.get("manipulation_score"), "fake_type_label": r.get("fake_type_label"),
            "llm_used": r.get("llm_used"), "headline": summary.headline(pub)}


async def list_cases(request: Request):
    out = []
    if CASES.exists():
        for d in CASES.iterdir():
            f = d / "result.json"
            if f.exists():
                try:
                    r = json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    continue
                out.append(_summary_row(r))
    out.sort(key=lambda c: -c.get("created", 0))
    return ok(out)


async def create_case(request: Request):
    use_llm = request.query_params.get("ai", "1") != "0" and envfile.ai_review_status()[0]
    ctype = request.headers.get("content-type", "")
    reuse = False
    if ctype.startswith("multipart/"):
        form = await request.form(max_part_size=MAX_UPLOAD)
        f = form.get("file")
        if f is None:
            return err("Attach a file in the 'file' field.")
        data, name, source = await f.read(), f.filename or "upload", "upload"
    else:
        body = await request.json()
        name = body.get("sample", "")
        reuse = bool(body.get("reuse"))
        p = (SAMPLES / name).resolve()
        if p.parent != SAMPLES.resolve() or not p.exists():
            return err("That sample doesn't exist.", 404)
        data, source = p.read_bytes(), "sample"
    if len(data) > MAX_UPLOAD:
        return err("That file is larger than 300 MB. Trim the video, or send it through WhatsApp first (it compresses it).", 413)
    if reuse:  # demo mode: open the existing analysis instead of running it again
        try:
            entry = load_case(case_id(hashlib.sha256(data).hexdigest()))
            if entry["result"]["case"].get("use_llm") == use_llm or not use_llm:
                return ok(_public(entry["result"]), 200)
        except KeyError:
            pass
    try:
        result = await run_in_threadpool(save_case, data, name, use_llm, source)
    except ValueError as e:
        return err(str(e), 422)
    except Exception as e:
        return _crash(e, f"analysing {name}")
    return ok(_public(result), 201)


async def reanalyse_case(request: Request):
    """Run a case again, e.g. after adding an API key: the old result stays in the custody log."""
    cid = request.path_params["cid"]
    try:
        entry = load_case(cid)
    except KeyError:
        return err("No such case.", 404)
    use_llm = envfile.ai_review_status()[0]
    meta = entry["result"]["case"]
    with _lock:
        _cache.pop(cid, None)
    try:
        result = await run_in_threadpool(save_case, entry["data"], meta["name"], use_llm, meta.get("source", "upload"))
    except ValueError as e:
        return err(str(e), 422)
    except Exception as e:
        return _crash(e, f"re-analysing {meta['name']}")
    return ok(_public(result))


async def get_case(request: Request):
    try:
        return ok(_public(load_case(request.path_params["cid"])["result"]))
    except KeyError:
        return err("No such case.", 404)


async def delete_case(request: Request):
    cid = request.path_params["cid"]
    try:
        entry = load_case(cid)
    except KeyError:
        return err("No such case.", 404)
    custody.record("case_removed_from_locker", entry["result"]["case"]["sha256"], {"case": cid})
    shutil.rmtree(_case_dir(cid), ignore_errors=True)
    with _lock:
        _cache.pop(cid, None)
    return ok({"removed": cid})


def _encode(im: Image.Image, max_side: int, fmt: str = "JPEG") -> bytes:
    im = im.convert("RGB") if im.mode not in ("RGB", "L") else im
    if max_side and max(im.size) > max_side:
        im = im.copy()
        im.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, fmt, quality=90) if fmt == "JPEG" else im.save(buf, fmt)
    return buf.getvalue()


async def case_image(request: Request):
    cid, kind = request.path_params["cid"], request.path_params["kind"]
    max_side = int(request.query_params.get("w", "2000") or 0)
    try:
        images = await run_in_threadpool(case_images, cid)
    except KeyError:
        return err("No such case.", 404)
    if kind in images and images[kind] is not None:
        im = images[kind]
    elif kind in advanced.LAYERS and images.get("original") is not None:
        im = await run_in_threadpool(advanced.layer, images["original"], kind)
        images[kind] = im
    else:
        return err(f"No '{kind}' layer for this case.", 404)
    fmt = "PNG" if kind in ("ground_truth", "bitplane") else "JPEG"
    body = await run_in_threadpool(_encode, im, max_side, fmt)
    return Response(body, media_type=f"image/{fmt.lower()}", headers={"Cache-Control": "max-age=86400"})


async def case_media(request: Request):
    """A browser-playable copy for the video / audio player (the original if no copy could be made).
    FileResponse answers Range requests, which browsers need to play and seek MP4."""
    cid = request.path_params["cid"]
    try:
        entry = load_case(cid)
    except KeyError:
        return err("No such case.", 404)
    kind = entry["result"].get("media_kind")
    if kind in STORED_KINDS:
        prev = await run_in_threadpool(_preview, _case_dir(cid), kind)
        if prev is not None:
            return FileResponse(prev, media_type="video/mp4" if kind == "video" else "audio/mpeg",
                                headers={"Cache-Control": "max-age=86400"})
    name = entry["result"]["case"]["name"]
    mt = mimetypes.guess_type(name)[0] or {"video": "video/mp4", "audio": "audio/mpeg"}.get(entry["result"].get("media_kind"), "application/octet-stream")
    if name.lower().endswith((".opus", ".ogg")):
        mt = "audio/ogg"
    return FileResponse(_case_dir(cid) / "original.bin", media_type=mt, headers={"Cache-Control": "max-age=86400"})


async def case_layers(request: Request):
    cid = request.path_params["cid"]
    try:
        images = await run_in_threadpool(case_images, cid)
        r = load_case(cid)["result"]
    except KeyError:
        return err("No such case.", 404)
    order = ("ela", "ghost", "copy_move", "compare", "thumbnail", "faces", "noise", "sheet", "waveform")
    available = [k for k in order if images.get(k) is not None]
    if r.get("media_kind") == "audio":
        available = [k for k in ("waveform",) if images.get(k) is not None]
    return ok({"available": available + (["ground_truth"] if images.get("ground_truth") is not None else []),
               "inspection": advanced.LAYERS if r.get("media_kind", "image") != "audio" else {},
               "faces": sorted(k for k in images if k.startswith("face_")),
               "frames": sorted((k for k in images if k.startswith("frame_")), key=lambda k: int("".join(c for c in k if c.isdigit()) or 0))})


async def case_histogram(request: Request):
    try:
        images = await run_in_threadpool(case_images, request.path_params["cid"])
    except KeyError:
        return err("No such case.", 404)
    return ok(await run_in_threadpool(advanced.histogram, images["original"]))


async def notice_check(request: Request):
    cid = request.path_params["cid"]
    body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
    try:
        entry = load_case(cid)
    except KeyError:
        return err("No such case.", 404)
    if (e := _llm_needed(entry, "Reading a notice")):
        return e
    try:
        check = await run_in_threadpool(campus_check.run_campus_check, entry["data"], bool(body.get("live")))
    except Exception as e:
        return err(f"The notice check failed: {type(e).__name__}: {str(e)[:200]}", 502)
    result = campus_check.apply_to_result(entry["result"], check)
    entry["result"] = result
    save_result(cid, result)
    custody.record("vtop_notice_check", result["case"]["sha256"], {"overall": check["overall"], "source": check["data_source"]})
    return ok(_public(result))


async def run_event_check(request: Request):
    cid = request.path_params["cid"]
    body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
    try:
        entry = load_case(cid)
    except KeyError:
        return err("No such case.", 404)
    if (e := _llm_needed(entry, "Reading a poster")):
        return e
    try:
        check = await run_in_threadpool(event_check.run_event_check, entry["data"], bool(body.get("live")))
    except Exception as e:
        return err(f"The event check failed: {type(e).__name__}: {str(e)[:200]}", 502)
    entry["result"]["event_check"] = check
    save_result(cid, entry["result"])
    custody.record("event_check", entry["result"]["case"]["sha256"],
                   {"verdict": check["verdict"], "event": check["event"]["event_name"]})
    return ok(_public(entry["result"]))


def _image_bytes(cid: str, entry: dict) -> bytes:
    """The picture to read: the file itself for images, the key frame for videos."""
    if entry["result"].get("media_kind", "image") == "image":
        return entry["data"]
    buf = io.BytesIO()
    case_images(cid)["original"].convert("RGB").save(buf, "JPEG", quality=92)
    return buf.getvalue()


async def run_screenshot_check(request: Request):
    cid = request.path_params["cid"]
    try:
        entry = load_case(cid)
    except KeyError:
        return err("No such case.", 404)
    if (e := _llm_needed(entry, "Reading a screenshot")):
        return e
    if entry["result"].get("media_kind", "image") == "audio":
        return err("Screenshot checks work on images.", 422)
    try:
        check = await run_in_threadpool(screenshot_check.run_screenshot_check, await run_in_threadpool(_image_bytes, cid, entry))
    except Exception as e:
        return err(f"The screenshot check failed: {type(e).__name__}: {str(e)[:200]}", 502)
    result = screenshot_check.apply_to_result(entry["result"], check)
    entry["result"] = result
    save_result(cid, result)
    custody.record("screenshot_check", result["case"]["sha256"], {"overall": check["overall"], "kind": check["kind"]})
    return ok(_public(result))


async def run_reverse_search(request: Request):
    cid = request.path_params["cid"]
    try:
        entry = load_case(cid)
    except KeyError:
        return err("No such case.", 404)
    if (e := _llm_needed(entry, "Searching for earlier copies")):
        return e
    if entry["result"].get("media_kind", "image") == "audio":
        return err("Reverse search works on images and video frames.", 422)
    import reverse_search
    exif = entry["result"].get("metadata", {}).get("exif", {})
    try:
        res = await run_in_threadpool(reverse_search.run_reverse_search, await run_in_threadpool(_image_bytes, cid, entry),
                                      exif.get("DateTimeOriginal") or exif.get("DateTime", ""))
    except Exception as e:
        return err(f"The search failed: {type(e).__name__}: {str(e)[:200]}", 502)
    res.pop("hashes", None)
    entry["result"]["reverse_search"] = res
    save_result(cid, entry["result"])
    custody.record("reverse_search", entry["result"]["case"]["sha256"],
                   {"verdict": res["verdict"], "matches": [m["url"] for m in res["matches"]][:5]})
    return ok(_public(entry["result"]))


async def compare(request: Request):
    cid = request.path_params["cid"]
    try:
        images = await run_in_threadpool(case_images, cid)
        entry = load_case(cid)
    except KeyError:
        return err("No such case.", 404)
    form = await request.form(max_part_size=MAX_UPLOAD)
    f = form.get("file")
    if f is None:
        return err("Attach the image to compare in the 'file' field.")
    other_bytes = await f.read()
    try:
        other = Image.open(io.BytesIO(other_bytes)).convert("RGB")
    except Exception:
        return err("That file isn't a readable image.", 422)
    stats, diff = await run_in_threadpool(advanced.compare_images, images["original"], other)
    images["compare"] = diff
    images["compare_other"] = other
    stats.update({"other_name": f.filename, "other_sha256": hashlib.sha256(other_bytes).hexdigest()})
    entry["result"]["comparison"] = stats
    save_result(cid, entry["result"])
    custody.record("compared_with_reference", entry["result"]["case"]["sha256"],
                   {"reference_sha256": stats["other_sha256"], "verdict": stats["verdict"]})
    return ok(stats)


async def verify_file(request: Request):
    try:
        entry = load_case(request.path_params["cid"])
    except KeyError:
        return err("No such case.", 404)
    form = await request.form(max_part_size=MAX_UPLOAD)
    f = form.get("file")
    if f is None:
        return err("Attach a file in the 'file' field.")
    sha = hashlib.sha256(await f.read()).hexdigest()
    match = sha == entry["result"]["case"]["sha256"]
    custody.record("integrity_verified", entry["result"]["case"]["sha256"], {"match": match, "checked_sha256": sha})
    return ok({"match": match, "sha256": sha})


def _report_input(cid: str) -> tuple[dict, str]:
    entry = load_case(cid)
    images = case_images(cid)
    sha = entry["result"]["case"]["sha256"]
    hist = custody.history(sha)
    r = {**_public(entry["result"]), "images": images, "custody": {"chain": custody.verify(), "history": hist}}
    return r, (hist[-1]["entry_hash"] if hist else "")


async def report(request: Request):
    cid = request.path_params["cid"]
    try:
        r, _ = await run_in_threadpool(_report_input, cid)
    except KeyError:
        return err("No such case.", 404)
    custody.record("report_exported", r["case"]["sha256"], {"format": "html"})
    html = await run_in_threadpool(build_report_html, r)
    disp = "attachment" if request.query_params.get("download") else "inline"
    return HTMLResponse(html, headers={"Content-Disposition": f'{disp}; filename="trustlens_report_{cid}.html"'})


async def report_pdf(request: Request):
    cid = request.path_params["cid"]
    try:
        import pdf_report
    except ImportError:
        return err("PDF reports need reportlab: pip install reportlab", 501)
    try:
        r, head = await run_in_threadpool(_report_input, cid)
    except KeyError:
        return err("No such case.", 404)
    custody.record("report_exported", r["case"]["sha256"], {"format": "pdf", "signing_key": signing.signer().key_id})
    pdf, token = await run_in_threadpool(pdf_report.build_pdf, r, head)
    disp = "attachment" if request.query_params.get("download") else "inline"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'{disp}; filename="trustlens_report_{cid}.pdf"'})


async def verify_report(request: Request):
    token, pem = "", None
    if request.headers.get("content-type", "").startswith("multipart/"):
        form = await request.form(max_part_size=MAX_UPLOAD)
        f = form.get("file")
        if f is not None:
            from pdf_report import token_from_pdf
            token = token_from_pdf(await f.read())
        token = token or str(form.get("token") or "")
        pem = str(form.get("public_key") or "") or None
    else:
        body = await request.json()
        token, pem = str(body.get("token", "")), body.get("public_key") or None
    if not token:
        return err("No TrustLens report code found. Paste the code under the QR, or upload the report PDF.", 422)
    res = signing.signer().verify(token, pem)
    p = res.get("payload") or {}
    if res["valid"] and p.get("case"):
        try:
            cur = load_case(p["case"])["result"]
            res["case_now"] = {"exists": True, "verdict": cur["verdict"], "score": cur["manipulation_score"],
                               "same_file": cur["case"]["sha256"] == p.get("sha256"),
                               "changed_since": cur["verdict"] != p.get("verdict") or cur["manipulation_score"] != p.get("score")}
        except KeyError:
            res["case_now"] = {"exists": False}
    return ok(res)


async def report_key(request: Request):
    s = signing.signer()
    return ok({"key_id": s.key_id, "algorithm": s.mode, "public_key_pem": s.public_pem})


async def custody_log(request: Request):
    sha = request.query_params.get("sha")
    entries = custody.history(sha) if sha else custody.read()[-300:]
    return ok({"chain": custody.verify(), "entries": entries})


# --------------------------------------------------------------------------- batches

def _batch_analyse(data: bytes, name: str, source: str) -> dict:
    return save_case(data, name, envfile.ai_review_status()[0], source)


_batches: batch.Batches | None = None


def batches() -> batch.Batches:
    global _batches
    if _batches is None:
        _batches = batch.Batches(CASES / "_batches", _batch_analyse)
    return _batches


async def create_batch(request: Request):
    form = await request.form(max_files=batch.MAX_FILES + 5, max_part_size=batch.MAX_ZIP_BYTES)
    uploads = form.getlist("files")
    if not uploads:
        return err("Choose files, or a WhatsApp chat export (.zip).")
    files, chat, skipped, name = [], {}, [], ""
    for f in uploads:
        data = await f.read()
        fname = f.filename or "file"
        if fname.lower().endswith(".zip"):
            try:
                zf, zc, zs = await run_in_threadpool(batch.files_from_zip, data)
            except Exception as e:
                return err(f"Couldn't open {fname}: {type(e).__name__}: {str(e)[:120]}", 422)
            files += zf
            chat.update(zc)
            skipped += zs
            name = name or fname.rsplit(".", 1)[0]
        elif media.kind_of(data, fname) in ("image", "video", "audio") and len(data) <= batch.MAX_FILE_BYTES:
            files.append((fname, data))
        else:
            skipped.append(fname)
    if not files:
        return err("None of those files is an image, video or audio file TrustLens can read.", 422)
    files = files[: batch.MAX_FILES]
    b = batches().create(name or f"{len(files)} files", files, chat, skipped)
    return ok(b, 201)


async def get_batch(request: Request):
    try:
        return ok(batches().get(request.path_params["bid"]))
    except KeyError:
        return err("No such batch.", 404)


async def list_batches(request: Request):
    return ok(batches().list())


# --------------------------------------------------------------------------- phone access (python server.py --lan)

import secrets
import socket

LAN = {"on": False, "port": 8000, "token": secrets.token_urlsafe(9)}
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def lan_ip() -> str:
    """This computer's address on the local network (no traffic is sent: UDP connect only picks a route)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def phone_url() -> str:
    return f"http://{lan_ip()}:{LAN['port']}/?k={LAN['token']}#/check"


class PhoneAccess:
    """With --lan, other devices on the network may only use TrustLens after opening the QR link, which
    carries a secret code (kept in a cookie afterwards). This computer itself never needs the code."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not LAN["on"]:
            return await self.app(scope, receive, send)
        client = (scope.get("client") or ("", 0))[0]
        if client in LOCAL_HOSTS:
            return await self.app(scope, receive, send)
        from urllib.parse import parse_qs
        cookies = {}
        for k, v in scope.get("headers", []):
            if k == b"cookie":
                for part in v.decode("latin-1").split(";"):
                    if "=" in part:
                        a, b = part.strip().split("=", 1)
                        cookies[a] = b
        key = parse_qs(scope.get("query_string", b"").decode()).get("k", [""])[0]
        if cookies.get("tl_access") == LAN["token"]:
            return await self.app(scope, receive, send)
        if key == LAN["token"]:
            async def send_with_cookie(msg):
                if msg["type"] == "http.response.start":
                    msg.setdefault("headers", []).append(
                        (b"set-cookie", f"tl_access={LAN['token']}; Path=/; SameSite=Lax; HttpOnly".encode()))
                await send(msg)
            return await self.app(scope, receive, send_with_cookie)
        body = ("<!doctype html><meta name=viewport content='width=device-width'><body style='font:16px system-ui;"
                "padding:2rem;max-width:30rem'><h1>TrustLens</h1><p>Scan the QR code shown on the TrustLens "
                "computer (\u201cUse on your phone\u201d) to open it here.</p>").encode()
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"text/html; charset=utf-8")]})
        await send({"type": "http.response.body", "body": body})


async def phone_info(request: Request):
    if not LAN["on"]:
        return ok({"on": False, "how": "Start TrustLens with: python server.py --lan"})
    return ok({"on": True, "url": phone_url(), "ip": lan_ip(), "port": LAN["port"]})


async def phone_qr(request: Request):
    if not LAN["on"]:
        return err("Phone access is off. Start TrustLens with: python server.py --lan", 409)
    import cv2
    q = cv2.QRCodeEncoder.create().encode(phone_url())
    q = cv2.copyMakeBorder(q, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=255)  # quiet zone: cameras need it
    im = Image.fromarray(q).convert("L").resize((q.shape[1] * 10, q.shape[0] * 10), Image.NEAREST)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


async def index(request: Request):
    page = WEB / "index.html"
    if not page.exists():
        return HTMLResponse("<h1>TrustLens</h1><p>The interface isn't built. Run <code>npm install && npm run build</code> "
                            "inside <code>web/</code>.</p>", status_code=503)
    return FileResponse(page, headers={"Cache-Control": "no-cache"})


routes = [
    Route("/api/status", status),
    Route("/api/samples", samples),
    Route("/api/samples/{name}", sample_file),
    Route("/api/cases", list_cases),
    Route("/api/cases", create_case, methods=["POST"]),
    Route("/api/cases/{cid}", get_case),
    Route("/api/cases/{cid}", delete_case, methods=["DELETE"]),
    Route("/api/cases/{cid}/reanalyse", reanalyse_case, methods=["POST"]),
    Route("/api/cases/{cid}/layers", case_layers),
    Route("/api/cases/{cid}/image/{kind}", case_image),
    Route("/api/cases/{cid}/media", case_media),
    Route("/api/cases/{cid}/histogram", case_histogram),
    Route("/api/cases/{cid}/notice-check", notice_check, methods=["POST"]),
    Route("/api/cases/{cid}/event-check", run_event_check, methods=["POST"]),
    Route("/api/cases/{cid}/screenshot-check", run_screenshot_check, methods=["POST"]),
    Route("/api/cases/{cid}/reverse-search", run_reverse_search, methods=["POST"]),
    Route("/api/cases/{cid}/compare", compare, methods=["POST"]),
    Route("/api/cases/{cid}/verify-file", verify_file, methods=["POST"]),
    Route("/api/cases/{cid}/report", report),
    Route("/api/cases/{cid}/report.pdf", report_pdf),
    Route("/api/verify-report", verify_report, methods=["POST"]),
    Route("/api/report-key", report_key),
    Route("/api/batches", list_batches),
    Route("/api/batches", create_batch, methods=["POST"]),
    Route("/api/batches/{bid}", get_batch),
    Route("/api/custody", custody_log),
    Route("/api/phone", phone_info),
    Route("/api/phone/qr.png", phone_qr),
    Route("/", index),
]
if (WEB / "assets").exists():
    routes.append(Mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets"))
if (WEB / "fonts").exists():
    routes.append(Mount("/fonts", StaticFiles(directory=WEB / "fonts"), name="fonts"))

app = Starlette(routes=routes)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(PhoneAccess)

if __name__ == "__main__":
    import sys
    import uvicorn
    port = int(os.getenv("TRUSTLENS_PORT", "8000"))
    LAN["on"] = "--lan" in sys.argv or os.getenv("TRUSTLENS_LAN") == "1"
    LAN["port"] = port
    host = "0.0.0.0" if LAN["on"] else "127.0.0.1"
    if os.getenv("TRUSTLENS_NO_BROWSER") != "1":
        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()

    class _Server(uvicorn.Server):
        """Ctrl+C stops the server even while the browser holds connections open or an analysis
        (or cli-top) is still running: a 2-second grace period, then a hard exit. A second Ctrl+C
        exits at once."""
        def handle_exit(self, sig, frame):
            if self.should_exit:
                os._exit(0)
            print("\nStopping TrustLens…", flush=True)
            threading.Timer(2.0, lambda: os._exit(0)).start()
            super().handle_exit(sig, frame)

    config = uvicorn.Config(app, host=host, port=port, log_level="warning", timeout_graceful_shutdown=1)
    print(f"TrustLens is running at http://127.0.0.1:{port}  (press Ctrl+C to stop)", flush=True)
    print(envfile.ai_review_status()[1], flush=True)
    if LAN["on"]:
        print(f"Phone access: ON. Press 'Use on your phone' in TrustLens and scan the QR code ({lan_ip()}:{port}).", flush=True)
        print("  If Windows asks whether to allow Python on networks, choose Allow (private networks).", flush=True)
    try:
        _Server(config).run()
    except KeyboardInterrupt:
        pass
    print("TrustLens stopped.", flush=True)
    os._exit(0)
