# Demo samples

| File | What it is | Source |
|---|---|---|
| `Tp_*.jpg` | Real tampered photos (splicing `Tp_D_`, copy-move `Tp_S_`) from the CASIA v2.0 image tampering dataset | [namtpham/casia2groundtruth](https://github.com/namtpham/casia2groundtruth) (samples folder) |
| `Tp_*_gt.png` | Ground-truth masks: white = the region that was actually edited | same |
| `Au_iphone_photo.jpg` | Authentic, unedited iPhone photo with full camera metadata | [ianare/exif-samples](https://github.com/ianare/exif-samples) (`jpg/hdr/iphone_hdr_NO.jpg`) |
| `AI_face_01.jpg` … `AI_face_08.jpg`, `AI_student_01.jpg` … `AI_student_05.jpg` | AI-generated portraits, incl. Indian students on campus (copies of `data/fake/`) | Google generative AI: each file carries Content Credentials signed by Google LLC ("Created by Google Generative AI", SynthID watermark) |
| `Forged_notice_demo.jpg` | Demo exam notice whose FAT date was pasted over (13-Nov → 20-Nov) from another image; labelled as a demo on the page | Made for TrustLens testing (no real institution named) |
| `Notice_original_demo.jpg` | The same notice before the edit, matching the official date | same |
| `Event_fake_hackathon_demo.jpg` | Demo scam poster: unknown "national hackathon", ₹499 fee to a UPI ID, WhatsApp payment proof, .xyz registration link, "last date today" | Made for TrustLens testing; fictional event, labelled as a demo |
| `vtop_demo/exams.txt` | cli-top exam-schedule output used when no live VTOP snapshot exists | cli-top |
| `Edited_iphone_photo_demo.jpg` | `Au_iphone_photo.jpg` with an area cloned over another, saved with the original camera metadata: its embedded thumbnail still shows the unedited scene | Made for TrustLens testing |
| `Au_jolla_phone_photo.jpg` | Authentic, unedited phone photo | [ianare/exif-samples](https://github.com/ianare/exif-samples) (`jpg/mobile/jolla.jpg`) |
| `Video_ai_talking_head_demo.mp4` | Deepfake talking head: an AI-generated portrait animated by SadTalker (re-encoded to H.264, no other change) | [OpenTalker/SadTalker](https://github.com/OpenTalker/SadTalker) `docs/example_full.gif`, Apache-2.0 |
| `Voice_note_original_demo.wav` | Three real recorded sentences by one speaker, joined with room noise between them | [speechbrain](https://github.com/speechbrain/speechbrain) `tests/samples/ASR/spk1_snt1-3.wav`, Apache-2.0 |
| `Voice_note_edited_demo.wav` | The same recording with the middle sentence cut out and the gap filled with 0.4 s of digital silence | Made for TrustLens testing |
| `Screenshot_payment_demo.png` | Receipt from a fictional "DemoPay" app with three planted errors (11-digit UPI reference, weekday that doesn't match the date, two different amounts) | Made for TrustLens testing; labelled as a demo |
| `Screenshot_chat_demo.png` | Fictional chat with a fee demand to a personal UPI ID and message times that go backwards | Made for TrustLens testing; labelled as a demo |

The video, voice-note and screenshot samples are re-created by `python tools/make_demo_samples.py <SadTalker checkout> <speechbrain checkout>`.

CASIA v2.0: J. Dong, W. Wang, T. Tan, "CASIA Image Tampering Detection Evaluation Database", ChinaSIP 2013. Used here for research/demo purposes with credit.

Add your own AI-generated images (for example from thispersondoesnotexist.com or an image generator) to this folder to show AI-image detection.
