"""
signing.py: sign evidence reports so a proctor or officer can check they weren't altered.

Each TrustLens install has its own Ed25519 key pair in keys/ (created on first use, never committed).
A report carries a token: the key facts (case, file SHA-256, verdict, score, type, custody-log head,
time) plus a signature over them. The token is printed as a QR code and stored in the PDF's metadata.

Verifying: TrustLens -> "Verify a report" (paste the QR text or upload the PDF), or
    python verify_report.py report.pdf
Changing any signed fact (say, the verdict) breaks the signature. Anyone holding the public key
(shown in the report as a key ID, downloadable at /api/report-key) can verify; only this install
can sign. Without the `cryptography` package it falls back to HMAC, which only this install can check.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KEY_DIR = Path(os.getenv("TRUSTLENS_KEYS", ROOT / "keys"))
PREFIX = "TLR1"


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class Signer:
    def __init__(self, key_dir: Path = KEY_DIR):
        self.key_dir = Path(key_dir)
        self.mode = "ed25519"
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        except Exception:
            self.mode = "hmac"
        if self.mode == "ed25519":
            p = self.key_dir / "report_signing_key.pem"
            if p.exists():
                self._priv = serialization.load_pem_private_key(p.read_bytes(), password=None)
            else:
                self.key_dir.mkdir(parents=True, exist_ok=True)
                self._priv = Ed25519PrivateKey.generate()
                p.write_bytes(self._priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                       serialization.NoEncryption()))
                try:
                    os.chmod(p, 0o600)
                except OSError:
                    pass
            self.public_raw = self._priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            self.public_pem = self._priv.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        else:
            p = self.key_dir / "report_hmac.key"
            if not p.exists():
                self.key_dir.mkdir(parents=True, exist_ok=True)
                p.write_bytes(os.urandom(32))
            self._secret = p.read_bytes()
            self.public_raw = hashlib.sha256(b"hmac" + self._secret).digest()
            self.public_pem = ""
        self.key_id = hashlib.sha256(self.public_raw).hexdigest()[:16]

    def _sig(self, msg: bytes) -> bytes:
        if self.mode == "ed25519":
            return self._priv.sign(msg)
        return hmac.new(self._secret, msg, hashlib.sha256).digest()

    def sign(self, payload: dict) -> str:
        body = json.dumps({**payload, "key": self.key_id, "alg": self.mode}, sort_keys=True, separators=(",", ":")).encode()
        return f"{PREFIX}.{_b64(body)}.{_b64(self._sig(body))}"

    def verify(self, token: str, public_pem: str | None = None) -> dict:
        token = (token or "").strip()
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != PREFIX:
            return {"valid": False, "reason": "This isn't a TrustLens report code."}
        try:
            body, sig = _unb64(parts[1]), _unb64(parts[2])
            payload = json.loads(body)
        except Exception:
            return {"valid": False, "reason": "The report code is damaged or incomplete."}
        alg = payload.get("alg")
        if public_pem and alg == "ed25519":
            from cryptography.hazmat.primitives import serialization
            pub = serialization.load_pem_public_key(public_pem.encode())
            key_note = "the public key you supplied"
        elif payload.get("key") != self.key_id:
            return {"valid": False, "payload": payload,
                    "reason": f"Signed by a different TrustLens install (key {payload.get('key')}). Ask its owner for "
                              "their public key, then verify with it."}
        else:
            pub = self._priv.public_key() if self.mode == "ed25519" else None
            key_note = "this install's key"
        try:
            if alg == "ed25519":
                pub.verify(sig, body)
            elif alg == "hmac" and self.mode == "hmac":
                if not hmac.compare_digest(sig, self._sig(body)):
                    raise ValueError
            else:
                raise ValueError
        except Exception:
            return {"valid": False, "payload": payload,
                    "reason": "The signature doesn't match: the report's facts were changed after it was signed."}
        return {"valid": True, "payload": payload, "reason": f"Signature valid ({key_note}, {alg})."}


_signer: Signer | None = None


def signer() -> Signer:
    global _signer
    if _signer is None:
        _signer = Signer()
    return _signer


def report_payload(result: dict, custody_head: str) -> dict:
    c = result.get("case", {})
    return {"case": c.get("id", ""), "file": c.get("name", "")[:60], "sha256": result["integrity"]["sha256"],
            "media": result.get("media_kind", "image"), "verdict": result["verdict"],
            "score": result["manipulation_score"], "type": result.get("fake_type", ""),
            "ai_review": bool(result.get("llm_used")), "custody_head": (custody_head or "")[:16],
            "tool": result.get("tool_version", ""), "issued": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
