"""
TrustLens — deepfake detection and digital evidence analysis.

Run:  streamlit run app.py
"""

import hashlib
import io
import os
from pathlib import Path

import numpy as np
import streamlit as st
from PIL import Image

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
    provider = os.getenv("LLM_PROVIDER", "gemini")
    key_ok = bool(os.getenv("GEMINI_API_KEY") if provider == "gemini" else os.getenv("GROQ_API_KEY"))
    use_llm = st.toggle("AI visual analysis (vision LLM)", value=key_ok, disabled=not key_ok,
                        help="Sends the image and its ELA heatmap to the vision model.")
    if not key_ok:
        st.warning(f"No API key for {provider}: running forensic tests only.")
    det = os.getenv("DETECTOR_MODEL")
    st.caption(f"Pretrained detector: {det if det else 'off (set DETECTOR_MODEL)'}")

    st.divider()
    st.subheader("Demo samples")
    sample_files = sorted(p for p in SAMPLES.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
                          and not p.stem.endswith("_gt")) if SAMPLES.exists() else []
    labels = {"(none)": None}
    for p in sample_files:
        tag = ("Tampered (CASIA)" if p.name.startswith("Tp_") else "Authentic" if p.name.startswith("Au_")
               else "AI-generated" if p.name.startswith("AI_") else "Sample")
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
d1.download_button("⬇ Download evidence report (HTML, print to PDF)", build_report_html(r),
                   file_name=f"trustlens_report_{sha[:12]}.html", mime="text/html")
d2.download_button("⬇ Download raw results (JSON)", result_to_json(r),
                   file_name=f"trustlens_result_{sha[:12]}.json", mime="application/json")
