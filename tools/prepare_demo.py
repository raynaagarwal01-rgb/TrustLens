"""
Prepare for a live demo, and measure accuracy on the samples, in one go.

    python tools/prepare_demo.py

  1. analyses every sample with the AI review (uses the key in .env) and keeps the cases, so demo mode
     and the locker open them instantly even if the venue's internet or the AI service fails later
  2. scores each result against what the sample really is (from its source, see samples/README.md)
  3. writes demo_backup/accuracy.csv, demo_backup/accuracy.md and a signed PDF report per demo case

Takes a few minutes. Run it the evening before, with the server stopped.
"""

import csv
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import envfile  # noqa: E402,F401
import server  # noqa: E402

OUT = ROOT / "demo_backup"
FAKE_VERDICTS = ("fake", "likely_fake")

# What each sample really is. "skip": not a manipulation test (posters and the notice need context checks).
TRUTH = [("Tp_", "manipulated"), ("Edited_", "manipulated"), ("AI_", "ai_generated"), ("Au_", "real"),
         ("Notice_", "real"), ("Video_ai", "ai_generated"), ("Voice_note_edited", "manipulated"),
         ("Voice_note_original", "real"), ("Screenshot_", "manipulated"), ("Forged_", "skip"), ("Event_", "skip")]
DEMO = ["Edited_iphone_photo_demo.jpg", "AI_student_05.jpg", "Tp_D_CRN_S_N_nat00033_cha00086_11502.jpg",
        "Video_ai_talking_head_demo.mp4", "Voice_note_edited_demo.wav", "Screenshot_payment_demo.png"]


def truth(name: str) -> str:
    return next((t for p, t in TRUTH if name.startswith(p)), "skip")


def main():
    ok, status = envfile.ai_review_status()
    print(status)
    if not ok:
        print("The AI review is off, so this would measure forensic tests only. Fix the key in .env first.")
        if input("Continue anyway? [y/N] ").strip().lower() != "y":
            return
    OUT.mkdir(exist_ok=True)
    files = sorted(p for p in server.SAMPLES.iterdir()
                   if p.suffix.lower() in server.MEDIA_TYPES and not p.stem.endswith("_gt"))
    rows = []
    for i, p in enumerate(files, 1):
        t0 = time.time()
        try:
            r = server.save_case(p.read_bytes(), p.name, ok, "sample")
            err = r.get("error") or ""
            row = {"file": p.name, "really": truth(p.name), "verdict": r["verdict"], "headline": server.summary.headline(r),
                   "score": r["manipulation_score"], "type": r.get("fake_type", ""), "ai_review": r["llm_used"],
                   "seconds": round(time.time() - t0, 1), "case": r["case"]["id"], "problem": err[:120]}
        except Exception as e:
            row = {"file": p.name, "really": truth(p.name), "verdict": "error", "headline": "", "score": "",
                   "type": "", "ai_review": False, "seconds": round(time.time() - t0, 1), "case": "",
                   "problem": f"{type(e).__name__}: {str(e)[:120]}"}
        rows.append(row)
        print(f"[{i}/{len(files)}] {p.name[:40]:40} {row['headline'] or row['verdict']:28} {row['score']!s:>4}  ({row['seconds']}s)")

    with open(OUT / "accuracy.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    scored = [r for r in rows if r["really"] != "skip" and r["verdict"] != "error"]
    fakes = [r for r in scored if r["really"] != "real"]
    reals = [r for r in scored if r["really"] == "real"]
    caught = [r for r in fakes if r["verdict"] in FAKE_VERDICTS]
    unsure = [r for r in fakes if r["verdict"] == "inconclusive"]
    false_alarms = [r for r in reals if r["verdict"] in FAKE_VERDICTS]
    by_kind = {}
    for r in fakes:
        k = r["really"]
        by_kind.setdefault(k, [0, 0])
        by_kind[k][1] += 1
        by_kind[k][0] += r["verdict"] in FAKE_VERDICTS
    lines = ["# TrustLens accuracy on the demo samples", "",
             f"AI review: {'on' if ok else 'off'}. {len(scored)} samples scored ({len(rows) - len(scored)} context-check samples or errors left out).", "",
             "| | Result |", "|---|---|",
             f"| Manipulated or AI-generated, flagged as fake or likely fake | **{len(caught)} of {len(fakes)}** |",
             f"| ...of which marked inconclusive instead | {len(unsure)} |",
             f"| Real files wrongly flagged | **{len(false_alarms)} of {len(reals)}** |", "",
             "| Kind of fake | Caught |", "|---|---|"]
    lines += [f"| {k.replace('_', ' ')} | {a} of {b} |" for k, (a, b) in by_kind.items()]
    lines += ["", "Small sample: these show the system works on real data, not a benchmark score.", "",
              "| File | Really | TrustLens says | Score |", "|---|---|---|---|"]
    lines += [f"| {r['file']} | {r['really']} | {r['headline'] or r['verdict']} | {r['score']} |" for r in rows]
    (OUT / "accuracy.md").write_text("\n".join(lines), encoding="utf-8")

    import pdf_report
    for name in DEMO:
        r = next((x for x in rows if x["file"] == name and x["case"]), None)
        if r:
            res, head = server._report_input(r["case"])
            pdf, _ = pdf_report.build_pdf(res, head)
            (OUT / f"report_{Path(name).stem}.pdf").write_bytes(pdf)

    print("\n" + "\n".join(lines[:12]))
    print(f"\nSaved in {OUT}: accuracy.csv, accuracy.md and signed PDF reports for the demo cases.")


if __name__ == "__main__":
    main()
