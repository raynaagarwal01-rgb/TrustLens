"""Run with: python tests/test_vtop.py   (or pytest)"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import vtop  # noqa: E402

FIXTURE = (Path(__file__).parent / "fixtures" / "attendance.txt").read_text(encoding="utf-8")


def test_parses_all_rows_and_wrapped_cells():
    courses = vtop.parse_attendance(FIXTURE)
    assert len(courses) == 11
    assert courses[0]["subject"] == "Problem Solving using Java"
    assert courses[5]["subject"] == "Embedded Systems Architecture"
    assert courses[10]["subject"] == "Qualitative and Quantitative Skills Practice I"
    assert courses[1]["cli_top_alert"] == "Can miss 0 class(es)"


def test_matches_vtop_percentages():
    shown = [84, 76, 79, 80, 84, 77, 75, 77, 73, 85, 76]
    assert [c["percentage"] for c in vtop.parse_attendance(FIXTURE)] == shown


def test_matches_cli_top_alerts():
    for c in vtop.parse_attendance(FIXTURE):
        alert = c["cli_top_alert"]
        n = int(re.search(r"\d+", alert).group())
        if alert.startswith("Attend"):
            assert c["need_to_attend"] == n, c
        else:
            assert c["can_miss"] == n, c


def test_status_and_what_if():
    courses = {(c["subject"], c["is_lab"]): c for c in vtop.parse_attendance(FIXTURE)}
    stats = courses[("Probability and Statistics", False)]
    assert stats["status"] == "below" and stats["need_to_attend"] == 2
    assert vtop.what_if(stats, attend=2) == 75
    cn = courses[("Computer Networks", False)]
    assert cn["status"] == "safe" and vtop.what_if(cn, skip=3) < 75


def test_records_and_plain_text():
    recs = vtop.records_from_output("attendance", FIXTURE)
    assert recs[0].startswith("[attendance] subject: Problem Solving using Java")
    lines = vtop.text_lines("→ ANNOUNCEMENTS\n\nCAT-2 will be held as scheduled.\n✓ ANNOUNCEMENTS (2.1s)")
    assert lines == ["CAT-2 will be held as scheduled."]


def test_demo_mode_without_snapshot(tmp=None):
    import os
    os.environ["VTOP_DEMO"] = "1"
    vtop.SNAPSHOT_DIR = Path("/nonexistent-dir")
    try:
        records, errors = vtop.official_records()
        assert records == [] and set(errors) == set(vtop.OFFICIAL_SOURCES)
    finally:
        del os.environ["VTOP_DEMO"]


EXAMS = (Path(__file__).parent / "fixtures" / "exams.txt").read_text(encoding="utf-8")
CALENDAR = (Path(__file__).parent / "fixtures" / "calendar.txt").read_text(encoding="utf-8")
MSG = (Path(__file__).parent / "fixtures" / "msg.txt").read_text(encoding="utf-8")


def test_exams_with_wrapped_terminal_output():
    ex = vtop.parse_exams(EXAMS)
    assert len(ex) == 6
    first = ex[0]
    assert first["exam"] == "FAT" and first["code"] == "BACSE202"
    assert first["course"] == "Database Systems" and first["date"] == "2026-11-13"
    assert first["time"] == "09:30 AM - 12:30 PM (Report by: 08:45 AM)"
    assert first["days_left"] == 22 and ex[5]["days_left"] == 35


def test_exam_records_are_readable():
    recs = vtop.records_from_output("exams", EXAMS)
    assert len(recs) == 6
    assert recs[0].startswith("[exams] code: BACSE202; course title: Database Systems")
    assert "exam date: 13-Nov-2026" in recs[0] and "section: FAT EXAMS" in recs[0]
    assert not any("ICS" in r or "Calendar" in r for r in recs)


def test_no_messages_gives_no_records():
    assert vtop.records_from_output("class_messages", MSG) == []


def test_calendar_colours():
    cal = vtop.parse_calendar(CALENDAR)
    d = cal["days"]
    assert cal["semester"] == "VL20252605" and cal["class_group"] == "General (Semester)"
    assert d["2025-12-01"] == "holiday" and d["2025-12-05"] == "instructional"
    assert all(d[f"2026-01-{x}"] == "exam" for x in range(27, 32))
    assert d["2026-02-01"] == d["2026-02-02"] == "exam" and d["2026-02-03"] == "instructional"
    assert d["2026-03-21"] == "holiday" and d["2026-03-22"] == "exam"
    assert d["2026-04-30"] == "holiday"
    assert len(d) == 31 + 31 + 28 + 31 + 30


def test_calendar_records():
    recs = vtop.calendar_records(vtop.parse_calendar(CALENDAR))
    assert "[calendar] Exam days: 27-Jan-2026 (Tue) to 02-Feb-2026 (Mon)" in recs
    assert "[calendar] Exam days: 15-Mar-2026 (Sun) to 20-Mar-2026 (Fri)" in recs
    assert "[calendar] Holiday: 26-Jan-2026 (Mon)" in recs[0:] or any("26-Jan-2026" in r for r in recs)
    assert not any(r == "[calendar] Holiday: 07-Dec-2025 (Sun)" for r in recs)  # plain Sunday skipped


def test_interactive_calendar_and_unknown_prompt():
    import os
    fake = Path(__file__).parent / "fake_clitop.py"
    os.environ["CLITOP_PATH"] = f"{sys.executable} {fake}"
    os.environ.pop("VTOP_DEMO", None)
    vtop.SNAPSHOT_DIR = Path(__file__).parent / "_snapshots"
    old_idle, vtop.IDLE_PROMPT_SECONDS = vtop.IDLE_PROMPT_SECONDS, 2
    try:
        cal = vtop.academic_calendar()                  # answers both prompts itself
        assert cal["semester"] == "VL20262701"           # picked the latest semester
        assert cal["class_group"] == "General (Semester)"
        assert (vtop.SNAPSHOT_DIR / "calendar.txt").exists()
        try:
            vtop.run("leave")
            assert False, "should refuse an unknown prompt"
        except vtop.VtopError as e:
            assert "can't answer" in str(e)
        try:
            vtop.run("announcements")
            assert False
        except vtop.VtopError as e:
            assert "unknown command" in str(e)
        records, errors = vtop.official_records()
        assert any(r.startswith("[exams]") for r in records)
        assert any(r.startswith("[calendar] Exam days") for r in records)
        assert "holiday" in errors                      # fake has no holiday command; others still ran
    finally:
        vtop.IDLE_PROMPT_SECONDS = old_idle
        del os.environ["CLITOP_PATH"]
        import shutil
        shutil.rmtree(vtop.SNAPSHOT_DIR, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
