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


def _model_key(provider: str | None = None, model: str | None = None) -> str:
    if provider is None:
        provider, model = os.getenv("LLM_PROVIDER", "gemini").lower(), os.getenv("LLM_MODEL", "")
    return f"{provider}:{model or ''}"


def _remembered_one_image(key: str | None = None) -> bool:
    try:
        return bool(json.load(open(_LIMITS)).get(key or _model_key(), {}).get("one_image"))
    except Exception:
        return False


def _remember_one_image(key: str | None = None):
    try:
        data = json.load(open(_LIMITS)) if os.path.exists(_LIMITS) else {}
        data[key or _model_key()] = {"one_image": True}
        json.dump(data, open(_LIMITS, "w"))
    except Exception:
        pass


_one_image: dict[str, bool] = {}


def _is_one_image(key: str) -> bool:
    if key not in _one_image:
        _one_image[key] = os.getenv("LLM_MAX_IMAGES", "") == "1" or _remembered_one_image(key)
    return _one_image[key]

# ---------------------------------------------------------------------------
# Fallbacks: free tiers have per-minute and per-day limits per model. When the chosen model is
# rate-limited or down, try the next one instead of dropping the AI review.
# ---------------------------------------------------------------------------

# Groq's vision models (console.groq.com/docs/vision, Oct 2026): qwen/qwen3.8-27b, and muse-spark-open in limited
# preview (skipped automatically without access). The dependable backup is a Gemini key in .env.
GROQ_VISION_FALLBACKS = ("meta-models/muse-spark-open",)
_resting: dict[str, float] = {}   # model key -> time it may be tried again
last_model = ""                   # which model answered the most recent call (shown in the terminal)


def _candidates() -> list[tuple[str, str]]:
    provider = os.getenv("LLM_PROVIDER", "gemini").lower()
    out = [(provider, os.getenv("LLM_MODEL", "gemini-3.8-flash" if provider == "gemini" else ""))]
    if os.getenv("GROQ_API_KEY"):
        extra = [m.strip() for m in os.getenv("LLM_FALLBACK_MODELS", ",".join(GROQ_VISION_FALLBACKS)).split(",") if m.strip()]
        out += [("groq", m) for m in extra]
    if os.getenv("GEMINI_API_KEY"):
        # current models first; 2.5 Flash still works for keys that used it before (ai.google.dev/gemini-api/docs/models)
        out += [("gemini", os.getenv("GEMINI_MODEL", "gemini-3.8-flash")), ("gemini", "gemini-3.5-flash-lite"),
                ("gemini", "gemini-2.5-flash")]
    seen, uniq = set(), []
    for c in out:
        if c[1] and c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def _wait_seconds(e: Exception) -> float | None:
    """Groq says 'Please try again in 7.5s' or '1m2.5s' or '2h3m'. Returns seconds, or None."""
    m = re.search(r"try again in ((?:\d+h)?(?:\d+m(?!s))?(?:[\d.]+s)?)", str(e))
    if not m or not m.group(1):
        return None
    t = 0.0
    for num, unit in re.findall(r"([\d.]+)([hms])", m.group(1)):
        t += float(num) * {"h": 3600, "m": 60, "s": 1}[unit]
    return t


def _switchable(e: Exception) -> bool:
    """Rate limits, overload, a model that doesn't exist (any more) or can't see images: try the next model."""
    m = str(e).lower()
    name = type(e).__name__.lower()
    return any(w in name for w in ("ratelimit", "notfound", "internalserver", "serviceunavailable", "apiconnection", "timeout")) or \
        any(w in m for w in ("429", "rate limit", "resource_exhausted", "quota", "503", "502", "overloaded", "unavailable",
                             "model_not_found", "does not exist", "403", "permission", "access", "decommissioned", "not found", "does not support image",
                             "vision", "image input"))


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
    than given, they are combined into one labelled picture and the call is retried (remembered afterwards).
    If the model is rate-limited or unavailable, a short wait is taken once, then the next model is tried."""
    import time
    global last_model
    images = images or []
    pictures = [i for i in images if i[1].startswith("image/")]
    others = [i for i in images if not i[1].startswith("image/")]
    errors = []
    for provider, model in _candidates():
        key = _model_key(provider, model)
        if _resting.get(key, 0) > time.time():
            continue
        for attempt in range(2):
            try:
                if _is_one_image(key) and len(pictures) > 1:
                    out = _call(system, _combined_note(user, len(pictures)), temperature,
                                [combine_images(pictures)] + others, provider, model)
                else:
                    try:
                        out = _call(system, user, temperature, images, provider, model)
                    except Exception as e:
                        if len(pictures) > 1 and _too_many_images(e):
                            _one_image[key] = True
                            _remember_one_image(key)
                            out = _call(system, _combined_note(user, len(pictures)), temperature,
                                        [combine_images(pictures)] + others, provider, model)
                        else:
                            raise
                if last_model and last_model != key:
                    print(f"AI review: answered by {model}", flush=True)
                last_model = key
                return out
            except Exception as e:
                if not _switchable(e):
                    raise
                wait = _wait_seconds(e)
                if attempt == 0 and wait is not None and wait <= 25:
                    time.sleep(wait + 0.5)       # a per-minute limit about to reset: wait once
                    continue
                _resting[key] = time.time() + (wait if wait else 60)
                errors.append(f"{model}: {str(e)[:140]}")
                print(f"AI review: {model} unavailable ({type(e).__name__}), trying the next model", flush=True)
                break
    raise RuntimeError("Every AI model is rate-limited or unavailable right now. " + " | ".join(errors[-3:]))


def _combined_note(user: str, n: int) -> str:
    return (f"NOTE: the {n} images were combined into one picture; each panel is labelled IMAGE 1 to IMAGE {n} "
            f"in the order described above.\n\n{user}")


def _call(system: str, user: str, temperature: float, images: list[tuple[bytes, str]],
          provider: str | None = None, model: str | None = None) -> str:
    provider = provider or os.getenv("LLM_PROVIDER", "gemini").lower()
    model = model or os.getenv("LLM_MODEL", "gemini-3.8-flash" if provider == "gemini" else "")

    if provider == "gemini":
        from google import genai  # pip install google-genai
        from google.genai import types
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        parts = [types.Part.from_bytes(data=b, mime_type=m) for b, m in images] + [user]
        resp = client.models.generate_content(
            model=model,
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
            model=model,
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
