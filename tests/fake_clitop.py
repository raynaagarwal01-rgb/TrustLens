"""Stand-in for cli-top in tests: replays a fixture and asks the same interactive questions."""
import sys
from pathlib import Path

FIX = Path(__file__).parent / "fixtures"
cmd = sys.argv[1] if len(sys.argv) > 1 else ""

if cmd == "calendar":
    text = (FIX / "calendar.txt").read_text(encoding="utf-8")
    head, rest = text.split("Choose a semester (enter a number): 2\n", 1)
    mid, tail = rest.split("Choose a class group (enter a number): 2\n", 1)
    print(head + "Choose a semester (enter a number): ", end="", flush=True)
    sem = input()
    if sem != "3":  # the latest semester in the fixture
        print(f"\nunexpected semester answer {sem!r}")
        sys.exit(2)
    print(mid.replace("VL20252605", "VL20262701") + "Choose a class group (enter a number): ", end="", flush=True)
    grp = input()
    print(tail.replace("General (Semester)", "General (Semester)" if grp == "2" else "?"), end="")
elif cmd == "leave":
    print("Apply for leave? (y/n): ", end="", flush=True)
    input()
elif cmd in ("exams", "msg", "attendance"):
    print((FIX / f"{ {'msg': 'msg'}.get(cmd, cmd) }.txt").read_text(encoding="utf-8"), end="")
else:
    print(f'Error: unknown command "{cmd}" for "cli-top"')
    sys.exit(1)
