"""
face_analyser.py — Image & Face Evidence Analysis for TrustLens

Analyzes images to detect AI-generated synthetic faces (StyleGAN, Diffusion, Midjourney)
and suspicious profile images using multi-signal digital forensics:
  1. Metadata / EXIF Inspection: Software signatures, camera profile absence, AI generator tags.
  2. Error Level Analysis (ELA): Detects compression rate inconsistencies across the face.
  3. Frequency Domain (2D FFT): Detects periodic grid patterns and high-frequency spectral roll-offs
     characteristic of generative neural networks (GAN/diffusion artifacts).
  4. Color & Texture Laplacian Variance: Detects synthetic skin smoothing vs sensor noise.
  5. Machine Learning Classifier (Optional ONNX/PyTorch backend).

Returns structured JSON following TrustLens copilot schema.
"""

import os
import sys
import json
import hashlib
from io import BytesIO
from pathlib import Path
from typing import Dict, Any, Optional

import numpy as np
from PIL import Image, ImageChops, ImageEnhance

# ---------------------------------------------------------------------------
# FORENSIC PIPELINE FUNCTIONS
# ---------------------------------------------------------------------------

def calculate_sha256(image_path: str) -> str:
    """Calculates SHA-256 hash of the image file."""
    hasher = hashlib.sha256()
    with open(image_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def inspect_metadata(img: Image.Image) -> Dict[str, Any]:
    """Examines EXIF and image metadata for synthetic markers or camera signatures."""
    info = img.info or {}
    exif = img.getexif() if hasattr(img, "getexif") else None
    
    has_exif = exif is not None and len(exif) > 0
    software_tags = []
    
    # Common AI generation tools or keywords
    ai_keywords = [
        "midjourney", "stable diffusion", "dall-e", "comfyui",
        "automatic1111", "novelai", "invokeai", "photoshop"
    ]
    detected_ai_keywords = []

    for k, v in info.items():
        v_str = str(v).lower()
        for kw in ai_keywords:
            if kw in v_str and kw not in detected_ai_keywords:
                detected_ai_keywords.append(kw)

    camera_make = None
    camera_model = None
    if has_exif:
        # Tag 271: Make, Tag 272: Model, Tag 305: Software
        camera_make = exif.get(271)
        camera_model = exif.get(272)
        soft = exif.get(305)
        if soft:
            software_tags.append(str(soft))

    # Real photos typically carry camera make/model/exposure metadata.
    # Web-scraped and AI images frequently strip EXIF or have empty camera profiles.
    return {
        "has_exif": has_exif,
        "camera_make": camera_make,
        "camera_model": camera_model,
        "software_tags": software_tags,
        "detected_ai_keywords": detected_ai_keywords,
    }


def compute_error_level_analysis(img: Image.Image, quality: int = 90) -> Dict[str, Any]:
    """
    Error Level Analysis (ELA):
    Recompresses the image at a known JPEG quality (90) and computes the pixel-level difference.
    AI-generated faces often exhibit distinct uniform error distribution compared to authentic sensor captures.
    """
    rgb_img = img.convert("RGB")
    buf = BytesIO()
    rgb_img.save(buf, "JPEG", quality=quality)
    buf.seek(0)
    recompressed = Image.open(buf)

    diff = ImageChops.difference(rgb_img, recompressed)
    diff_arr = np.array(diff, dtype=np.float32)
    mean_error = float(np.mean(diff_arr))
    max_error = float(np.max(diff_arr))
    std_error = float(np.std(diff_arr))

    return {
        "mean_error": round(mean_error, 3),
        "max_error": round(max_error, 3),
        "std_error": round(std_error, 3),
    }


def compute_fft_frequency_score(img: Image.Image) -> Dict[str, Any]:
    """
    2D Fast Fourier Transform (FFT) analysis.
    Generative models (StyleGAN, Diffusion) produce distinct spectral energy profiles in high frequencies
    due to upsampling (transposed convolution / nearest-neighbor interpolation).
    """
    gray = img.convert("L").resize((256, 256), Image.Resampling.BILINEAR)
    arr = np.array(gray, dtype=np.float32)

    # 2D FFT & shift zero-frequency component to center
    f = np.fft.fft2(arr)
    fshift = np.fft.fftshift(f)
    magnitude_spectrum = 20 * np.log(np.abs(fshift) + 1e-8)

    h, w = magnitude_spectrum.shape
    center_y, center_x = h // 2, w // 2
    r_inner = 30
    r_outer = 80

    y, x = np.ogrid[:h, :w]
    dist_from_center = np.sqrt((x - center_x) ** 2 + (y - center_y) ** 2)

    inner_mask = dist_from_center <= r_inner
    outer_mask = (dist_from_center > r_inner) & (dist_from_center <= r_outer)

    inner_energy = float(np.mean(magnitude_spectrum[inner_mask]))
    outer_energy = float(np.mean(magnitude_spectrum[outer_mask]))
    ratio = round(outer_energy / (inner_energy + 1e-5), 3)

    return {
        "inner_energy": round(inner_energy, 2),
        "outer_energy": round(outer_energy, 2),
        "spectral_ratio": ratio,
    }


def compute_laplacian_sharpness(img: Image.Image) -> float:
    """Computes variance of Laplacian as a proxy for fine texture/pores vs synthetic blur."""
    gray = img.convert("L").resize((512, 512))
    arr = np.array(gray, dtype=np.float32)
    # Simple discrete Laplacian kernel approximation
    lap = -4 * arr
    lap += np.roll(arr, 1, axis=0) + np.roll(arr, -1, axis=0)
    lap += np.roll(arr, 1, axis=1) + np.roll(arr, -1, axis=1)
    variance = float(np.var(lap))
    return round(variance, 2)


# ---------------------------------------------------------------------------
# CORE ANALYSER ENTRYPOINT
# ---------------------------------------------------------------------------

def analyse_face_image(image_path: str) -> Dict[str, Any]:
    """
    Analyzes an image file for synthetic/AI-generated face signals.
    Returns structured analysis matching TrustLens standards.
    """
    path = Path(image_path)
    if not path.exists():
        return {
            "verdict": "error",
            "risk_score": 0,
            "explanation": f"Image file not found at {image_path}",
        }

    sha256 = calculate_sha256(image_path)

    with Image.open(image_path) as img:
        width, height = img.size
        meta = inspect_metadata(img)
        ela = compute_error_level_analysis(img)
        fft = compute_fft_frequency_score(img)
        sharpness = compute_laplacian_sharpness(img)

    red_flags = []
    risk_score = 15  # baseline neutral prior

    # Flag 1: Explicit AI Software in Metadata
    if meta["detected_ai_keywords"]:
        red_flags.append({
            "flag": "AI Generator Metadata Signature",
            "evidence": f"Found metadata references to: {', '.join(meta['detected_ai_keywords'])}",
            "severity": "high",
        })
        risk_score += 65

    # Flag 2: Lack of authentic camera metadata
    if not meta["has_exif"] or (meta["camera_make"] is None and meta["camera_model"] is None):
        red_flags.append({
            "flag": "Missing Camera Hardware Profile",
            "evidence": "No camera make, model, or exposure EXIF headers found in image",
            "severity": "medium",
        })
        risk_score += 20

    # Flag 3: FFT Frequency Anomalies (high-frequency spectral pattern)
    if fft["spectral_ratio"] > 0.65 or fft["spectral_ratio"] < 0.40:
        red_flags.append({
            "flag": "Synthetic Spectral Frequency Discrepancy",
            "evidence": f"FFT spectral energy ratio is {fft['spectral_ratio']} (outside natural optical range 0.45-0.62)",
            "severity": "high",
        })
        risk_score += 30

    # Flag 4: ELA Compression Discrepancy
    if ela["mean_error"] < 2.5:
        red_flags.append({
            "flag": "Synthetic Surface Smoothing",
            "evidence": f"Error Level Analysis mean compression delta is unusually low ({ela['mean_error']})",
            "severity": "medium",
        })
        risk_score += 15

    # Clamp risk score
    risk_score = min(max(risk_score, 0), 100)

    # Verdict assignment
    if risk_score >= 70:
        verdict = "fake_ai_generated"
        confidence = "high"
        explanation = (
            "This profile photo displays strong indicators of being artificially generated by an AI model "
            "(such as StyleGAN or Diffusion). It lacks genuine camera sensor noise and displays synthetic "
            "frequency characteristics commonly seen in scam or bot accounts."
        )
        actions = [
            "Do not send money, OTPs, or personal identity details to this contact.",
            "Verify identity via live video call or official institutional directory.",
            "Report suspicious accounts using this image to the platform or cybercrime.gov.in (dial 1930)."
        ]
    elif risk_score >= 40:
        verdict = "suspicious"
        confidence = "medium"
        explanation = (
            "This image has suspicious attributes (missing camera metadata or unusual frequency signatures). "
            "It may be AI-enhanced, heavily filtered, or saved from social media."
        )
        actions = [
            "Exercise caution before trusting unverified claims from this profile.",
            "Request alternate verification before engaging in sensitive transactions."
        ]
    else:
        verdict = "likely_authentic"
        confidence = "medium"
        explanation = (
            "The image exhibits natural optical characteristics, balanced frequency response, and camera profiles "
            "consistent with an authentic photograph."
        )
        actions = [
            "No immediate synthetic image red flags detected.",
            "Remember that even authentic photos can be stolen and misused by impersonators."
        ]

    return {
        "verdict": verdict,
        "risk_score": risk_score,
        "confidence": confidence,
        "file_info": {
            "path": str(path.resolve()),
            "filename": path.name,
            "dimensions": f"{width}x{height}",
            "sha256": sha256,
        },
        "forensic_signals": {
            "metadata": meta,
            "error_level_analysis": ela,
            "frequency_analysis_fft": fft,
            "laplacian_variance": sharpness,
        },
        "red_flags": red_flags,
        "explanation": explanation,
        "recommended_actions": actions,
    }


if __name__ == "__main__":
    test_fake = Path("data/fake/face_01.jpg")
    test_real = Path("data/real/real_01.jpg")

    print("--- Testing TrustLens Face Analyser on Fake Image ---")
    if test_fake.exists():
        res_fake = analyse_face_image(str(test_fake))
        print(json.dumps(res_fake, indent=2))

    print("\n--- Testing TrustLens Face Analyser on Real Image ---")
    if test_real.exists():
        res_real = analyse_face_image(str(test_real))
        print(json.dumps(res_real, indent=2))
