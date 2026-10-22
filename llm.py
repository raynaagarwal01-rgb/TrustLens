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


def call_llm(system: str, user: str, temperature: float = 0.2,
             images: list[tuple[bytes, str]] | None = None) -> str:
    """images: optional list of (bytes, mime_type), sent before the text."""
    provider = os.getenv("LLM_PROVIDER", "gemini").lower()
    images = images or []

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
