"""
face_swap.py — run the pretrained face-swap detector (face_model.py) on faces in photos and video frames,
and turn its output into evidence: a signal, and a verdict floor when it is confident.

Measured here before it was allowed to decide anything (details in README):
  face-swap videos with a known label        2/2 scored 0.99 on every frame
  real videos (actor clip, phone clip)        2/2 scored about 0.01
  real portraits                              8/8 between 0.01 and 0.02
  simple face swaps made from those portraits 12/24 above 0.5, 10/24 above 0.8
  AI-generated faces, talking-head animation  not detected (about 0.01-0.05): not what it was trained on
So a high score is strong evidence of a face swap; a low score clears nothing.
"""

from __future__ import annotations

import threading
import time

import numpy as np

import face_model
import forensics

NAME = "Face-swap detector"
MAX_FRAMES = 8
FAKE = 0.8


def _face_p(image, box) -> float:
    with np.errstate(over="ignore"):
        return face_model.fake_probability(face_model.crop_face(np.asarray(image.convert("RGB")), box))


def _summarise(rows: list[dict], seconds: float) -> dict:
    ps = [r["p"] for r in rows]
    return {"available": True, "model": "EfficientNet-B7 trained on about 100,000 deepfake videos",
            "frames": rows, "n": len(ps), "score": round(face_model.confident_strategy(ps), 3) if ps else None,
            "fake_frames": sum(p > FAKE for p in ps), "seconds": round(seconds, 1)}


def check_image(image, boxes) -> dict | None:
    """Largest face of a photo. None when there's no face; {'available': False} when the model isn't installed."""
    if not boxes:
        return None
    if not face_model.available():
        return {"available": False}
    t0 = time.perf_counter()
    try:
        return _summarise([{"label": "face 1", "p": round(_face_p(image, boxes[0]), 3)}], time.perf_counter() - t0)
    except Exception as e:  # never let the extra model break an analysis
        return {"available": False, "error": f"{type(e).__name__}: {str(e)[:120]}"}


def start_image(image, boxes):
    """check_image in a background thread, so it runs while the AI review is thinking."""
    job = {"result": None}

    def run():
        job["result"] = check_image(image, boxes)

    job["thread"] = threading.Thread(target=run, daemon=True)
    job["thread"].start()
    return job


def start_frames(frames: list[dict]):
    """Score the largest face in each frame in a background thread (numpy releases the GIL in matrix maths),
    so it runs while the AI review is thinking. Writes f['swap'] on each frame."""
    todo = [f for f in frames if f.get("faces")]
    if not todo:
        return None
    if not face_model.available():
        return {"result": {"available": False}}
    if len(todo) > MAX_FRAMES:
        todo = [todo[int(round(x))] for x in np.linspace(0, len(todo) - 1, MAX_FRAMES)]
    job = {"result": None}

    def run():
        t0 = time.perf_counter()
        rows = []
        try:
            for f in todo:
                p = round(_face_p(f["image"], f["faces"][0]), 3)
                f["swap"] = p
                rows.append({"label": f["label"], "p": p})
            job["result"] = _summarise(rows, time.perf_counter() - t0)
        except Exception as e:
            job["result"] = {"available": False, "error": f"{type(e).__name__}: {str(e)[:120]}"}

    job["thread"] = threading.Thread(target=run, daemon=True)
    job["thread"].start()
    return job


def finish(job) -> dict | None:
    if not job:
        return None
    if job.get("thread"):
        job["thread"].join()
    return job["result"]


def verdict_inputs(swap: dict, video: bool) -> tuple[dict, str, int]:
    """(signal, rule note or '', verdict floor) for one result of this detector."""
    if not swap.get("available"):
        detail = ("Not installed on this computer: run python tools/get_face_model.py once (downloads the "
                  "official 267 MB checkpoint)." if not swap.get("error") else f"Didn't run: {swap['error']}")
        return forensics._signal(NAME, "info", detail), "", 0
    n, score, fake = swap["n"], swap["score"], swap["fake_frames"]
    where = f"{fake} of {n} frames with a face scored as fake" if video else "the face"
    if video:
        confident = n >= 4 and score >= FAKE and fake / n >= 0.5
    else:
        confident = score >= 0.9
    if confident:
        note = (f"The face-swap detector found a swapped face "
                f"({where}; fake probability {score:.0%}).")
        detail = (f"{note} Measured on known clips: face-swap videos scored 99%, real videos and portraits 1–2%. "
                  f"Took {swap['seconds']} s.")
        return forensics._signal(NAME, "high", detail, "face_swap_or_deepfake"), note, (88 if score >= 0.95 else 80) if video else 75
    if score >= 0.5:
        return forensics._signal(NAME, "medium",
                                 f"Possible face swap: fake probability {score:.0%} ({where}). Below the level that "
                                 "decides the verdict; worth a closer look at the face edges and skin.",
                                 "face_swap_or_deepfake"), "", 0
    return forensics._signal(NAME, "info",
                             f"No face swap detected (fake probability {score:.0%}{f', {n} frames' if video else ''}). "
                             "It catches face swaps and face reenactment; it was not trained on fully AI-generated "
                             "faces or animated photos, so this doesn't clear the file."), "", 0
