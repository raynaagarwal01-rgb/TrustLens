"""
report.py — self-contained HTML evidence report (opens in any browser, prints to PDF).

    from report import build_report_html, result_to_json
"""

import base64
import html
import io
import json

SEV_COLOUR = {"high": "#c0392b", "medium": "#d68910", "low": "#2e86c1", "info": "#7f8c8d"}
VERDICT_COLOUR = {"fake": "#c0392b", "likely_fake": "#e67e22", "inconclusive": "#d4ac0d", "no_evidence": "#27ae60"}


def _img(im, max_side=900) -> str:
    im = im.convert("RGB").copy()
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _e(x) -> str:
    return html.escape(str(x))


def result_to_json(r: dict) -> str:
    """Machine-readable copy of the result (images left out)."""
    return json.dumps({k: v for k, v in r.items() if k != "images"}, indent=2, default=str)


def _official_section(r: dict) -> str:
    oc = r.get("official_check")
    if not oc:
        return ""
    icon = {"confirmed": "✅", "contradicted": "❌"}
    rows = "".join(f"<tr><td>{icon.get(c['status'], '❔')} {_e(c['status'])}</td><td><b>{_e(c['statement'])}</b></td>"
                   f"<td>{_e(c['official'])}</td></tr>" for c in oc["claims"]) or \
        "<tr><td colspan=3 class='muted'>No checkable claims found.</td></tr>"
    src = ", ".join(f"{k}: {v}" for k, v in oc["data_source"].items()) or "none"
    steps = "".join(f"<li><b>{_e(st['title'])}</b>" + (f" <code>{_e(st['command'])}</code>" if st.get("command") else "")
                    + f"<br>{_e(st['detail'])}" + ("<ul>" + "".join(f"<li>{_e(x)}</li>" for x in st.get("lines", [])) + "</ul>" if st.get("lines") else "")
                    + "</li>" for st in oc.get("steps", []))
    steps = f"<h3>How it was checked</h3><ol>{steps}</ol>" if steps else ""
    return (f"<h2>Official record check (VTOP)</h2><p><b>{_e(oc['summary'])}</b></p>"
            f"<table><tr><th>Result</th><th>Claim in the image</th><th>Official record</th></tr>{rows}</table>"
            f"{steps}<p class='muted'>Data source: {_e(src)}</p>")


def _event_section(r: dict) -> str:
    ec = r.get("event_check")
    if not ec:
        return ""
    ev = ec["event"]
    flags = "".join(f"<tr><td><span class='sev' style='background:{SEV_COLOUR[f['severity']]}'>{_e(f['severity'])}</span></td>"
                    f"<td><b>{_e(f['flag'])}</b></td><td>{_e(f['detail'])}</td></tr>" for f in ec["red_flags"]) or \
        "<tr><td colspan=3 class='muted'>No red flags.</td></tr>"
    reasons = "".join(f"<li>{_e(x)}</li>" for x in ec["reasons"])
    urls = "".join(f"<li>{_e(u)}</li>" for u in ec["web"].get("official_urls", []))
    return (f"<h2>Event / hackathon check</h2><p><b>{_e(ec['verdict_label'])}</b> (risk {ec['risk_score']}/100): {_e(ec['summary'])}</p>"
            f"<p>{_e(ev['event_name'])} · {_e(ev['organizer'])} · {_e(ev['dates'])} · fee: {_e(ev['fee'] or 'none stated')}</p>"
            f"<ul>{reasons}</ul><table><tr><th>Severity</th><th>Red flag</th><th>Detail</th></tr>{flags}</table>"
            + (f"<p>Official sources found:</p><ul>{urls}</ul>" if urls else ""))


def _extra_integrity(r: dict) -> str:
    rows = ""
    ph = r["integrity"].get("perceptual") or {}
    if ph:
        rows += f"<tr><td>Perceptual hashes</td><td><code>pHash {ph['phash']} · dHash {ph['dhash']} · aHash {ph['ahash']}</code></td></tr>"
    if r.get("gps"):
        g = r["gps"]
        rows += f"<tr><td>GPS location</td><td>{g['lat']}, {g['lon']} (personal data)</td></tr>"
    th = r.get("thumbnail")
    if th:
        rows += (f"<tr><td>Embedded thumbnail</td><td>{th['thumbnail_size'][0]}x{th['thumbnail_size'][1]}"
                 + (f"; differs from the image at {th['changed_region']}" if th.get("changed_region") else "")
                 + (f"; {_e(th['note'])}" if th.get("note") else "") + "</td></tr>")
    return rows


def _custody_section(r: dict) -> str:
    c = r.get("custody")
    if not c:
        return ""
    chain = c["chain"]
    rows = "".join(f"<tr><td>{e['seq']}</td><td>{_e(e['time'])}</td><td>{_e(e['action'])}</td>"
                   f"<td><code>{e['entry_hash'][:24]}…</code></td></tr>" for e in c["history"])
    status = (f"Chain intact ({chain['entries']} entries). Head hash: <code>{chain['head']}</code>" if chain["ok"]
              else f"<b>Chain broken:</b> {_e(chain['problem'])}")
    return (f"<h3>Chain of custody</h3><p class='muted'>Every action on this file is recorded in a SHA-256 "
            f"hash-chained log; changing, deleting or reordering any entry breaks the chain. {status}</p>"
            f"<table><tr><th>#</th><th>Time (UTC)</th><th>Action</th><th>Entry hash</th></tr>{rows}</table>")


def _figures(r: dict) -> str:
    imgs = r["images"]
    kind = r.get("media_kind", "image")
    items = {"image": [("original", "Image under analysis"),
                       ("ela", "Error-level analysis (bright = reacts to re-compression; box = most anomalous region)"),
                       ("faces", "Faces found (each sent to the AI review as a close-up)"),
                       ("noise", "Noise consistency map, experimental (smooth areas such as sky often light up; weak hint only)")],
             "video": [("sheet", "Frames sampled across the video"), ("original", f"Key frame {(r.get('video') or {}).get('key_frame', '')}"),
                       ("faces", "Faces found on the key frame")],
             "audio": [("original", "Spectrogram (time left to right, pitch bottom to top)"), ("waveform", "Waveform (loudness over time)")]}[kind]
    return "".join(f'<figure><img src="{_img(imgs[k])}"><figcaption class="muted">{_e(c)}</figcaption></figure>'
                   for k, c in items if imgs.get(k) is not None)


def _summary_section(r: dict) -> str:
    sm = r.get("summary")
    if not sm:
        return ""
    en = "".join(f"<li>{_e(x)}</li>" for x in sm.get("en", []))
    hi = "".join(f"<li>{_e(x)}</li>" for x in sm.get("hi", []))
    return (f"<h2>In short</h2><div class='grid'><div><ol>{en}</ol></div>"
            f"<div lang='hi' style=\"font-family:'Nirmala UI','Noto Sans Devanagari','Mangal',sans-serif\"><ol>{hi}</ol></div></div>")


def build_report_html(r: dict) -> str:
    i = r["integrity"]
    colour = VERDICT_COLOUR.get(r["verdict"], "#555")
    findings = "".join(
        f"<tr><td><span class='sev' style='background:{SEV_COLOUR[f['severity']]}'>{_e(f['severity'])}</span></td>"
        f"<td><b>{_e(f['finding'])}</b><br><span class='muted'>{_e(f['location'])}</span></td><td>{_e(f['evidence'])}</td></tr>"
        for f in r["visual_findings"]) or "<tr><td colspan=3 class='muted'>No visual findings reported.</td></tr>"
    signals = "".join(
        f"<tr><td><span class='sev' style='background:{SEV_COLOUR[s['severity']]}'>{_e(s['severity'])}</span></td>"
        f"<td><b>{_e(s['check'])}</b></td><td>{_e(s['detail'])}</td></tr>" for s in r["forensic_signals"])
    exif_rows = "".join(f"<tr><td>{_e(k)}</td><td>{_e(v)}</td></tr>"
                        for k, v in list(r["metadata"]["exif"].items())[:25]) or \
        "<tr><td colspan=2 class='muted'>No EXIF metadata.</td></tr>"
    text_rows = "".join(f"<tr><td>{_e(k)}</td><td>{_e(v)}</td></tr>" for k, v in r["metadata"]["text_chunks"].items())
    rules = "".join(f"<li>{_e(n)}</li>" for n in r["rule_notes"])
    limits = "".join(f"<li>{_e(x)}</li>" for x in r["limitations"])
    actions = "".join(f"<li>{_e(x)}</li>" for x in r["recommended_actions"])
    det = r["detector"]
    det_line = (f"{_e(det['model'])}: fake probability {det['fake_probability']:.0%}" if det.get("status") == "ok"
                else _e(det.get("detail", "not used")))
    imgs = r["images"]

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TrustLens Evidence Report</title>
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:980px;margin:24px auto;padding:0 16px;color:#1c2833;background:#fff}}
 h1{{margin:0 0 4px}} h2{{border-bottom:2px solid #eaecee;padding-bottom:4px;margin-top:32px}}
 .muted{{color:#7f8c8d;font-size:.9em}} .verdict{{border-left:8px solid {colour};background:#f8f9f9;padding:16px 20px;margin:20px 0}}
 .verdict .label{{font-size:1.5em;font-weight:700;color:{colour}}}
 table{{border-collapse:collapse;width:100%;font-size:.92em}} td,th{{border-bottom:1px solid #eaecee;padding:6px 8px;text-align:left;vertical-align:top}}
 .sev{{color:#fff;border-radius:4px;padding:1px 7px;font-size:.8em;text-transform:uppercase}}
 .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}} .grid img{{width:100%;border:1px solid #d5d8dc}}
 code{{font-size:.85em;word-break:break-all}}
 @media print{{.noprint{{display:none}}}}
</style></head><body>
<h1>TrustLens Evidence Report</h1>
<div class="muted">{_e(r['tool_version'])} · generated {_e(i.get('analysed_at', ''))} · a signed PDF version with a verification QR code is available from TrustLens</div>

<div class="verdict">
 <div class="label">{_e(r.get('headline') or r['verdict_label'])}</div>
 <div>Manipulation score <b>{r['manipulation_score']}/100</b> · Type: <b>{_e(r['fake_type_label'])}</b> ·
 Confidence: <b>{_e(r['confidence'])}</b>{' · AI visual analysis used' if r['llm_used'] else ' · forensic tests only (AI analysis unavailable)'}</div>
 <p>{_e(r['explanation'])}</p>
 {f'<b>Rules applied:</b><ul>{rules}</ul>' if rules else ''}
</div>
{_summary_section(r)}

<h2>1. Evidence integrity (chain of custody)</h2>
<table>
 <tr><td>File name</td><td>{_e(i['filename'])}</td></tr>
 <tr><td>SHA-256</td><td><code>{i['sha256']}</code></td></tr>
 <tr><td>MD5</td><td><code>{i['md5']}</code></td></tr>
 <tr><td>Size</td><td>{i['size_bytes']:,} bytes</td></tr>
 <tr><td>Format</td><td>{_e(i['format'])}, {i['width']} × {i['height']} px{(', ' + _e(i['mode'])) if i.get('mode') else ''}{f", JPEG quality ≈ {r['jpeg_quality']}" if r.get('jpeg_quality') else ''}</td></tr>
 <tr><td>Analysed at</td><td>{_e(i.get('analysed_at', ''))}</td></tr>
 {_extra_integrity(r)}
</table>
{_custody_section(r)}
<p class="muted">The file was analysed read-only. Anyone can confirm they hold the same file by computing its
SHA-256 hash (e.g. <code>certutil -hashfile file SHA256</code> on Windows, <code>sha256sum file</code> on Linux/macOS) and comparing it with the value above.</p>

<h2>2. Visual analysis</h2>
<table><tr><th>Severity</th><th>Finding</th><th>Evidence</th></tr>{findings}</table>
{f"<p><b>Heatmap reading:</b> {_e(r['heatmap_reading'])}</p>" if r['heatmap_reading'] else ''}

<h2>3. Forensic tests</h2>
<table><tr><th>Severity</th><th>Test</th><th>Result</th></tr>{signals}</table>
<p class="muted">Pretrained detector: {det_line}</p>
<div class="grid">
 {_figures(r)}
</div>

{_official_section(r)}
{_event_section(r)}
<h2>4. Metadata</h2>
<table>{exif_rows}{text_rows}</table>
<p class="muted">XMP present: {r['metadata'].get('xmp_present', False)} · Content Credentials (C2PA) present: {bool(r['metadata'].get('c2pa_present') or r['metadata'].get('c2pa'))}</p>

<h2>5. Limitations</h2><ul>{limits}</ul>
<h2>6. Recommended actions</h2><ul>{actions}</ul>
<p class="muted">This report supports, but does not replace, examination by a qualified digital forensics expert.</p>
</body></html>"""
