# TrustLens

A misinformation detector for university students. TrustLens checks news, social posts and WhatsApp forwards, and verifies **campus rumours against official college records from VTOP** (via [cli-top](https://cli-top.acmvit.in)), so "CAT-2 is postponed, forward to all!" gets checked against the actual announcements and exam schedule.

Built solo in 24 hours for a hackathon (Track 3: AI-Powered Misinformation and Fake News Detection).

## Features

| Module | Status |
|---|---|
| Misinformation analyser (`misinfo_analyser.py`) | ✅ Done |
| Campus rumour check against official records | ✅ Done (analyser side); VTOP wrapper next |
| Source and link credibility (`link_checker.py`) | ✅ Done |
| cli-top / VTOP wrapper | 🔜 Next |
| Daily verified news briefing for your courses | 🔜 Planned |
| Attendance alerts and study timetable | 🔜 Planned |
| Scam message analyser (`scam_analyser.py`) | ✅ Done (from the earlier scam-detection idea) |

## How the misinformation analyser works

```python
from misinfo_analyser import verify

verify("Breaking!! CAT-2 postponed, forward to all", official_context=vtop_records)
verify(article_text, url="https://example.com/story")
```

1. **Language signals** (offline): forward-chain pressure, vague sourcing ("my senior told me"), false certainty, sensational wording, deletion urgency.
2. **Source credibility**: reputable-outlet and fact-checker allowlists, plus the link checker for look-alike and scam domains.
3. **Claim extraction**: the LLM pulls out checkable claims and search queries (heuristic fallback if it fails).
4. **Corroboration**: Google News RSS (no key needed) and the Google Fact Check Tools API (optional).
5. **Verdict**: `true`, `likely_true`, `unverified`, `misleading` or `false`, with per-claim evidence, a comparison against official records, manipulation tactics and next steps.
6. **Hard rules the LLM can't override**: a published fact-check rating the claim false, or an official record that contradicts it, always caps the score. With no matching official record, a campus rumour can't be rated above "unverified."

**Robust by design:** all input and search results are treated as untrusted (defending against prompt injection hidden in articles), LLM output is validated, and if the API fails an offline check still returns a cautious result instead of crashing. Offline results never claim "true" or "false" outright, since nothing was fact-checked.

## How the link checker works

**Offline checks:** brand impersonation (`sbi-kyc-update.xyz`), look-alike domains (`amaz0n.in`), raw IPs, punycode, the `@` trick, risky domain endings, phishing keywords, shorteners.

**Online checks** (optional, cached in `.trustlens_cache.json`): domain age via RDAP, short-link expansion, Google Safe Browsing (`GSB_API_KEY`), VirusTotal (`VT_API_KEY`).

## Setup

```bash
pip install -r requirements.txt

# LLM: Gemini (default) or Groq
export GEMINI_API_KEY=your_key
# export LLM_PROVIDER=groq GROQ_API_KEY=your_key LLM_MODEL=model_name

# optional
export FACTCHECK_API_KEY=your_key   # Google Fact Check Tools
export GSB_API_KEY=your_key         # Google Safe Browsing
export VT_API_KEY=your_key          # VirusTotal

python misinfo_analyser.py   # runs the demo cases
```

## Privacy

VTOP credentials stay in cli-top's encrypted local store. TrustLens only passes the specific official records relevant to a claim (announcements, calendar, exam dates) to the LLM, never passwords or full academic records.

## Report misinformation and fraud

- Suspected fraud calls or messages: Chakshu on [sancharsaathi.gov.in](https://sancharsaathi.gov.in)
- If you've lost money: call **1930** or report at [cybercrime.gov.in](https://cybercrime.gov.in)
