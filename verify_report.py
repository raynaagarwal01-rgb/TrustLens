"""
Verify a TrustLens PDF report or report code.

    python verify_report.py report.pdf
    python verify_report.py TLR1.xxxx.yyyy
    python verify_report.py report.pdf --public-key their_key.pem   # report from another install
"""

import json
import sys
from pathlib import Path

import signing
from pdf_report import token_from_pdf


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    src = argv[0]
    pem = None
    if "--public-key" in argv:
        pem = Path(argv[argv.index("--public-key") + 1]).read_text()
    token = token_from_pdf(Path(src).read_bytes()) if Path(src).exists() else src
    if not token:
        print("No TrustLens report code found in that file.")
        return 1
    res = signing.signer().verify(token, pem)
    print(("VALID: " if res["valid"] else "NOT VALID: ") + res["reason"])
    if res.get("payload"):
        print(json.dumps(res["payload"], indent=2))
    return 0 if res["valid"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
