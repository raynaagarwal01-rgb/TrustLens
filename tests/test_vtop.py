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
    assert recs[0].startswith("[attendance] index: 1; subject: Problem Solving using Java")
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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
