"""Run with: python tests/test_campus.py   (or pytest). No API key or VTOP needed."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import campus_check as cc  # noqa: E402
import evidence_analyser as ea  # noqa: E402

OFFICIAL = cc.load_official(live=False)  # demo snapshot: real FAT schedule format from cli-top


def claim(**k):
    base = {"type": "exam", "course": "", "exam": "FAT", "date": "", "previous_date": "", "statement": ""}
    return {**base, **k}


def test_demo_snapshot_loads():
    assert len(OFFICIAL["exams"]) == 6 and OFFICIAL["source"]["exams"] in ("demo snapshot", "saved VTOP snapshot")


def test_wrong_exam_date_is_contradicted():
    c = cc.check_claim(claim(course="BACSE202", date="20-Nov-2026", statement="DBMS FAT on 20 Nov"), OFFICIAL)
    assert c["status"] == "contradicted" and "13-Nov-2026" in c["official"]


def test_alias_and_date_formats():
    c = cc.check_claim(claim(course="DBMS", date="13th November 2026"), OFFICIAL)
    assert c["status"] == "confirmed"
    c = cc.check_claim(claim(course="CN", date="15/11/2026"), OFFICIAL)
    assert c["status"] == "confirmed"


def test_postponement_story_explained():
    c = cc.check_claim(claim(course="Database Systems", date="20-Nov-2026", previous_date="13-Nov-2026"), OFFICIAL)
    assert c["status"] == "contradicted" and "still shows the original date" in c["official"]


def test_holiday_on_exam_day_is_contradicted():
    c = cc.check_claim(claim(type="holiday", exam="", date="13-Nov-2026"), OFFICIAL)
    assert c["status"] == "contradicted" and "Database Systems" in c["official"]


def test_unknown_course_and_other_claims_not_checked():
    assert cc.check_claim(claim(course="Quantum Basket Weaving", date="13-Nov-2026"), OFFICIAL)["status"] == "not_checked"
    assert cc.check_claim(claim(type="other", exam="", statement="Hostel curfew extended"), OFFICIAL)["status"] == "not_checked"


def test_contradiction_raises_verdict():
    res = ea.analyse((ROOT / "samples" / "Forged_notice_demo.jpg").read_bytes(), "notice", use_llm=False)
    check = cc.check_claims({"claims": [claim(course="BACSE202", date="20-Nov-2026", statement="x")]}, OFFICIAL)
    res = cc.apply_to_result(res, check)
    assert res["verdict"] == "likely_fake" and res["fake_type"] == "document_or_text_edited"
    assert any("VTOP" in n for n in res["rule_notes"])



def test_steps_show_the_whole_process():
    from unittest import mock
    notice = {"is_campus_notice": True, "title": "FAT rescheduled", "issuer": "COE", "notice_date": "05-Nov-2026", "visible_text": "",
              "claims": [claim(course="BACSE202", date="20-Nov-2026", statement="DBMS FAT on 20 Nov")]}
    with mock.patch.object(cc, "extract_notice", return_value=notice):
        r = cc.run_campus_check(b"")
    titles = [s["title"] for s in r["steps"]]
    assert titles[0] == "Read the circular" and titles[1] == "Fetched your exam schedule" and titles[-1] == "Result"
    claim_step = next(s for s in r["steps"] if s["title"].startswith("Checked:"))
    assert claim_step["tone"] == "bad" and claim_step["command"] == "code, not AI"
    assert any("13-Nov-2026" in line for line in claim_step["lines"]) and any("contradicts" in line for line in claim_step["lines"])
    assert r["summary"].startswith("One claim")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
