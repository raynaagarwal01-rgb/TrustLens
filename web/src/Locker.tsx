import { useRef } from "react";
import { ACCEPT, api, type BatchSummary, type CaseSummary, type Sample, type Status } from "./api";
import { BrandMark, fmtTime, Icon } from "./ui";

interface Props {
  open: boolean;
  status: Status | null;
  cases: CaseSummary[];
  batches: BatchSummary[];
  samples: Sample[];
  currentId: string | null;
  ai: boolean;
  onAi: (v: boolean) => void;
  onFiles: (f: File[]) => void;
  onSample: (name: string) => void;
  onCase: (id: string) => void;
  onBatch: (id: string) => void;
  onVerify: () => void;
  onDemo: () => void;
  onClose: () => void;
}

const GROUP_ORDER = ["tp", "edited", "ai", "video", "voice", "screenshot", "au", "forged", "notice", "event", "other"];
const GROUP_LABEL: Record<string, string> = {
  tp: "Tampered photos (CASIA dataset)", edited: "Edited photo", ai: "AI-generated images", video: "Deepfake video",
  voice: "Voice notes", screenshot: "Screenshots", au: "Authentic photos", forged: "Forged notice", notice: "Genuine notice",
  event: "Event poster", other: "Other samples",
};
const KIND_TAG: Record<string, string> = { video: "Video", audio: "Audio" };

export function Locker({ open, status, cases, batches, samples, currentId, ai, onAi, onFiles, onSample, onCase, onBatch,
                         onVerify, onDemo, onClose }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const groups = GROUP_ORDER.map((g) => ({ g, items: samples.filter((s) => s.group === g) })).filter((x) => x.items.length);
  const aiAvailable = !!status?.llm.configured;
  return (
    <nav className="locker" data-open={open} aria-label="Evidence locker">
      <div className="locker__brand">
        <BrandMark />
        <div><b>TrustLens</b><small>Evidence workbench</small></div>
        <button className="btn btn--quiet menu-btn" style={{ marginLeft: "auto", color: "#c6d0d8" }} onClick={onClose} aria-label="Close menu">
          <Icon name="close" />
        </button>
      </div>
      <div className="locker__open">
        <input ref={input} type="file" accept={ACCEPT} multiple hidden
               onChange={(e) => { const fs = Array.from(e.target.files ?? []); if (fs.length) onFiles(fs); e.target.value = ""; }} />
        <button className="btn btn--marker" onClick={() => input.current?.click()}><Icon name="open" /> Open files</button>
        <label className="toggle" title={aiAvailable ? "" : "Add GROQ_API_KEY or GEMINI_API_KEY to the .env file and restart"}>
          <input type="checkbox" checked={ai && aiAvailable} disabled={!aiAvailable} onChange={(e) => onAi(e.target.checked)} />
          AI review{aiAvailable ? "" : " (no API key)"}
        </label>
        <div className="locker__links">
          <button className="link-btn" onClick={onDemo}><Icon name="play" /> Play demo</button>
          <button className="link-btn" onClick={onVerify}><Icon name="shield" /> Verify a report</button>
        </div>
      </div>

      <div className="locker__scroll">
        <div className="locker__heading"><span>Your cases</span><span>{cases.length || ""}</span></div>
        {cases.length === 0 && <p className="locker__empty">Files you open are kept here.</p>}
        {cases.map((c) => (
          <button key={c.id} className="case-item" aria-current={c.id === currentId} onClick={() => onCase(c.id)}>
            <span className="case-item__thumb">
              <img src={api.image(c.id, "original", 160)} alt="" loading="lazy" />
              {KIND_TAG[c.media_kind ?? ""] && <span className="case-item__kind">{KIND_TAG[c.media_kind ?? ""]}</span>}
            </span>
            <span style={{ minWidth: 0 }}>
              <span className="case-item__name">{c.name}</span>
              <span className="case-item__meta">
                <span className={`dot dot--${c.verdict === "no_evidence" && (!c.llm_used || c.media_kind === "audio") ? "inconclusive" : c.verdict}`} />
                {c.headline || c.verdict_label}
              </span>
            </span>
          </button>
        ))}

        {batches.length > 0 && (
          <>
            <div className="locker__heading"><span>Batches</span><span>{batches.length}</span></div>
            {batches.map((b) => (
              <button key={b.id} className="case-item case-item--batch" onClick={() => onBatch(b.id)}>
                <span className="case-item__thumb case-item__thumb--icon"><Icon name="stack" /></span>
                <span style={{ minWidth: 0 }}>
                  <span className="case-item__name">{b.name}</span>
                  <span className="case-item__meta">{b.done < b.total ? `${b.done} of ${b.total} analysed` : `${b.total} files`} · {fmtTime(b.created)}</span>
                </span>
              </button>
            ))}
          </>
        )}

        <div className="locker__heading"><span>Demo evidence</span></div>
        {groups.map(({ g, items }) => (
          <details key={g} className="sample-group" open={g === "tp" || g === "edited" || g === "video" || g === "voice"}>
            <summary><span>{GROUP_LABEL[g] ?? items[0].label}</span><span>{items.length}</span></summary>
            <div className="sample-grid">
              {items.map((s) => (
                <button key={s.name} className="sample-btn" onClick={() => onSample(s.name)} title={s.name}
                        aria-label={`Open demo: ${s.label}, ${s.name}`}>
                  <img src={api.sampleThumb(s.name)} alt="" loading="lazy" />
                  {KIND_TAG[s.kind] && <span className="case-item__kind">{KIND_TAG[s.kind]}</span>}
                </button>
              ))}
            </div>
          </details>
        ))}
      </div>

      {status && (
        <div className="locker__status" aria-label="System status">
          <div><span className={status.llm.configured ? "ok" : "off"}>●</span>AI review: {status.llm.configured ? cap(status.llm.provider) : "off (add key to .env)"}</div>
          <div><span className={status.opencv && status.faces ? "ok" : "off"}>●</span>Clones and faces: {status.opencv ? (status.faces ? "on" : "no face model") : "needs OpenCV"}</div>
          <div><span className={status.ffmpeg ? "ok" : "off"}>●</span>Video and audio: {status.ffmpeg ? "on" : "needs ffmpeg"}</div>
          <div><span className={status.pdf ? "ok" : "off"}>●</span>Signed PDF: {status.pdf ? `on (${status.signing})` : "needs reportlab"}</div>
          <div><span className={status.vtop.snapshots.length || status.vtop.cli_top_found ? "ok" : "off"}>●</span>VTOP: {status.vtop.cli_top_found ? "cli-top found" : status.vtop.snapshots.length ? `${status.vtop.snapshots.length} snapshots` : "not connected"}</div>
          <div><span className={status.custody.ok ? "ok" : "off"}>●</span>Custody log: {status.custody.ok ? `intact, ${status.custody.entries} entries` : "broken"}</div>
        </div>
      )}
    </nav>
  );
}

const cap = (s: string) => s[0].toUpperCase() + s.slice(1);
