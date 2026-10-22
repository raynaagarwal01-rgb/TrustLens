# TrustLens

**AI + LLM-based deepfake detection and digital evidence analysis.** Open a photo, video, voice note, screenshot, notice or event poster: TrustLens checks whether it's AI-generated, deepfaked or edited, shows *where*, explains the evidence in plain English and Hindi, checks claims against official VTOP records and the web, and keeps a hash-chained chain of custody with a signed PDF report anyone can verify.

Built for a hackathon (Track 1: AI + LLM-Based Deepfake Detection and Digital Evidence Analysis).

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
# edit .env and paste your Groq (or Gemini) key, once
python server.py
```

Your browser opens at `http://127.0.0.1:8000`, and the terminal prints whether the AI review is on. The key in `.env` is loaded automatically in any terminal (`.env` is gitignored). The interface is prebuilt in `web/dist`, so no Node.js is needed; ffmpeg for video and audio comes with the `imageio-ffmpeg` package.

**Keep the AI review on.** Forensic tests only catch edits that leave technical traces. AI-generated images without credentials, deepfake videos and clean edits are usually only visible to the vision model. Without a key, a result with no traces reads "Not enough evidence: AI review was off", never "no evidence".

Cases analysed before you added the key show a **Re-analyse with AI review** button. **Phone:** start with `python server.py --lan`, click **Use on your phone** and scan the QR code: the phone opens a simple Check page (the link carries a secret code, so others on the Wi-Fi can't use it). **Before a demo:** `python tools/prepare_demo.py` analyses every sample with the AI review, writes an accuracy table and signed PDFs to `demo_backup/`. Press **Play the 90-second demo** on the home screen for a guided tour of six prepared cases (photo edit, AI image, dataset splice, deepfake video, edited voice note, fake receipt).

Optional: `pip install c2pa-python` verifies Content Credentials signatures; `DETECTOR_MODEL=<huggingface id>` with `transformers` adds a pretrained classifier. The earlier Streamlit interface still works: `streamlit run app.py`. **Editing the interface:** `cd web && npm install && npm run build`. Design notes: [web/DESIGN.md](web/DESIGN.md).

## What it does

| | |
|---|---|
| **Photos** | Content Credentials, camera-preview comparison, error levels, JPEG ghost, clone detection, crop detection, 7 inspection layers, faces sent to the AI review as zoomed close-ups |
| **Videos** | 12 frames across the clip, faces in each, a contact sheet and face close-ups to the AI review, a per-frame score on a timeline, credentials and AI tool names in metadata, the soundtrack through the voice-note check |
| **Voice notes** | Spectrogram with marked edit points, digital-silence detection, transcript (Groq Whisper or Gemini) and a scam check of what is said |
| **Screenshots** | Payment receipts and chats read by the AI review, then checked by code: 12-digit UPI references, real dates that match their weekday, one amount everywhere, message times in order |
| **Context** | Circulars checked against VTOP via cli-top automatically, with every step shown; earlier copies of a photo online (confirmed by image fingerprint); event posters against official listings |
| **Many files** | Several files or a whole WhatsApp chat export (.zip): analysed in the background, sorted by risk, each file matched to its sender and time, CSV export |
| **Evidence** | Plain three-line summary in English and Hindi, HTML report, signed PDF report with a QR code, "Verify a report" page and `python verify_report.py`, hash-chained custody log |

## How it works

```
                ┌ forensics.py / advanced.py   hashes, metadata, C2PA, thumbnail, ELA, ghost, clones, grid, layers
image ──────────┤ faces.py                      face boxes + close-ups for the AI review
                └ vision LLM                    image + error-level map + face close-ups + every forensic finding
circular ── campus_check.py  AI reads the claims → cli-top exams/calendar/holiday → code compares dates → step log
video ── video_analyser.py   frames, faces, contact sheet → vision LLM; metadata/C2PA; soundtrack → audio_analyser
audio ── audio_analyser.py   digital silence, spectrogram, metadata/C2PA; transcript → scam check (LLM)
                        │
     evidence_analyser.py hard rules the LLM can't override → verdict, type, findings; summary.py (EN + HI)
                        │
 screenshot_check.py  reverse_search.py  campus_check.py (VTOP)  event_check.py  custody.py  batch.py
                        │
     server.py (Starlette API) ──► web/ (React + TypeScript)   report.py (HTML)  pdf_report.py + signing.py (PDF)
```

**Hard rules the LLM can't override:** Content Credentials or metadata declaring AI generation, or naming an AI video/voice tool, force "AI-generated"; credentials that fail verification, a camera preview showing a different version, a strong copy-move match, a notice that contradicts VTOP records, or a screenshot that fails format checks set minimum scores. Without the LLM, pixel tests alone never produce a "manipulated" verdict. The lowest band is "no evidence of manipulation found", never "authentic"; a voice note with no traces stays amber, because a cloned voice leaves none.

## Calibration: what each test is allowed to do

Techniques follow [Sherloq](https://github.com/GuidoBartoli/sherloq), [c2patool](https://github.com/contentauth/c2patool) and [forenix-oss](https://github.com/thunderstornX/forenix-oss), re-implemented here (no code copied). Every test was measured on real data first, and its role was set by that measurement: tests that proved reliable decide the verdict, tests that find *where* an edit is point the AI review and the reviewer to it, and tests that couldn't yet separate real from fake are still run and shown to the reviewer but can't raise the score. That is deliberate: it is how TrustLens stays at **0/4 false alarms** on real files.

| Test | Measured | Role |
|---|---|---|
| Content Credentials (C2PA) | 13/13 AI faces identified from Google-signed credentials | Decides the verdict |
| Embedded camera preview | 3/3 edited photos caught and located; hints on 2/37 odd camera files | Decides the verdict |
| Error-level analysis | Region in 4/4 CASIA forgeries, 62–89% inside the true edit | Locates the edit for the AI review |
| JPEG ghost | 3/3 low-quality splices located; none on authentic photos | Locates the edit for the AI review |
| Copy-move | CASIA clone found; no medium/high alarms on real photos or AI faces | Decides the verdict |
| JPEG grid alignment | 0/58 false alarms; ~45% of high-quality crops | Decides the verdict |
| AI tool named in video/audio metadata | Tested with a tagged copy of the demo video | Decides the verdict |
| Digital silence (voice notes) | 0 false alarms on 17 real recordings × 4 formats (WAV, WhatsApp-style Opus, MP3, AAC); 12/12 inserted silences found in WAV, survives MP3/AAC, erased by Opus (0/12) | Decides the verdict (likely edited) |
| Screenshot format checks | Deterministic rules (UPI reference length, dates, weekdays, amounts, time order) with unit tests; run automatically when the AI review sees a payment or chat screenshot; 2 failures → likely manipulated, 3 → manipulated | Decides the verdict |
| Circular vs VTOP (cli-top) | Deterministic date comparison with unit tests; a changed exam date, or a "holiday" on your exam day, is caught | Decides the verdict (likely manipulated) |
| Reverse search | Only a perceptual-hash match counts (resized, recompressed copy: distance 0/64; different photo: 29/64) | Finds the earlier original |
| Face noise/detail vs surroundings | Didn't yet separate 91 synthetic face swaps from 8 real and 13 AI portraits | Shown to the reviewer; face close-ups go to the AI review, which does judge faces |
| Face flicker between video frames | Real clips 1.6–3.4×, AI talking heads 1.4–4.3×: overlapping ranges | Shown on the video timeline |
| Background-noise jumps (audio) | 2 false alarms in 68 real files, ~half of test splices found | Marks possible edit points on the spectrogram |
| Median filtering, contrast, noise map | Didn't separate edited from authentic | Inspection layers for the reviewer |
| Chain of custody | Detects edited, deleted or reordered entries | Proves the evidence wasn't changed |

Real-photo baselines: **0/4** false alarms on authentic phone photos and **0/11** on real portraits. Live with the vision model (Groq `qwen/qwen3.8-27b`): a screenshot of an AI face, with its credentials stripped as WhatsApp would, was still identified as AI-generated. These are small samples: they show the tools work on real data, not a benchmark score. There is no trained voice-clone detector, and TrustLens says so instead of guessing.

## Evidence you can hand over

- **Signed PDF report** (`Signed PDF` button): verdict, English and Hindi summary, marked evidence, every test, video timeline or transcript, context checks, custody log, and a QR code holding the key facts (file SHA-256, verdict, score, custody-log head, time) signed with this computer's Ed25519 key (in `keys/`, never committed).
- **Verify a report**: upload the PDF or paste the code under the QR. Change any signed fact and verification fails. Reports from another computer verify with that computer's public key: `python verify_report.py report.pdf --public-key key.pem`.
- **Custody log**: every analysis, check, comparison and export is a hash-chained entry; `python custody.py verify` checks it independently.

## Campus checks

**Is this circular true?** Open a notice, circular or forwarded announcement and TrustLens checks it against your official VTOP records automatically (or press **Check against VTOP** in *Context checks*, with **Fetch fresh VTOP data** to call cli-top live). The check shows its work, step by step:

1. **Read the circular**: the AI review reads the title, issuer, date and every dated claim (exam moved, holiday declared, deadline).
2. **Fetched your exam schedule** (`cli-top exams`), **academic calendar** (`cli-top calendar`) and **holiday list** (`cli-top holiday`) through [cli-top](https://cli-top.acmvit.in): what came back, and whether it was live VTOP or a saved copy.
3. **Checked each claim, in code, not AI**: which course it matched and how (course code or name), the date the notice gives, the date VTOP gives, and the result.
4. **Result**: a claim that contradicts VTOP raises the verdict to at least *likely manipulated*; a claim VTOP has no record for is marked *not checked*, never true.

For example, the demo forged notice says the Database Systems FAT moved to 20-Nov-2026; TrustLens matches BACSE202 on the schedule, finds 13-Nov-2026, and reports the 7-day contradiction. The same steps appear on the phone page and in the signed PDF. Tested live on a real VTOP account; `samples/vtop_demo/` holds a saved cli-top output so the demo works without a login.

**Is this event real?** `event_check.py` looks for the event in VTOP club events and on the web, flags fees to personal UPI IDs, urgency, personal email, risky links and copies of real events. "Not found online" is reported as unverified, never as proof of a scam.

## Files

| File | Purpose |
|---|---|
| `server.py` | Starlette API and the web interface; cases in `cases/` |
| `web/` | React + TypeScript interface (`src/`), built bundle (`dist/`), design notes |
| `evidence_analyser.py` | Image pipeline with the vision LLM; hard rules; verdict |
| `video_analyser.py`, `audio_analyser.py`, `faces.py`, `media.py` | Video, voice notes, faces, file-type detection and ffmpeg |
| `forensics.py`, `advanced.py` | Image forensic tests and inspection layers |
| `screenshot_check.py`, `reverse_search.py` | Chat/payment forgery checks; earlier copies online |
| `campus_check.py`, `event_check.py`, `vtop.py` | Campus checks and the cli-top wrapper |
| `summary.py` | Three-line English and Hindi summary (templates, no AI) |
| `report.py`, `pdf_report.py`, `signing.py`, `verify_report.py` | HTML report, signed PDF report, verification |
| `batch.py` | Batches and WhatsApp export parsing |
| `custody.py` | Hash-chained chain-of-custody log |
| `llm.py`, `envfile.py` | Gemini / Groq calls and transcription; `.env` loading |
| `samples/`, `tools/make_demo_samples.py` | Demo evidence with sources ([details](samples/README.md)) |
| `models/`, `assets/fonts/` | OpenCV face detector (BSD), Noto Sans Devanagari for Hindi in PDFs (OFL) |
| `tests/` | Tests on real samples |
| `app.py` | Earlier Streamlit interface |
| `data/`, `face_analyser.py`, `train_face_detector.py` | Face dataset and an experimental analyser/trainer: **not calibrated** (it labels real web photos as AI-generated), so the app doesn't use them |

## Limitations

- Forensic tests show signs of manipulation; they can't prove a file is authentic.
- Files forwarded through WhatsApp or social media lose metadata, credentials and fine detail.
- Modern generators can be very clean; the AI review lowers its confidence rather than calling them real.
- Video checks 12 sampled frames; a manipulation between them can be missed. Cloned voices can't be detected from sound alone.

## If you're targeted

Download the signed PDF report (it records the file's fingerprint and custody log) and report at [cybercrime.gov.in](https://cybercrime.gov.in) or call **1930**.
