import { useState } from "react";
import type { CaseResult, Speech } from "./api";
import { evidenceMarks } from "./evidence";
import { Tent } from "./ui";

const BANDS = [
  { from: 0, to: 30, label: "No evidence", colour: "#1D6E52" },
  { from: 30, to: 55, label: "Inconclusive", colour: "#9A6410" },
  { from: 55, to: 80, label: "Likely", colour: "#C4542B" },
  { from: 80, to: 100, label: "Manipulated", colour: "#B3312A" },
];

function ScoreScale({ score }: { score: number }) {
  const ticks = Array.from({ length: 21 }, (_, i) => i * 5);
  return (
    <figure className="score-scale" aria-label={`Manipulation score ${score} out of 100`}>
      <div className="score-row"><span>Manipulation score</span><b>{score}<span className="muted" style={{ fontSize: 13 }}> /100</span></b></div>
      <svg viewBox="0 0 300 54" preserveAspectRatio="none" role="img" aria-hidden="true">
        {BANDS.map((b) => (
          <rect key={b.from} className="zone" x={b.from * 3} width={(b.to - b.from) * 3} y={14} height={8} fill={b.colour}
                opacity={score >= b.from && (score < b.to || (b.to === 100 && score === 100)) ? 1 : 0.22} />
        ))}
        {ticks.map((t) => <line key={t} x1={t * 3} x2={t * 3} y1={22} y2={t % 25 === 0 ? 31 : 26} stroke="#566370" strokeWidth={1} />)}
        <path d={`M${score * 3} 13 l-6 -9 h12 z`} fill="#14202B" />
        {BANDS.map((b) => (
          <text key={b.label} x={(b.from + b.to) * 1.5} y={45} textAnchor="middle">{b.label}</text>
        ))}
      </svg>
    </figure>
  );
}

interface Props {
  result: CaseResult;
  onMark: (n: number | null) => void;
}

/** Name the specific finding when the type is known, instead of "manipulated or AI-generated". */
const unchecked = (r: CaseResult) => r.verdict === "no_evidence" && (!r.llm_used || r.media_kind === "audio");

function Summary({ r }: { r: CaseResult }) {
  const [lang, setLang] = useState<"en" | "hi">(() => {
    try { return (localStorage.getItem("tl-summary-lang") as "en" | "hi") || "en"; } catch { return "en"; }
  });
  const pick = (l: "en" | "hi") => { setLang(l); try { localStorage.setItem("tl-summary-lang", l); } catch { /* private mode */ } };
  if (!r.summary) return null;
  return (
    <section className="in-short" aria-label="Summary">
      <div className="in-short__head">
        <h3>In short</h3>
        <div className="seg" role="group" aria-label="Summary language">
          <button aria-pressed={lang === "en"} onClick={() => pick("en")}>English</button>
          <button aria-pressed={lang === "hi"} onClick={() => pick("hi")} lang="hi">हिंदी</button>
        </div>
      </div>
      <ol lang={lang}>{r.summary[lang].map((line, i) => <li key={i}>{line}</li>)}</ol>
    </section>
  );
}

function ScamRisk({ s }: { s: Speech }) {
  if (s.status !== "ok" || !s.scam_risk) return null;
  const tone = s.scam_risk === "high" ? "bad" : s.scam_risk === "medium" ? "warn" : "good";
  return (
    <section className={`risk risk--${tone}`} aria-label="Scam risk of what is said">
      <div className="risk__head"><span>What is said</span><b>Scam risk: {s.scam_risk}</b></div>
      {s.summary && <p>{s.summary}</p>}
      {(s.scam_cues ?? []).slice(0, 3).map((c) => <p key={c.cue} className="risk__cue"><b>{c.cue}:</b> “{c.quote}”</p>)}
    </section>
  );
}

export function Verdict({ result: r, onMark }: Props) {
  const marks = evidenceMarks(r);
  const strong = r.forensic_signals.filter((s) => s.severity === "high" || s.severity === "medium");
  const mode = r.media_kind === "audio"
    ? (r.llm_used ? "File tests and transcript" : "File and sound tests only")
    : r.llm_used ? "Forensic tests and AI review" : "Forensic tests only";
  const speech = r.audio?.speech ?? r.video?.audio?.speech;
  return (
    <aside className={`verdict verdict--${unchecked(r) ? "inconclusive" : r.verdict}`} aria-label="Verdict">
      <div className="verdict__band">
        <h2 className="verdict__label display">{r.headline || r.verdict_label}</h2>
        <div className="verdict__type">{unchecked(r) && r.media_kind === "audio" ? "A cloned voice can't be ruled out from the sound alone"
            : unchecked(r) ? `AI review was off, and forensic tests alone can't spot most ${r.media_kind === "video" ? "deepfakes" : "AI images"}`
            : r.verdict === "no_evidence" ? "Nothing found that indicates editing or AI generation" : r.fake_type_label}</div>
      </div>
      <div className="verdict__body">
        <ScoreScale score={r.manipulation_score} />
        <Summary r={r} />
        {speech && <ScamRisk s={speech} />}
        <dl className="facts">
          <dt>Confidence</dt><dd>{r.confidence[0].toUpperCase() + r.confidence.slice(1)}</dd>
          <dt>Based on</dt><dd>{mode}</dd>
          {r.image_kind && <><dt>Looks like</dt><dd>{r.image_kind[0].toUpperCase() + r.image_kind.slice(1)}</dd></>}
        </dl>
        {r.explanation && <p className="verdict__explain">{r.explanation}</p>}
        {r.error && <p className="muted" style={{ fontSize: 13, margin: 0 }}>AI review didn't run ({r.error.slice(0, 90)}), so this verdict uses forensic tests only.</p>}

        {(r.rule_notes.length > 0 || marks.length > 0 || strong.length > 0) && (
          <section>
            <h3 style={{ marginBottom: "0.5rem" }}>Why</h3>
            <ul className="reasons">
              {r.rule_notes.map((n) => <li key={n}><Tent n="!" plain /><span>{n}</span></li>)}
              {marks.map((m) => (
                <li key={`m${m.n}`} onMouseEnter={() => onMark(m.n)} onMouseLeave={() => onMark(null)}
                    onFocus={() => onMark(m.n)} onBlur={() => onMark(null)} tabIndex={0}>
                  <Tent n={m.n} /><span><b>{m.title}.</b> <span className="muted">{m.detail}</span></span>
                </li>
              ))}
              {r.rule_notes.length === 0 && marks.length === 0 && strong.slice(0, 3).map((s) => (
                <li key={s.check}><Tent n="·" plain /><span><b>{s.check}.</b> <span className="muted">{s.detail.split(". ")[0]}.</span></span></li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </aside>
  );
}
