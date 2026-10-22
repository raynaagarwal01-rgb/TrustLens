# TrustLens

**AI + LLM-based deepfake detection and digital evidence analysis.** Open a photo, screenshot, certificate, notice or event poster: TrustLens checks whether it's AI-generated, deepfaked or edited, shows *where* on the image, explains the evidence in plain language, checks campus claims against official VTOP records, and keeps a hash-chained chain of custody with an exportable evidence report.

Built for a hackathon (Track 1: AI + LLM-Based Deepfake Detection and Digital Evidence Analysis).

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
# edit .env and paste your Groq (or Gemini) key, once
python server.py
```

Your browser opens at `http://127.0.0.1:8000`, and the terminal prints whether the AI review is on. The key in `.env` is loaded automatically every time, in any terminal (`.env` is gitignored). The interface is prebuilt in `web/dist`, so no Node.js is needed.

**Keep the AI review on.** Forensic tests only catch edits that leave technical traces (clones, a mismatched camera preview, Content Credentials, re-saves). AI-generated images without credentials (screenshots, downloads, WhatsApp forwards) and clean edits are usually only visible to the vision model. Without a key, a result with no traces reads "Not enough evidence: AI review was off", never "no evidence".

Optional: `pip install c2pa-python` verifies Content Credentials signatures; `DETECTOR_MODEL=<huggingface id>` with `transformers` adds a pretrained classifier. The previous Streamlit interface still works: `streamlit run app.py`.

**Editing the interface:** `cd web && npm install && npm run build` (or `npm run watch` while `python server.py` runs). Design notes: [web/DESIGN.md](web/DESIGN.md).

## The interface

- **Evidence locker** (left): your cases, kept in `cases/` across restarts, plus demo evidence grouped by kind, and live system status (AI review, clone detection, signature checks, VTOP, custody chain).
- **Viewer**: the image framed by a forensic measurement scale. Drag the wipe to compare the photo with any analysis layer (error levels, JPEG ghost, clone map, camera preview, difference from a reference, noise, and seven inspection layers). Numbered evidence markers show regions the tests point at; a magnifier and, for dataset samples, the ground-truth mask are one click away.
- **Verdict**: the finding in plain words, the score on a ruled scale, confidence, and a "why" list linked to the markers.
- **Details**: findings, every test that ran (experimental ones labelled), metadata with JPEG structure, quantisation table and histogram, Content Credentials provenance, campus checks, and custody & integrity.
- **Evidence report**: a self-contained HTML report (print to PDF) with hashes, findings, layers and the custody log.

## How it works

```
                ┌ forensics.py   hashes, metadata, C2PA, thumbnail, GPS, ELA, noise, JPEG quality
image ──────────┤ advanced.py    JPEG ghost, copy-move, grid alignment, inspection layers, structure
                └ vision LLM     sees the image AND its error-level map, plus every forensic finding
                        │
                evidence_analyser.py  hard rules the LLM can't override → verdict, type, findings
                        │
     campus_check.py (VTOP via cli-top)   event_check.py (web + VTOP events)   custody.py (hash chain)
                        │
           server.py (Starlette API)  ──►  web/ (React + TypeScript)   report.py (evidence report)
```

**Hard rules the LLM can't override:** Content Credentials or metadata declaring AI generation force "AI-generated"; credentials that fail verification (image changed after signing), a camera preview showing a different version, or a strong copy-move match set minimum scores; a notice that contradicts VTOP records becomes "likely manipulated (edited document)". Without the LLM, pixel tests alone never produce a "manipulated" verdict. The lowest band is "no evidence of manipulation found", never "authentic", because forensics can't prove a negative.

## Forensic tools and how they were calibrated

Techniques follow [Sherloq](https://github.com/GuidoBartoli/sherloq)'s tool list, [c2patool](https://github.com/contentauth/c2patool) and [forenix-oss](https://github.com/thunderstornX/forenix-oss), re-implemented here (no code copied; Sherloq is GPL). Each tool was tested on real images before it was allowed to affect the verdict (`tests/test_advanced.py`, `tests/test_evidence.py`, `tests/test_custody.py`).

| Tool | What it finds | Measured | In verdict |
|---|---|---|---|
| Content Credentials (C2PA) | Signed declarations such as `trainedAlgorithmicMedia`; signer; SynthID; ingredients | 13/13 AI faces identified from Google-signed credentials | Yes |
| C2PA signature verification | Image changed after signing | Uses `c2pa-python` when installed | Yes |
| Embedded thumbnail | Camera preview still shows the original | 3/3 edited photos caught and located; hints on 2/37 odd camera test files | Yes |
| Error-level analysis | Areas that re-compress differently | Region in 4/4 CASIA forgeries, 62–89% inside the true edit (3–14% by chance); hints on some untouched thumbnails | Hint |
| JPEG ghost | Content pasted from a lower-quality JPEG | 3/3 such splices located in phone photos; none on authentic photos | Hint |
| Copy-move | Cloned areas (SIFT self-matching + RANSAC) | CASIA clone found; no medium/high alarms on real photos or AI faces; downgraded on documents | Yes |
| JPEG grid alignment | Crop or shift after an earlier save | 0/58 false alarms; ~45% of high-quality crops | Yes |
| Median filtering, contrast enhancement | Smoothing, levels edits | Did not separate edited from authentic | No (shown as experimental) |
| Noise consistency | Different noise patterns | Lights up skies | No (experimental layer) |
| Perceptual hashes, GPS, JPEG structure, histogram, reference comparison | Evidence context | | Context |
| Chain of custody | Hash-chained log of every action | Detects edited, deleted or reordered entries | Integrity |

Real-photo baselines: **0/4** false alarms on authentic full-size phone photos and **0/11** on real web portraits. Live with the vision model (Groq `qwen/qwen3.8-27b`): a screenshot of an AI face, which strips its credentials as WhatsApp would, was still identified as AI-generated; a screenshot of an authentic photo came back "no evidence". Small samples: these show the tools work on real data, not a benchmark score.

## Campus checks

**Is this notice true?** For circulars and forwarded announcements, the vision model reads the dated claims; `vtop.py` fetches your exam schedule, academic calendar and holidays from VTOP through [cli-top](https://cli-top.acmvit.in) (answering its semester and class-group prompts, reading the colour-coded calendar); `campus_check.py` compares dates **in code**, not with AI. Tested live on a real VTOP account.

**Is this event real?** For hackathon, workshop and internship posters, `event_check.py` looks for the event in VTOP club events and on the web (Groq browser search, Bing fallback), flags fees to UPI IDs, urgency, personal email, risky links, and impersonation of real events. "Not found online" is reported as unverified, never as proof of a scam.

## Files

| File | Purpose |
|---|---|
| `server.py` | Starlette API and the web interface; cases stored in `cases/` |
| `web/` | React + TypeScript interface (`src/`), built bundle (`dist/`), design notes |
| `forensics.py` | Hashes, metadata, C2PA, thumbnail, GPS, perceptual hashes, ELA, noise, JPEG quality |
| `advanced.py` | JPEG ghost, copy-move, grid alignment, experimental tools, inspection layers, structure, comparison |
| `evidence_analyser.py` | Combines everything with the vision LLM; hard rules; verdict |
| `custody.py` | Hash-chained chain-of-custody log; `python custody.py verify` |
| `report.py` | Self-contained HTML evidence report |
| `campus_check.py`, `event_check.py`, `vtop.py` | Campus checks and the cli-top wrapper |
| `llm.py` | Gemini / Groq calls with image support |
| `samples/` | Demo evidence with sources and ground truth ([details](samples/README.md)) |
| `tests/` | Tests on real samples |
| `app.py` | Earlier Streamlit interface |
| `data/`, `face_analyser.py`, `train_face_detector.py` | Face dataset and an experimental analyser/trainer: **not calibrated** (the analyser labels real web photos as AI-generated; the 16–26 image baseline isn't meaningful), so the app doesn't use them |

`scam_analyser.py` and `link_checker.py` are reused by the event check; `misinfo_analyser.py` is from an earlier prototype.

## Limitations

- Forensic tests show signs of manipulation; they can't prove an image is authentic.
- Images forwarded through WhatsApp or social media lose metadata, credentials and fine detail.
- Modern AI generators can produce very clean images; the visual review lowers its confidence rather than calling them real.
- Video and audio deepfakes are on the roadmap.

## If you're targeted

Export the evidence report (it records the file's hash and custody log) and report at [cybercrime.gov.in](https://cybercrime.gov.in) or call **1930**.
