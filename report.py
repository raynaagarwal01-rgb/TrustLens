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
    return (f"<h2>Official record check (VTOP via cli-top)</h2><p><b>{_e(oc['summary'])}</b></p>"
            f"<table><tr><th>Result</th><th>Claim in the image</th><th>Official record</th></tr>{rows}</table>"
            f"<p class='muted'>Data source: {_e(src)}</p>")


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
<div class="muted">{_e(r['tool_version'])} · generated {_e(i['analysed_at'])}</div>

<div class="verdict">
 <div class="label">{_e(r['verdict_label'])}</div>
 <div>Manipulation score <b>{r['manipulation_score']}/100</b> · Type: <b>{_e(r['fake_type_label'])}</b> ·
 Confidence: <b>{_e(r['confidence'])}</b>{' · AI visual analysis used' if r['llm_used'] else ' · forensic tests only (AI analysis unavailable)'}</div>
 <p>{_e(r['explanation'])}</p>
 {f'<b>Rules applied:</b><ul>{rules}</ul>' if rules else ''}
</div>

<h2>1. Evidence integrity (chain of custody)</h2>
<table>
 <tr><td>File name</td><td>{_e(i['filename'])}</td></tr>
 <tr><td>SHA-256</td><td><code>{i['sha256']}</code></td></tr>
 <tr><td>MD5</td><td><code>{i['md5']}</code></td></tr>
 <tr><td>Size</td><td>{i['size_bytes']:,} bytes</td></tr>
 <tr><td>Format</td><td>{_e(i['format'])}, {i['width']} × {i['height']} px, {_e(i['mode'])}{f", JPEG quality ≈ {r['jpeg_quality']}" if r['jpeg_quality'] else ''}</td></tr>
 <tr><td>Analysed at</td><td>{_e(i['analysed_at'])}</td></tr>
</table>
<p class="muted">The file was analysed read-only. Anyone can confirm they hold the same file by computing its
SHA-256 hash (e.g. <code>certutil -hashfile file SHA256</code> on Windows, <code>sha256sum file</code> on Linux/macOS) and comparing it with the value above.</p>

<h2>2. Visual analysis</h2>
<table><tr><th>Severity</th><th>Finding</th><th>Evidence</th></tr>{findings}</table>
{f"<p><b>Heatmap reading:</b> {_e(r['heatmap_reading'])}</p>" if r['heatmap_reading'] else ''}

<h2>3. Forensic tests</h2>
<table><tr><th>Severity</th><th>Test</th><th>Result</th></tr>{signals}</table>
<p class="muted">Pretrained detector: {det_line}</p>
<div class="grid">
 <figure><img src="{_img(imgs['original'])}"><figcaption class="muted">Image under analysis</figcaption></figure>
 <figure><img src="{_img(imgs['ela'])}"><figcaption class="muted">Error-level analysis (bright = reacts to re-compression; box = most anomalous region)</figcaption></figure>
 <figure><img src="{_img(imgs['noise'])}"><figcaption class="muted">Noise consistency map, experimental (smooth areas such as sky often light up; weak hint only)</figcaption></figure>
</div>

{_official_section(r)}
{_event_section(r)}
<h2>4. Metadata</h2>
<table>{exif_rows}{text_rows}</table>
<p class="muted">XMP present: {r['metadata']['xmp_present']} · Content Credentials (C2PA) present: {r['metadata']['c2pa_present']}</p>

<h2>5. Limitations</h2><ul>{limits}</ul>
<h2>6. Recommended actions</h2><ul>{actions}</ul>
<p class="muted">This report supports, but does not replace, examination by a qualified digital forensics expert.</p>
</body></html>"""
