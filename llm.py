"""
llm.py — one place for LLM calls, shared by every analyser.

Pick a provider with env var LLM_PROVIDER = "gemini" (default) | "groq".
Set LLM_MODEL to whatever current model your key supports.
"""

import json
import os
import re


def call_llm(system: str, user: str, temperature: float = 0.2) -> str:
    provider = os.getenv("LLM_PROVIDER", "gemini").lower()

    if provider == "gemini":
        from google import genai  # pip install google-genai
        from google.genai import types
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        resp = client.models.generate_content(
            model=os.getenv("LLM_MODEL", "gemini-2.5-flash"),
            contents=user,
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
        resp = client.chat.completions.create(
            model=os.environ["LLM_MODEL"],
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
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
