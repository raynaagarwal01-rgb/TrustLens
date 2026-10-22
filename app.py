"""
TrustLens — deepfake detection and digital evidence analysis.

Run:  streamlit run app.py
"""

import hashlib
import io
import os
import envfile  # loads .env
from pathlib import Path

import numpy as np
import streamlit as st
from PIL import Image

import campus_check
import custody
import event_check
import evidence_analyser as ea
from report import build_report_html, result_to_json

st.set_page_config(page_title="TrustLens", page_icon="🔍", layout="wide")

SAMPLES = Path(__file__).parent / "samples"
VERDICT_STYLE = {
    "fake": ("#c0392b", "🚨"),
    "likely_fake": ("#e67e22", "⚠️"),
    "inconclusive": ("#b7950b", "❓"),
    "no_evidence": ("#1e8449", "✅"),
}
SEV_ICON = {"high": "🔴", "medium": "🟠", "low": "🔵", "info": "⚪"}

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("🔍 TrustLens")
    st.caption("AI + LLM deepfake detection and digital evidence analysis")
    key_ok, ai_status = envfile.ai_review_status()
    use_llm = st.toggle("AI visual analysis (vision LLM)", value=key_ok, disabled=not key_ok,
                        help="Sends the image and its ELA heatmap to the vision model.")
    if not key_ok:
        st.error(f"{ai_status} Without it, AI-generated images without Content Credentials "
                 "(screenshots, downloads, WhatsApp forwards) can't be detected.")
    det = os.getenv("DETECTOR_MODEL")
    st.caption(f"Pretrained detector: {det if det else 'off (set DETECTOR_MODEL)'}")

    st.divider()
    st.subheader("Demo samples")
    sample_files = sorted(p for p in SAMPLES.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
                          and not p.stem.endswith("_gt")) if SAMPLES.exists() else []
    labels = {"(none)": None}
    for p in sample_files:
        tag = ("Tampered (CASIA)" if p.name.startswith("Tp_") else "Authentic" if p.name.startswith("Au_")
               else "AI-generated" if p.name.startswith("AI_") else "Forged notice (demo)" if p.name.startswith("Forged_")
               else "Notice (demo)" if p.name.startswith("Notice_")
               else "Event poster (demo)" if p.name.startswith("Event_")
               else "Edited photo (demo)" if p.name.startswith("Edited_") else "Sample")
        labels[f"{tag} · {p.name[:28]}"] = p
    choice = st.selectbox("Pick a sample", list(labels))

# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

st.header("Is this image real?")
st.write("Upload a photo, screenshot, certificate or circular. TrustLens checks for AI generation, "
         "deepfakes and edits, and produces an evidence report you can download.")
upload = st.file_uploader("Image to analyse", type=["jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff"])

data, name, gt_path = None, None, None
if upload is not None:
    data, name = upload.getvalue(), upload.name
elif labels.get(choice):
    p = labels[choice]
    data, name = p.read_bytes(), p.name
    g = p.with_name(p.stem + "_gt.png")
    gt_path = g if g.exists() else None

if data is None:
    st.info("Upload an image or pick a demo sample in the sidebar.")
    st.stop()

sha = hashlib.sha256(data).hexdigest()
cache_key = f"{sha}:{use_llm}"
if st.session_state.get("key") != cache_key:
    with st.spinner("Running forensic tests and AI visual analysis..."):
        try:
            st.session_state["result"] = ea.analyse(data, name, use_llm=use_llm)
            st.session_state["key"] = cache_key
            res = st.session_state["result"]
            custody.record("analysed", sha, {"file": name, "verdict": res["verdict"],
                                             "score": res["manipulation_score"], "tool": res["tool_version"]})
        except ValueError as e:
            st.error(str(e))
            st.stop()
r = st.session_state["result"]

# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

colour, icon = VERDICT_STYLE[r["verdict"]]
st.markdown(
    f"""<div style="border-left:8px solid {colour};padding:14px 20px;border-radius:6px;
    background:rgba(127,127,127,0.08);margin:8px 0 16px">
    <div style="font-size:1.6em;font-weight:700;color:{colour}">{icon} {r['verdict_label']}</div>
    <div>{r['explanation']}</div></div>""", unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Manipulation score", f"{r['manipulation_score']}/100")
c2.metric("Type", r["fake_type_label"])
c3.metric("Confidence", r["confidence"].title())
c4.metric("Analysis", "AI + forensics" if r["llm_used"] else "Forensics only")
if r["error"]:
    st.caption(f"AI analysis unavailable ({r['error'][:120]}); result based on forensic tests only.")
for note in r["rule_notes"]:
    st.caption(f"Rule applied: {note}")

# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------

imgs = r["images"]
cols = st.columns(3 if gt_path else 2)
cols[0].image(imgs["original"], caption="Image under analysis")
cols[1].image(imgs["ela"], caption="Error-level analysis (box = most anomalous region)")
if gt_path:
    mask = np.asarray(Image.open(gt_path).convert("L").resize(imgs["original"].size)) > 127
    overlay = np.asarray(imgs["original"]).copy()
    overlay[mask] = (0.5 * overlay[mask] + 0.5 * np.array([255, 0, 0])).astype(np.uint8)
    cols[2].image(Image.fromarray(overlay), caption="Ground truth: the area that was actually edited (dataset mask)")
with st.expander("Noise consistency map (experimental)"):
    st.image(imgs["noise"], caption="Bright = noise unlike the rest of the image. Smooth areas such as sky "
                                    "often light up too, so treat this as a weak hint.")

# ---------------------------------------------------------------------------
# Details
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Campus check against official VTOP records (cli-top)
# ---------------------------------------------------------------------------

STATUS_ICON = {"confirmed": "✅", "contradicted": "❌", "not_checked": "❔"}
st.subheader("🏫 Campus check: compare with official VTOP records")
st.caption("For notices, circulars and forwarded messages. TrustLens reads the claims in the image and checks "
           "them against your exam schedule, academic calendar and holidays from VTOP, fetched with cli-top.")
if not r["llm_used"]:
    st.info("Turn on AI visual analysis (needs an API key) so TrustLens can read the notice.")
else:
    live = st.checkbox("Fetch fresh data from VTOP now (slower, about a minute)", value=False,
                       help="Off: uses the VTOP snapshot saved by your last cli-top run.")
    if st.button("Check this notice against VTOP"):
        with st.spinner("Reading the notice and checking your VTOP records..."):
            try:
                check = campus_check.run_campus_check(data, live=live)
                st.session_state["result"] = campus_check.apply_to_result(r, check)
                custody.record("vtop_notice_check", sha, {"overall": check["overall"], "source": check["data_source"]})
                st.rerun()
            except Exception as e:
                st.error(f"Campus check failed: {type(e).__name__}: {str(e)[:200]}")
    oc = r.get("official_check")
    if oc:
        box = {"contradicted": st.error, "confirmed": st.success}.get(oc["overall"], st.info)
        box(oc["summary"])
        if not oc["claims"]:
            st.write("No exam, holiday or deadline claims found in this image.")
        for c in oc["claims"]:
            st.markdown(f"{STATUS_ICON.get(c['status'], '❔')} **{c['statement']}**  \n{c['official']}")
        src = ", ".join(f"{k}: {v}" for k, v in oc["data_source"].items()) or "no VTOP data found"
        st.caption(f"Official data source: {src}")
        if oc["vtop_errors"]:
            with st.expander("VTOP fetch problems"):
                for k, v in oc["vtop_errors"].items():
                    st.write(f"{k}: {v}")

# ---------------------------------------------------------------------------
# Event / hackathon check: does it exist, and is the registration safe?
# ---------------------------------------------------------------------------

st.subheader("🎟️ Event / hackathon check: is it real?")
st.caption("For posters and forwards promoting hackathons, workshops, fests or internships. TrustLens reads the "
           "details, looks for the event in VTOP club events (cli-top) and on the web, and checks the payment "
           "and registration links.")
if not r["llm_used"]:
    st.info("Turn on AI visual analysis (needs an API key) so TrustLens can read the poster.")
else:
    live_ev = st.checkbox("Fetch VTOP club events live now (slower)", value=False, key="live_events",
                          help="Off: uses the snapshot saved by your last `python vtop.py events` run.")
    if st.button("Check this event"):
        with st.spinner("Reading the poster, searching for the official event and checking links..."):
            try:
                r["event_check"] = event_check.run_event_check(data, live_vtop=live_ev)
                custody.record("event_check", sha, {"verdict": r["event_check"]["verdict"],
                                                    "event": r["event_check"]["event"]["event_name"]})
                st.session_state["result"] = r
            except Exception as e:
                st.error(f"Event check failed: {type(e).__name__}: {str(e)[:200]}")
    ec = r.get("event_check")
    if ec:
        box = {"likely_scam": st.error, "verified": st.success}.get(ec["verdict"], st.warning)
        box(f"**{ec['verdict_label']}** · {ec['summary']}")
        ev = ec["event"]
        st.markdown(f"**{ev['event_name'] or 'Unnamed event'}** · {ev['organizer'] or 'organiser not stated'}"
                    + (f" · {ev['dates']}" if ev["dates"] else "") + (f" · fee: {ev['fee']}" if ev["fee"] else ""))
        for reason in ec["reasons"]:
            st.markdown(f"- {reason}")
        for f in ec["red_flags"]:
            st.markdown(f"{SEV_ICON[f['severity']]} **{f['flag']}**  \n{f['detail']}")
        web = ec["web"]
        if web.get("status") == "ok":
            st.caption(f"Checked via {web.get('method', 'web search')}" + (f": {web['summary']}" if web.get("summary") else ""))
            for u in web.get("official_urls", []):
                st.markdown(f"- [{u}]({u})")
        elif web.get("detail"):
            st.caption(f"Web check unavailable: {web['detail'][:200]}")
        v = ec["vtop"]
        st.caption("VTOP club events: " + (f"{v['events_listed']} events checked ({v['source']})" if v.get("status") == "ok"
                                             else v.get("detail", "not checked")))

t1, t2, t3, t4 = st.tabs(["Visual findings", "Forensic tests", "Metadata", "Evidence integrity"])
with t1:
    if r["visual_findings"]:
        for f in r["visual_findings"]:
            st.markdown(f"{SEV_ICON[f['severity']]} **{f['finding']}** · _{f['location']}_  \n{f['evidence']}")
    else:
        st.write("No visual findings reported." if r["llm_used"] else "Turn on AI visual analysis to get visual findings.")
    if r["heatmap_reading"]:
        st.markdown(f"**Heatmap reading:** {r['heatmap_reading']}")
with t2:
    for s in r["forensic_signals"]:
        st.markdown(f"{SEV_ICON[s['severity']]} **{s['check']}**  \n{s['detail']}")
    d = r["detector"]
    if d.get("status") == "ok":
        st.markdown(f"**Pretrained detector** ({d['model']}): fake probability {d['fake_probability']:.0%}")
with t3:
    exif = r["metadata"]["exif"]
    if exif:
        st.table({"Field": list(exif)[:30], "Value": [str(v) for v in list(exif.values())[:30]]})
    else:
        st.write("No EXIF metadata.")
    if r["metadata"]["text_chunks"]:
        st.write("Embedded text metadata:")
        st.json(r["metadata"]["text_chunks"])
    if r["metadata"].get("c2pa"):
        st.write("Content Credentials (C2PA) manifest, as read by TrustLens (signature not verified):")
        st.json(r["metadata"]["c2pa"])
    st.caption(f"XMP present: {r['metadata']['xmp_present']} · Content Credentials present: {r['metadata']['c2pa_present']}")
with t4:
    i = r["integrity"]
    st.markdown(f"**SHA-256:** `{i['sha256']}`  \n**MD5:** `{i['md5']}`  \n"
                f"**Size:** {i['size_bytes']:,} bytes · **Format:** {i['format']} {i['width']}×{i['height']}  \n"
                f"**Analysed:** {i['analysed_at']} · {r['tool_version']}")
    ph = i.get("perceptual") or {}
    if ph:
        st.markdown(f"**Perceptual hashes** (match re-saved or resized copies of the same picture): "
                    f"pHash `{ph['phash']}` · dHash `{ph['dhash']}` · aHash `{ph['ahash']}`")
    if r.get("gps"):
        g = r["gps"]
        st.markdown(f"**GPS location in file:** {g['lat']}, {g['lon']} · [open map]({g['map']})  \n"
                    "_Personal data: share the original file with care._")
    if r.get("thumbnail") and imgs.get("thumbnail") is not None:
        tc1, tc2 = st.columns([1, 3])
        tc1.image(imgs["thumbnail"], caption="Camera preview stored inside the file")
        th = r["thumbnail"]
        tc2.markdown("**Embedded thumbnail check:** cameras save a small preview inside the photo; editors often "
                     "change the photo but not the preview.  \n"
                     + (f"Area that differs from the preview: `{th['changed_region']}`" if th.get("changed_region")
                        else f"Largest local difference: {th.get('max_local_difference', 'n/a')} "
                             f"(edited areas measured 31–115 in testing)."))

    st.markdown("**Find the original online** (upload this image on any of these): "
                "[Google Lens](https://lens.google.com/) · [Bing Visual Search](https://www.bing.com/visualsearch) · "
                "[TinEye](https://tineye.com/) · [Yandex Images](https://yandex.com/images/)")

    chain = custody.verify()
    hist = custody.history(sha)
    st.markdown("**Chain of custody** (tamper-evident, SHA-256 hash-chained log)")
    if chain["ok"]:
        st.success(f"Log verified: {chain['entries']} entries, chain intact. Head hash `{(chain['head'] or '')[:16]}…`")
    else:
        st.error(f"Custody log broken: {chain['problem']}")
    if hist:
        st.table({"#": [e["seq"] for e in hist], "Time (UTC)": [e["time"] for e in hist],
                  "Action": [e["action"] for e in hist],
                  "Entry hash": [e["entry_hash"][:16] + "…" for e in hist]})
    st.caption("Verify independently: `python custody.py verify`")

    st.write("Check that a file is the exact one in this report:")
    other = st.file_uploader("File to verify", key="verify")
    if other is not None:
        h = hashlib.sha256(other.getvalue()).hexdigest()
        if h == i["sha256"]:
            st.success("Hashes match: this is the same file, unaltered.")
        else:
            st.error(f"Hashes differ: this file is not identical to the analysed one.\n\n`{h}`")

st.subheader("Limitations")
for l in r["limitations"]:
    st.markdown(f"- {l}")
st.subheader("What to do next")
for a in r["recommended_actions"]:
    st.markdown(f"- {a}")

st.divider()
d1, d2 = st.columns(2)
r["custody"] = {"chain": custody.verify(), "history": custody.history(sha)}
d1.download_button("⬇ Download evidence report (HTML, print to PDF)", build_report_html(r),
                   file_name=f"trustlens_report_{sha[:12]}.html", mime="text/html",
                   on_click=custody.record, args=("report_exported", sha, {"format": "html"}))
d2.download_button("⬇ Download raw results (JSON)", result_to_json(r),
                   file_name=f"trustlens_result_{sha[:12]}.json", mime="application/json",
                   on_click=custody.record, args=("report_exported", sha, {"format": "json"}))
