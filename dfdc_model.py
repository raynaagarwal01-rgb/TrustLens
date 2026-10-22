"""
dfdc_model.py — the winning model of Facebook's Deepfake Detection Challenge (DFDC, 2020), run without PyTorch.

Model: Selim Seferbekov's EfficientNet-B7 face classifier, 1st place of 2,265 teams
(github.com/selimsef/dfdc_deepfake_challenge, MIT licence). Trained on the DFDC dataset:
about 100,000 face-swap and face-reenactment videos of 3,426 paid actors.

The network is re-implemented here in numpy (BatchNorm folded into the convolutions), so the only
extra download is the official checkpoint; `python tools/get_dfdc_model.py` fetches and converts it.

What it is good at: face swaps and reenactment in real-looking video, the DFDC kinds of fake.
What it was never trained on: fully AI-generated faces and images, talking-head animation of a photo.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).parent
MODEL_DIR = Path(os.getenv("DFDC_MODEL_DIR", ROOT / "models" / "dfdc"))
NPZ = MODEL_DIR / "dfdc_b7_111_36.npz"
SOURCE_URL = ("https://github.com/selimsef/dfdc_deepfake_challenge/releases/download/0.0.1/"
              "final_111_DeepFakeClassifier_tf_efficientnet_b7_ns_0_36")
INPUT = 380
EPS = 1e-3            # TensorFlow-port EfficientNets use BatchNorm eps 1e-3
STAGE_STRIDES = (1, 2, 2, 2, 1, 2, 1)
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)


def available() -> bool:
    return NPZ.exists()


# ---------------------------------------------------------------------------
# weights
# ---------------------------------------------------------------------------

def convert(checkpoint: str | Path, out: Path = NPZ) -> Path:
    """Official .pth checkpoint → compact .npz with BatchNorm folded into each convolution."""
    import torch_free
    sd = torch_free.load(checkpoint)
    w: dict[str, np.ndarray] = {}

    def fold(conv: str, bn: str):
        k = sd[f"{conv}.weight"].astype(np.float32)
        g, b, m, v = (sd[f"{bn}.{x}"].astype(np.float32) for x in ("weight", "bias", "running_mean", "running_var"))
        s = g / np.sqrt(v + EPS)
        w[f"{conv}.w"] = k * s[:, None, None, None]
        w[f"{conv}.b"] = b - m * s

    e = "encoder"
    fold(f"{e}.conv_stem", f"{e}.bn1")
    blocks = sorted({tuple(map(int, k.split(".")[2:4])) for k in sd if k.startswith(f"{e}.blocks.")})
    for i, j in blocks:
        p = f"{e}.blocks.{i}.{j}"
        if f"{p}.conv_pwl.weight" in sd:      # inverted residual: expand, depthwise, project
            fold(f"{p}.conv_pw", f"{p}.bn1"); fold(f"{p}.conv_dw", f"{p}.bn2"); fold(f"{p}.conv_pwl", f"{p}.bn3")
        else:                                  # first stage: depthwise, project
            fold(f"{p}.conv_dw", f"{p}.bn1"); fold(f"{p}.conv_pw", f"{p}.bn2")
        for c in ("conv_reduce", "conv_expand"):
            w[f"{p}.se.{c}.w"] = sd[f"{p}.se.{c}.weight"].astype(np.float32)
            w[f"{p}.se.{c}.b"] = sd[f"{p}.se.{c}.bias"].astype(np.float32)
    fold(f"{e}.conv_head", f"{e}.bn2")
    w["fc.w"], w["fc.b"] = sd["fc.weight"].astype(np.float32), sd["fc.bias"].astype(np.float32)
    w["_blocks"] = np.array(blocks, np.int32)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez(out, **w)
    return out


# ---------------------------------------------------------------------------
# network (CHW float32)
# ---------------------------------------------------------------------------

def _silu(x):
    return x * (1.0 / (1.0 + np.exp(-x)))


def _same_pad(x, k, s):
    """TensorFlow 'SAME' padding (extra pixel on the bottom/right), as the TF-ported weights expect."""
    h, w_ = x.shape[1:]
    ph = max((-(-h // s) - 1) * s + k - h, 0)
    pw = max((-(-w_ // s) - 1) * s + k - w_, 0)
    return np.pad(x, ((0, 0), (ph // 2, ph - ph // 2), (pw // 2, pw - pw // 2))), -(-h // s), -(-w_ // s)


def _pw(x, w, b):
    c, h, w_ = x.shape
    return (w.reshape(w.shape[0], c) @ x.reshape(c, h * w_) + b[:, None]).reshape(-1, h, w_)


def _dw(x, w, b, s):
    k = w.shape[-1]
    xp, oh, ow = _same_pad(x, k, s)
    out = np.empty((x.shape[0], oh, ow), np.float32)
    out[:] = b[:, None, None]
    for dy in range(k):
        for dx in range(k):
            out += xp[:, dy:dy + oh * s:s, dx:dx + ow * s:s] * w[:, 0, dy, dx][:, None, None]
    return out


def _stem(x, w, b):
    xp, oh, ow = _same_pad(x, 3, 2)
    cols = np.stack([xp[c, dy:dy + oh * 2:2, dx:dx + ow * 2:2] for c in range(3) for dy in range(3) for dx in range(3)])
    return (w.reshape(w.shape[0], -1) @ cols.reshape(27, -1) + b[:, None]).reshape(-1, oh, ow)


def _se(x, W, p):
    s = x.mean(axis=(1, 2))
    s = _silu(W[f"{p}.se.conv_reduce.w"][:, :, 0, 0] @ s + W[f"{p}.se.conv_reduce.b"])
    s = W[f"{p}.se.conv_expand.w"][:, :, 0, 0] @ s + W[f"{p}.se.conv_expand.b"]
    return x * (1.0 / (1.0 + np.exp(-s)))[:, None, None]


class Classifier:
    def __init__(self, path: Path = NPZ):
        z = np.load(path)
        self.W = {k: z[k] for k in z.files}
        self.blocks = [tuple(b) for b in self.W.pop("_blocks")]

    def logit(self, img: np.ndarray) -> float:
        """img: 3×380×380 normalised float32. Returns the raw score (sigmoid → probability of fake)."""
        W, e = self.W, "encoder"
        x = _silu(_stem(img, W[f"{e}.conv_stem.w"], W[f"{e}.conv_stem.b"]))
        for i, j in self.blocks:
            p = f"{e}.blocks.{i}.{j}"
            s = STAGE_STRIDES[i] if j == 0 else 1
            inp = x
            if f"{p}.conv_pwl.w" in W:
                x = _silu(_pw(x, W[f"{p}.conv_pw.w"], W[f"{p}.conv_pw.b"]))
                x = _silu(_dw(x, W[f"{p}.conv_dw.w"], W[f"{p}.conv_dw.b"], s))
                x = _se(x, W, p)
                x = _pw(x, W[f"{p}.conv_pwl.w"], W[f"{p}.conv_pwl.b"])
            else:
                x = _silu(_dw(x, W[f"{p}.conv_dw.w"], W[f"{p}.conv_dw.b"], s))
                x = _se(x, W, p)
                x = _pw(x, W[f"{p}.conv_pw.w"], W[f"{p}.conv_pw.b"])
            if s == 1 and inp.shape == x.shape:
                x = x + inp
        x = _silu(_pw(x, W[f"{e}.conv_head.w"], W[f"{e}.conv_head.b"]))
        return float(W["fc.w"][0] @ x.mean(axis=(1, 2)) + W["fc.b"][0])


_model: Classifier | None = None
_lock = threading.Lock()


def model() -> Classifier:
    global _model
    with _lock:
        if _model is None:
            _model = Classifier()
        return _model


# ---------------------------------------------------------------------------
# faces in, probability out (preprocessing as in the winning solution)
# ---------------------------------------------------------------------------

def crop_face(rgb: np.ndarray, box) -> np.ndarray:
    """Face box [x0, y0, x1, y1] plus a third of its size on every side, as the DFDC solution crops."""
    x, y = box[0], box[1]
    w, h = box[2] - box[0], box[3] - box[1]
    pw, ph = w // 3, h // 3
    return rgb[max(y - ph, 0):y + h + ph, max(x - pw, 0):x + w + pw]


def prepare(face_rgb: np.ndarray) -> np.ndarray:
    h, w = face_rgb.shape[:2]
    scale = INPUT / max(h, w)
    face = cv2.resize(face_rgb, (int(w * scale), int(h * scale)),
                      interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)[:INPUT, :INPUT]
    canvas = np.zeros((INPUT, INPUT, 3), np.uint8)
    y0, x0 = (INPUT - face.shape[0]) // 2, (INPUT - face.shape[1]) // 2
    canvas[y0:y0 + face.shape[0], x0:x0 + face.shape[1]] = face
    return ((canvas.astype(np.float32) / 255.0 - MEAN) / STD).transpose(2, 0, 1).copy()


def fake_probability(face_rgb: np.ndarray) -> float:
    return float(1.0 / (1.0 + np.exp(-model().logit(prepare(face_rgb)))))


def confident_strategy(pred: list[float], t: float = 0.8) -> float:
    """The winning solution's video score: trust a confident majority of frames, otherwise average."""
    p = np.asarray(pred)
    fakes = int(np.count_nonzero(p > t))
    if fakes > len(p) // 2.5 and fakes > 11:
        return float(p[p > t].mean())
    if np.count_nonzero(p < 0.2) > 0.9 * len(p):
        return float(p[p < 0.2].mean())
    return float(p.mean())
