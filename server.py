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
import os

import envfile  # loads .env before anything reads the key
import shutil
import threading
import time
import webbrowser
from pathlib import Path

import numpy as np
from PIL import Image
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

import advanced
import campus_check
import custody
import event_check
import evidence_analyser as ea
import forensics
import vtop
from report import build_report_html

ROOT = Path(__file__).resolve().parent
CASES = Path(os.getenv("TRUSTLENS_CASES", ROOT / "cases"))
SAMPLES = ROOT / "samples"
WEB = ROOT / "web" / "dist"
MAX_UPLOAD = 40 * 1024 * 1024
IMAGE_TYPES = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff")

_cache: dict[str, dict] = {}       # case id -> {"result", "images", "data", "name"}
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
    return {k: v for k, v in result.items() if k != "images"}


def sample_label(name: str) -> tuple[str, str]:
    groups = [("Tp_", "Tampered photo (CASIA dataset)"), ("Au_", "Authentic photo"), ("AI_", "AI-generated image"),
              ("Edited_", "Edited photo"), ("Forged_", "Forged notice"), ("Notice_", "Genuine notice"),
              ("Event_", "Event poster")]
    for prefix, label in groups:
        if name.startswith(prefix):
            return prefix.rstrip("_").lower(), label
    return "other", "Sample"


def save_case(data: bytes, name: str, use_llm: bool, source: str) -> dict:
    sha = hashlib.sha256(data).hexdigest()
    cid = case_id(sha)
    d = CASES / cid
    d.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in Path(name).name if c.isalnum() or c in "._- ")[:80] or "evidence"
    (d / "original.bin").write_bytes(data)
    result = ea.analyse(data, safe, use_llm=use_llm)
    images = result.pop("images")
    gt = SAMPLES / (Path(name).stem + "_gt.png")
    if source == "sample" and gt.exists():
        images["ground_truth"] = Image.open(gt).convert("L")
    meta = {"id": cid, "sha256": sha, "name": safe, "source": source, "created": time.time(), "use_llm": use_llm}
    result["case"] = meta
    (d / "result.json").write_text(json.dumps(result, default=_json_default), encoding="utf-8")
    with _lock:
        _cache[cid] = {"result": result, "images": images, "data": data}
    custody.record("analysed", sha, {"file": safe, "case": cid, "verdict": result["verdict"],
                                     "score": result["manipulation_score"], "tool": result["tool_version"],
                                     "ai_analysis": result["llm_used"]})
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
    """Re-create analysis images on demand (they are not stored on disk)."""
    entry = load_case(cid)
    if entry["images"] is None:
        fx = forensics.analyse_image(entry["data"], entry["result"]["case"]["name"])
        images = fx["images"]
        try:
            raw = Image.open(io.BytesIO(entry["data"])).convert("RGB")
            images.update(advanced.run_all(images["original"], entry["data"], fx["jpeg_quality"], raw)[2])
        except Exception:
            pass
        gt = SAMPLES / (Path(entry["result"]["case"]["name"]).stem + "_gt.png")
        if entry["result"]["case"]["source"] == "sample" and gt.exists():
            images["ground_truth"] = Image.open(gt).convert("L")
        entry["images"] = images
    return entry["images"]


def save_result(cid: str, result: dict):
    (_case_dir(cid) / "result.json").write_text(json.dumps(result, default=_json_default), encoding="utf-8")

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
    clitop = shutil.which(os.getenv("CLITOP_PATH", "cli-top")) or (os.path.exists(os.getenv("CLITOP_PATH", "")) or None)
    snaps = sorted(p.stem for p in Path(vtop.SNAPSHOT_DIR).glob("*.txt")) if Path(vtop.SNAPSHOT_DIR).exists() else []
    return ok({
        "llm": {"provider": provider, "configured": bool(key), "model": os.getenv("LLM_MODEL", "")},
        "opencv": advanced.cv2 is not None,
        "c2pa_verification": c2pa_ok,
        "vtop": {"cli_top_found": bool(clitop), "snapshots": snaps},
        "custody": custody.verify(),
        "version": ea.VERSION,
    })


async def samples(request: Request):
    out = []
    for p in sorted(SAMPLES.iterdir()) if SAMPLES.exists() else []:
        if p.suffix.lower() in IMAGE_TYPES and not p.stem.endswith("_gt"):
            group, label = sample_label(p.name)
            out.append({"name": p.name, "group": group, "label": label,
                        "ground_truth": (SAMPLES / (p.stem + "_gt.png")).exists()})
    return ok(out)


async def sample_file(request: Request):
    name = request.path_params["name"]
    p = (SAMPLES / name).resolve()
    if p.parent != SAMPLES.resolve() or not p.exists():
        return err("No such sample.", 404)
    w = int(request.query_params.get("w", "0") or 0)
    if w:
        im = Image.open(p).convert("RGB")
        im.thumbnail((w, w))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        return Response(buf.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})
    return FileResponse(p)


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
                c = r.get("case", {})
                out.append({**c, "verdict": r.get("verdict"), "verdict_label": r.get("verdict_label"),
                            "score": r.get("manipulation_score"), "fake_type_label": r.get("fake_type_label")})
    out.sort(key=lambda c: -c.get("created", 0))
    return ok(out)


async def create_case(request: Request):
    use_llm = request.query_params.get("ai", "1") != "0" and envfile.ai_review_status()[0]
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("multipart/"):
        form = await request.form(max_part_size=MAX_UPLOAD)
        f = form.get("file")
        if f is None:
            return err("Attach an image in the 'file' field.")
        data, name, source = await f.read(), f.filename or "upload", "upload"
    else:
        body = await request.json()
        name = body.get("sample", "")
        p = (SAMPLES / name).resolve()
        if p.parent != SAMPLES.resolve() or not p.exists():
            return err("That sample doesn't exist.", 404)
        data, source = p.read_bytes(), "sample"
    if len(data) > MAX_UPLOAD:
        return err("That file is larger than 40 MB.", 413)
    try:
        result = await run_in_threadpool(save_case, data, name, use_llm, source)
    except ValueError as e:
        return err(str(e), 422)
    return ok(_public(result), 201)


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
    elif kind in advanced.LAYERS:
        im = await run_in_threadpool(advanced.layer, images["original"], kind)
        images[kind] = im
    else:
        return err(f"No '{kind}' layer for this case.", 404)
    fmt = "PNG" if kind in ("ground_truth", "bitplane") else "JPEG"
    body = await run_in_threadpool(_encode, im, max_side, fmt)
    return Response(body, media_type=f"image/{fmt.lower()}", headers={"Cache-Control": "max-age=86400"})


async def case_layers(request: Request):
    cid = request.path_params["cid"]
    try:
        images = await run_in_threadpool(case_images, cid)
    except KeyError:
        return err("No such case.", 404)
    verdict_layers = [k for k in ("ela", "ghost", "copy_move", "compare", "thumbnail", "noise") if images.get(k) is not None]
    return ok({"available": verdict_layers + (["ground_truth"] if images.get("ground_truth") is not None else []),
               "inspection": advanced.LAYERS})


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
    if not entry["result"].get("llm_used"):
        return err("Reading a notice needs AI analysis. Add an API key and re-run the case.", 409)
    try:
        check = await run_in_threadpool(campus_check.run_campus_check, entry["data"], bool(body.get("live")))
    except Exception as e:
        return err(f"The notice check failed: {type(e).__name__}: {str(e)[:200]}", 502)
    result = campus_check.apply_to_result(entry["result"], check)
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
    if not entry["result"].get("llm_used"):
        return err("Reading a poster needs AI analysis. Add an API key and re-run the case.", 409)
    try:
        check = await run_in_threadpool(event_check.run_event_check, entry["data"], bool(body.get("live")))
    except Exception as e:
        return err(f"The event check failed: {type(e).__name__}: {str(e)[:200]}", 502)
    entry["result"]["event_check"] = check
    save_result(cid, entry["result"])
    custody.record("event_check", entry["result"]["case"]["sha256"],
                   {"verdict": check["verdict"], "event": check["event"]["event_name"]})
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


async def report(request: Request):
    cid = request.path_params["cid"]
    try:
        entry = load_case(cid)
        images = await run_in_threadpool(case_images, cid)
    except KeyError:
        return err("No such case.", 404)
    sha = entry["result"]["case"]["sha256"]
    custody.record("report_exported", sha, {"format": "html"})
    r = {**entry["result"], "images": images, "custody": {"chain": custody.verify(), "history": custody.history(sha)}}
    html = await run_in_threadpool(build_report_html, r)
    disp = "attachment" if request.query_params.get("download") else "inline"
    return HTMLResponse(html, headers={"Content-Disposition": f'{disp}; filename="trustlens_report_{cid}.html"'})


async def custody_log(request: Request):
    sha = request.query_params.get("sha")
    entries = custody.history(sha) if sha else custody.read()[-300:]
    return ok({"chain": custody.verify(), "entries": entries})


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
    Route("/api/cases/{cid}/layers", case_layers),
    Route("/api/cases/{cid}/image/{kind}", case_image),
    Route("/api/cases/{cid}/histogram", case_histogram),
    Route("/api/cases/{cid}/notice-check", notice_check, methods=["POST"]),
    Route("/api/cases/{cid}/event-check", run_event_check, methods=["POST"]),
    Route("/api/cases/{cid}/compare", compare, methods=["POST"]),
    Route("/api/cases/{cid}/verify-file", verify_file, methods=["POST"]),
    Route("/api/cases/{cid}/report", report),
    Route("/api/custody", custody_log),
    Route("/", index),
]
if (WEB / "assets").exists():
    routes.append(Mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets"))
if (WEB / "fonts").exists():
    routes.append(Mount("/fonts", StaticFiles(directory=WEB / "fonts"), name="fonts"))

app = Starlette(routes=routes)
app.add_middleware(GZipMiddleware, minimum_size=1000)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("TRUSTLENS_PORT", "8000"))
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

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", timeout_graceful_shutdown=1)
    print(f"TrustLens is running at http://127.0.0.1:{port}  (press Ctrl+C to stop)", flush=True)
    print(envfile.ai_review_status()[1], flush=True)
    try:
        _Server(config).run()
    except KeyboardInterrupt:
        pass
    print("TrustLens stopped.", flush=True)
    os._exit(0)
