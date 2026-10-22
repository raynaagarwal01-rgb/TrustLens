import { useEffect, useMemo, useState } from "react";
import { api, type Batch as BatchT, type BatchItem } from "./api";
import { Icon } from "./ui";

const TONE: Record<string, string> = { fake: "bad", likely_fake: "bad", inconclusive: "warn", no_evidence: "good" };
const KIND: Record<string, string> = { image: "Image", video: "Video", audio: "Voice note", unknown: "File" };

function csv(b: BatchT): string {
  const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const rows = [["file", "kind", "sender", "sent", "status", "finding", "score", "type", "case"].map(esc).join(",")];
  for (const i of b.items) {
    rows.push([i.file, i.kind, i.sender, i.sent, i.status, i.headline || i.verdict_label || i.error, i.score, i.fake_type_label, i.case_id].map(esc).join(","));
  }
  return rows.join("\n");
}

export function BatchView({ id, onOpen, onMenu }: { id: string; onOpen: (caseId: string) => void; onMenu: () => void }) {
  const [b, setB] = useState<BatchT | null>(null);
  const [error, setError] = useState("");
  const done = b ? b.items.filter((i) => i.status === "done" || i.status === "error").length : 0;
  const finished = !!b && done === b.total;

  useEffect(() => {
    let stop = false;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const next = await api.batch(id);
        if (stop) return;
        setB(next);
        if (next.items.some((i) => i.status === "queued" || i.status === "running")) timer = window.setTimeout(tick, 2000);
      } catch (e) { if (!stop) setError((e as Error).message); }
    };
    tick();
    return () => { stop = true; window.clearTimeout(timer); };
  }, [id]);

  const rows = useMemo(() => {
    if (!b) return [];
    const rank = (i: BatchItem) => (i.status === "done" ? -(i.score ?? 0) : i.status === "error" ? 1 : 2);
    return [...b.items].sort((x, y) => rank(x) - rank(y) || x.n - y.n);
  }, [b]);

  const counts = useMemo(() => {
    const c = { bad: 0, warn: 0, good: 0 };
    for (const i of b?.items ?? []) if (i.verdict) c[TONE[i.verdict] as keyof typeof c] += 1;
    return c;
  }, [b]);

  const download = () => {
    if (!b) return;
    const url = URL.createObjectURL(new Blob([csv(b)], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url; a.download = `trustlens_batch_${b.id}.csv`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <>
      <header className="case-head">
        <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", minWidth: 0 }}>
          <button className="btn btn--quiet menu-btn" onClick={onMenu} aria-label="Open cases and samples"><Icon name="menu" /></button>
          <div className="case-head__title">
            <h1>{b ? b.name : "Batch"}</h1>
            {b && (
              <div className="case-head__meta">
                <span>{b.total} file{b.total === 1 ? "" : "s"}{b.from_chat ? " from a WhatsApp export" : ""}</span>
                <span>{finished ? "All analysed" : `${done} of ${b.total} analysed`}</span>
                {b.skipped.length > 0 && <span>{b.skipped.length} skipped</span>}
              </div>
            )}
          </div>
        </div>
        {b && (
          <div className="case-head__actions">
            <button className="btn" onClick={download}><Icon name="download" /> Download table (CSV)</button>
          </div>
        )}
      </header>
      <div className="batch">
        {error && <div className="callout callout--bad"><p>{error}</p></div>}
        {b && (
          <>
            <div className="batch__progress" role="progressbar" aria-valuemin={0} aria-valuemax={b.total} aria-valuenow={done}
                 aria-label="Files analysed">
              <span style={{ width: `${(done / Math.max(1, b.total)) * 100}%` }} />
            </div>
            <div className="batch__counts">
              <span><b className="dot dot--fake" />{counts.bad} manipulated or likely</span>
              <span><b className="dot dot--inconclusive" />{counts.warn} inconclusive or not fully checked</span>
              <span><b className="dot dot--no_evidence" />{counts.good} nothing found</span>
            </div>
            <div className="tbl-wrap">
              <table className="tbl batch__table">
                <thead><tr><th aria-label="Preview" /><th>File</th>{b.from_chat && <th>Sent by</th>}<th>Finding</th><th>Score</th></tr></thead>
                <tbody>
                  {rows.map((i) => (
                    <tr key={i.n} className={i.case_id ? "is-link" : undefined} tabIndex={i.case_id ? 0 : -1}
                        onClick={() => i.case_id && onOpen(i.case_id)}
                        onKeyDown={(e) => { if (e.key === "Enter" && i.case_id) onOpen(i.case_id); }}>
                      <td className="batch__thumb">
                        {i.case_id ? <img src={api.image(i.case_id, "original", 120)} alt="" loading="lazy" />
                          : <span className={`batch__wait ${i.status === "running" ? "is-running" : ""}`} />}
                      </td>
                      <td><b className="batch__file">{i.file}</b><span className="muted">{KIND[i.kind] ?? "File"}</span></td>
                      {b.from_chat && <td>{i.sender ?? <span className="muted">Unknown</span>}<span className="muted">{i.sent}</span></td>}
                      <td>
                        {i.status === "done" && <span className={`pill pill--${TONE[i.verdict ?? ""] ?? ""}`}>{i.headline || i.verdict_label}</span>}
                        {i.status === "done" && i.fake_type_label && i.verdict !== "no_evidence" && <span className="muted">{i.fake_type_label}</span>}
                        {i.status === "running" && <span className="muted">Analysing…</span>}
                        {i.status === "queued" && <span className="muted">Waiting</span>}
                        {i.status === "error" && <span className="pill pill--bad">Couldn't analyse</span>}
                        {i.status === "error" && <span className="muted">{i.error}</span>}
                      </td>
                      <td className="batch__score">{i.score ?? ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {b.skipped.length > 0 && (
              <p className="muted" style={{ fontSize: 13 }}>Skipped (not an image, video or audio file, a sticker, or over 40 MB): {b.skipped.slice(0, 12).join(", ")}{b.skipped.length > 12 ? "…" : ""}</p>
            )}
          </>
        )}
      </div>
    </>
  );
}
