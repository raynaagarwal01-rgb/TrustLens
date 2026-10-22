import { useRef, useState } from "react";
import { ACCEPT, api, type CaseResult } from "./api";
import { evidenceMarks } from "./evidence";
import { Icon } from "./ui";

/** Phone-first page (#/check): pick a file, get a plain verdict card. The phone QR code opens it. */
export function CheckView({ ai, onOpen }: { ai: boolean; onOpen: (id: string) => void }) {
  const [busy, setBusy] = useState<{ name: string; kind: string } | null>(null);
  const [r, setR] = useState<CaseResult | null>(null);
  const [error, setError] = useState("");
  const [lang, setLang] = useState<"en" | "hi">("en");
  const input = useRef<HTMLInputElement>(null);

  const pick = async (f: File) => {
    setR(null); setError("");
    const kind = f.type.startsWith("video/") ? "video" : f.type.startsWith("audio/") ? "voice note" : "image";
    setBusy({ name: f.name, kind });
    try { setR(await api.upload(f, ai)); } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  };

  const tone = r ? (r.verdict === "fake" || r.verdict === "likely_fake" ? "bad"
    : r.verdict === "inconclusive" || !r.llm_used || r.media_kind !== "image" ? "warn" : "good") : "";
  const reasons = r ? [...r.rule_notes, ...(r.rule_notes.length ? [] : evidenceMarks(r).map((m) => `${m.title}.`)),
    ...r.visual_findings.filter((f) => f.severity !== "low").map((f) => `${f.finding[0].toUpperCase()}${f.finding.slice(1)} (${f.location}).`)]
    .filter((x, i, a) => a.indexOf(x) === i).slice(0, 3) : [];

  return (
    <div className="check">
      <header className="check__brand"><b>TrustLens</b><span>Is this real?</span></header>
      <input ref={input} type="file" accept={ACCEPT} hidden
             onChange={(e) => { const f = e.target.files?.[0]; if (f) pick(f); e.target.value = ""; }} />

      {!busy && !r && (
        <section className="check__start">
          <h1 className="display">Check a photo, video or voice note</h1>
          <p>Choose it from your gallery or files. If it came on WhatsApp, save it to your phone first.</p>
          <button className="btn btn--marker check__big" onClick={() => input.current?.click()}>
            <Icon name="open" /> Choose a file
          </button>
          {error && <div className="callout callout--bad"><p>{error}</p></div>}
          {!ai && <p className="muted" style={{ fontSize: 13 }}>AI review is off on the TrustLens computer: results will use forensic tests only.</p>}
        </section>
      )}

      {busy && (
        <section className="check__busy" role="status">
          <div className="check__scan"><span /></div>
          <b>Checking {busy.name}</b>
          <p className="muted">{busy.kind === "video" ? "Videos take up to a minute." : busy.kind === "voice note" ? "Usually 10–20 seconds." : "Usually 5–20 seconds."}</p>
        </section>
      )}

      {r && (
        <section className={`check__result check__result--${tone}`} aria-live="polite">
          <img src={api.image(r.case.id, "original", 900)} alt="" className="check__thumb" />
          <div className="check__verdict">
            <h1 className="display">{r.headline || r.verdict_label}</h1>
            <p className="check__score">Score <b>{r.manipulation_score}</b>/100 · confidence {r.confidence}</p>
          </div>
          <div className="check__summary">
            <div className="seg" role="group" aria-label="Language">
              <button aria-pressed={lang === "en"} onClick={() => setLang("en")}>English</button>
              <button aria-pressed={lang === "hi"} onClick={() => setLang("hi")} lang="hi">हिंदी</button>
            </div>
            <ol lang={lang}>{r.summary[lang].map((l, i) => <li key={i}>{l}</li>)}</ol>
          </div>
          {reasons.length > 0 && (
            <div className="check__why"><h2>Why</h2><ul>{reasons.map((x) => <li key={x}>{x}</li>)}</ul></div>
          )}
          <div className="check__actions">
            <a className="btn btn--primary" href={api.reportPdf(r.case.id, true)}><Icon name="shield" /> Signed report</a>
            <button className="btn" onClick={() => onOpen(r.case.id)}><Icon name="lens" /> All the evidence</button>
            <button className="btn btn--marker" onClick={() => { setR(null); input.current?.click(); }}><Icon name="open" /> Check another</button>
          </div>
        </section>
      )}
    </div>
  );
}
