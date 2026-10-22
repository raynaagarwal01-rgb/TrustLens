# Demo samples

| File | What it is | Source |
|---|---|---|
| `Tp_*.jpg` | Real tampered photos (splicing `Tp_D_`, copy-move `Tp_S_`) from the CASIA v2.0 image tampering dataset | [namtpham/casia2groundtruth](https://github.com/namtpham/casia2groundtruth) (samples folder) |
| `Tp_*_gt.png` | Ground-truth masks: white = the region that was actually edited | same |
| `Au_iphone_photo.jpg` | Authentic, unedited iPhone photo with full camera metadata | [ianare/exif-samples](https://github.com/ianare/exif-samples) (`jpg/hdr/iphone_hdr_NO.jpg`) |
| `AI_face_01.jpg` … `AI_face_08.jpg`, `AI_student_01.jpg` … `AI_student_05.jpg` | AI-generated portraits, incl. Indian students on campus (copies of `data/fake/`) | Google generative AI: each file carries Content Credentials signed by Google LLC ("Created by Google Generative AI", SynthID watermark) |
| `Forged_notice_demo.jpg` | Demo exam notice whose FAT date was pasted over (13-Nov → 20-Nov) from another image; labelled as a demo on the page | Made for TrustLens testing (no real institution named) |
| `Notice_original_demo.jpg` | The same notice before the edit, matching the official date | same |
| `vtop_demo/exams.txt` | cli-top exam-schedule output used when no live VTOP snapshot exists | cli-top |
| `Au_jolla_phone_photo.jpg` | Authentic, unedited phone photo | [ianare/exif-samples](https://github.com/ianare/exif-samples) (`jpg/mobile/jolla.jpg`) |

CASIA v2.0: J. Dong, W. Wang, T. Tan, "CASIA Image Tampering Detection Evaluation Database", ChinaSIP 2013. Used here for research/demo purposes with credit.

Add your own AI-generated images (for example from thispersondoesnotexist.com or an image generator) to this folder to show AI-image detection.
