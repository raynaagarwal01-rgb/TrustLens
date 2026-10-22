"""
vtop.py — read VTOP through cli-top (ACM-VIT) and turn its terminal tables into data.

    from vtop import attendance, official_records
    attendance()            -> list of courses with attendance maths done
    official_records()      -> list of strings for misinfo_analyser.verify(official_context=...)

Privacy: cli-top keeps your VTOP login encrypted on your machine. This module only
runs cli-top locally; it never sees or sends your password.

Demo mode (VTOP_DEMO=1) reads saved outputs from snapshots/<command>.txt instead of
calling VTOP, so the demo works even if VTOP or the Wi-Fi is down. Every live call
saves a fresh snapshot automatically.

Config (env vars):
    CLITOP_PATH     path to the cli-top binary (default: "cli-top" on PATH)
    VTOP_SEMESTER   value passed to --semester for commands that take it
    VTOP_DEMO=1     use snapshots only
"""

import math
import os
import re
import subprocess
from pathlib import Path

SNAPSHOT_DIR = Path(os.getenv("VTOP_SNAPSHOTS", "snapshots"))
TIMEOUT = 90  # VTOP can be slow; attendance alone took ~6 s

# Command names for each data source. Adjust after checking `cli-top --help`.
# Matches `cli-top --help`. Interactive commands (leave, nightslip, login) are deliberately left out.
COMMANDS = {
    "attendance": ["attendance"],
    "timetable": ["timetable"],
    "exams": ["exams"],
    "calendar": ["calendar"],
    "holiday": ["holiday"],
    "class_messages": ["msg"],
    "course_allocation": ["course-allocation"],
    "marks": ["marks"],
    "digital_assignments": ["da"],
    "today": ["today"],
    "tomorrow": ["tomorrow"],
    "dayafter": ["dayafter"],
}
TAKES_SEMESTER = {"attendance", "timetable", "exams", "holiday", "marks"}

# Sources used to verify campus rumours (cli-top has no separate announcements command)
OFFICIAL_SOURCES = ["class_messages", "exams", "calendar", "holiday"]

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
SEP = re.compile(r"\s*[│┃|]\s*")
RULE = re.compile(r"^[\s─━═\-+┼┬┴├┤┌┐└┘╋]+$")
BANNER = re.compile(r"^\s*[→✓✗✔✘]\s")


class VtopError(RuntimeError):
    pass

# ---------------------------------------------------------------------------
# Running cli-top
# ---------------------------------------------------------------------------

def run(source: str, extra_args: list[str] | None = None) -> str:
    """Run a cli-top command (or read its snapshot in demo mode). Returns plain text."""
    snap = SNAPSHOT_DIR / f"{source}.txt"
    if os.getenv("VTOP_DEMO") == "1":
        if not snap.exists():
            raise VtopError(f"Demo mode: no snapshot at {snap}. Run once without VTOP_DEMO to create it.")
        return strip_ansi(snap.read_text(encoding="utf-8"))

    args = [os.getenv("CLITOP_PATH", "cli-top"), *COMMANDS.get(source, [source])]
    sem = os.getenv("VTOP_SEMESTER")
    if sem and source in TAKES_SEMESTER:
        args += ["--semester", sem]
    args += extra_args or []
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT,
                              stdin=subprocess.DEVNULL,  # never hang on an interactive prompt
                              env={**os.environ, "NO_COLOR": "1"})
    except FileNotFoundError:
        raise VtopError("cli-top not found. Install it from cli-top.acmvit.in or set CLITOP_PATH.")
    except subprocess.TimeoutExpired:
        raise VtopError(f"cli-top {source} timed out after {TIMEOUT}s (VTOP may be slow or down).")

    out = proc.stdout + ("\n" + proc.stderr if proc.stderr.strip() else "")
    if proc.returncode != 0:
        raise VtopError(f"cli-top {source} failed: {strip_ansi(out).strip()[:300]}")
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    snap.write_text(out, encoding="utf-8")
    return strip_ansi(out)


def strip_ansi(text: str) -> str:
    return ANSI.sub("", text)

# ---------------------------------------------------------------------------
# Generic table parser for cli-top's box-drawn tables
# ---------------------------------------------------------------------------

def _key(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", header.lower()).strip("_") or "col"


def _cells(line: str, ncols: int | None = None) -> list[str]:
    cells = SEP.split(line.rstrip())
    if ncols:
        if len(cells) == ncols + 1 and not cells[0].strip():
            cells = cells[1:]                    # leading border
        while len(cells) > ncols and not cells[-1].strip():
            cells = cells[:-1]                   # trailing border
        cells += [""] * (ncols - len(cells))
    return [c.strip() for c in cells]


def _is_header(cells: list[str]) -> bool:
    text = [c for c in cells if c]
    return len(text) >= 2 and all(c == c.upper() and re.search(r"[A-Z]", c) for c in text)


def parse_tables(text: str) -> list[list[dict]]:
    """Parse every table in cli-top output. Wrapped cells are joined back together:
    a line whose first cell is empty continues the previous row."""
    tables, headers, rows = [], None, []
    lines = strip_ansi(text).splitlines()
    for i, line in enumerate(lines):
        if not SEP.search(line):
            if RULE.match(line) or not line.strip():
                if not line.strip() and headers and rows:
                    tables.append(rows); headers, rows = None, []
                continue
            if headers and rows:                 # any other text ends the table
                tables.append(rows); headers, rows = None, []
            continue
        cells = _cells(line)
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if _is_header(cells) and (headers is None or RULE.match(nxt)):
            if headers and rows:
                tables.append(rows)
            headers, rows = [_key(c) for c in cells if c], []
            continue
        if headers is None:
            continue
        cells = _cells(line, len(headers))
        if cells[0] or not rows:
            rows.append(dict(zip(headers, cells)))
        else:
            for h, c in zip(headers, cells):
                if c:
                    rows[-1][h] = f"{rows[-1][h]} {c}".strip()
    if headers and rows:
        tables.append(rows)
    return tables


def text_lines(text: str) -> list[str]:
    """Meaningful lines from non-table output (banners and rules removed)."""
    out = []
    for line in strip_ansi(text).splitlines():
        line = line.strip()
        if line and not BANNER.match(line) and not RULE.match(line):
            out.append(line)
    return out

# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------

THRESHOLD = 75


def vit_percent(attended: int, total: int) -> int:
    """VTOP rounds attendance UP (31/39 = 79.49% is shown as 80%)."""
    return -(-100 * attended // total) if total else 100


def can_miss(attended: int, total: int, unit: int) -> int:
    """How many more sessions you can skip and stay at or above 75%."""
    k = 0
    while vit_percent(attended, total + unit * (k + 1)) >= THRESHOLD:
        k += 1
    return k


def need_to_attend(attended: int, total: int, unit: int) -> int:
    """How many sessions in a row you must attend to get back to 75%."""
    n = 0
    while vit_percent(attended + unit * n, total + unit * n) < THRESHOLD:
        n += 1
    return n


def parse_attendance(text: str) -> list[dict]:
    courses = []
    for table in parse_tables(text):
        for row in table:
            m = re.search(r"(\d+)\s*/\s*(\d+)", row.get("classes_attended", ""))
            if not m:
                continue
            attended, total = int(m.group(1)), int(m.group(2))
            kind = row.get("type", "")
            is_lab = "lab" in kind.lower()
            unit = 2 if is_lab else 1  # a lab session counts as 2 classes
            pct = vit_percent(attended, total)
            miss = can_miss(attended, total, unit)
            need = need_to_attend(attended, total, unit)
            courses.append({
                "subject": row.get("subject", ""),
                "type": kind,
                "is_lab": is_lab,
                "attended": attended,
                "total": total,
                "percentage": pct,
                "can_miss": miss,
                "need_to_attend": need,
                "status": "below" if pct < THRESHOLD else "on_edge" if miss == 0 else "safe",
                "cli_top_alert": row.get("75_alert", ""),
            })
    return courses


def attendance() -> list[dict]:
    return parse_attendance(run("attendance"))


def what_if(course: dict, skip: int = 0, attend: int = 0) -> int:
    """Percentage after skipping and/or attending some sessions."""
    unit = 2 if course["is_lab"] else 1
    return vit_percent(course["attended"] + unit * attend, course["total"] + unit * (skip + attend))


def attendance_summary(courses: list[dict]) -> str:
    lines = []
    for c in sorted(courses, key=lambda c: (c["status"] != "below", c["status"] != "on_edge", c["percentage"])):
        what = "lab(s)" if c["is_lab"] else "class(es)"
        name = f"{c['subject']} ({'lab' if c['is_lab'] else 'theory'})"
        if c["status"] == "below":
            lines.append(f"⚠ {name}: {c['percentage']}%, attend the next {c['need_to_attend']} {what}")
        elif c["status"] == "on_edge":
            lines.append(f"• {name}: {c['percentage']}%, can't miss any {what}")
        else:
            lines.append(f"✓ {name}: {c['percentage']}%, can miss {c['can_miss']} {what}")
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# Official records for rumour checking
# ---------------------------------------------------------------------------

def records_from_output(source: str, text: str) -> list[str]:
    tables = parse_tables(text)
    if tables:
        return [f"[{source}] " + "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in row.items() if v)
                for table in tables for row in table]
    return [f"[{source}] {line}" for line in text_lines(text)]


def official_records(sources: list[str] | None = None) -> tuple[list[str], dict]:
    """Collect official records for misinfo_analyser. Returns (records, errors_by_source);
    one failing command never stops the others."""
    records, errors = [], {}
    for src in sources or OFFICIAL_SOURCES:
        try:
            records += records_from_output(src, run(src))
        except VtopError as e:
            errors[src] = str(e)
    return records, errors


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) > 1 and Path(sys.argv[1]).exists():  # parse a saved output file
        print(json.dumps(parse_tables(Path(sys.argv[1]).read_text(encoding="utf-8")), indent=2))
    else:
        print(attendance_summary(attendance()))
