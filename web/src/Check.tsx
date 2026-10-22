import { useRef, useState } from "react";
import { ACCEPT, api, type CaseResult } from "./api";
import { evidenceMarks } from "./evidence";
import { Trace } from "./Trace";
import { Icon } from "./ui";

type Item = { key: string; name: string; kind: string; status: "waiting" | "checking" | "done" | "error"; result?: CaseResult; error?: string };

const kindOf = (f: File) => (f.type.startsWith("video/") ? "video" : f.type.startsWith("audio/") ? "voice note" : "image");
const toneOf = (r: CaseResult) => (r.verdict === "fake" || r.verdict === "likely_fake" ? "bad"
  : r.verdict === "inconclusive" || !r.llm_used || r.media_kind !== "image" ? "warn" : "good");

function ResultCard({ r, onOpen }: { r: CaseResult; onOpen: (id: string) => void }) {
  const [lang, setLang] = useState<"en" | "hi">("en");
  const reasons = [...r.rule_notes, ...(r.rule_notes.length ? [] : evidenceMarks(r).map((m) => `${m.title}.`)),
    ...r.visual_findings.filter((f) => f.severity !== "low").map((f) => `${f.finding[0].toUpperCase()}${f.finding.slice(1)} (${f.location}).`)]
    .filter((x, i, a) => a.indexOf(x) === i).slice(0, 3);
  return (
    <section className={`check__result check__result--${toneOf(r)}`} aria-live="polite">
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
      {r.official_check?.steps && (
        <div className="check__why"><h2>Checked against VTOP</h2><Trace steps={r.official_check.steps} compact /></div>
      )}
      {reasons.length > 0 && (
        <div className="check__why"><h2>Why</h2><ul>{reasons.map((x) => <li key={x}>{x}</li>)}</ul></div>
      )}
      <div className="check__actions">
        <a className="btn btn--primary" href={api.reportPdf(r.case.id, true)}><Icon name="shield" /> Signed report</a>
        <button className="btn" onClick={() => onOpen(r.case.id)}><Icon name="lens" /> All the evidence</button>
      </div>
    </section>
  );
}

/** Phone-first page (#/check): pick one or more files, get plain verdict cards. The phone QR code opens it. */
export function CheckView({ ai, onOpen }: { ai: boolean; onOpen: (id: string) => void }) {
  const [items, setItems] = useState<Item[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const update = (key: string, patch: Partial<Item>) =>
    setItems((list) => list.map((it) => (it.key === key ? { ...it, ...patch } : it)));

  const pick = async (files: File[]) => {
    const batch: Item[] = files.map((f, i) => ({ key: `${Date.now()}-${i}`, name: f.name, kind: kindOf(f), status: "waiting" }));
    setItems(batch);
    setOpen(files.length === 1 ? batch[0].key : null);
    setRunning(true);
    // one at a time: keeps within the AI service's per-minute limit and shows each result as it lands
    for (const [i, f] of files.entries()) {
      update(batch[i].key, { status: "checking" });
      try { update(batch[i].key, { status: "done", result: await api.upload(f, ai) }); }
      catch (e) { update(batch[i].key, { status: "error", error: (e as Error).message }); }
    }
    setRunning(false);
  };

  const single = items.length === 1 ? items[0] : null;
  const shown = items.find((it) => it.key === open && it.result);
  const done = items.filter((it) => it.status === "done" || it.status === "error").length;
  const current = items.find((it) => it.status === "checking");

  return (
    <div className="check">
      <header className="check__brand"><b>TrustLens</b><span>Is this real?</span></header>
      <input ref={input} type="file" accept={ACCEPT} multiple hidden
             onChange={(e) => { const fs = Array.from(e.target.files ?? []); if (fs.length) pick(fs.slice(0, 20)); e.target.value = ""; }} />

      {items.length === 0 && (
        <section className="check__start">
          <h1 className="display">Check photos, videos or voice notes</h1>
          <p>Choose one or several from your gallery or files. If they came on WhatsApp, save them to your phone first.</p>
          <button className="btn btn--marker check__big" onClick={() => input.current?.click()}>
            <Icon name="open" /> Choose files
          </button>
          {!ai && <p className="muted" style={{ fontSize: 13 }}>AI review is off on the TrustLens computer: results will use forensic tests only.</p>}
        </section>
      )}

      {single && single.status !== "done" && single.status !== "error" && (
        <section className="check__busy" role="status">
          <div className="check__scan"><span /></div>
          <b>Checking {single.name}</b>
          <p className="muted">{single.kind === "video" ? "Videos take up to a minute." : single.kind === "voice note" ? "Usually 10–20 seconds." : "Usually 5–20 seconds."}</p>
        </section>
      )}
      {single?.status === "error" && <div className="callout callout--bad"><p>{single.error}</p></div>}

      {items.length > 1 && (
        <section className="check__list" aria-label="Your files">
          <div className="check__progress">
            <span>{running ? `Checking ${current?.name ?? ""} · ${done} of ${items.length} done` : `All ${items.length} checked`}</span>
            <div className="batch__progress" role="progressbar" aria-valuemin={0} aria-valuemax={items.length} aria-valuenow={done}>
              <span style={{ width: `${(done / items.length) * 100}%` }} />
            </div>
          </div>
          {items.map((it) => (
            <button key={it.key} className="check__row" aria-expanded={open === it.key} disabled={!it.result}
                    onClick={() => setOpen(open === it.key ? null : it.key)}>
              {it.result ? <img src={api.image(it.result.case.id, "original", 160)} alt="" />
                : <span className={`batch__wait ${it.status === "checking" ? "is-running" : ""}`} />}
              <span className="check__row-text">
                <b>{it.name}</b>
                {it.result && <span className={`pill pill--${toneOf(it.result)}`}>{it.result.headline || it.result.verdict_label}</span>}
                {it.status === "checking" && <span className="muted">Checking…</span>}
                {it.status === "waiting" && <span className="muted">Waiting</span>}
                {it.status === "error" && <span className="muted">{it.error}</span>}
              </span>
              {it.result && <span className="check__row-score">{it.result.manipulation_score}</span>}
            </button>
          ))}
        </section>
      )}

      {shown?.result && <ResultCard r={shown.result} onOpen={onOpen} />}

      {items.length > 0 && !running && (
        <button className="btn btn--marker check__big" onClick={() => input.current?.click()}><Icon name="open" /> Check more files</button>
      )}
    </div>
  );
}
