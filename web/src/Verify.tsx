import { useEffect, useRef, useState } from "react";
import { api, type VerifyResult } from "./api";
import { Icon } from "./ui";

const VERDICT_WORDS: Record<string, string> = {
  fake: "Manipulated", likely_fake: "Likely manipulated", inconclusive: "Inconclusive", no_evidence: "No evidence found",
};

export function VerifyView({ onMenu, onOpen }: { onMenu: () => void; onOpen: (id: string) => void }) {
  const [code, setCode] = useState("");
  const [res, setRes] = useState<VerifyResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [key, setKey] = useState<{ key_id: string; algorithm: string; public_key_pem: string } | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => { api.reportKey().then(setKey).catch(() => undefined); }, []);

  const run = async (p: Promise<VerifyResult>) => {
    setBusy(true); setError(""); setRes(null);
    try { setRes(await p); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };

  const downloadKey = () => {
    if (!key) return;
    const url = URL.createObjectURL(new Blob([key.public_key_pem], { type: "application/x-pem-file" }));
    const a = document.createElement("a");
    a.href = url; a.download = `trustlens_public_key_${key.key_id}.pem`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const p = res?.payload;
  return (
    <>
      <header className="case-head">
        <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", minWidth: 0 }}>
          <button className="btn btn--quiet menu-btn" onClick={onMenu} aria-label="Open cases and samples"><Icon name="menu" /></button>
          <div className="case-head__title"><h1>Verify a report</h1>
            <div className="case-head__meta"><span>Check that a TrustLens PDF report wasn't altered after it was signed</span></div></div>
        </div>
      </header>
      <div className="verify">
        <section className="sheet verify__input">
          <h2>Upload the report, or paste its code</h2>
          <p className="muted">The code is printed under the QR code on the last page. Scanning the QR code with a phone shows the same text.</p>
          <div className="dropline">
            <span>Report PDF</span>
            <input ref={input} type="file" accept="application/pdf,.pdf" hidden
                   onChange={(e) => { const f = e.target.files?.[0]; if (f) run(api.verifyPdf(f)); e.target.value = ""; }} />
            <button className="btn" onClick={() => input.current?.click()} disabled={busy}><Icon name="open" /> Choose PDF</button>
          </div>
          <label className="verify__code">
            <span>Report code</span>
            <textarea value={code} onChange={(e) => setCode(e.target.value)} rows={4} spellCheck={false}
                      placeholder="TLR1.eyJ…" className="mono" />
          </label>
          <button className="btn btn--primary" disabled={busy || !code.trim()} onClick={() => run(api.verifyToken(code.trim()))}>
            <Icon name="shield" /> {busy ? "Checking…" : "Check the signature"}
          </button>
          {error && <div className="callout callout--bad"><p>{error}</p></div>}
        </section>

        {res && (
          <section className={`sheet verify__result verify__result--${res.valid ? "good" : "bad"}`} aria-live="polite">
            <h2>{res.valid ? "Signature valid" : "Not valid"}</h2>
            <p>{res.reason}</p>
            {p && !res.valid && <p className="muted" style={{ fontSize: 13 }}>What the code claims (not trustworthy, because the signature fails):</p>}
            {p && (
              <dl className="facts" style={res.valid ? undefined : { opacity: 0.7, textDecoration: "line-through", textDecorationColor: "rgba(179,49,42,0.5)" }}>
                <dt>File</dt><dd>{p.file}</dd>
                <dt>SHA-256</dt><dd className="mono" style={{ wordBreak: "break-all" }}>{p.sha256}</dd>
                <dt>Finding</dt><dd>{VERDICT_WORDS[p.verdict] ?? p.verdict}, score {p.score}{p.type && p.type !== "none" ? ` (${p.type.replace(/_/g, " ")})` : ""}</dd>
                <dt>Based on</dt><dd>{p.ai_review ? "Forensic tests and AI review" : "Forensic tests only"}</dd>
                <dt>Signed</dt><dd>{p.issued.replace("T", " ").replace("Z", " UTC")} with key {p.key} ({p.alg})</dd>
                <dt>Custody log</dt><dd className="mono">{p.custody_head || "none"}…</dd>
              </dl>
            )}
            {res.valid && res.case_now?.exists && (
              <div className={`callout callout--${res.case_now.changed_since ? "warn" : "good"}`}>
                <p>{res.case_now.changed_since
                  ? `This case is in your locker but its result has changed since the report was signed (now ${VERDICT_WORDS[res.case_now.verdict ?? ""] ?? res.case_now.verdict}, score ${res.case_now.score}), for example after a VTOP or screenshot check.`
                  : "This case is in your locker and its result still matches the report."}{" "}
                  <button className="link-btn" onClick={() => onOpen(p!.case)}>Open the case</button></p>
              </div>
            )}
            {res.valid && <p className="muted" style={{ fontSize: 13 }}>To check the evidence file itself, compare its SHA-256 with the one above (Custody & integrity → Is this the same file?).</p>}
          </section>
        )}

        {key && (
          <section className="verify__key">
            <h3>This computer's signing key</h3>
            <p className="muted">Key ID <span className="mono">{key.key_id}</span> ({key.algorithm}). Reports signed on another computer show a
              different key ID; to verify them, use that computer's public key with <span className="mono">python verify_report.py report.pdf --public-key key.pem</span>.</p>
            {key.public_key_pem && <button className="btn" onClick={downloadKey}><Icon name="download" /> Download public key</button>}
          </section>
        )}
      </div>
    </>
  );
}
