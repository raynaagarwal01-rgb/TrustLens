"""
vtop.py — read VTOP through cli-top (ACM-VIT) and turn its terminal output into data.

    from vtop import attendance, exams, academic_calendar, official_records
    attendance()          -> courses with VTOP attendance maths done
    exams()               -> exam schedule with dates and days left
    academic_calendar()   -> every dated day: exam / holiday / instructional
    official_records()    -> strings for misinfo_analyser.verify(official_context=...)

cli-top asks some questions interactively (e.g. `calendar` asks for a semester and a class
group). The runner answers those prompts itself: latest semester by default, class group
from VTOP_CLASS_GROUP. Any prompt it doesn't recognise stops the command safely.

Privacy: cli-top keeps your VTOP login encrypted on your machine. This module only runs
cli-top locally; it never sees or sends your password.

Demo mode (VTOP_DEMO=1) reads saved outputs from snapshots/<source>.txt instead of
calling VTOP. Every successful live call saves a fresh snapshot.

Config (env vars):
    CLITOP_PATH       cli-top binary (default "cli-top" on PATH)
    VTOP_SEMESTER_ID  semester to pick when asked, e.g. VL20262701 (default: latest listed)
    VTOP_CLASS_GROUP  class group to pick for the calendar (default "General (Semester)")
    VTOP_DEMO=1       use snapshots only
"""

import datetime as dt
import os
import queue
import re
import shlex
import subprocess
import threading
import time
from pathlib import Path

SNAPSHOT_DIR = Path(os.getenv("VTOP_SNAPSHOTS", "snapshots"))
TIMEOUT = 120  # VTOP is slow; calendar alone can take ~40 s
IDLE_PROMPT_SECONDS = 8  # silence after a line ending in ":" or "?" = waiting for input

# Matches `cli-top --help`. Commands that apply for things (leave, nightslip) are left out.
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
    "events": ["events"],
}
# commands that list things and then offer an interactive action (e.g. "register for an event"):
# keep the list, stop at the question instead of failing
LIST_THEN_PROMPT = {"events"}

# Sources used to verify campus rumours (cli-top has no separate announcements command)
OFFICIAL_SOURCES = ["class_messages", "exams", "calendar", "holiday"]

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
SEP = re.compile(r"\s*[│┃|]\s*")
RULE = re.compile(r"^[\s─━═_\-+┼┬┴├┤┌┐└┘╋]+$")
BANNER = re.compile(r"^\s*[→✓✗✔✘]\s")
PROMPT = re.compile(r"(choose|select|enter)[^\n]*:\s*$", re.I)
EMPTY_NOTICE = re.compile(r"^no .* found\.?$", re.I)


class VtopError(RuntimeError):
    pass

# ---------------------------------------------------------------------------
# Running cli-top
# ---------------------------------------------------------------------------

def _binary() -> list[str]:
    path = os.getenv("CLITOP_PATH", "cli-top")
    return [path] if os.path.exists(path) or " " not in path else shlex.split(path, posix=os.name != "nt")


def choose_answer(output_so_far: str) -> str | None:
    """Answer cli-top's interactive prompts using the table printed just above the prompt."""
    text = strip_ansi(output_so_far)
    prompt = text.strip().splitlines()[-1].lower()
    tables = parse_tables(text)
    options = tables[-1] if tables else []
    if not options:
        return None
    if "semester" in prompt:
        wanted = os.getenv("VTOP_SEMESTER_ID")
        if wanted:
            for row in options:
                if row.get("semester_id", "").upper() == wanted.upper():
                    return row["index"]
            return None
        # default: latest semester (IDs sort chronologically, e.g. VL20262701)
        return max(options, key=lambda r: r.get("semester_id", ""))["index"]
    if "class group" in prompt:
        wanted = os.getenv("VTOP_CLASS_GROUP", "General (Semester)").lower()
        for row in options:
            if row.get("class_group", "").lower() == wanted:
                return row["index"]
        return None
    return None  # unknown prompt: don't guess


def _run_live(args: list[str], stop_on_prompt: bool = False) -> str:
    try:
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                env={**os.environ, "CLICOLOR_FORCE": "1", "FORCE_COLOR": "1"})
    except FileNotFoundError:
        raise VtopError("cli-top not found. Install it from cli-top.acmvit.in or set CLITOP_PATH.")

    chunks: queue.Queue = queue.Queue()

    def reader():
        fd = proc.stdout.fileno()
        while True:
            data = os.read(fd, 4096)
            chunks.put(data)
            if not data:
                break

    threading.Thread(target=reader, daemon=True).start()
    buf, answered_at, deadline = b"", 0, time.time() + TIMEOUT
    last_data = time.time()
    while True:
        try:
            data = chunks.get(timeout=1.0)
        except queue.Empty:
            tail = strip_ansi(buf[answered_at:].decode("utf-8", "replace")).rstrip("\n")
            # waiting on a question we don't recognise (e.g. "y/n?"): stop instead of hanging
            if time.time() - last_data > IDLE_PROMPT_SECONDS and re.search(r"[?:]\s*$", tail):
                proc.kill()
                if stop_on_prompt:
                    return buf.decode("utf-8", "replace")
                last = tail.strip().splitlines()[-1] if tail.strip() else ""
                raise VtopError(f"cli-top is waiting for input I can't answer safely: {last!r}")
            if time.time() > deadline:
                proc.kill()
                raise VtopError(f"cli-top {args[-1]} timed out after {TIMEOUT}s (VTOP may be slow or down).")
            continue
        if not data:
            break
        buf += data
        last_data = time.time()
        tail = strip_ansi(buf[answered_at:].decode("utf-8", "replace"))
        if PROMPT.search(tail):
            answer = choose_answer(buf.decode("utf-8", "replace"))
            if answer is None:
                proc.kill()
                if stop_on_prompt:
                    return buf.decode("utf-8", "replace")
                last = tail.strip().splitlines()[-1]
                raise VtopError(f"cli-top asked a question I can't answer safely: {last!r}. "
                                "Set VTOP_SEMESTER_ID / VTOP_CLASS_GROUP.")
            proc.stdin.write(f"{answer}\n".encode())
            proc.stdin.flush()
            buf += f"{answer}\n".encode()
            answered_at = len(buf)
    proc.wait(timeout=10)
    out = buf.decode("utf-8", "replace")
    if proc.returncode != 0:
        raise VtopError(f"cli-top {args[-1]} failed: {strip_ansi(out).strip()[-300:]}")
    return out


def run_raw(source: str, extra_args: list[str] | None = None) -> str:
    """Run a cli-top command (or read its snapshot in demo mode). Keeps colour codes."""
    snap = SNAPSHOT_DIR / f"{source}.txt"
    if os.getenv("VTOP_DEMO") == "1":
        if not snap.exists():
            raise VtopError(f"Demo mode: no snapshot at {snap}. Run once without VTOP_DEMO to create it.")
        return snap.read_text(encoding="utf-8")
    out = _run_live(_binary() + COMMANDS.get(source, [source]) + (extra_args or []),
                    stop_on_prompt=source in LIST_THEN_PROMPT)
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    snap.write_text(out, encoding="utf-8")
    return out


def run(source: str, extra_args: list[str] | None = None) -> str:
    return strip_ansi(run_raw(source, extra_args))


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
    """Parse every table in cli-top output.
    - wrapped cells: a line whose first cell is empty continues the previous row
    - blank lines inside a table are ignored (narrow terminals wrap row padding)
    - a header word split across lines ("DAYS L" / "EFT") is joined back
    - a plain text line just before a table (e.g. "FAT EXAMS") becomes each row's 'section'
    """
    tables, raw_headers, rows = [], None, []
    section, last_text, header_wrap = None, None, False

    def close():
        nonlocal raw_headers, rows
        if raw_headers and rows:
            tables.append(rows)
        raw_headers, rows = None, []

    lines = strip_ansi(text).splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or RULE.match(line):
            continue
        if not SEP.search(line):
            if header_wrap and raw_headers and not rows and stripped.isupper() and len(stripped) <= 12:
                raw_headers[-1] += stripped     # "DAYS L" + "EFT" -> "DAYS LEFT"
                header_wrap = False
                continue
            close()
            if not BANNER.match(line) and not PROMPT.search(stripped):
                last_text = stripped
            continue
        header_wrap = False
        cells = _cells(line)
        nxt = next((l for l in lines[i + 1:] if l.strip()), "")
        if _is_header(cells) and (raw_headers is None or RULE.match(nxt)):
            close()
            raw_headers, header_wrap = [c for c in cells if c], True
            section, last_text = last_text, None
            continue
        if raw_headers is None:
            continue
        keys = [_key(h) for h in raw_headers]
        cells = _cells(line, len(keys))
        if cells[0] or not rows:
            row = dict(zip(keys, cells))
            if section:
                row["section"] = section
            rows.append(row)
        else:
            for k, c in zip(keys, cells):
                if c:
                    rows[-1][k] = f"{rows[-1][k]} {c}".strip()
    close()
    return tables


def text_lines(text: str) -> list[str]:
    """Meaningful lines from non-table output (banners, rules and 'No ... found' removed)."""
    out = []
    for line in strip_ansi(text).splitlines():
        line = line.strip()
        if line and not BANNER.match(line) and not RULE.match(line) and not EMPTY_NOTICE.match(line):
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
            courses.append({
                "subject": row.get("subject", ""),
                "type": kind,
                "is_lab": is_lab,
                "attended": attended,
                "total": total,
                "percentage": pct,
                "can_miss": miss,
                "need_to_attend": need_to_attend(attended, total, unit),
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
# Exams
# ---------------------------------------------------------------------------

def _date(s: str) -> dt.date | None:
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            pass
    return None


def parse_exams(text: str) -> list[dict]:
    exams_ = []
    for table in parse_tables(text):
        for row in table:
            date = _date(row.get("exam_date", ""))
            if not row.get("code") and not date:
                continue
            exams_.append({
                "exam": (row.get("section") or "").replace(" EXAMS", "").strip() or "EXAM",
                "code": row.get("code", ""),
                "course": row.get("course_title", ""),
                "date": date.isoformat() if date else row.get("exam_date", ""),
                "time": row.get("exam_time", ""),
                "venue": row.get("venue", ""),
                "seat": row.get("seat_no", "") or row.get("seat", ""),
                "days_left": int(row["days_left"]) if row.get("days_left", "").isdigit() else None,
            })
    return exams_


def exams() -> list[dict]:
    return parse_exams(run("exams"))

# ---------------------------------------------------------------------------
# Academic calendar (information is in the colours)
# ---------------------------------------------------------------------------

MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}
TOKEN = re.compile(r"\x1b\[([0-9;]*)m|(\d+)|(.)", re.S)


def _sgr_kind(params: str, current: str | None) -> str | None:
    """Map an ANSI colour code to the calendar legend (red exam, blue holiday, green class, yellow today)."""
    if params in ("", "0", "39"):
        return None
    p = [int(x) for x in params.split(";") if x.isdigit()]
    basic = {31: "exam", 91: "exam", 34: "holiday", 94: "holiday",
             32: "instructional", 92: "instructional", 33: "today", 93: "today"}
    for i, v in enumerate(p):
        if v in basic:
            return basic[v]
        if v == 38 and i + 2 < len(p) and p[i + 1] == 5:             # 256-colour
            return {1: "exam", 9: "exam", 4: "holiday", 12: "holiday", 2: "instructional",
                    10: "instructional", 3: "today", 11: "today"}.get(p[i + 2], current)
        if v == 38 and i + 4 < len(p) and p[i + 1] == 2:             # true colour
            r, g, b = p[i + 2:i + 5]
            if r > 150 and g > 150 and b < 120:
                return "today"
            if r > max(g, b) + 60:
                return "exam"
            if g > max(r, b) + 40:
                return "instructional"
            if b > max(r, g) + 40:
                return "holiday"
    return current


def _coloured_numbers(line: str) -> list[tuple[int, int, str | None]]:
    """(visible column, number, colour kind) for every number in a line."""
    col, kind, out = 0, None, []
    for m in TOKEN.finditer(line):
        if m.group(1) is not None:
            kind = _sgr_kind(m.group(1), kind)
        elif m.group(2):
            out.append((col, int(m.group(2)), kind))
            col += len(m.group(2))
        else:
            col += 1
    return out


def parse_calendar(raw: str) -> dict:
    """Read cli-top's coloured month grids. Returns {'semester', 'class_group', 'days': {iso: kind}}."""
    plain = strip_ansi(raw)
    sem = re.search(r"selected semester:\s*(\S+)", plain)
    grp = re.search(r"selected class group:\s*(.+?)\s*$", plain, re.M)
    days, year, months, starts = {}, None, [], []
    for line in raw.splitlines():
        text = strip_ansi(line).strip()
        if not text:
            continue
        if re.fullmatch(r"(19|20)\d\d", text):
            year = int(text)
            continue
        words = text.split()
        if words and all(w in MONTHS for w in words):
            months, starts = [MONTHS[w] for w in words], []
            continue
        if words[:2] == ["Su", "Mo"]:
            plain_line = strip_ansi(line)
            starts = [m.start() for m in re.finditer(r"\bSu\b", plain_line)]
            continue
        if not (year and months and starts) or not re.fullmatch(r"[\d\s]+", text):
            continue
        for col, day, kind in _coloured_numbers(line):
            block = max((i for i, s in enumerate(starts) if s <= col + 1), default=0)
            if block >= len(months) or kind is None:
                continue
            m = months[block]
            # a block of months can roll over into the next year (e.g. DEC printed after JAN)
            y = year + (1 if months[0] > m else 0)
            try:
                days[dt.date(y, m, day).isoformat()] = kind
            except ValueError:
                pass
    return {"semester": sem.group(1) if sem else "", "class_group": grp.group(1) if grp else "",
            "days": dict(sorted(days.items()))}


def _ranges(dates: list[dt.date]) -> list[tuple[dt.date, dt.date]]:
    out = []
    for d in sorted(dates):
        if out and (d - out[-1][1]).days == 1:
            out[-1] = (out[-1][0], d)
        else:
            out.append((d, d))
    return out


def _fmt(d: dt.date) -> str:
    return d.strftime("%d-%b-%Y") + f" ({d.strftime('%a')})"


def calendar_records(cal: dict) -> list[str]:
    days = {dt.date.fromisoformat(k): v for k, v in cal["days"].items()}
    who = f"semester {cal['semester']}, class group {cal['class_group']}".strip(", ")
    recs = [f"[calendar] Academic calendar for {who}"]
    for kind, label in (("exam", "Exam days"), ("holiday", "Holiday")):
        for a, b in _ranges([d for d, k in days.items() if k == kind]):
            if kind == "holiday" and all(x.weekday() >= 5 for x in (a + dt.timedelta(n) for n in range((b - a).days + 1))):
                continue  # plain weekends aren't news
            recs.append(f"[calendar] {label}: {_fmt(a)}" + (f" to {_fmt(b)}" if b != a else ""))
    instructional = sorted(d for d, k in days.items() if k == "instructional")
    if instructional:
        recs.append(f"[calendar] Instructional days run from {_fmt(instructional[0])} to {_fmt(instructional[-1])}")
    return recs


def academic_calendar() -> dict:
    return parse_calendar(run_raw("calendar"))

# ---------------------------------------------------------------------------
# Official records for rumour checking
# ---------------------------------------------------------------------------

SKIP_KEYS = {"index"}


def records_from_output(source: str, raw: str) -> list[str]:
    if source == "calendar":
        return calendar_records(parse_calendar(raw))
    tables = parse_tables(raw)
    if tables:
        return [f"[{source}] " + "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in row.items()
                                           if v and k not in SKIP_KEYS)
                for table in tables for row in table]
    return [f"[{source}] {line}" for line in text_lines(raw)
            if not line.lower().startswith(("ics file", "import into", "add to "))]


def official_records(sources: list[str] | None = None) -> tuple[list[str], dict]:
    """Collect official records for misinfo_analyser. Returns (records, errors_by_source);
    one failing command never stops the others."""
    records, errors = [], {}
    for src in sources or OFFICIAL_SOURCES:
        try:
            records += records_from_output(src, run_raw(src))
        except VtopError as e:
            errors[src] = str(e)
    return records, errors


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) > 2 and Path(sys.argv[2]).exists():   # python vtop.py exams saved.txt
        print("\n".join(records_from_output(sys.argv[1], Path(sys.argv[2]).read_text(encoding="utf-8"))))
    elif len(sys.argv) > 1:                                 # python vtop.py exams
        print("\n".join(records_from_output(sys.argv[1], run_raw(sys.argv[1]))))
    else:
        print(attendance_summary(attendance()))
