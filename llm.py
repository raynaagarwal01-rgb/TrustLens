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


def parse_json(raw) -> dict:
    """Parse an LLM reply that should be JSON, tolerating ```json fences."""
    if isinstance(raw, dict):
        return raw
    return json.loads(re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.M))
