"""
envfile.py: load settings such as GROQ_API_KEY from a `.env` file next to this script, so the key
doesn't have to be set again in every new terminal. Variables already set in the terminal win.

.env format, one per line:
    GROQ_API_KEY=gsk_...
    LLM_PROVIDER=groq
    LLM_MODEL=qwen/qwen3.8-27b
"""

import os
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent / ".env"


def load(path: Path = ENV_PATH) -> list[str]:
    """Set variables from the file that aren't already set. Returns the names it set."""
    loaded = []
    try:
        raw = path.read_bytes()
    except OSError:
        return loaded
    # PowerShell's ">" writes UTF-16; Notepad may add a UTF-8 BOM
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig", "replace")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.lower().startswith("export "):
            line = line[7:]
        name, value = (s.strip() for s in line.split("=", 1))
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name and value and not os.environ.get(name):
            os.environ[name] = value
            loaded.append(name)
    return loaded


def ai_review_status() -> tuple[bool, str]:
    """(configured, one-line description) for the AI visual review."""
    provider = os.getenv("LLM_PROVIDER", "gemini").lower()
    key_name = "GEMINI_API_KEY" if provider == "gemini" else "GROQ_API_KEY"
    if not os.getenv(key_name):
        return False, f"AI review: OFF (no {key_name}). Put it in {ENV_PATH.name} to turn it on."
    if provider == "groq" and not os.getenv("LLM_MODEL"):
        return False, "AI review: OFF (LLM_PROVIDER=groq needs LLM_MODEL, e.g. qwen/qwen3.8-27b)."
    return True, f"AI review: ON ({provider}, {os.getenv('LLM_MODEL') or 'gemini-2.5-flash'})"


load()
