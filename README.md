# TrustLens

**AI + LLM-based deepfake detection and digital evidence analysis.** Upload a photo, screenshot, certificate or circular: TrustLens checks whether it's AI-generated, deepfaked or edited, shows *where*, explains the evidence in plain language, and produces a hash-stamped evidence report.

Built solo in 24 hours for a hackathon (Track 1: AI + LLM-Based Deepfake Detection and Digital Evidence Analysis).

## How it works

```
image ──► forensics.py ──────────────► signals + heatmaps ─┐
            hash · metadata · ELA · noise · JPEG quality    │
      ──► optional pretrained detector ────────────────────┤
                                                            ▼
          vision LLM sees the image AND its ELA heatmap ──► evidence_analyser.py
          + every forensic finding                          hard rules · verdict · findings
                                                            ▼
                                       app.py (Streamlit)  +  report.py (evidence report)
```

1. **Evidence integrity**: SHA-256 and MD5 at upload, timestamp, tool version. A built-in checker confirms whether any file is byte-identical to the analysed one.
2. **Metadata forensics**: camera make/model and capture time, editing software (Photoshop, Canva, Snapseed…), modified-after-capture dates, AI-generator traces (Stable Diffusion/ComfyUI settings, the IPTC `trainedAlgorithmicMedia` marker, generator names), Content Credentials (C2PA): TrustLens reads what the manifest declares (e.g. `trainedAlgorithmicMedia` = AI-generated, who signed it, SynthID watermark noted).
3. **Error-level analysis (ELA)**: re-compresses the image and maps how each area reacts, normalised by local texture so ordinary edges don't dominate, then boxes the most anomalous region.
4. **Noise consistency** (experimental) and **JPEG quality estimate**.
5. **Vision LLM**: receives the image, its ELA heatmap and all forensic findings; reports visual artifacts with locations (hands, eyes, face boundaries, lighting, garbled text, fonts that don't match in documents).
6. **Hard rules the LLM can't override**: AI-generator metadata forces an "AI-generated" verdict; agreeing pixel tests and edit metadata set minimum scores; without the LLM, pixel tests alone can never produce a "fake" verdict.
7. **Verdict**: manipulation score 0–100, type (AI-generated, face swap, spliced region, edited document, retouched), confidence, findings, limitations and next steps. The lowest band is "no evidence of manipulation found", never "authentic", because forensics can't prove a negative.

## Measured on real data (`python tests/test_evidence.py`)

| Test set | Result |
|---|---|
| 4 real CASIA v2.0 forgeries with ground-truth masks | ELA box found in **4/4**, 62–89% of each box inside the truly edited area (3–14% by chance) |
| 4 authentic full-size phone photos (iPhone, Nokia, Jolla) | **0/4** false alarms, about 2 s each |
| 11 real photos (`data/real/`, Unsplash) | **0/11** false alarms |
| 13 AI-generated faces (`data/fake/`, made with Google's generative AI) | **13/13** identified as AI-generated from their Google-signed Content Credentials, even when the LLM was told to say "genuine" |
| Small edited thumbnails | ELA raises hints on some untouched images too, so pixel tests are reported as *hints*, never proof |

Small sample sizes: these numbers show the pipeline works on real forgeries, not a benchmark score.

## Run it

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=your_key        # Windows PowerShell: $env:GEMINI_API_KEY="your_key"
streamlit run app.py
```

Pick a demo sample in the sidebar (CASIA forgeries show the dataset's ground-truth mask next to TrustLens's heatmap) or upload your own image. Without an API key, TrustLens runs the forensic tests only.

Optional:
- `LLM_PROVIDER=groq` with `GROQ_API_KEY` and a vision-capable `LLM_MODEL`
- `DETECTOR_MODEL=<huggingface model id>` plus `pip install transformers torch` to add a pretrained AI-image/deepfake classifier

## Synthetic Face Dataset & Model Training

TrustLens includes a curated dataset of photorealistic AI-generated faces and model training pipelines:

- **Dataset**: High-resolution (1024x1024) photorealistic synthetic faces in `data/fake/`, paired reference faces in `data/real/`, and metadata manifest in `data/dataset_manifest.json`.
- **Training**:
  ```bash
  # Train baseline classifier (runs immediately):
  python train_face_detector.py --backend baseline

  # Train deep learning transfer learning model (PyTorch):
  pip install torch torchvision
  python train_face_detector.py --backend pytorch --epochs 15
  ```
- **Dataset Scaler**: Run `python data/download_synthetic_dataset.py` to fetch additional samples.
- **Standalone Face Analyser**: Run `python face_analyser.py` to analyze images using metadata, ELA, and 2D FFT frequency spectrum analysis.

## Files

| File | Purpose |
|---|---|
| `forensics.py` | Hash, metadata, ELA, noise and JPEG checks (Pillow + numpy only) |
| `evidence_analyser.py` | Combines forensics, detector and vision LLM; hard rules; verdict |
| `report.py` | Self-contained HTML evidence report (print to PDF) and JSON export |
| `app.py` | Streamlit interface |
| `llm.py` | Gemini / Groq calls, with image support |
| `samples/` | Demo images with sources and ground truth ([details](samples/README.md)) |
| `tests/` | Tests on the real samples |
| `data/` | Synthetic AI-generated faces, reference real faces, and dataset manifest |
| `face_analyser.py` | Experimental standalone face analyser (metadata, ELA, FFT). **Not calibrated yet:** its fixed thresholds currently label real web photos as AI-generated too, so it isn't used by the app |
| `train_face_detector.py` | Training pipeline scaffold (baseline + PyTorch). Needs a large dataset: the small baseline in `models/` (16–26 images) is not a meaningful result |

Earlier prototypes from other tracks (`scam_analyser.py`, `link_checker.py`, `misinfo_analyser.py`, `vtop.py`) remain in the repo but aren't part of the Track 1 app.

## Limitations

- Forensic tests show signs of manipulation; they can't prove an image is authentic.
- Images forwarded through WhatsApp or social media lose metadata and fine detail, which hides evidence.
- Modern AI generators can produce very clean images; visual analysis lowers its confidence rather than calling them real.
- Video and audio deepfakes are on the roadmap, not in this build.

## If you're targeted

Save the evidence report (it records the file's hash) and report at [cybercrime.gov.in](https://cybercrime.gov.in) or call **1930**.
