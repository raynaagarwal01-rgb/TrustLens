"""
pdf_report.py: signed PDF evidence report with a verification QR code.

    from pdf_report import build_pdf
    pdf_bytes, token = build_pdf(result_with_images_and_custody, custody_head)

The PDF holds: the verdict and plain summary (English, and Hindi when the system can shape
Devanagari text), the evidence image with numbered markers and its key analysis layer, file
fingerprints, findings, every test, campus/screenshot/reverse-search checks, the video timeline or
voice-note transcript, the chain-of-custody entries, and a QR code carrying the signed report token
(also stored in the PDF's metadata) so anyone can check the facts weren't changed.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (Image as RLImage, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)
from xml.sax.saxutils import escape

import signing
import summary

ROOT = Path(__file__).resolve().parent
INK, GRAPHITE, RULE, SHEET = colors.HexColor("#14202B"), colors.HexColor("#566370"), colors.HexColor("#C3CDD5"), colors.HexColor("#F7F9FA")
MARKER = colors.HexColor("#F2C230")
TONE = {"fake": "#B3312A", "likely_fake": "#B3312A", "inconclusive": "#9A6410", "no_evidence": "#1D6E52"}
WASH = {"fake": "#F6E1DF", "likely_fake": "#F6E1DF", "inconclusive": "#F6EBD5", "no_evidence": "#DDEFE6"}
SEV = {"high": "#B3312A", "medium": "#9A6410", "low": "#2F5E86", "info": "#566370"}

S = {
    "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=INK),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12.5, leading=16, textColor=INK, spaceBefore=10, spaceAfter=4),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9.5, leading=13, textColor=INK, alignment=TA_LEFT),
    "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8, leading=10.5, textColor=GRAPHITE),
    "mono": ParagraphStyle("mono", fontName="Courier", fontSize=8, leading=10, textColor=INK),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8.5, leading=11, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="Helvetica-Bold", fontSize=8.5, leading=11, textColor=INK),
}


def P(text, style="body"):
    return Paragraph(escape(str(text)), S[style])


def evidence_marks(r: dict) -> list[dict]:
    """Same numbered regions the interface shows (web/src/evidence.ts)."""
    marks = []
    if r.get("media_kind") == "video":  # still-image tests on decoded frames are hints only
        for f in (r.get("faces") or {}).get("faces", []):
            if f.get("assessment") in ("suspicious", "likely manipulated"):
                marks.append({"box": f["box"], "title": f"Face {f['n']}: {f['assessment']}"})
        return [{**m, "n": i + 1} for i, m in enumerate(marks)]
    th = (r.get("thumbnail") or {}).get("changed_region")
    if th:
        marks.append({"box": th, "title": "Differs from the camera's stored preview"})
    cm = (r.get("advanced") or {}).get("copy_move", {}).get("regions")
    sig = next((s for s in r.get("forensic_signals", []) if s["check"] == "Cloned area (copy-move)"), None)
    if cm and len(cm) == 2 and sig and sig["severity"] not in ("low", "info"):
        marks += [{"box": cm[0], "title": "Matching area A (copy-move)"}, {"box": cm[1], "title": "Matching area B (copy-move)"}]
    cmp = r.get("comparison") or {}
    if cmp.get("changed_region") and cmp.get("verdict") == "edited":
        marks.append({"box": cmp["changed_region"], "title": "Differs from the reference image"})
    ela = ((r.get("ela") or {}).get("region") or {}).get("box")
    if ela:
        marks.append({"box": ela, "title": "Reacts differently to re-compression (ELA)"})
    gh = ((r.get("advanced") or {}).get("ghost") or {}).get("region")
    if gh and gh.get("box"):
        marks.append({"box": gh["box"], "title": "Matches an earlier lower-quality save (JPEG ghost)"})
    for f in (r.get("faces") or {}).get("faces", []):
        if f.get("assessment") in ("suspicious", "likely manipulated"):
            marks.append({"box": f["box"], "title": f"Face {f['n']}: {f['assessment']}"})
    for m in (r.get("audio") or {}).get("marks", []):
        marks.append(m)
    return [{**m, "n": i + 1} for i, m in enumerate(marks)]


def _font(size):
    for name in ("DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_marks(img: Image.Image, marks: list[dict]) -> Image.Image:
    im = img.convert("RGB").copy()
    d = ImageDraw.Draw(im)
    lw = max(2, im.width // 300)
    font = _font(max(14, im.width // 40))
    for m in marks:
        x0, y0, x1, y1 = m["box"]
        d.rectangle((x0, y0, x1, y1), outline=(242, 194, 48), width=lw)
        s = font.size + 10
        d.rectangle((x0, max(0, y0 - s), x0 + s, max(s, y0)), fill=(242, 194, 48))
        d.text((x0 + 6, max(0, y0 - s) + 3), str(m["n"]), fill=(20, 32, 43), font=font)
    return im


def _rl_image(im: Image.Image, max_w: float, max_h: float) -> RLImage:
    im = im.convert("RGB")
    im.thumbnail((1400, 1400))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    buf.seek(0)
    k = min(max_w / im.width, max_h / im.height)
    return RLImage(buf, width=im.width * k, height=im.height * k)


def _hindi_image(lines: list[str], width_px: int = 1500) -> Image.Image | None:
    """Devanagari needs shaping; ReportLab can't, PIL with raqm can. None when unavailable."""
    try:
        from PIL import features
        if not features.check("raqm"):
            return None
        font = ImageFont.truetype(str(ROOT / "assets" / "fonts" / "NotoSansDevanagari-Regular.ttf"), 30,
                                  layout_engine=ImageFont.Layout.RAQM)
    except Exception:
        return None
    rows = []
    for line in lines:  # word wrap by measured width
        words, cur = line.split(" "), ""
        for w in words:
            t = (cur + " " + w).strip()
            if font.getlength(t) > width_px - 20 and cur:
                rows.append(cur)
                cur = w
            else:
                cur = t
        rows.append(cur)
        rows.append("")
    lh = 46
    im = Image.new("RGB", (width_px, lh * max(1, len(rows) - 1) + 10), (255, 255, 255))
    d = ImageDraw.Draw(im)
    for i, row in enumerate(rows[:-1]):
        d.text((4, 4 + i * lh), row, font=font, fill=(20, 32, 43))
    return im


def _qr(token: str) -> Image.Image | None:
    try:
        import cv2
        q = cv2.QRCodeEncoder.create().encode(token)
        im = Image.fromarray(q).convert("L")
        return im.resize((im.width * 8, im.height * 8), Image.NEAREST)
    except Exception:
        return None


def _table(rows, widths, header=True):
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
             ("LEFTPADDING", (0, 0), (-1, -1), 2)]
    if header:
        style += [("LINEBELOW", (0, 0), (-1, 0), 0.8, INK)]
    t.setStyle(TableStyle(style))
    return t


def _key_layer(r: dict, images: dict):
    order = [("compare", "Difference from reference"), ("copy_move", "Clone map"), ("thumbnail", "Camera preview"),
             ("ghost", "JPEG ghost"), ("faces", "Faces found"), ("ela", "Error levels"), ("waveform", "Waveform")]
    if r.get("media_kind") == "video" and images.get("sheet") is not None:
        return images["sheet"], "Frames sampled across the video"
    for k, label in order:
        if images.get(k) is not None:
            if k == "copy_move" and not any(m["title"].startswith("Matching") for m in evidence_marks(r)):
                continue
            return images[k], label
    return None, ""


def build_pdf(r: dict, custody_head: str = "") -> tuple[bytes, str]:
    images = r.get("images") or {}
    token = signing.signer().sign(signing.report_payload(r, custody_head))
    case = r.get("case", {})
    integ = r["integrity"]
    v = r["verdict"]
    unchecked = v == "no_evidence" and (not r.get("llm_used") or r.get("media_kind", "image") != "image")
    if unchecked:
        v = "inconclusive"  # colour only: a result nobody could fully check is never shown as cleared
    buf = io.BytesIO()
    W = A4[0] - 30 * mm

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(GRAPHITE)
        canvas.drawString(15 * mm, 10 * mm, f"TrustLens evidence report · case {case.get('id', '')} · file SHA-256 {integ['sha256'][:16]}…")
        canvas.drawRightString(A4[0] - 15 * mm, 10 * mm, f"Page {doc.page}")
        canvas.setStrokeColor(MARKER)
        canvas.setLineWidth(2)
        canvas.line(15 * mm, A4[1] - 12 * mm, 45 * mm, A4[1] - 12 * mm)
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"TrustLens evidence report: {case.get('name', '')}", author="TrustLens",
                            subject=f"Case {case.get('id', '')}", keywords=token, creator=r.get("tool_version", "TrustLens"))
    story = [P("Evidence report", "h1"),
             P(f"{case.get('name', '')}  ·  case {case.get('id', '')}  ·  {r.get('media_kind', 'image')}  ·  "
               f"{r.get('tool_version', '')}  ·  signed {signing.report_payload(r, custody_head)['issued']}", "small"),
             Spacer(1, 6)]

    # verdict block
    sm = r.get("summary") or {}
    type_line = ("A cloned voice can't be ruled out from the sound alone" if unchecked and r.get("media_kind") == "audio"
                 else "The AI review saw no deepfake signs, but a clean-looking video can still be one"
                 if unchecked and r.get("media_kind") == "video" and r.get("llm_used")
                 else "AI review was off, and forensic tests alone can't spot most AI images and deepfakes" if unchecked
                 else "Nothing found that indicates editing or AI generation" if r["verdict"] == "no_evidence"
                 else r.get("fake_type_label") or "")
    head = Paragraph(f"<font color='{TONE[v]}' size='16'><b>{escape(summary.headline(r))}</b></font><br/>"
                     f"<font size='10'>{escape(type_line)}</font>", S["body"])
    facts = Paragraph(f"Score <b>{r['manipulation_score']}</b>/100 &nbsp; Confidence <b>{escape(str(r['confidence']))}</b>"
                      f" &nbsp; Based on <b>{('file and sound tests' + (' and transcript' if r.get('llm_used') else '')) if r.get('media_kind') == 'audio' else 'forensic tests and AI review' if r.get('llm_used') else 'forensic tests only'}</b>",
                      S["body"])
    en = "<br/>".join(escape(x) for x in sm.get("en", []))
    vb = Table([[head], [facts], [Paragraph(en, S["body"])]], colWidths=[W])
    vb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(WASH[v])),
                            ("LINEBEFORE", (0, 0), (0, -1), 4, colors.HexColor(TONE[v])),
                            ("LEFTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 5),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story += [vb]
    hi = _hindi_image(sm.get("hi", [])) if sm.get("hi") else None
    if hi is not None:
        story += [Spacer(1, 4), P("Summary in Hindi", "small"), _rl_image(hi, W, 60 * mm)]

    # evidence images
    marks = evidence_marks(r)
    if images.get("original") is not None:
        layer, label = _key_layer(r, images)
        left = _rl_image(draw_marks(images["original"], marks), W / 2 - 4, 85 * mm)
        cells = [[left, _rl_image(layer, W / 2 - 4, 85 * mm) if layer is not None else ""],
                 [P("Evidence with numbered markers" if r.get("media_kind") != "audio" else "Spectrogram with markers", "small"),
                  P(label, "small")]]
        t = Table(cells, colWidths=[W / 2, W / 2])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        story += [Spacer(1, 8), t]
    if marks:
        story += [Spacer(1, 4), _table([[P("#", "cellb"), P("Marked region", "cellb")]] +
                                       [[P(m["n"], "cell"), P(m["title"], "cell")] for m in marks], [10 * mm, W - 10 * mm])]

    # why
    why = [n for n in r.get("rule_notes", [])]
    if why or r.get("explanation"):
        story += [P("Why", "h2")] + [P("• " + n) for n in why]
        if r.get("explanation"):
            story += [P(r["explanation"])]
    vf = r.get("visual_findings") or []
    if vf:
        story += [P("What the AI review saw", "h2"),
                  _table([[P("Finding", "cellb"), P("Where", "cellb"), P("Evidence", "cellb"), P("Severity", "cellb")]] +
                         [[P(f["finding"], "cell"), P(f.get("location", ""), "cell"), P(f.get("evidence", ""), "cell"),
                           P(f["severity"], "cell")] for f in vf], [40 * mm, 35 * mm, W - 95 * mm, 20 * mm])]
    fcs = [f for f in (r.get("faces") or {}).get("faces", []) if f.get("assessment")]
    if fcs:
        story += [P("Faces", "h2"), _table([[P("Face", "cellb"), P("Assessment", "cellb"), P("Evidence", "cellb")]] +
                                           [[P(f["n"], "cell"), P(f["assessment"], "cell"), P(f.get("evidence", ""), "cell")] for f in fcs],
                                           [14 * mm, 35 * mm, W - 49 * mm])]

    # media specific
    vid = r.get("video")
    if vid:
        story += [P("Video timeline", "h2"),
                  P(f"{vid.get('duration')} s, {vid.get('fps')} fps, {vid.get('frames_total')} frames, codec {vid.get('codec')}. "
                    f"Key frame {vid.get('key_frame')}." + (f" AI tools named in metadata: {', '.join(vid['ai_tools_named'])}." if vid.get("ai_tools_named") else ""), "small"),
                  _table([[P(h, "cellb") for h in ("Frame", "Time", "Faces", "AI score", "Note")]] +
                         [[P(f["label"], "cell"), P(f"{f['t']}s", "cell"), P(len(f["faces"]), "cell"),
                           P("" if f.get("ai_score") is None else f["ai_score"], "cell"), P(f.get("ai_note", ""), "cell")]
                          for f in vid.get("timeline", [])], [16 * mm, 16 * mm, 14 * mm, 18 * mm, W - 64 * mm])]
    sp = (r.get("audio") or {}).get("speech") or ((vid or {}).get("audio") or {}).get("speech")
    if sp and sp.get("status") == "ok":
        story += [P("What is said", "h2"), P(f"Scam risk: {sp.get('scam_risk', '')}. {sp.get('summary', '')}")]
        for c in sp.get("scam_cues", []):
            story += [P(f"• {c['cue']}: “{c['quote']}”")]
        if sp.get("transcript"):
            story += [P("Transcript (machine-generated; check against the recording)", "small"), P(sp["transcript"][:3000], "small")]

    for key, title in (("official_check", "Notice checked against VTOP"), ("event_check", "Event check"),
                       ("screenshot_check", "Screenshot check"), ("reverse_search", "Earlier copies online")):
        sec = r.get(key)
        if not sec:
            continue
        story += [P(title, "h2")]
        if key == "official_check":
            story += [_table([[P("Status", "cellb"), P("Claim", "cellb"), P("Official record", "cellb")]] +
                             [[P(c["status"], "cell"), P(c["statement"], "cell"), P(c["official"], "cell")] for c in sec.get("claims", [])],
                             [26 * mm, (W - 26 * mm) / 2, (W - 26 * mm) / 2])]
        elif key == "event_check":
            story += [P(f"{sec.get('verdict_label', sec.get('verdict', ''))}: {sec.get('summary', '')}")]
            story += [P(f"• {f['flag']}: {f['detail']}", "small") for f in sec.get("flags", [])]
        elif key == "screenshot_check":
            story += [P(f"{sec.get('kind', '')} screenshot from {sec.get('app') or 'an unknown app'}: {sec.get('overall', '').replace('_', ' ')}")]
            story += [_table([[P("Check", "cellb"), P("Result", "cellb"), P("Detail", "cellb")]] +
                             [[P(c["check"], "cell"), P(c["status"], "cell"), P(c["detail"], "cell")] for c in sec.get("checks", [])],
                             [50 * mm, 24 * mm, W - 74 * mm])]
            story += [P(f"• Visual: {a['anomaly']} ({a['where']}, {a['severity']})", "small") for a in sec.get("visual_anomalies", [])]
        else:
            story += [P(sec.get("summary", ""))]
            story += [P(f"• {m.get('date', '')[:10] or 'undated'}  {m.get('title', '')}  {m['url']}  (fingerprint distance {m['best_distance']}/64)", "small")
                      for m in sec.get("matches", [])]

    # file
    story += [P("File and fingerprints", "h2"),
              _table([[P(k, "cellb"), P(v_, "mono" if k in ("SHA-256", "MD5") else "cell")] for k, v_ in [
                  ("File", case.get("name", integ.get("filename", ""))), ("Format", f"{integ.get('format', '')}, {(r.get('audio') or {}).get('measurements', {}).get('duration', '?')} s of audio"
                             if r.get("media_kind") == "audio" else f"{integ.get('format', '')} {integ.get('width', '')}×{integ.get('height', '')}"),
                  ("Size", f"{integ.get('size_bytes', 0):,} bytes"), ("SHA-256", integ["sha256"]), ("MD5", integ.get("md5", ""))]],
                     [28 * mm, W - 28 * mm], header=False)]

    # tests
    sigs = r.get("forensic_signals", [])
    if sigs:
        story += [P("Every test", "h2"),
                  _table([[P("Test", "cellb"), P("Result", "cellb"), P("Detail", "cellb")]] +
                         [[P(s["check"], "cell"), Paragraph(f"<font color='{SEV.get(s['severity'], '#566370')}'><b>{escape(s['severity'])}</b></font>", S["cell"]),
                           P(s["detail"], "cell")] for s in sigs], [52 * mm, 16 * mm, W - 68 * mm])]

    # custody
    hist = (r.get("custody") or {}).get("history") or []
    chain = (r.get("custody") or {}).get("chain") or {}
    story += [P("Chain of custody", "h2"),
              P(f"Log {'intact' if chain.get('ok') else 'BROKEN'}: {chain.get('entries', 0)} entries; every entry contains the hash of "
                "the one before it, so edits, deletions and reordering are detectable (python custody.py verify).", "small")]
    if hist:
        story += [_table([[P(h, "cellb") for h in ("#", "Time (UTC)", "Action", "Entry hash")]] +
                         [[P(e.get("seq", ""), "cell"), P(str(e.get("time", ""))[:19], "cell"), P(e.get("action", ""), "cell"),
                           P(str(e.get("entry_hash", ""))[:24] + "…", "mono")] for e in hist[-15:]],
                         [10 * mm, 40 * mm, 55 * mm, W - 105 * mm])]

    # limitations + signature
    story += [P("Limitations", "h2")] + [P("• " + l, "small") for l in r.get("limitations", [])]
    qr = _qr(token)
    sig_text = [P("Verify this report", "h2"),
                P("The QR code holds the report's key facts (case, file SHA-256, verdict, score, type, custody-log head, time) "
                  "and a digital signature over them. To check it, open TrustLens → Verify a report and scan or paste the code, "
                  "or upload this PDF; or run: python verify_report.py thisfile.pdf. If any of those facts was changed, "
                  "the signature fails.", "small"),
                P(f"Signing key ID {signing.signer().key_id} ({signing.signer().mode}).", "small")]
    if qr is not None:
        t = Table([[_rl_image(qr, 42 * mm, 42 * mm), sig_text]], colWidths=[46 * mm, W - 46 * mm])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        story += [Spacer(1, 6), KeepTogether(t)]
    else:
        story += sig_text
    story += [P("Report code", "small"), P(token, "mono")]
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue(), token


def token_from_pdf(pdf: bytes) -> str:
    """Read the signed token back out of a TrustLens PDF (metadata keywords)."""
    try:
        from pypdf import PdfReader
        meta = PdfReader(io.BytesIO(pdf)).metadata or {}
        kw = meta.get("/Keywords", "") or ""
        if kw.startswith(signing.PREFIX + "."):
            return kw
    except Exception:
        pass
    import re
    m = re.search(rb"TLR1\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+", pdf)
    return m.group(0).decode() if m else ""
