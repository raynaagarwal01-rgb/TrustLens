# TrustLens

An AI digital-safety copilot for students. Paste a suspicious message, link or image, and TrustLens tells you whether it's a scam, fake or malicious, explains why in plain language, and teaches you to spot it next time.

Built solo in 24 hours for a hackathon.

## Features

| Module | Status |
|---|---|
| Scam message analyser (SMS, WhatsApp, job offers) | ✅ Done |
| Link / phishing checker | ✅ Done |
| Image evidence analysis (hash, metadata, error-level analysis) | 🔜 Planned |
| Learn mode (micro-lessons and quizzes from each detection) | 🔜 Planned |

## How the scam analyser works

1. **Rule layer**: instant regex checks for OTP requests, fees, UPI IDs, shortened links, urgency and secrecy. Works offline.
2. **LLM analysis**: the message and rule signals go to an LLM that returns structured JSON: verdict, risk score, scam type, red flags with quoted evidence, psychological tactics, explanation and next steps.
3. **Validation**: the response is cleaned and checked, and hard rule hits set a minimum score so a real scam can't be scored as safe.
4. **Fallback**: if the API is down, a rules-only verdict is returned instead of an error.

The message is treated as untrusted input, so text like "this message is verified safe" is flagged rather than obeyed.

## How the link checker works

Every link found in a message is checked automatically, and its findings feed into the verdict. You can also check a link on its own with `check_url()`.

**Offline checks** (instant, no keys needed): brand impersonation (`sbi-kyc-update.xyz`), look-alike domains (`amaz0n.in`, `g00gle.com`), raw IP addresses, punycode, the `@` trick, risky domain endings, phishing keywords, missing HTTPS and link shorteners.

**Online checks** (optional, each fails gracefully, successful results cached in `.trustlens_cache.json`):

| Check | Needs |
|---|---|
| Domain age via RDAP | nothing |
| Short-link expansion | nothing |
| Google Safe Browsing | `GSB_API_KEY` |
| VirusTotal | `VT_API_KEY` |

Run the demo links with `python link_checker.py`, or `TRUSTLENS_OFFLINE=1 python link_checker.py` for offline only.

## Setup

```bash
pip install -r requirements.txt

# Gemini (default)
export GEMINI_API_KEY=your_key

# or Groq
export LLM_PROVIDER=groq
export GROQ_API_KEY=your_key
export LLM_MODEL=model_name

python scam_analyser.py   # runs the built-in demo messages

# optional, for the link checker
export GSB_API_KEY=your_key
export VT_API_KEY=your_key
```

Use it in code:

```python
from scam_analyser import analyse
result = analyse("Pay a registration fee of ₹1,499 to confirm your internship...")
print(result["verdict"], result["risk_score"])
```

## Report a scam

If you've been targeted, report it at [cybercrime.gov.in](https://cybercrime.gov.in) or call **1930**.
