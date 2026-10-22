"""
batch.py: analyse many files at once: a set of uploads or a WhatsApp chat export (.zip).

A disciplinary committee or a class group admin may need to check dozens of screenshots and
photos. Files are queued and analysed one by one in the background; the batch page shows progress
and a table sorted by risk. For a WhatsApp export, each file is matched to who sent it and when,
from the chat text file in the export.
"""

from __future__ import annotations

import io
import json
import re
import threading
import time
import uuid
import zipfile
from pathlib import Path

import media

MAX_FILES = 200
MAX_FILE_BYTES = 40 * 1024 * 1024
MAX_ZIP_BYTES = 600 * 1024 * 1024

# Android: "12/03/24, 9:41 pm - Rahul: IMG-20240312-WA0003.jpg (file attached)"
ANDROID = re.compile(r"^(\d{1,2}/\d{1,2}/\d{2,4}),\s*(\d{1,2}:\d{2}(?:\s*[apAP]\.?\s?[mM]\.?)?)\s*-\s*([^:]{1,60}):\s*(.*)$")
# iOS: "[12/03/24, 9:41:22 PM] Rahul: <attached: 00000012-PHOTO-2024-03-12-21-41-22.jpg>"
IOS = re.compile(r"^\[(\d{1,2}/\d{1,2}/\d{2,4}),\s*(\d{1,2}:\d{2}(?::\d{2})?(?:\s*[apAP]\.?\s?[mM]\.?)?)\]\s*([^:]{1,60}):\s*(.*)$")
ATTACH = re.compile(r"<attached:\s*([^>]+)>|([\w\-. ]+\.(?:jpe?g|png|webp|gif|mp4|3gp|mov|opus|ogg|m4a|aac|mp3|wav|pdf))\s*\(file attached\)", re.I)


def parse_chat(text: str) -> dict[str, dict]:
    """Attachment file name -> {"sender", "sent", "message"} from a WhatsApp chat export."""
    out = {}
    for raw in text.splitlines():
        line = raw.replace("‎", "").replace(" ", " ").replace("‏", "").strip()
        m = ANDROID.match(line) or IOS.match(line)
        if not m:
            continue
        date, tm, sender, msg = m.groups()
        a = ATTACH.search(msg)
        if a:
            name = (a.group(1) or a.group(2)).strip()
            out[name] = {"sender": sender.strip(), "sent": f"{date} {tm.strip()}", "message": msg[:200]}
    return out


def files_from_zip(data: bytes) -> tuple[list[tuple[str, bytes]], dict, list[str]]:
    """Analysable files, sender info from the chat text, and skipped names."""
    if len(data) > MAX_ZIP_BYTES:
        raise ValueError("That archive is larger than 600 MB.")
    zf = zipfile.ZipFile(io.BytesIO(data))
    chat, files, skipped = {}, [], []
    for info in zf.infolist():
        name = Path(info.filename).name
        if info.is_dir() or not name or name.startswith("."):
            continue
        if name.lower().endswith(".txt") and ("chat" in name.lower() or "whatsapp" in name.lower()):
            chat.update(parse_chat(zf.read(info).decode("utf-8", "replace")))
            continue
        if name.upper().startswith("STK-"):  # stickers
            skipped.append(name)
            continue
        if info.file_size > MAX_FILE_BYTES:
            skipped.append(f"{name} (over 40 MB)")
            continue
        body = zf.read(info)
        if media.kind_of(body, name) in ("image", "video", "audio"):
            files.append((name, body))
        else:
            skipped.append(name)
        if len(files) >= MAX_FILES:
            break
    return files, chat, skipped


class Batches:
    """Batch records on disk (cases/_batches/<id>.json) and a single background worker."""

    def __init__(self, folder: Path, analyse):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.analyse = analyse          # (data, name, source) -> result with result["case"]["id"]
        self.lock = threading.Lock()
        self.queue: list[tuple[str, int, bytes]] = []
        self.worker: threading.Thread | None = None

    def _path(self, bid: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{12}", bid):
            raise KeyError(bid)
        return self.folder / f"{bid}.json"

    def get(self, bid: str) -> dict:
        p = self._path(bid)
        if not p.exists():
            raise KeyError(bid)
        return json.loads(p.read_text(encoding="utf-8"))

    def _save(self, b: dict):
        self._path(b["id"]).write_text(json.dumps(b), encoding="utf-8")

    def list(self) -> list[dict]:
        out = []
        for p in sorted(self.folder.glob("*.json"), key=lambda p: -p.stat().st_mtime):
            try:
                b = json.loads(p.read_text(encoding="utf-8"))
                out.append({k: b[k] for k in ("id", "name", "created", "total")} | {"done": sum(1 for i in b["items"] if i["status"] in ("done", "error"))})
            except Exception:
                continue
        return out

    def create(self, name: str, files: list[tuple[str, bytes]], chat: dict | None = None, skipped=None) -> dict:
        bid = uuid.uuid4().hex[:12]
        chat = chat or {}
        items = [{"n": i, "file": fn, "kind": media.kind_of(data, fn), "size": len(data), "status": "queued",
                  **({"sender": chat[fn]["sender"], "sent": chat[fn]["sent"]} if fn in chat else {})}
                 for i, (fn, data) in enumerate(files)]
        b = {"id": bid, "name": name, "created": time.time(), "total": len(items), "items": items,
             "skipped": skipped or [], "from_chat": bool(chat)}
        with self.lock:
            self._save(b)
            self.queue += [(bid, i, data) for i, (_, data) in enumerate(files)]
            if not self.worker or not self.worker.is_alive():
                self.worker = threading.Thread(target=self._run, daemon=True)
                self.worker.start()
        return b

    def _update(self, bid: str, n: int, **fields):
        with self.lock:
            b = self.get(bid)
            b["items"][n].update(fields)
            self._save(b)

    def _run(self):
        while True:
            with self.lock:
                if not self.queue:
                    return
                bid, n, data = self.queue.pop(0)
            try:
                item = self.get(bid)["items"][n]
                self._update(bid, n, status="running", started=time.time())
                r = self.analyse(data, item["file"], "batch")
                self._update(bid, n, status="done", case_id=r["case"]["id"], verdict=r["verdict"],
                             verdict_label=r["verdict_label"], score=r["manipulation_score"],
                             fake_type_label=r.get("fake_type_label", ""), media_kind=r.get("media_kind", "image"),
                             headline=r.get("headline", ""))
            except Exception as e:
                try:
                    self._update(bid, n, status="error", error=f"{type(e).__name__}: {str(e)[:160]}")
                except Exception:
                    pass
