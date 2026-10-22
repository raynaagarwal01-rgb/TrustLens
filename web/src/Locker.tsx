import { useRef } from "react";
import { api, type CaseSummary, type Sample, type Status } from "./api";
import { BrandMark, Icon } from "./ui";

interface Props {
  open: boolean;
  status: Status | null;
  cases: CaseSummary[];
  samples: Sample[];
  currentId: string | null;
  ai: boolean;
  onAi: (v: boolean) => void;
  onFile: (f: File) => void;
  onSample: (name: string) => void;
  onCase: (id: string) => void;
  onClose: () => void;
}

const GROUP_ORDER = ["tp", "edited", "ai", "au", "forged", "notice", "event", "other"];
const GROUP_LABEL: Record<string, string> = {
  tp: "Tampered photos (CASIA dataset)", edited: "Edited photo", ai: "AI-generated images", au: "Authentic photos",
  forged: "Forged notice", notice: "Genuine notice", event: "Event poster", other: "Other samples",
};
const SHORT: Record<string, string> = {
  fake: "Manipulated", likely_fake: "Likely manipulated", inconclusive: "Inconclusive", no_evidence: "No evidence found",
};

export function Locker({ open, status, cases, samples, currentId, ai, onAi, onFile, onSample, onCase, onClose }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const groups = GROUP_ORDER.map((g) => ({ g, items: samples.filter((s) => s.group === g) })).filter((x) => x.items.length);
  const aiAvailable = !!status?.llm.configured;
  return (
    <nav className="locker" data-open={open} aria-label="Evidence locker">
      <div className="locker__brand">
        <BrandMark />
        <div><b>TrustLens</b><small>Image evidence workbench</small></div>
        <button className="btn btn--quiet menu-btn" style={{ marginLeft: "auto", color: "#c6d0d8" }} onClick={onClose} aria-label="Close menu">
          <Icon name="close" />
        </button>
      </div>
      <div className="locker__open">
        <input ref={input} type="file" accept="image/*" hidden
               onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = ""; }} />
        <button className="btn btn--marker" onClick={() => input.current?.click()}><Icon name="open" /> Open an image</button>
        <label className="toggle" title={aiAvailable ? "" : "Start the server with GEMINI_API_KEY or GROQ_API_KEY set"}>
          <input type="checkbox" checked={ai && aiAvailable} disabled={!aiAvailable} onChange={(e) => onAi(e.target.checked)} />
          AI visual review{aiAvailable ? "" : " (no API key)"}
        </label>
      </div>

      <div className="locker__scroll">
        <div className="locker__heading"><span>Your cases</span><span>{cases.length || ""}</span></div>
        {cases.length === 0 && <p className="locker__empty">Cases you open are kept here.</p>}
        {cases.map((c) => (
          <button key={c.id} className="case-item" aria-current={c.id === currentId} onClick={() => onCase(c.id)}>
            <img src={api.image(c.id, "original", 160)} alt="" loading="lazy" />
            <span style={{ minWidth: 0 }}>
              <span className="case-item__name">{c.name}</span>
              <span className="case-item__meta"><span className={`dot dot--${c.verdict}`} />{SHORT[c.verdict] ?? c.verdict_label}</span>
            </span>
          </button>
        ))}

        <div className="locker__heading"><span>Demo evidence</span></div>
        {groups.map(({ g, items }) => (
          <details key={g} className="sample-group" open={g === "tp" || g === "edited"}>
            <summary><span>{GROUP_LABEL[g] ?? items[0].label}</span><span>{items.length}</span></summary>
            <div className="sample-grid">
              {items.map((s) => (
                <button key={s.name} className="sample-btn" onClick={() => onSample(s.name)} title={s.name}
                        aria-label={`Open demo: ${s.label}, ${s.name}`}>
                  <img src={api.sampleThumb(s.name)} alt="" loading="lazy" />
                </button>
              ))}
            </div>
          </details>
        ))}
      </div>

      {status && (
        <div className="locker__status" aria-label="System status">
          <div><span className={status.llm.configured ? "ok" : "off"}>●</span>AI review: {status.llm.configured ? cap(status.llm.provider) : "off"}</div>
          <div><span className={status.opencv ? "ok" : "off"}>●</span>Clone detection: {status.opencv ? "on" : "needs OpenCV"}</div>
          <div><span className={status.c2pa_verification ? "ok" : "off"}>●</span>Signature checks: {status.c2pa_verification ? "on" : "read-only"}</div>
          <div><span className={status.vtop.snapshots.length || status.vtop.cli_top_found ? "ok" : "off"}>●</span>VTOP: {status.vtop.cli_top_found ? "cli-top found" : status.vtop.snapshots.length ? `${status.vtop.snapshots.length} snapshots` : "not connected"}</div>
          <div><span className={status.custody.ok ? "ok" : "off"}>●</span>Custody log: {status.custody.ok ? `intact, ${status.custody.entries} entries` : "broken"}</div>
        </div>
      )}
    </nav>
  );
}

const cap = (s: string) => s[0].toUpperCase() + s.slice(1);
