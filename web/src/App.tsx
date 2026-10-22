import { useCallback, useEffect, useRef, useState } from "react";
import { ACCEPT, api, isMedia, type BatchSummary, type CaseResult, type CaseSummary, type Layers, type Sample,
         type Status } from "./api";
import { BatchView } from "./Batch";
import { DEMO_STEPS, DemoBar, STEP_SECONDS } from "./Demo";
import { Details } from "./Details";
import { Locker } from "./Locker";
import { PhoneDialog } from "./Phone";
import { Verdict } from "./Verdict";
import { VerifyView } from "./Verify";
import { Ruler, Viewer } from "./Viewer";
import { fmtTime, Icon, Toast } from "./ui";

const TRY = ["Edited_iphone_photo_demo.jpg", "AI_student_05.jpg", "Video_ai_talking_head_demo.mp4", "Voice_note_edited_demo.wav",
             "Screenshot_payment_demo.png", "Forged_notice_demo.jpg"];
const TRY_LABEL: Record<string, string> = {
  "Edited_iphone_photo_demo.jpg": "Edited phone photo", "AI_student_05.jpg": "AI-generated student",
  "Video_ai_talking_head_demo.mp4": "Deepfake video", "Voice_note_edited_demo.wav": "Edited voice note",
  "Screenshot_payment_demo.png": "Fake payment receipt", "Forged_notice_demo.jpg": "Forged exam notice",
};

type Route = { kind: "home" } | { kind: "case"; id: string } | { kind: "batch"; id: string } | { kind: "verify" };

const routeFromHash = (): Route => {
  const h = location.hash;
  let m = h.match(/^#\/case\/([0-9a-f]{12})$/);
  if (m) return { kind: "case", id: m[1] };
  m = h.match(/^#\/batch\/([0-9a-f]{12})$/);
  if (m) return { kind: "batch", id: m[1] };
  if (h === "#/verify") return { kind: "verify" };
  return { kind: "home" };
};

export function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [batchList, setBatchList] = useState<BatchSummary[]>([]);
  const [route, setRoute] = useState<Route>(routeFromHash);
  const [result, setResult] = useState<CaseResult | null>(null);
  const [layers, setLayers] = useState<Layers | null>(null);
  const [busy, setBusy] = useState<string | null>(null); // preview URL while an analysis runs
  const [ai, setAi] = useState(true);
  const [toast, setToast] = useState<{ message: string; kind: "error" | "info" } | null>(null);
  const [mark, setMark] = useState<number | null>(null);
  const [lockerOpen, setLockerOpen] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [phoneOpen, setPhoneOpen] = useState(false);
  const [demo, setDemo] = useState<{ step: number; playing: boolean; ids: string[]; preparing: { done: number; total: number } | null } | null>(null);
  const compareInput = useRef<HTMLInputElement>(null);
  const shownId = useRef("");

  const aiOn = !!status?.llm.configured;
  const fail = useCallback((message: string) => setToast({ message, kind: "error" }), []);
  const info = useCallback((message: string) => setToast({ message, kind: "info" }), []);
  const refresh = useCallback(() => {
    api.cases().then(setCases).catch(() => undefined);
    api.batches().then(setBatchList).catch(() => undefined);
    api.status().then(setStatus).catch(() => undefined);
  }, []);

  const go = useCallback((hash: string, replace = false) => {
    if (location.hash !== hash) (replace ? history.replaceState : history.pushState).call(history, null, "", hash);
    setRoute(routeFromHash());
  }, []);

  const show = useCallback(async (r: CaseResult, replace = false) => {
    shownId.current = r.case.id;
    setLayers(null);  // never pair a case with another case's layers
    setResult(r);
    api.layers(r.case.id).then((l) => { if (shownId.current === r.case.id) setLayers(l); }).catch(() => undefined);
    go(`#/case/${r.case.id}`, replace);
    document.title = `${r.case.name}: ${r.headline || r.verdict_label} · TrustLens`;
  }, [go]);

  const loadCase = useCallback(async (id: string, replace = false) => {
    setLockerOpen(false);
    try { await show(await api.getCase(id), replace); } catch (e) { fail((e as Error).message); }
  }, [fail, show]);

  const applyRoute = useCallback((r: Route) => {
    setRoute(r);
    if (r.kind === "case") loadCase(r.id, true);
    if (r.kind !== "case") { setResult(null); setLayers(null); document.title = "TrustLens"; }
  }, [loadCase]);

  useEffect(() => {
    api.status().then((s) => { setStatus(s); setAi(s.llm.configured); }).catch((e) => fail(e.message));
    api.samples().then(setSamples).catch(() => undefined);
    api.cases().then(setCases).catch(() => undefined);
    api.batches().then(setBatchList).catch(() => undefined);
    applyRoute(routeFromHash());
    const onPop = () => applyRoute(routeFromHash());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [fail, applyRoute]);

  const analyse = async (run: () => Promise<CaseResult>, preview: string) => {
    setLockerOpen(false);
    setResult(null); setLayers(null); setBusy(preview); setToast(null);
    setRoute({ kind: "case", id: "" });
    try {
      await show(await run());
      refresh();
    } catch (e) {
      fail((e as Error).message);
      go("#/");
    } finally {
      setBusy(null);
    }
  };
  const openFile = (f: File) => {
    if (!isMedia(f)) return fail(`${f.name} isn't an image, video or audio file. For many files or a WhatsApp export (.zip), drop them together.`);
    const preview = f.type.startsWith("image/") ? URL.createObjectURL(f) : "";
    analyse(() => api.upload(f, ai), preview);
  };
  const openFiles = async (files: File[]) => {
    if (files.length === 1 && !/\.zip$/i.test(files[0].name)) return openFile(files[0]);
    setLockerOpen(false);
    try {
      info(`Uploading ${files.length} file${files.length > 1 ? "s" : ""}…`);
      const b = await api.createBatch(files);
      setToast(null);
      refresh();
      go(`#/batch/${b.id}`);
    } catch (e) { fail((e as Error).message); }
  };
  const openSample = (name: string) => {
    const s = samples.find((x) => x.name === name);
    analyse(() => api.openSample(name, ai), s?.kind === "image" ? `/api/samples/${encodeURIComponent(name)}?w=1600` : "");
  };

  const compare = async (f: File) => {
    if (!result) return;
    try {
      const c = await api.compare(result.case.id, f);
      info(`Compared with ${f.name}: ${c.summary}`);
      await show(await api.getCase(result.case.id), true);
    } catch (e) { fail((e as Error).message); }
  };

  const reanalyse = async () => {
    if (!result) return;
    const r0 = result;
    analyse(() => api.reanalyse(r0.case.id), r0.media_kind === "image" ? api.image(r0.case.id, "original", 1600) : "");
  };

  const remove = async () => {
    if (!result || !confirm(`Remove ${result.case.name} from your cases? The custody log keeps a record that it was removed.`)) return;
    try {
      await api.remove(result.case.id);
      setResult(null); setLayers(null); go("#/"); refresh();
      info("Removed from your cases.");
    } catch (e) { fail((e as Error).message); }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault(); setDragOver(false);
    const files = Array.from(e.dataTransfer.files ?? []);
    if (files.length) openFiles(files);
  };

  /* ---------------------------------------------------------------- demo mode */
  const steps = DEMO_STEPS.filter((s) => samples.some((x) => x.name === s.sample));
  const startDemo = async () => {
    setLockerOpen(false);
    const ids: string[] = [];
    setDemo({ step: 0, playing: false, ids, preparing: { done: 0, total: steps.length } });
    for (const [i, s] of steps.entries()) {
      try {
        const r = await api.openSample(s.sample, ai, true);
        ids.push(r.case.id);
        if (i === 0) await show(r);
      } catch (e) {
        fail(`Demo case ${s.sample} failed: ${(e as Error).message}`);
        setDemo(null);
        return;
      }
      setDemo((d) => d && { ...d, preparing: { done: i + 1, total: steps.length } });
    }
    refresh();
    setDemo({ step: 0, playing: true, ids, preparing: null });
  };
  const demoGo = useCallback((step: number) => {
    setDemo((d) => {
      if (!d || d.preparing) return d;
      if (step >= d.ids.length) return null;
      const n = Math.max(0, step);
      loadCase(d.ids[n], true);
      return { ...d, step: n };
    });
  }, [loadCase]);
  useEffect(() => {
    if (!demo || demo.preparing || !demo.playing) return;
    const t = window.setTimeout(() => demoGo(demo.step + 1), STEP_SECONDS * 1000);
    return () => window.clearTimeout(t);
  }, [demo, demoGo]);
  // walk through the "why" markers while a demo case is on screen
  useEffect(() => {
    if (!demo || demo.preparing || !demo.playing || !result) { setMark(null); return; }
    let n = 0;
    const t = window.setInterval(() => { n = (n % 4) + 1; setMark(n); }, 2200);
    return () => { window.clearInterval(t); setMark(null); };
  }, [demo, result]);

  const caseView = route.kind === "case" && (result || busy !== null);
  const mediaKind = result?.media_kind ?? "image";

  return (
    <div className={`app${demo ? " app--demo" : ""}`} onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
         onDragLeave={() => setDragOver(false)} onDrop={onDrop}>
      <Locker open={lockerOpen} status={status} cases={cases} batches={batchList} samples={samples} currentId={result?.case.id ?? null}
              ai={ai} onAi={setAi} onFiles={openFiles} onSample={openSample} onCase={(id) => loadCase(id)}
              onBatch={(id) => { setLockerOpen(false); go(`#/batch/${id}`); }}
              onVerify={() => { setLockerOpen(false); go("#/verify"); }} onDemo={startDemo}
              onPhone={() => { setLockerOpen(false); setPhoneOpen(true); }} onClose={() => setLockerOpen(false)} />
      <main className="main" id="main">
        {route.kind === "batch" && <BatchView id={route.id} onOpen={(id) => loadCase(id)} onMenu={() => setLockerOpen(true)} />}
        {route.kind === "verify" && <VerifyView onMenu={() => setLockerOpen(true)} onOpen={(id) => loadCase(id)} />}
        {caseView && (
          <>
            <header className="case-head">
              <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", minWidth: 0 }}>
                <button className="btn btn--quiet menu-btn" onClick={() => setLockerOpen(true)} aria-label="Open cases and samples"><Icon name="menu" /></button>
                <div className="case-head__title">
                  <h1>{result ? result.case.name : "Opening evidence…"}</h1>
                  {result && (
                    <div className="case-head__meta">
                      <span>Case <span className="mono">{result.case.id}</span></span>
                      <span>Opened {fmtTime(result.case.created)}</span>
                      <span>{mediaKind === "image" ? `${result.integrity.format} ${result.integrity.width}×${result.integrity.height}`
                        : mediaKind === "video" ? `Video, ${result.video?.duration}s, ${result.integrity.width}×${result.integrity.height}`
                        : `Voice note, ${result.audio?.measurements?.duration}s`}</span>
                    </div>
                  )}
                </div>
              </div>
              {result && (
                <div className="case-head__actions">
                  {aiOn && !result.llm_used && (
                    <button className="btn btn--marker" onClick={reanalyse} title="This case was analysed before the AI review was on">
                      <Icon name="search" /> Re-analyse with AI review
                    </button>
                  )}
                  <input ref={compareInput} type="file" accept="image/*" hidden
                         onChange={(e) => { const f = e.target.files?.[0]; if (f) compare(f); e.target.value = ""; }} />
                  {mediaKind === "image" && (
                    <button className="btn" onClick={() => compareInput.current?.click()}><Icon name="compare" /> Compare with original</button>
                  )}
                  <a className="btn" href={api.report(result.case.id)} target="_blank" rel="noreferrer"><Icon name="report" /> HTML report</a>
                  {status?.pdf !== false && (
                    <a className="btn btn--primary" href={api.reportPdf(result.case.id)} target="_blank" rel="noreferrer"><Icon name="shield" /> Signed PDF</a>
                  )}
                  <button className="btn btn--quiet" onClick={remove} aria-label="Remove from your cases"><Icon name="trash" /></button>
                </div>
              )}
            </header>
            <div className="workspace">
              <div className="workspace__left">
                <Viewer result={result} layers={layers} busyPreview={busy} activeMark={mark} />
                {result && <Details result={result} aiOn={aiOn} onResult={(r) => { setResult(r); refresh(); }} onError={fail} onInfo={info} />}
              </div>
              {result && <Verdict result={result} onMark={setMark} />}
            </div>
          </>
        )}
        {(route.kind === "home" || (route.kind === "case" && !caseView)) && (
          <div className="welcome">
            <button className="btn btn--quiet menu-btn" style={{ width: "fit-content" }} onClick={() => setLockerOpen(true)}>
              <Icon name="menu" /> Cases and samples
            </button>
            <section className="dropzone" data-over={dragOver}>
              <div className="frame">
                <div className="scale scale--top"><Ruler /></div>
                <div className="scale scale--left"><Ruler vertical /></div>
                <div className="scale-corner"><span /></div>
                <div className="dropzone__inner">
                  <div className="dropzone__copy">
                    <h1 className="display">Is this real?</h1>
                    <p>TrustLens checks photos, videos, voice notes and screenshots for deepfakes, AI generation and edits,
                      shows where the evidence is, and signs a report you can hand to a proctor or the cyber cell.</p>
                    {steps.length > 0 && (
                      <button className="btn btn--marker" onClick={startDemo}><Icon name="play" /> Play the 90-second demo</button>
                    )}
                  </div>
                  <label className="droptarget">
                    <span className="corner corner--tl" /><span className="corner corner--tr" />
                    <span className="corner corner--bl" /><span className="corner corner--br" />
                    <span>
                      <Icon name="open" />
                      <b>Drop files here, or choose them</b>
                      Images, videos, voice notes, or a WhatsApp chat export (.zip). Several files become a batch.
                      Files stay on this computer.
                    </span>
                    <input type="file" accept={ACCEPT} multiple className="visually-hidden"
                           onChange={(e) => { const fs = Array.from(e.target.files ?? []); if (fs.length) openFiles(fs); e.target.value = ""; }} />
                  </label>
                </div>
              </div>
            </section>
            <section className="uses" aria-label="What TrustLens checks">
              <div className="use">
                <h2>Photos, videos and voice notes</h2>
                <p>Reads Content Credentials, compares a photo with the preview its camera stored, maps error levels and clones,
                  samples video frames, finds faces for close inspection, and marks digital silence in audio.</p>
              </div>
              <div className="use">
                <h2>Screenshots, notices and posters</h2>
                <p>Checks payment receipts and chats against real formats, notice dates against your VTOP records via cli-top,
                  and event posters against official listings.</p>
              </div>
              <div className="use">
                <h2>Evidence you can hand over</h2>
                <p>Finds earlier copies of a photo online, analyses whole WhatsApp exports, and signs a PDF report with a QR code
                  anyone can verify. Every action goes into a tamper-evident custody log.</p>
              </div>
            </section>
            <section>
              <h2 style={{ marginBottom: "0.6rem" }}>Or try one</h2>
              <div className="try-row">
                {TRY.filter((t) => samples.some((s) => s.name === t)).map((t) => (
                  <button key={t} className="try" onClick={() => openSample(t)}>
                    <img src={api.sampleThumb(t)} alt="" />{TRY_LABEL[t]}
                  </button>
                ))}
              </div>
            </section>
          </div>
        )}
      </main>
      {demo && (
        <DemoBar step={demo.step} total={demo.ids.length || steps.length} playing={demo.playing} preparing={demo.preparing}
                 onPrev={() => demoGo((demo?.step ?? 0) - 1)} onNext={() => demoGo((demo?.step ?? 0) + 1)}
                 onToggle={() => setDemo((d) => d && { ...d, playing: !d.playing })} onExit={() => setDemo(null)} />
      )}
      {phoneOpen && <PhoneDialog onClose={() => setPhoneOpen(false)} />}
      {toast && <Toast message={toast.message} kind={toast.kind} onClose={() => setToast(null)} />}
    </div>
  );
}
