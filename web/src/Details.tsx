import { Trace } from "./Trace";
import { useEffect, useRef, useState } from "react";
import { api, type CaseResult, type Chain, type CustodyEntry, type Severity, type Signal } from "./api";
import { verdictTone } from "./evidence";
import { fmtBytes, fmtTime, Icon, Sev, shortHash } from "./ui";

type TabId = "findings" | "tests" | "metadata" | "provenance" | "campus" | "custody";

interface Props {
  result: CaseResult;
  aiOn: boolean;
  onResult: (r: CaseResult) => void;
  onError: (msg: string) => void;
  onInfo: (msg: string) => void;
}

const ORDER: Record<Severity, number> = { high: 0, medium: 1, low: 2, info: 3 };
const bySeverity = (a: { severity: Severity }, b: { severity: Severity }) => ORDER[a.severity] - ORDER[b.severity];
const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);

export function Details({ result, aiOn, onResult, onError, onInfo }: Props) {
  // a circular checked against VTOP opens on that check: it's usually the deciding evidence
  const startTab = (): TabId => (result.official_check?.steps && result.official_check.overall !== "not_verifiable" ? "campus" : "findings");
  const [tab, setTab] = useState<TabId>(startTab);
  useEffect(() => { setTab(startTab()); }, [result.case.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const tabs: { id: TabId; label: string; count?: number }[] = [
    { id: "findings", label: "Findings", count: result.forensic_signals.filter((s) => s.severity !== "info").length + result.visual_findings.length },
    { id: "tests", label: "Tests" },
    { id: "metadata", label: "Metadata" },
    { id: "provenance", label: "Provenance" },
    ...(result.media_kind !== "audio" ? [{ id: "campus" as TabId, label: "Context checks" }] : []),
    { id: "custody", label: "Custody & integrity" },
  ];
  return (
    <div className="sheet">
      <div className="tabs" role="tablist" aria-label="Case details">
        {tabs.map((t) => (
          <button key={t.id} role="tab" id={`tab-${t.id}`} aria-selected={tab === t.id} aria-controls={`panel-${t.id}`}
                  className="tab" onClick={() => setTab(t.id)}>
            {t.label}{t.count ? <span className="count">{t.count}</span> : null}
          </button>
        ))}
      </div>
      <div className="tab-panel" role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "findings" && <Findings r={result} />}
        {tab === "tests" && (result.media_kind === "image" || !result.media_kind ? <Tests r={result} /> : <MediaTests r={result} />)}
        {tab === "metadata" && <Metadata r={result} />}
        {tab === "provenance" && <Provenance r={result} />}
        {tab === "campus" && <Campus r={result} aiOn={aiOn} onResult={onResult} onError={onError} />}
        {tab === "custody" && <Custody r={result} onError={onError} onInfo={onInfo} />}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ findings */

function SignalRow({ s }: { s: Signal }) {
  return (
    <div className="finding">
      <Sev level={s.severity} />
      <div><h3>{s.check}</h3><p>{s.detail}</p></div>
    </div>
  );
}

/** The DFDC-winning face-swap detector: one score, and one bar per video frame. */
function SwapPanel({ r }: { r: CaseResult }) {
  const fs = r.face_swap;
  if (!fs) return null;
  if (!fs.available) {
    return (
      <section className="swap swap--off">
        <h3>Face-swap detector</h3>
        <p className="muted">{fs.error ? `Didn't run: ${fs.error}` : <>Not installed on this computer. Run <span className="mono">python tools/get_dfdc_model.py</span> once to add the model that won Facebook's Deepfake Detection Challenge.</>}</p>
      </section>
    );
  }
  const score = fs.score ?? 0;
  const tone = score > 0.8 ? "bad" : score >= 0.5 ? "warn" : "good";
  const video = r.media_kind === "video";
  return (
    <section className={`swap swap--${tone}`} aria-label="Face-swap detector">
      <div className="swap__head">
        <div>
          <h3>Face-swap detector</h3>
          <p className="muted">EfficientNet-B7 that won Facebook's Deepfake Detection Challenge (1st of 2,265 teams), run on {video ? `${fs.n} frames with a face` : "the face"} in {fs.seconds}s.</p>
        </div>
        <p className="swap__score"><b>{Math.min(99, Math.round(score * 100))}%</b><span>{tone === "bad" ? "swapped face" : tone === "warn" ? "possible swap" : score >= 0.2 ? "below the line: not flagged" : "no swap found"}</span></p>
      </div>
      {video && fs.frames && fs.frames.length > 1 && (
        <div className="swap__bars" role="img" aria-label={`Per-frame fake probability: ${fs.frames.map((f) => `${f.label} ${Math.round(f.p * 100)}%`).join(", ")}`}>
          {fs.frames.map((f) => (
            <span key={f.label} className="swap__bar">
              <i style={{ height: `${Math.max(3, f.p * 100)}%` }} className={f.p > 0.8 ? "bad" : f.p >= 0.5 ? "warn" : "good"} />
              <small>{f.label}</small>
            </span>
          ))}
        </div>
      )}
      <p className="swap__note">{tone === "good"
        ? "It catches face swaps and face reenactment. It was not trained on fully AI-generated faces or animated photos, so a low score doesn't clear the file; the AI review covers those."
        : "Measured on clips with a known answer: face-swap videos scored 99%, real videos and portraits 1–2%."}</p>
    </section>
  );
}

function Findings({ r }: { r: CaseResult }) {
  const signals = [...r.forensic_signals].sort(bySeverity);
  const evidence = signals.filter((s) => s.points_to !== "none");
  const notes = signals.filter((s) => s.points_to === "none");
  return (
    <>
      <SwapPanel r={r} />
      {r.comparison && (
        <div className={`callout callout--${r.comparison.verdict === "edited" ? "bad" : r.comparison.verdict === "same" ? "good" : "warn"}`}>
          <p><b>Compared with {r.comparison.other_name}:</b> {r.comparison.summary}</p>
        </div>
      )}
      {r.media_kind === "audio" && <SpeechSection r={r} />}
      <FacesSection r={r} />
      {r.video && <FramesSection r={r} />}
      {r.media_kind !== "audio" && <section>
        <h2>What the AI review saw</h2>
        {r.llm_used ? (
          r.visual_findings.length ? (
            [...r.visual_findings].sort(bySeverity).map((f) => (
              <div className="finding" key={f.finding + f.location}>
                <Sev level={f.severity} />
                <div><h3>{cap(f.finding)}</h3><p>{f.evidence}</p>{f.location && <small>Where: {f.location}</small>}</div>
              </div>
            ))
          ) : <p className="muted">The vision model didn't point to any specific visual artefact.</p>
        ) : (
          <div className="callout"><p>AI review was off for this case, so only forensic tests ran. Add your Gemini or Groq key
            to the <span className="mono">.env</span> file, restart TrustLens, then open the file again to get visual findings.</p></div>
        )}
        {r.heatmap_reading && <p className="muted" style={{ fontSize: 13 }}><b>Reading of the error-level map:</b> {r.heatmap_reading}</p>}
      </section>}
      <section>
        <h2>Forensic evidence</h2>
        {evidence.length ? evidence.map((s) => <SignalRow key={s.check} s={s} />)
          : <p className="muted">No forensic test found signs of editing or AI generation.</p>}
      </section>
      {notes.length > 0 && (
        <section>
          <h2>Notes about the file</h2>
          {notes.map((s) => <SignalRow key={s.check} s={s} />)}
        </section>
      )}
      <div className="split">
        <section>
          <h2>What this can't tell you</h2>
          <ul style={{ margin: 0, paddingLeft: "1.1rem", fontSize: 13 }}>{r.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
        </section>
        <section>
          <h2>What to do next</h2>
          <ul style={{ margin: 0, paddingLeft: "1.1rem", fontSize: 13 }}>{r.recommended_actions.map((a) => <li key={a}>{a}</li>)}</ul>
        </section>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ tests */

function Tests({ r }: { r: CaseResult }) {
  const a = r.advanced ?? {};
  const has = (check: string) => r.forensic_signals.find((s) => s.check === check);
  type Row = { name: string; what: string; result: string; tone: "bad" | "warn" | "good" | ""; note?: string };
  const rows: Row[] = [
    { name: "Content Credentials", what: "Signed provenance manifest",
      result: r.metadata.c2pa ? (r.metadata.c2pa.source_types.length ? `Declares: ${r.metadata.c2pa.source_types.join(", ")}` : "Present") : "None in file",
      tone: has("Content Credentials declare AI generation") || has("Content Credentials fail verification") ? "bad" : "" },
    { name: "Metadata", what: "Camera, software, dates, AI-generator traces",
      result: has("AI generator trace in metadata") ? "AI-generator trace" : has("Editing software recorded") ? "Editing software recorded" : has("Camera metadata present") ? "Camera metadata" : "No camera metadata",
      tone: has("AI generator trace in metadata") ? "bad" : has("Editing software recorded") ? "warn" : "" },
    { name: "Embedded thumbnail", what: "Camera preview vs photo",
      result: r.thumbnail ? (r.thumbnail.changed_region ? "Preview shows a different version" : r.thumbnail.note ?? "Matches the photo") : "No preview stored",
      tone: r.thumbnail?.changed_region ? "bad" : r.thumbnail ? "good" : "" },
    { name: "Error-level analysis", what: "Areas that react differently to re-compression",
      result: r.ela.region ? `Region flagged (strength ${r.ela.region.strength})` : "Consistent", tone: r.ela.region ? "warn" : "good" },
    { name: "JPEG ghost", what: "Content from a lower-quality save",
      result: a.ghost?.region ? `Ghost at about quality ${a.ghost.region_quality}` : a.ghost?.status === "error" ? "Error" : "None", tone: a.ghost?.region ? "warn" : "good" },
    { name: "Copy-move", what: "Cloned areas inside the image",
      result: a.copy_move?.status === "skipped" ? "Skipped: install OpenCV" : a.copy_move?.regions?.length ? `${a.copy_move.inliers} matching points` : "None found",
      tone: a.copy_move?.regions?.length ? (has("Cloned area (copy-move)")?.severity === "low" ? "warn" : "bad") : a.copy_move?.status === "skipped" ? "" : "good" },
    { name: "JPEG grid alignment", what: "Crop or shift after an earlier save",
      result: has("Shifted JPEG grid") ? `Shifted ${a.grid?.offset?.join(", ")} px` : a.grid?.status === "not a JPEG" ? "Not a JPEG" : "Aligned",
      tone: has("Shifted JPEG grid") ? "warn" : a.grid?.status === "not a JPEG" ? "" : "good" },
    { name: "Noise consistency", what: "Areas with a different noise pattern", note: "Experimental",
      result: r.noise.region ? "Region differs" : "Consistent", tone: "" },
    { name: "Median filtering", what: "Smoothing that hides traces", note: "Experimental, not in verdict",
      result: a.median?.equal_neighbour_ratio !== undefined ? `${(Number(a.median.equal_neighbour_ratio) * 100).toFixed(1)}% equal neighbours` : "n/a", tone: "" },
    { name: "Contrast enhancement", what: "Levels or contrast adjustments", note: "Experimental, not in verdict",
      result: a.contrast?.histogram_gaps !== undefined ? `${a.contrast.histogram_gaps} histogram gaps` : "n/a", tone: "" },
    { name: "Pretrained detector", what: "AI-image / deepfake classifier",
      result: r.detector.status === "ok" ? `${Math.round((r.detector.fake_probability ?? 0) * 100)}% fake` : "Not configured", tone: "" },
    { name: "AI visual review", what: "Vision model reads image and heatmap", result: r.llm_used ? "Done" : "Off (no API key)", tone: "" },
  ];
  return (
    <section>
      <h2>Every test that ran</h2>
      <p className="muted" style={{ fontSize: 13 }}>Tests marked experimental are shown for inspection but never change the verdict: in calibration they didn't separate edited from authentic images reliably.</p>
      <div className="tbl-wrap">
        <table className="tbl">
          <thead><tr><th>Test</th><th>Looks for</th><th>Result</th></tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.name}>
                <td><b>{row.name}</b>{row.note && <div className="muted" style={{ fontSize: 12 }}>{row.note}</div>}</td>
                <td className="muted">{row.what}</td>
                <td>{row.tone ? <span className={`pill pill--${row.tone}`}>{row.result}</span> : row.result}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ metadata */

function Histogram({ id }: { id: string }) {
  const [h, setH] = useState<Record<string, number[]> | null>(null);
  useEffect(() => { api.histogram(id).then(setH).catch(() => setH(null)); }, [id]);
  if (!h) return <p className="muted">Loading histogram…</p>;
  const max = Math.max(...["r", "g", "b"].flatMap((c) => h[c].slice(1, 255)));
  const path = (c: string) => "M0 120 " + h[c].map((v, i) => `L${(i / 255) * 512} ${120 - Math.min(1, v / max) * 115}`).join(" ") + " L512 120 Z";
  return (
    <figure className="hist" style={{ margin: 0 }}>
      <svg viewBox="0 0 512 120" preserveAspectRatio="none" role="img" aria-label="Colour histogram">
        <path d={path("r")} fill="rgba(200,60,50,0.35)" />
        <path d={path("g")} fill="rgba(40,140,90,0.35)" />
        <path d={path("b")} fill="rgba(50,90,180,0.35)" />
      </svg>
      <figcaption className="muted" style={{ fontSize: 12 }}>Red, green and blue pixel values from dark (left) to bright (right). Combs of regular gaps suggest levels or contrast edits.</figcaption>
    </figure>
  );
}

/** EXIF pointers and layout tags mean nothing to a reader; long floats get trimmed. */
const EXIF_HIDE = new Set(["GPSInfo", "ExifOffset", "ResolutionUnit", "YCbCrPositioning", "ExifVersion",
  "ComponentsConfiguration", "FlashPixVersion", "ColorSpace", "SceneType", "MakerNote", "PrintImageMatching"]);
const EXIF_FIRST = ["Make", "Model", "Software", "DateTimeOriginal", "DateTime", "LensModel", "Artist", "Copyright"];
const tidy = (v: string) => /^-?\d+\.\d{4,}$/.test(v) ? String(Math.round(parseFloat(v) * 1000) / 1000) : v;

function Metadata({ r }: { r: CaseResult }) {
  const exif = Object.entries(r.metadata.exif)
    .filter(([k, v]) => !EXIF_HIDE.has(k) && String(v).length < 200)
    .map(([k, v]) => [k, tidy(String(v))] as [string, string])
    .sort(([a], [b]) => {
      const ia = EXIF_FIRST.indexOf(a), ib = EXIF_FIRST.indexOf(b);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    });
  const st = r.advanced?.structure;
  const q0 = st?.quant_tables?.["0"];
  return (
    <>
      {r.gps && (
        <div className="callout callout--warn">
          <p><b>Location recorded in the file:</b> {r.gps.lat}, {r.gps.lon}. <a href={r.gps.map} target="_blank" rel="noreferrer">Open map</a>. This is personal
            data: share the original file with care.</p>
        </div>
      )}
      <div className="split">
        <section>
          <h2>{r.media_kind === "image" || !r.media_kind ? "Camera and file metadata" : "File and container metadata"}</h2>
          {exif.length ? (
            <div className="tbl-wrap"><table className="tbl"><tbody>
              {exif.slice(0, 40).map(([k, v]) => <tr key={k}><td className="muted">{k}</td><td>{v}</td></tr>)}
            </tbody></table></div>
          ) : <p className="muted">No EXIF metadata. Normal for screenshots and anything forwarded through WhatsApp or social media.</p>}
          {Object.keys(r.metadata.text_chunks).length > 0 && (
            <>
              <h3>Embedded text</h3>
              <div className="tbl-wrap"><table className="tbl"><tbody>
                {Object.entries(r.metadata.text_chunks).map(([k, v]) => <tr key={k}><td className="muted">{k}</td><td style={{ wordBreak: "break-word" }}>{v}</td></tr>)}
              </tbody></table></div>
            </>
          )}
        </section>
        {r.media_kind !== "audio" && <section>
          <h2>Colour histogram{r.media_kind === "video" ? " (key frame)" : ""}</h2>
          <Histogram id={r.case.id} />
          {st && (
            <>
              <h2 style={{ marginTop: "0.75rem" }}>JPEG structure</h2>
              <dl className="facts">
                <dt>Encoding</dt><dd>{st.progressive ? "Progressive" : "Baseline"}{st.subsampling ? `, ${st.subsampling} colour` : ""}</dd>
                {r.jpeg_quality && <><dt>Save quality</dt><dd>About {r.jpeg_quality}</dd></>}
                {st.encoder_hint && <><dt>Tables</dt><dd>{st.encoder_hint}</dd></>}
              </dl>
            </>
          )}
        </section>}
      </div>
      {st && r.media_kind !== "video" && (
        <div className="split">
          <section>
            <h3>File segments</h3>
            <div className="tbl-wrap"><table className="tbl">
              <thead><tr><th>Segment</th><th>Offset</th><th>Size</th></tr></thead>
              <tbody>{st.segments.map((s, i) => (
                <tr key={i}><td>{s.marker}</td><td className="mono">{s.offset}</td><td>{fmtBytes(s.length)}</td></tr>
              ))}</tbody>
            </table></div>
          </section>
          {q0 && q0.length === 64 && (
            <section>
              <h3>Brightness quantisation table</h3>
              <p className="muted" style={{ fontSize: 13 }}>How strongly each frequency was compressed. Cameras and editors use characteristic tables.</p>
              <div className="qgrid" aria-label="Quantisation table">
                {q0.map((v, i) => {
                  const t = Math.min(1, v / 100);
                  return <span key={i} style={{ background: `rgba(242,194,48,${0.12 + t * 0.85})` }}>{v}</span>;
                })}
              </div>
            </section>
          )}
        </div>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ provenance */

function Provenance({ r }: { r: CaseResult }) {
  const c = r.metadata.c2pa;
  if (!c) {
    return (
      <section>
        <h2>No Content Credentials</h2>
        <p>This file carries no C2PA manifest. Most photos don't yet. Images from Google, OpenAI, Adobe and some cameras
          include one; WhatsApp, screenshots and most social media remove it, so its absence proves nothing.</p>
      </section>
    );
  }
  const v = c.verification;
  const ai = c.source_types.some((t) => /trainedAlgorithmic|algorithmicMedia|Synthetic/i.test(t));
  return (
    <>
      <div className={`callout callout--${ai ? "bad" : "good"}`}>
        <p><b>{ai ? "The file's own credentials declare it AI-generated." : "The file carries Content Credentials."}</b>{" "}
          {c.actions.join(". ")}{c.actions.length ? "." : ""}</p>
      </div>
      <dl className="facts">
        <dt>Signed by</dt><dd>{c.signed_by.join(", ") || "Unknown"}</dd>
        <dt>Created with</dt><dd>{c.generator || "Not stated"}</dd>
        <dt>Source type</dt><dd>{c.source_types.join(", ") || "Not stated"}</dd>
        {c.watermark && <><dt>Watermark</dt><dd>{c.watermark} (invisible watermark recorded in the manifest)</dd></>}
        {c.ingredients.length > 0 && <><dt>Made from</dt><dd>{c.ingredients.join(", ")}</dd></>}
        <dt>Signature</dt>
        <dd>{v?.status === "ok" ? `${v.state ?? "Checked"}${v.failures?.length ? `: ${v.failures.join("; ")}` : ""}`
          : "Not cryptographically checked. Install c2pa-python, or verify at contentcredentials.org/verify."}</dd>
      </dl>
    </>
  );
}

/* ------------------------------------------------------------------ campus checks */

type CheckKind = "notice" | "event" | "screenshot" | "reverse";

function Campus({ r, aiOn, onResult, onError }: { r: CaseResult; aiOn: boolean; onResult: (r: CaseResult) => void; onError: (m: string) => void }) {
  const [busy, setBusy] = useState<"" | CheckKind>("");
  const [live, setLive] = useState(false);
  const run = async (kind: CheckKind) => {
    setBusy(kind);
    try {
      onResult(kind === "notice" ? await api.noticeCheck(r.case.id, live)
        : kind === "event" ? await api.eventCheck(r.case.id, live)
        : kind === "screenshot" ? await api.screenshotCheck(r.case.id)
        : await api.reverseSearch(r.case.id));
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy("");
    }
  };
  const oc = r.official_check;
  const ev = r.event_check;
  const icon = { confirmed: "✓", contradicted: "✕", not_checked: "?" } as const;
  return (
    <>
      {!aiOn && <div className="callout callout--warn"><p>These checks read what the image shows, which needs the AI review. Add your Gemini or Groq key to the <span className="mono">.env</span> file and restart TrustLens.</p></div>}
      <ReverseSection r={r} busy={busy === "reverse"} disabled={!aiOn || !!busy} onRun={() => run("reverse")} />
      {r.media_kind !== "video" && <ScreenshotSection r={r} busy={busy === "screenshot"} disabled={!aiOn || !!busy} onRun={() => run("screenshot")} />}
      <section>
        <h2>Is this notice true?</h2>
        <p className="muted" style={{ fontSize: 13 }}>For circulars, exam notices and forwarded announcements: the dated claims are compared with your official VTOP exam schedule, academic calendar and holidays. The date comparison is done by code, not by AI.</p>
        <div className="check-actions">
          <label className="toggle" style={{ color: "inherit" }}>
            <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} /> Fetch fresh data from VTOP (slower)
          </label>
          <button className="btn btn--primary" disabled={!aiOn || !!busy} onClick={() => run("notice")}>
            {busy === "notice" ? "Checking VTOP records…" : oc ? "Check again" : "Check against VTOP"}
          </button>
        </div>
        {oc && (
          <>
            <div className={`callout callout--${oc.overall === "contradicted" ? "bad" : oc.overall === "confirmed" ? "good" : "warn"}`}><p>{oc.summary}</p></div>
            {oc.claims.length === 0 && <p className="muted">No exam, holiday or deadline claims found in this image.</p>}
            {oc.steps ? (
              <>
                <h3 className="trace__heading">How it was checked{oc.checked_at ? `, ${oc.checked_at}` : ""}</h3>
                <Trace key={oc.checked_at} steps={oc.steps} />
              </>
            ) : (
              <div>
                {oc.claims.map((c, i) => (
                  <div className="claim" key={i}>
                    <span className={`pill pill--${c.status === "contradicted" ? "bad" : c.status === "confirmed" ? "good" : ""}`} aria-label={c.status}>{icon[c.status]}</span>
                    <div><b>{c.statement}</b><span className="muted">{c.official}</span></div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </section>
      <section>
        <h2>Is this event real?</h2>
        <p className="muted" style={{ fontSize: 13 }}>For hackathon, workshop, fest and internship posters: looks for the event in VTOP club events and on the web, and checks payment details and links for scam signs.</p>
        <div className="check-actions">
          <button className="btn btn--primary" disabled={!aiOn || !!busy} onClick={() => run("event")}>
            {busy === "event" ? "Searching for the event…" : ev ? "Check again" : "Check this event"}
          </button>
        </div>
        {ev && (
          <>
            <div className={`callout callout--${verdictTone(ev.verdict)}`}>
              <p><b>{ev.verdict_label}.</b> {ev.summary}</p>
            </div>
            <dl className="facts">
              <dt>Event</dt><dd>{ev.event.event_name || "Not readable"}</dd>
              <dt>Organiser</dt><dd>{ev.event.organizer || "Not stated"}</dd>
              {ev.event.dates && <><dt>Dates</dt><dd>{ev.event.dates}</dd></>}
              <dt>Fee</dt><dd>{ev.event.fee || "None stated"}</dd>
            </dl>
            {ev.reasons.length > 0 && <ul style={{ margin: 0, paddingLeft: "1.1rem", fontSize: 13 }}>{ev.reasons.map((x) => <li key={x}>{x}</li>)}</ul>}
            <div>{[...ev.red_flags].sort(bySeverity).map((f) => (
              <div className="finding" key={f.flag}><Sev level={f.severity} /><div><h3>{f.flag}</h3><p>{f.detail}</p></div></div>
            ))}</div>
            {ev.web.official_urls && ev.web.official_urls.length > 0 && (
              <p style={{ fontSize: 13 }}>Official sources: {ev.web.official_urls.map((u) => <a key={u} href={u} target="_blank" rel="noreferrer" style={{ marginRight: 8 }}>{u}</a>)}</p>
            )}
            <p className="muted" style={{ fontSize: 12 }}>
              Web: {ev.web.status === "ok" ? ev.web.method : `unavailable${ev.web.detail ? ` (${ev.web.detail.slice(0, 80)})` : ""}`}.{" "}
              VTOP club events: {ev.vtop.status === "ok" ? `${ev.vtop.events_listed} checked (${ev.vtop.source})` : ev.vtop.detail ?? "not checked"}.
            </p>
          </>
        )}
      </section>
    </>
  );
}

/* ------------------------------------------------------------------ custody */

function Custody({ r, onError, onInfo }: { r: CaseResult; onError: (m: string) => void; onInfo: (m: string) => void }) {
  const [log, setLog] = useState<{ chain: Chain; entries: CustodyEntry[] } | null>(null);
  const [check, setCheck] = useState<{ match: boolean; sha256: string; name: string } | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const load = () => api.custody(r.case.sha256).then(setLog).catch((e) => onError(e.message));
  useEffect(() => { load(); }, [r.case.sha256]); // eslint-disable-line react-hooks/exhaustive-deps
  const verify = async (f: File) => {
    try {
      const res = await api.verifyFile(r.case.id, f);
      setCheck({ ...res, name: f.name });
      onInfo(res.match ? "Same file: hashes match." : "Different file: hashes don't match.");
      load();
    } catch (e) { onError((e as Error).message); }
  };
  const i = r.integrity;
  const ph = i.perceptual ?? {};
  return (
    <>
      <div className="split">
        <section>
          <h2>Fingerprints</h2>
          <dl className="facts">
            <dt>SHA-256</dt><dd className="mono" style={{ wordBreak: "break-all" }}>{i.sha256}</dd>
            <dt>MD5</dt><dd className="mono">{i.md5}</dd>
            {ph.phash && <><dt>Perceptual</dt><dd className="mono">p {ph.phash} · d {ph.dhash}</dd></>}
            <dt>File</dt><dd>{i.format}, {i.width}×{i.height}, {fmtBytes(i.size_bytes)}</dd>
            <dt>Analysed</dt><dd>{i.analysed_at}, {r.tool_version}</dd>
          </dl>
          <p className="muted" style={{ fontSize: 13 }}>SHA-256 changes if a single byte changes. Perceptual hashes stay the same when the picture is only re-saved or resized, so they match forwarded copies.</p>
        </section>
        <section>
          <h2>Is this the same file?</h2>
          <div className="dropline">
            <span>Choose a file to compare its SHA-256 with this evidence.</span>
            <input ref={input} type="file" hidden onChange={(e) => e.target.files?.[0] && verify(e.target.files[0])} />
            <button className="btn" onClick={() => input.current?.click()}>Choose file</button>
          </div>
          {check && (
            <div className={`callout callout--${check.match ? "good" : "bad"}`}>
              <p><b>{check.name}</b>: {check.match ? "identical to the analysed file." : "not identical: at least one byte differs."}</p>
            </div>
          )}
          <h3>Signed evidence report</h3>
          <p style={{ fontSize: 13 }}>The PDF report carries a QR code with this file's SHA-256, the verdict and the custody-log head,
            signed with this computer's TrustLens key. Anyone can check it wasn't altered.</p>
          <div className="check-actions">
            <a className="btn btn--primary" href={api.reportPdf(r.case.id, true)}><Icon name="download" /> Download signed PDF</a>
            <a className="btn" href="#/verify"><Icon name="shield" /> Verify a report</a>
          </div>
          <h3>Search manually</h3>
          <p style={{ fontSize: 13 }}>Context checks searches the web for you. You can also upload the file to:{" "}
            <a href="https://lens.google.com/" target="_blank" rel="noreferrer">Google Lens</a>,{" "}
            <a href="https://www.bing.com/visualsearch" target="_blank" rel="noreferrer">Bing Visual Search</a>,{" "}
            <a href="https://tineye.com/" target="_blank" rel="noreferrer">TinEye</a>,{" "}
            <a href="https://yandex.com/images/" target="_blank" rel="noreferrer">Yandex Images</a>.</p>
        </section>
      </div>
      <section>
        <div className="chain">
          <h2>Chain of custody</h2>
          {log && (log.chain.ok
            ? <span className="pill pill--good"><Icon name="check" /> Log intact, {log.chain.entries} entries</span>
            : <span className="pill pill--bad">Log broken: {log.chain.problem}</span>)}
        </div>
        <p className="muted" style={{ fontSize: 13 }}>Every action on this evidence is written to a log where each entry contains the hash of the one before. Editing, deleting or reordering any entry breaks the chain. Verify it independently with <span className="mono">python custody.py verify</span>.</p>
        {log && log.entries.length > 0 && (
          <div className="tbl-wrap"><table className="tbl">
            <thead><tr><th>#</th><th>When</th><th>Action</th><th>Entry hash</th></tr></thead>
            <tbody>{log.entries.map((e) => (
              <tr key={e.seq}>
                <td>{e.seq}</td><td>{fmtTime(e.time)}</td><td>{cap(e.action.replace(/_/g, " "))}</td>
                <td className="mono">{shortHash(e.entry_hash, 12)}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </section>
    </>
  );
}

/* ------------------------------------------------------------------ media sections */

const ASSESS_TONE: Record<string, string> = { "likely manipulated": "bad", suspicious: "warn", "no visible sign": "good" };

function FacesSection({ r }: { r: CaseResult }) {
  const id = r.case.id;
  const items: { key: string; title: string; assessment?: string; evidence?: string }[] = r.media_kind === "video"
    ? (r.video?.face_findings ?? []).map((f, i) => ({ key: `face_${i + 1}`, title: `Face close-up ${f.face || i + 1}`, assessment: f.assessment, evidence: f.evidence }))
    : (r.faces?.faces ?? []).filter((f) => f.closeup).map((f) => ({ key: `face_${f.n}`, title: `Face ${f.n}`, assessment: f.assessment, evidence: f.evidence }));
  const videoCrops = r.media_kind === "video" && items.length === 0
    ? (r.video?.timeline ?? []).filter((t) => t.faces.length && t.on_sheet).slice(0, 3).map((_, i) => ({ key: `face_${i + 1}`, title: `Face close-up ${i + 1}` }))
    : [];
  const all = items.length ? items : videoCrops;
  if (!all.length) return null;
  return (
    <section>
      <h2>Faces</h2>
      <p className="muted" style={{ fontSize: 13 }}>Each face was sent to the AI review as a zoomed close-up{r.media_kind === "video" ? ", from different moments of the video" : ""}.
        Noise and detail comparisons with the surroundings are shown in Tests as experimental: on 91 synthetic face swaps they didn't separate swaps from real faces.</p>
      <div className="faces">
        {all.map((f) => (
          <figure key={f.key} className="face">
            <img src={api.image(id, f.key, 360)} alt={f.title} loading="lazy" />
            <figcaption>
              <b>{f.title}</b>
              {"assessment" in f && f.assessment
                ? <span className={`pill pill--${ASSESS_TONE[f.assessment] ?? ""}`}>{f.assessment}</span>
                : <span className="muted">{r.llm_used ? "No comment from the AI review" : "AI review off"}</span>}
              {"evidence" in f && f.evidence && <small>{f.evidence}</small>}
            </figcaption>
          </figure>
        ))}
      </div>
    </section>
  );
}

function FramesSection({ r }: { r: CaseResult }) {
  const v = r.video!;
  const noted = v.timeline.filter((f) => f.ai_note && f.ai_note.toLowerCase() !== "nothing unusual");
  return (
    <section>
      <h2>Across the video</h2>
      <dl className="facts">
        <dt>Clip</dt><dd>{v.duration}s at {v.fps} fps, {v.frames_total} frames, {v.codec || "unknown codec"}</dd>
        <dt>Checked</dt><dd>{v.timeline.length} frames spread across the clip; {v.timeline.filter((f) => f.faces.length).length} with a face</dd>
        {v.ai_tools_named.length > 0 && <><dt>AI tools named</dt><dd>{v.ai_tools_named.join(", ")}</dd></>}
        {v.audio?.measurements && <><dt>Sound</dt><dd>{v.audio.measurements.duration}s, {v.audio.measurements.sample_rate} Hz{v.audio.speech?.status === "ok" ? `, speech in ${v.audio.speech.language || "unknown language"}` : ""}</dd></>}
      </dl>
      {noted.map((f) => (
        <div className="finding" key={f.label}>
          <span className={`pill pill--${(f.ai_score ?? 0) >= 55 ? "bad" : (f.ai_score ?? 0) >= 30 ? "warn" : "good"}`}>{f.label}</span>
          <div><h3>{f.t.toFixed(1)}s{f.ai_score !== null ? `, score ${f.ai_score}` : ""}</h3><p>{f.ai_note}</p></div>
        </div>
      ))}
      {v.audio?.speech && v.audio.speech.status === "ok" && <Transcript s={v.audio.speech} />}
    </section>
  );
}

function Transcript({ s }: { s: NonNullable<CaseResult["audio"]>["speech"] }) {
  if (!s || s.status !== "ok") return null;
  return (
    <details className="transcript">
      <summary>Transcript{s.language ? ` (${s.language})` : ""}</summary>
      <p>{s.transcript || "No speech recognised."}</p>
      <small className="muted">Machine transcription: check quotes against the recording before relying on them.</small>
    </details>
  );
}

function SpeechSection({ r }: { r: CaseResult }) {
  const a = r.audio;
  const s = a?.speech;
  return (
    <section>
      <h2>What is said</h2>
      {!s && <div className="callout"><p>Transcription and the scam check need the AI review. Add your key to the <span className="mono">.env</span> file and open the voice note again.</p></div>}
      {s && s.status !== "ok" && <div className="callout callout--warn"><p>Transcription failed: {s.detail}</p></div>}
      {s && s.status === "ok" && (
        <>
          <div className={`callout callout--${s.scam_risk === "high" ? "bad" : s.scam_risk === "medium" ? "warn" : "good"}`}>
            <p><b>Scam risk: {s.scam_risk}.</b> {s.summary}</p>
          </div>
          <dl className="facts">
            {s.claimed_speaker && <><dt>Speaker claims to be</dt><dd>{s.claimed_speaker}</dd></>}
            {(s.requests ?? []).length > 0 && <><dt>Asks the listener to</dt><dd>{s.requests!.join("; ")}</dd></>}
            {s.language && <><dt>Language</dt><dd>{s.language}</dd></>}
          </dl>
          {(s.scam_cues ?? []).map((c) => (
            <div className="finding" key={c.cue}><Sev level="medium" /><div><h3>{cap(c.cue)}</h3><p>“{c.quote}”</p></div></div>
          ))}
          <Transcript s={s} />
        </>
      )}
      <p className="muted" style={{ fontSize: 13 }}>TrustLens has no trained voice-clone detector, so it can't tell a cloned voice from a real one by sound.
        If a voice note asks for money or codes, call the person back on a number you already know.</p>
    </section>
  );
}

function MediaTests({ r }: { r: CaseResult }) {
  const has = (check: string) => r.forensic_signals.find((s) => s.check.startsWith(check));
  type Row = { name: string; what: string; result: string; tone: "bad" | "warn" | "good" | ""; note?: string };
  const v = r.video, a = r.audio;
  const m = a?.measurements ?? v?.audio?.measurements;
  const tools = v?.ai_tools_named ?? a?.ai_tools_named ?? [];
  const rows: Row[] = [
    { name: "Content Credentials", what: "Signed provenance manifest in the file",
      result: r.metadata.c2pa ? (r.metadata.c2pa.source_types.join(", ") || "Present") : "None in file",
      tone: has("Content Credentials declare AI generation") ? "bad" : "" },
    { name: "AI tool in metadata", what: "Generator or voice-tool names in tags", result: tools.length ? tools.join(", ") : "None named",
      tone: tools.length ? "bad" : "good" },
  ];
  if (v) {
    const flick = v.timeline.map((f) => f.flicker).filter((x): x is number => x !== null).sort((x, y) => x - y);
    rows.push(
      { name: "Faces", what: "Faces found in sampled frames", result: `${v.timeline.filter((f) => f.faces.length).length} of ${v.timeline.length} frames`, tone: "" },
      { name: "Face flicker", what: "Face change between consecutive frames vs the rest", note: "Experimental, not in verdict",
        result: flick.length ? `median ${flick[Math.floor(flick.length / 2)].toFixed(1)}×` : "No face", tone: "" },
      { name: "Still-image tests", what: `Error levels, ghost, clones on key frame ${v.key_frame}`, note: "Hints only for video",
        result: r.forensic_signals.filter((s) => s.check.includes("(key frame")).map((s) => s.check.replace(/ \(key frame.*$/, "")).join(", ") || "Nothing flagged", tone: "" },
    );
  }
  if (m) {
    rows.push(
      { name: "Digital silence", what: "Exact silence inside speech (software edit or generation)",
        result: m.digital_silence.length ? `${m.digital_silence.length} stretch${m.digital_silence.length > 1 ? "es" : ""}, first at ${m.digital_silence[0].start}s` : "None",
        tone: m.digital_silence.length ? "warn" : "good" },
      { name: "Background jumps", what: "Background noise changes between pauses", note: "Context only",
        result: m.background_jumps.length ? `${m.background_jumps.length} at ${m.background_jumps.map((j) => `${j.at}s`).join(", ")}` : "None", tone: "" },
      { name: "Bandwidth", what: "Highest frequency carrying sound", note: "Context only",
        result: m.bandwidth?.content_up_to_hz ? `${(m.bandwidth.content_up_to_hz / 1000).toFixed(1)} of ${((m.bandwidth.nyquist_hz ?? 0) / 1000).toFixed(0)} kHz` : "n/a", tone: "" },
    );
  }
  const sp = a?.speech ?? v?.audio?.speech;
  rows.push(
    { name: a ? "Transcript and scam check" : "AI visual review", what: a ? "Speech to text, then scam cues" : "Contact sheet and face close-ups",
      result: a ? (sp?.status === "ok" ? `Scam risk ${sp.scam_risk}` : "Off (no API key)") : r.llm_used ? "Done" : "Off (no API key)",
      tone: sp?.scam_risk === "high" ? "bad" : sp?.scam_risk === "medium" ? "warn" : "" },
    { name: "Voice-clone detector", what: "Trained model for cloned voices", result: a || v?.audio ? "Not available" : "n/a", tone: "",
      note: a || v?.audio ? "TrustLens doesn't claim to detect cloned voices" : undefined },
  );
  return (
    <section>
      <h2>Every test that ran</h2>
      <p className="muted" style={{ fontSize: 13 }}>Only Content Credentials, AI tools named in the file and the AI review can make a {r.media_kind === "audio" ? "voice note" : "video"} "manipulated".
        Digital silence can make a voice note "possible editing". The rest is context: it didn't separate real from fake reliably in calibration.</p>
      <div className="tbl-wrap">
        <table className="tbl">
          <thead><tr><th>Test</th><th>Looks for</th><th>Result</th></tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.name}>
                <td><b>{row.name}</b>{row.note && <div className="muted" style={{ fontSize: 12 }}>{row.note}</div>}</td>
                <td className="muted">{row.what}</td>
                <td>{row.tone ? <span className={`pill pill--${row.tone}`}>{row.result}</span> : row.result}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ReverseSection({ r, busy, disabled, onRun }: { r: CaseResult; busy: boolean; disabled: boolean; onRun: () => void }) {
  const rs = r.reverse_search;
  return (
    <section>
      <h2>Has this appeared online before?</h2>
      <p className="muted" style={{ fontSize: 13 }}>Real photos reused with a false caption are the most common fake on WhatsApp. The AI review describes the
        {r.media_kind === "video" ? " key frame" : " picture"}, TrustLens searches the web, downloads the images on the result pages and compares fingerprints.
        Only a fingerprint match counts. Your file is never uploaded: only text queries leave this computer.</p>
      <div className="check-actions">
        <button className="btn btn--primary" disabled={disabled} onClick={onRun}><Icon name="search" />
          {busy ? " Searching and comparing images…" : rs ? " Search again" : " Search the web for earlier copies"}</button>
      </div>
      {rs && (
        <>
          <div className={`callout callout--${rs.matches.length ? "warn" : ""}`}><p>{rs.summary}</p></div>
          {rs.matches.map((m) => (
            <div className="match" key={m.url}>
              <span className="pill pill--warn">Match</span>
              <div>
                <a href={m.url} target="_blank" rel="noreferrer"><b>{m.title || m.domain || m.url}</b></a>
                <span className="muted">{m.domain}{m.date ? ` · ${m.date.slice(0, 10)}` : " · undated"} · fingerprint distance {m.best_distance}/64</span>
              </div>
            </div>
          ))}
          {rs.unconfirmed.length > 0 && (
            <details className="transcript">
              <summary>{rs.unconfirmed.length} other result{rs.unconfirmed.length > 1 ? "s" : ""} without a matching image</summary>
              <ul>{rs.unconfirmed.map((u) => (
                <li key={u.url}><a href={u.url} target="_blank" rel="noreferrer">{u.title || u.url}</a>
                  <span className="muted"> {u.status === "unreachable" ? "(couldn't open)" : u.best_distance !== null ? `(closest image ${u.best_distance}/64)` : "(no images)"}</span></li>
              ))}</ul>
            </details>
          )}
          <p className="muted" style={{ fontSize: 12 }}>Searched with {rs.method || "no search engine"} for: {rs.description.queries.join(" · ")}. {rs.checked} pages checked.
            {rs.errors.length > 0 && ` Problems: ${rs.errors.join("; ")}.`}</p>
        </>
      )}
    </section>
  );
}

function ScreenshotSection({ r, busy, disabled, onRun }: { r: CaseResult; busy: boolean; disabled: boolean; onRun: () => void }) {
  const sc = r.screenshot_check;
  const tone = sc?.overall === "contradicted" ? "bad" : sc?.overall === "suspicious" ? "warn" : sc?.overall === "no_contradiction" ? "good" : "";
  const label = { contradicted: "Fails format checks", suspicious: "Visual anomalies to check", no_contradiction: "No contradictions found",
                  not_checkable: "Nothing checkable found" } as const;
  return (
    <section>
      <h2>Is this screenshot forged?</h2>
      <p className="muted" style={{ fontSize: 13 }}>For payment receipts and chats: the AI review reads the fields, then code checks what can be checked:
        12-digit UPI reference numbers, real dates that match their weekday, one amount everywhere, message times in order, one time format.</p>
      <div className="check-actions">
        <button className="btn btn--primary" disabled={disabled} onClick={onRun}><Icon name="chat" />
          {busy ? " Reading the screenshot…" : sc ? " Check again" : " Check this screenshot"}</button>
      </div>
      {sc && (
        <>
          <div className={`callout callout--${tone}`}><p><b>{label[sc.overall]}.</b> {sc.kind !== "other" ? `Read as a ${sc.kind} screenshot${sc.app ? ` from ${sc.app}` : ""}.` : "This doesn't look like a chat or payment screenshot."}</p></div>
          {sc.checks.map((c) => (
            <div className="claim" key={c.check + c.detail}>
              <span className={`pill pill--${c.status === "contradicted" ? "bad" : c.status === "ok" ? "good" : ""}`}>{c.status === "contradicted" ? "✕" : c.status === "ok" ? "✓" : "?"}</span>
              <div><b>{c.check}</b><span className="muted">{c.detail}</span></div>
            </div>
          ))}
          {sc.visual_anomalies.map((a) => (
            <div className="finding" key={a.anomaly + a.where}><Sev level={a.severity} /><div><h3>{cap(a.anomaly)}</h3><p>{a.where}</p></div></div>
          ))}
        </>
      )}
    </section>
  );
}
