"""
custody.py — tamper-evident chain-of-custody log (idea from forenix-oss, MIT; own implementation).

Every action on a piece of evidence (analysed, checked against VTOP, report exported) is appended to
custody_log.jsonl. Each entry stores the SHA-256 of the previous entry, and its own hash covers
its contents plus that previous hash:

    entry_hash = SHA-256( canonical JSON of {seq, time, action, file_sha256, details, prev_hash} )

Editing, deleting or reordering any past entry breaks every hash after it, which verify() detects.
What it does NOT prove: who performed an action, or that the clock was right. It proves the log
wasn't altered after the fact.

Verify offline without TrustLens:  python custody.py verify [custody_log.jsonl]
"""

import datetime as dt
import hashlib
import json
import os
import sys
import threading
from pathlib import Path

LOG = Path(os.getenv("TRUSTLENS_CUSTODY_LOG", "custody_log.jsonl"))
GENESIS = "0" * 64
_lock = threading.Lock()


def _canonical(entry: dict) -> bytes:
    body = {k: entry[k] for k in ("seq", "time", "action", "file_sha256", "details", "prev_hash")}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def entry_hash(entry: dict) -> str:
    return hashlib.sha256(_canonical(entry)).hexdigest()


def read(path: Path = None) -> list[dict]:
    path = Path(path or LOG)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def record(action: str, file_sha256: str, details: dict | None = None, path: Path = None) -> dict:
    """Append one action to the log and return the new entry."""
    path = Path(path or LOG)
    with _lock:
        entries = read(path)
        prev = entries[-1]["entry_hash"] if entries else GENESIS
        entry = {
            "seq": len(entries) + 1,
            "time": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "action": action,
            "file_sha256": file_sha256,
            "details": details or {},
            "prev_hash": prev,
        }
        entry["entry_hash"] = entry_hash(entry)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def verify(path: Path = None) -> dict:
    """Recompute the whole chain. Returns {'ok', 'entries', 'head', 'problem'}."""
    entries = read(path)
    prev = GENESIS
    for i, e in enumerate(entries, 1):
        if e.get("seq") != i:
            return {"ok": False, "entries": len(entries), "head": None, "problem": f"entry {i}: sequence number is {e.get('seq')}"}
        if e.get("prev_hash") != prev:
            return {"ok": False, "entries": len(entries), "head": None,
                    "problem": f"entry {i}: doesn't link to the entry before it (deleted or reordered?)"}
        if entry_hash(e) != e.get("entry_hash"):
            return {"ok": False, "entries": len(entries), "head": None, "problem": f"entry {i}: contents were changed"}
        prev = e["entry_hash"]
    return {"ok": True, "entries": len(entries), "head": prev, "problem": ""}


def history(file_sha256: str, path: Path = None) -> list[dict]:
    return [e for e in read(path) if e["file_sha256"] == file_sha256]


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "verify":
        res = verify(Path(sys.argv[2]) if len(sys.argv) > 2 else None)
        print(("CHAIN OK" if res["ok"] else "CHAIN BROKEN: " + res["problem"]) + f" ({res['entries']} entries)")
        if res["ok"]:
            print("head:", res["head"])
        sys.exit(0 if res["ok"] else 1)
    print(__doc__)
