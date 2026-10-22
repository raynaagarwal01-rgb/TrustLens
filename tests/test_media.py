"""Tests for faces, video, voice notes, screenshots, reverse search, signed PDF, batches and summaries.

Run with: python tests/test_media.py   (or pytest)
Uses the demo samples in samples/ (made by tools/make_demo_samples.py).
"""
import datetime as dt
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import audio_analyser  # noqa: E402
import batch  # noqa: E402
import faces  # noqa: E402
import media  # noqa: E402
import reverse_search  # noqa: E402
import screenshot_check as sc  # noqa: E402
import signing  # noqa: E402
import summary  # noqa: E402

S = ROOT / "samples"


def test_media_kind_sniffing():
    assert media.kind_of((S / "AI_face_01.jpg").read_bytes()) == "image"
    assert media.kind_of((S / "Video_ai_talking_head_demo.mp4").read_bytes()) == "video"
    assert media.kind_of((S / "Voice_note_edited_demo.wav").read_bytes()) == "audio"
    assert media.kind_of(b"OggS" + b"\0" * 60, "note.opus") == "audio"
    assert media.kind_of(b"\0" * 64, "x.txt") == "unknown"


def test_ai_tool_names_match_whole_words():
    assert media.ai_tool_mentions('{"encoder": "Sora 2"}') == ["sora"]
    assert media.ai_tool_mentions('{"comment": "made with ElevenLabs"}') == ["elevenlabs"]
    assert media.ai_tool_mentions('{"title": "Kinara sorority fest"}') == []  # 'sora' inside a word


def test_faces_found_on_portraits():
    stats, crops, overlay = faces.analyse(Image.open(S / "AI_face_01.jpg"))
    assert stats["count"] == 1 and len(crops) == 1 and overlay is not None
    assert crops[0].size[0] == 512 or crops[0].size[1] == 512


def test_digital_silence_found_in_edited_voice_note_only():
    for name, expect in (("Voice_note_edited_demo.wav", True), ("Voice_note_original_demo.wav", False)):
        x, sr = audio_analyser.decode(str(S / name))
        m = audio_analyser.measure(x, sr)
        assert bool(m["digital_silence"]) is expect, name


def test_voice_note_verdicts():
    r = audio_analyser.analyse_audio((S / "Voice_note_edited_demo.wav").read_bytes(), "e.wav", use_llm=False)
    assert r["verdict"] == "inconclusive" and r["audio"]["marks"]
    r = audio_analyser.analyse_audio((S / "Voice_note_original_demo.wav").read_bytes(), "o.wav", use_llm=False)
    assert r["verdict"] == "no_evidence" and "can't be ruled out" in r["verdict_label"]
    assert summary.headline(r) == "No traces found"


def test_video_pipeline_without_ai():
    import video_analyser
    r = video_analyser.analyse_video((S / "Video_ai_talking_head_demo.mp4").read_bytes(), "v.mp4", use_llm=False)
    v = r["video"]
    assert r["media_kind"] == "video" and len(v["timeline"]) == 12
    assert sum(1 for f in v["timeline"] if f["faces"]) >= 10
    # without the AI review, pixel tests on frames never make a video "manipulated"
    assert r["verdict"] == "no_evidence" and r["verdict_label"].startswith("Not enough evidence")
    assert all(s["points_to"] == "none" for s in r["forensic_signals"] if "key frame" in s["check"])
    assert "sheet" in r["images"] and any(k.startswith("frame_") for k in r["images"])


def test_video_ai_tool_in_metadata_is_decisive():
    import subprocess
    import video_analyser
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "tagged.mp4"
        subprocess.run([media.ffmpeg_path(), "-v", "error", "-y", "-i", str(S / "Video_ai_talking_head_demo.mp4"), "-c", "copy",
                        "-metadata", "comment=Generated with Sora", str(out)], check=True)
        r = video_analyser.analyse_video(out.read_bytes(), "tagged.mp4", use_llm=False)
    assert r["verdict"] == "fake" and r["fake_type"] == "ai_generated" and r["confidence"] == "high"


def test_screenshot_checks():
    today = dt.date(2026, 10, 22)
    fake = {"kind": "payment", "app": "Google Pay", "payment": {
        "amount_texts": ["₹25,000", "₹2,500.00"], "date": "Friday, 22 Oct 2026", "weekday": "Friday", "time": "10:12 AM",
        "ids": [{"label": "UPI transaction ID", "value": "61234567890"}]}}
    bad = {c["check"] for c in sc.check_fields(fake, today) if c["status"] == "contradicted"}
    assert bad == {"UPI transaction ID format", "Amount is the same everywhere", "Weekday matches the date"}
    good = {"kind": "payment", "app": "PhonePe", "payment": {"amount_texts": ["₹1,00,000"], "date": "22/10/2026",
            "ids": [{"label": "UTR", "value": "629512345678"}, {"label": "Transaction ID", "value": "T2610222141123456789012"}]}}
    assert all(c["status"] == "ok" for c in sc.check_fields(good, today))
    chat = {"kind": "chat", "chat": {"messages": [{"time": "9:52"}, {"time": "9:58"}, {"time": "9:55"}]}}
    assert any(c["status"] == "contradicted" for c in sc.check_fields(chat, today))
    for s, ok in [("₹100,000", False), ("₹1,00,000", True), ("₹12,345", True), ("₹1,000,000", False)]:
        assert sc.indian_grouping_ok(s) is ok


def test_screenshot_contradictions_raise_verdict():
    r = {"verdict": "no_evidence", "verdict_label": "x", "manipulation_score": 10, "fake_type": "none", "rule_notes": []}
    check = {"kind": "payment", "checks": [{"check": "a", "status": "contradicted", "detail": "d1"},
                                           {"check": "b", "status": "contradicted", "detail": "d2"}]}
    out = sc.apply_to_result(r, check)
    assert out["manipulation_score"] == 70 and out["fake_type"] == "document_or_text_edited" and out["rule_notes"]


def test_reverse_search_confirms_only_fingerprint_matches():
    ev = (S / "Au_iphone_photo.jpg").read_bytes()
    copy = io.BytesIO()
    Image.open(io.BytesIO(ev)).convert("RGB").resize((800, 600)).save(copy, "JPEG", quality=70)
    other = io.BytesIO()
    Image.open(S / "Au_jolla_phone_photo.jpg").convert("RGB").resize((800, 600)).save(other, "JPEG")
    site = {"https://a.example/news": b'<meta property="og:image" content="/i.jpg"><meta property="article:published_time" content="2019-08-14">',
            "https://a.example/i.jpg": copy.getvalue(),
            "https://b.example/post": b'<img src="https://b.example/x.jpg" width="800">', "https://b.example/x.jpg": other.getvalue()}

    def fetch(url, limit):
        if url not in site:
            raise IOError("404")
        return site[url], url
    with mock.patch.object(reverse_search, "describe", lambda b: {"description": "d", "queries": ["q"], "visible_text": "", "claimed_context": ""}):
        r = reverse_search.run_reverse_search(ev, search=lambda d: [{"url": u, "title": "", "date": ""} for u in
                                                                    ("https://a.example/news", "https://b.example/post", "https://c.example/")], fetch=fetch)
    assert [m["url"] for m in r["matches"]] == ["https://a.example/news"] and r["matches"][0]["date"].startswith("2019")
    statuses = {u["url"]: u["status"] for u in r["unconfirmed"]}
    assert statuses == {"https://b.example/post": "unconfirmed", "https://c.example/": "unreachable"}


def test_signing_detects_changes():
    s = signing.Signer(Path(tempfile.mkdtemp()))
    tok = s.sign({"case": "abc", "sha256": "00" * 32, "verdict": "fake", "score": 90})
    assert s.verify(tok)["valid"]
    head, body, sig = tok.split(".")
    payload = json.loads(signing._unb64(body))
    payload["verdict"] = "no_evidence"
    forged = ".".join([head, signing._b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()), sig])
    assert not s.verify(forged)["valid"]
    other = signing.Signer(Path(tempfile.mkdtemp()))
    assert not other.verify(tok)["valid"] and other.verify(tok, s.public_pem)["valid"]


def test_pdf_report_carries_verifiable_token():
    import evidence_analyser as ea
    import pdf_report
    r = ea.analyse((S / "AI_student_05.jpg").read_bytes(), "AI_student_05.jpg", use_llm=False)
    r["case"] = {"id": "2ac99ef6d398", "name": "AI_student_05.jpg"}
    r["custody"] = {"chain": {"ok": True, "entries": 1}, "history": []}
    with mock.patch.object(signing, "_signer", signing.Signer(Path(tempfile.mkdtemp()))):
        pdf, token = pdf_report.build_pdf(r, "ab" * 32)
        assert pdf.startswith(b"%PDF") and pdf_report.token_from_pdf(pdf) == token
        assert signing.signer().verify(token)["payload"]["verdict"] == "fake"


def test_whatsapp_export_parsing_and_zip():
    chat = ("20/10/26, 9:41 pm - Rahul: IMG-20261020-WA0003.jpg (file attached)\n"
            "‎[13/03/24, 10:05:22 AM] Priya: ‎<attached: 00000012-PHOTO-2024-03-13-10-05-22.jpg>\n"
            "20/10/26, 9:43 pm - Rahul: <Media omitted>\n")
    m = batch.parse_chat(chat)
    assert m["IMG-20261020-WA0003.jpg"]["sender"] == "Rahul" and m["00000012-PHOTO-2024-03-13-10-05-22.jpg"]["sender"] == "Priya"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("WhatsApp Chat with CSE.txt", chat)
        z.writestr("IMG-20261020-WA0003.jpg", (S / "AI_face_01.jpg").read_bytes())
        z.writestr("STK-20261020-WA0001.webp", b"RIFF0000WEBP")
        z.writestr("notes.pdf", b"%PDF-1.4")
    files, info, skipped = batch.files_from_zip(buf.getvalue())
    assert [f for f, _ in files] == ["IMG-20261020-WA0003.jpg"] and "IMG-20261020-WA0003.jpg" in info
    assert set(skipped) == {"STK-20261020-WA0001.webp", "notes.pdf"}


def test_batch_runner_processes_queue():
    seen = []

    def analyse(data, name, source):
        seen.append(name)
        return {"case": {"id": "0" * 12}, "verdict": "fake", "verdict_label": "x", "manipulation_score": 90}
    b = batch.Batches(Path(tempfile.mkdtemp()), analyse)
    rec = b.create("t", [("a.jpg", b"1"), ("b.jpg", b"2")])
    b.worker.join(10)
    got = b.get(rec["id"])
    assert seen == ["a.jpg", "b.jpg"] and all(i["status"] == "done" and i["score"] == 90 for i in got["items"])


def test_summaries_in_both_languages():
    for v, t, llm in [("fake", "ai_generated", True), ("likely_fake", "spliced_or_object_edited", True),
                      ("inconclusive", "edited", False), ("no_evidence", "none", True), ("no_evidence", "none", False)]:
        s = summary.build({"verdict": v, "fake_type": t, "llm_used": llm, "rule_notes": [], "visual_findings": [],
                           "forensic_signals": []})
        assert len(s["en"]) == 3 and len(s["hi"]) == 3 and all(s["en"]) and all(s["hi"])
        assert any("ऀ" <= ch <= "ॿ" for ch in "".join(s["hi"]))
    s = summary.build({"verdict": "no_evidence", "llm_used": False, "rule_notes": [], "visual_findings": [], "forensic_signals": []})
    assert "wasn't fully checked" in s["en"][0]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
