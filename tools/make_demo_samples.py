"""
Re-create the video, voice-note and screenshot demo samples in samples/.

    python tools/make_demo_samples.py <path to SadTalker checkout> <path to speechbrain checkout>

Sources (see samples/README.md):
  Video_ai_talking_head_demo.mp4  SadTalker docs/example_full.gif (Apache-2.0): an AI-generated
                                  portrait animated into a talking head by SadTalker. Re-encoded only.
  Voice_note_original_demo.wav    speechbrain tests/samples/ASR spk1_snt1-3 (Apache-2.0), joined.
  Voice_note_edited_demo.wav      the same recording with a sentence cut out and the gap filled
                                  with 0.4 s of digital silence, as a careless edit would.
  Screenshot_payment_demo.png     a fictional "DemoPay" receipt (not a real app) with three planted
                                  errors: an 11-digit UPI reference, a weekday that doesn't match
                                  the date, and two different amounts.
  Screenshot_chat_demo.png        a fictional chat with message times that go backwards.
"""

import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "samples"


def font(size, bold=False):
    for n in (("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"), "arial.ttf"):
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            pass
    return ImageFont.load_default()


def video(sadtalker: Path):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(sadtalker / "docs/example_full.gif"),
                    "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p", "-c:v", "libx264", "-crf", "20",
                    "-movflags", "+faststart", "-map_metadata", "-1", str(OUT / "Video_ai_talking_head_demo.mp4")], check=True)


def voice(speechbrain: Path):
    parts = []
    for i in (1, 2, 3):
        sr, x = wavfile.read(speechbrain / f"tests/samples/ASR/spk1_snt{i}.wav")
        parts.append(x.astype(np.float32) / 32768)
    gap = np.random.default_rng(0).normal(0, 0.002, int(0.35 * sr)).astype(np.float32)  # room noise between takes
    orig = np.concatenate([parts[0], gap, parts[1], gap, parts[2]])
    wavfile.write(OUT / "Voice_note_original_demo.wav", sr, (orig * 32767).astype(np.int16))
    edited = np.concatenate([parts[0], np.zeros(int(0.4 * sr), np.float32), parts[2]])
    wavfile.write(OUT / "Voice_note_edited_demo.wav", sr, (edited * 32767).astype(np.int16))


def payment():
    W, H = 720, 1400
    im = Image.new("RGB", (W, H), (247, 249, 250))
    d = ImageDraw.Draw(im)
    d.text((28, 22), "9:41", font=font(26, True), fill=(20, 32, 43))
    d.text((W - 120, 22), "4G  82%", font=font(22), fill=(20, 32, 43))
    d.rectangle((0, 80, W, 420), fill=(29, 110, 82))
    d.ellipse((W // 2 - 60, 120, W // 2 + 60, 240), fill=(255, 255, 255))
    d.line((W // 2 - 28, 182, W // 2 - 6, 204, W // 2 + 32, 160), fill=(29, 110, 82), width=10)
    d.text((W // 2, 280), "Payment successful", font=font(34, True), fill=(255, 255, 255), anchor="mm")
    d.text((W // 2, 350), "₹25,000", font=font(64, True), fill=(255, 255, 255), anchor="mm")
    rows = [("Paid to", "Hostel Fee Collection"), ("UPI ID", "hostelfees.demo@okdemo"), ("Amount", "₹2,500.00"),
            ("Date", "Friday, 22 Oct 2026"), ("Time", "10:12 AM"), ("UPI transaction ID", "61234567890"),
            ("From", "Student account ••4821")]
    y = 470
    for k, v in rows:
        d.text((40, y), k, font=font(24), fill=(86, 99, 112))
        d.text((40, y + 34), v, font=font(30, True), fill=(20, 32, 43))
        d.line((40, y + 84, W - 40, y + 84), fill=(195, 205, 213), width=2)
        y += 104
    d.text((W // 2, H - 60), "DemoPay · fictional app · TrustLens demo sample", font=font(20), fill=(150, 160, 170), anchor="mm")
    im.save(OUT / "Screenshot_payment_demo.png")


def chat():
    W, H = 720, 1280
    im = Image.new("RGB", (W, H), (231, 236, 239))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, W, 150), fill=(20, 32, 43))
    d.text((28, 20), "10:05", font=font(24, True), fill=(255, 255, 255))
    d.text((W - 110, 20), "5G  64%", font=font(20), fill=(255, 255, 255))
    d.text((40, 80), "Class Rep (demo)", font=font(32, True), fill=(255, 255, 255))
    d.rounded_rectangle((W // 2 - 60, 175, W // 2 + 60, 215), 12, fill=(255, 255, 255))
    d.text((W // 2, 195), "Today", font=font(20, True), fill=(86, 99, 112), anchor="mm")
    msgs = [("other", "Fee for the trip is due today, pay\nto my UPI before 12", "9:52"),
            ("me", "Which UPI?", "9:58"),
            ("other", "classrep.demo@okdemo, ₹1,500.\nDon't tell the HOD, it's urgent", "9:55"),
            ("me", "Ok sending now", "10:01")]
    y = 250
    for who, text, t in msgs:
        lines = text.split("\n")
        h = 40 * len(lines) + 50
        x0, x1 = (30, 520) if who == "other" else (200, 690)
        d.rounded_rectangle((x0, y, x1, y + h), 18, fill=(255, 255, 255) if who == "other" else (214, 236, 222))
        for i, line in enumerate(lines):
            d.text((x0 + 20, y + 16 + i * 40), line, font=font(26), fill=(20, 32, 43))
        d.text((x1 - 20, y + h - 14), t, font=font(18), fill=(86, 99, 112), anchor="rb")
        y += h + 24
    d.text((W // 2, H - 40), "fictional chat · TrustLens demo sample", font=font(20), fill=(150, 160, 170), anchor="mm")
    im.save(OUT / "Screenshot_chat_demo.png")


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        video(Path(sys.argv[1]))
        voice(Path(sys.argv[2]))
    payment()
    chat()
    print("Samples written to", OUT)
