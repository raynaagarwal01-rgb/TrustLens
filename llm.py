"""
llm.py — one place for LLM calls, shared by every analyser.

Pick a provider with env var LLM_PROVIDER = "gemini" (default) | "groq".
Set LLM_MODEL to whatever current model your key supports (for images, a vision model).
"""

import base64
import json
import os
import re

import envfile  # noqa: F401  (loads .env so the key survives new terminals)


_LIMITS = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".trustlens_models.json")


def _model_key() -> str:
    return f"{os.getenv('LLM_PROVIDER', 'gemini').lower()}:{os.getenv('LLM_MODEL', '')}"


def _remembered_one_image() -> bool:
    try:
        return bool(json.load(open(_LIMITS)).get(_model_key(), {}).get("one_image"))
    except Exception:
        return False


def _remember_one_image():
    try:
        data = json.load(open(_LIMITS)) if os.path.exists(_LIMITS) else {}
        data[_model_key()] = {"one_image": True}
        json.dump(data, open(_LIMITS, "w"))
    except Exception:
        pass


_one_image_only = os.getenv("LLM_MAX_IMAGES", "") == "1" or _remembered_one_image()


def combine_images(images: list[tuple[bytes, str]]) -> tuple[bytes, str]:
    """Several images as one labelled picture, for models that accept one image: IMAGE 1 across the full
    width (it is the main evidence, often a frame sheet), the rest side by side underneath."""
    import io
    from PIL import Image, ImageDraw, ImageFont
    W = 1536
    ims = [Image.open(io.BytesIO(b)).convert("RGB") for b, _ in images]
    first = ims[0].copy()
    first.thumbnail((W, 1400))
    rest = ims[1:]
    cell = W // max(1, len(rest)) if rest else W
    for im in rest:
        im.thumbnail((cell, cell))
    rest_h = (max(im.height for im in rest) + 34) if rest else 0
    sheet = Image.new("RGB", (W, first.height + 34 + rest_h), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    font = None
    for name in ("DejaVuSans-Bold.ttf", "arialbd.ttf"):
        try:
            font = ImageFont.truetype(name, 22)
            break
        except OSError:
            continue
    font = font or ImageFont.load_default()
    d.text((6, 4), "IMAGE 1", fill=(0, 0, 0), font=font)
    sheet.paste(first, (0, 30))
    y = first.height + 34
    for i, im in enumerate(rest):
        d.text((i * cell + 6, y + 4), f"IMAGE {i + 2}", fill=(0, 0, 0), font=font)
        sheet.paste(im, (i * cell, y + 30))
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=88)
    return buf.getvalue(), "image/jpeg"


def _too_many_images(e: Exception) -> bool:
    m = str(e).lower()
    return "image" in m and any(w in m for w in ("too many", "at most", "maximum", "only one", "only 1", "max"))


def call_llm(system: str, user: str, temperature: float = 0.2,
             images: list[tuple[bytes, str]] | None = None) -> str:
    """images: optional list of (bytes, mime_type), sent before the text. If the model accepts fewer images
    than given, they are combined into one labelled picture and the call is retried (remembered afterwards)."""
    global _one_image_only
    images = images or []
    pictures = [i for i in images if i[1].startswith("image/")]
    if _one_image_only and len(pictures) > 1:
        return _call(system, _combined_note(user, len(pictures)), temperature, [combine_images(pictures)] +
                     [i for i in images if not i[1].startswith("image/")])
    try:
        return _call(system, user, temperature, images)
    except Exception as e:
        if len(pictures) > 1 and _too_many_images(e):
            _one_image_only = True
            _remember_one_image()
            return _call(system, _combined_note(user, len(pictures)), temperature, [combine_images(pictures)] +
                         [i for i in images if not i[1].startswith("image/")])
        raise


def _combined_note(user: str, n: int) -> str:
    return (f"NOTE: the {n} images were combined into one picture; each panel is labelled IMAGE 1 to IMAGE {n} "
            f"in the order described above.\n\n{user}")


def _call(system: str, user: str, temperature: float, images: list[tuple[bytes, str]]) -> str:
    provider = os.getenv("LLM_PROVIDER", "gemini").lower()

    if provider == "gemini":
        from google import genai  # pip install google-genai
        from google.genai import types
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        parts = [types.Part.from_bytes(data=b, mime_type=m) for b, m in images] + [user]
        resp = client.models.generate_content(
            model=os.getenv("LLM_MODEL", "gemini-2.5-flash"),
            contents=parts,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                temperature=temperature,
            ),
        )
        return resp.text

    if provider == "groq":
        from groq import Groq  # pip install groq
        client = Groq(api_key=os.environ["GROQ_API_KEY"])
        if images:
            content = [{"type": "image_url", "image_url": {
                "url": f"data:{m};base64,{base64.b64encode(b).decode()}"}} for b, m in images]
            content.append({"type": "text", "text": user})
        else:
            content = user
        resp = client.chat.completions.create(
            model=os.environ["LLM_MODEL"],
            messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
            response_format={"type": "json_object"},
            temperature=temperature,
        )
        return resp.choices[0].message.content

    raise ValueError(f"Unknown LLM_PROVIDER: {provider}")


AUDIO_MIME = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg", ".opus": "audio/ogg",
              ".m4a": "audio/mp4", ".aac": "audio/aac", ".flac": "audio/flac", ".amr": "audio/amr",
              ".webm": "audio/webm", ".mp4": "audio/mp4"}


def transcribe(audio: bytes, filename: str) -> dict:
    """Speech to text: {"text", "language", "segments": [{"start", "end", "text"}]}.
    Groq uses Whisper (GROQ_STT_MODEL, default whisper-large-v3-turbo); Gemini listens to the audio."""
    provider = os.getenv("LLM_PROVIDER", "gemini").lower()
    ext = os.path.splitext(filename)[1].lower()
    if provider == "groq":
        from groq import Groq
        client = Groq(api_key=os.environ["GROQ_API_KEY"])
        name = filename if ext in AUDIO_MIME else filename + ".mp3"
        resp = client.audio.transcriptions.create(
            file=(name, audio), model=os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo"),
            response_format="verbose_json", temperature=0.0)
        data = resp if isinstance(resp, dict) else getattr(resp, "model_dump", lambda: resp.__dict__)()
        segs = [{"start": round(float(s.get("start", 0)), 2), "end": round(float(s.get("end", 0)), 2),
                 "text": str(s.get("text", "")).strip()} for s in (data.get("segments") or []) if isinstance(s, dict)]
        return {"text": str(data.get("text", "")), "language": str(data.get("language", "")), "segments": segs}
    if provider == "gemini":
        raw = call_llm("Transcribe this audio exactly, in its original language. Respond with JSON: "
                       '{"text": "...", "language": "...", "segments": [{"start": seconds, "end": seconds, "text": "..."}]}',
                       "Transcribe the attached audio.", temperature=0.0,
                       images=[(audio, AUDIO_MIME.get(ext, "audio/mpeg"))])
        d = parse_json(raw)
        return {"text": str(d.get("text", "")), "language": str(d.get("language", "")),
                "segments": [s for s in d.get("segments") or [] if isinstance(s, dict)]}
    raise ValueError(f"Unknown LLM_PROVIDER: {provider}")


def parse_json(raw) -> dict:
    """Parse an LLM reply that should be JSON, tolerating ```json fences."""
    if isinstance(raw, dict):
        return raw
    return json.loads(re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.M))
