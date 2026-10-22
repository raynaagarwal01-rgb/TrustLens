import { useCallback, useEffect, useRef, useState } from "react";
import { api, type CaseResult, type CaseSummary, type Layers, type Sample, type Status } from "./api";
import { Details } from "./Details";
import { Locker } from "./Locker";
import { Verdict } from "./Verdict";
import { Ruler, Viewer } from "./Viewer";
import { fmtTime, Icon, Toast } from "./ui";

const TRY = ["Edited_iphone_photo_demo.jpg", "AI_student_05.jpg", "Tp_D_CRN_S_N_nat00033_cha00086_11502.jpg",
             "Forged_notice_demo.jpg", "Event_fake_hackathon_demo.jpg"];
const TRY_LABEL: Record<string, string> = {
  "Edited_iphone_photo_demo.jpg": "Edited phone photo", "AI_student_05.jpg": "AI-generated student",
  "Tp_D_CRN_S_N_nat00033_cha00086_11502.jpg": "Spliced photo (dataset)", "Forged_notice_demo.jpg": "Forged exam notice",
  "Event_fake_hackathon_demo.jpg": "Hackathon poster",
};

const idFromHash = () => (location.hash.match(/^#\/case\/([0-9a-f]{12})$/) ?? [])[1] ?? null;

export function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [result, setResult] = useState<CaseResult | null>(null);
  const [layers, setLayers] = useState<Layers | null>(null);
  const [busy, setBusy] = useState<string | null>(null); // preview URL while an analysis runs
  const [ai, setAi] = useState(true);
  const [toast, setToast] = useState<{ message: string; kind: "error" | "info" } | null>(null);
  const [mark, setMark] = useState<number | null>(null);
  const [lockerOpen, setLockerOpen] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const compareInput = useRef<HTMLInputElement>(null);

  const fail = useCallback((message: string) => setToast({ message, kind: "error" }), []);
  const info = useCallback((message: string) => setToast({ message, kind: "info" }), []);
  const refresh = useCallback(() => {
    api.cases().then(setCases).catch(() => undefined);
    api.status().then(setStatus).catch(() => undefined);
  }, []);

  const show = useCallback(async (r: CaseResult) => {
    setResult(r);
    setLayers(await api.layers(r.case.id).catch(() => null));
    if (idFromHash() !== r.case.id) history.pushState(null, "", `#/case/${r.case.id}`);
    document.title = `${r.case.name}: ${r.verdict_label} · TrustLens`;
  }, []);

  const loadCase = useCallback(async (id: string) => {
    setLockerOpen(false);
    try { await show(await api.getCase(id)); } catch (e) { fail((e as Error).message); }
  }, [fail, show]);

  useEffect(() => {
    api.status().then((s) => { setStatus(s); setAi(s.llm.configured); }).catch((e) => fail(e.message));
    api.samples().then(setSamples).catch(() => undefined);
    api.cases().then(setCases).catch(() => undefined);
    const id = idFromHash();
    if (id) loadCase(id);
    const onPop = () => { const h = idFromHash(); if (h) loadCase(h); else { setResult(null); setLayers(null); } };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [fail, loadCase]);

  const analyse = async (run: () => Promise<CaseResult>, preview: string) => {
    setLockerOpen(false);
    setResult(null); setLayers(null); setBusy(preview); setToast(null);
    try {
      await show(await run());
      refresh();
    } catch (e) {
      fail((e as Error).message);
      history.pushState(null, "", "#/");
    } finally {
      setBusy(null);
    }
  };
  const openFile = (f: File) => {
    if (!f.type.startsWith("image/")) return fail(`${f.name} isn't an image. Open a JPEG, PNG, WebP, BMP or TIFF file.`);
    analyse(() => api.upload(f, ai), URL.createObjectURL(f));
  };
  const openSample = (name: string) => analyse(() => api.openSample(name, ai), api.sampleThumb(name).replace("w=160", "w=1600"));

  const compare = async (f: File) => {
    if (!result) return;
    try {
      const c = await api.compare(result.case.id, f);
      info(`Compared with ${f.name}: ${c.summary}`);
      await show(await api.getCase(result.case.id));
    } catch (e) { fail((e as Error).message); }
  };

  const remove = async () => {
    if (!result || !confirm(`Remove ${result.case.name} from your cases? The custody log keeps a record that it was removed.`)) return;
    try {
      await api.remove(result.case.id);
      setResult(null); setLayers(null); history.pushState(null, "", "#/"); refresh();
      info("Removed from your cases.");
    } catch (e) { fail((e as Error).message); }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault(); setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) openFile(f);
  };

  return (
    <div className="app" onDragOver={(e) => { e.preventDefault(); setDragOver(true); }} onDragLeave={() => setDragOver(false)} onDrop={onDrop}>
      <Locker open={lockerOpen} status={status} cases={cases} samples={samples} currentId={result?.case.id ?? null}
              ai={ai} onAi={setAi} onFile={openFile} onSample={openSample} onCase={loadCase} onClose={() => setLockerOpen(false)} />
      <main className="main" id="main">
        {(result || busy) ? (
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
                      <span>{result.integrity.format} {result.integrity.width}×{result.integrity.height}</span>
                    </div>
                  )}
                </div>
              </div>
              {result && (
                <div className="case-head__actions">
                  <input ref={compareInput} type="file" accept="image/*" hidden
                         onChange={(e) => { const f = e.target.files?.[0]; if (f) compare(f); e.target.value = ""; }} />
                  <button className="btn" onClick={() => compareInput.current?.click()}><Icon name="compare" /> Compare with original</button>
                  <a className="btn btn--primary" href={api.report(result.case.id)} target="_blank" rel="noreferrer"><Icon name="report" /> Evidence report</a>
                  <button className="btn btn--quiet" onClick={remove} aria-label="Remove from your cases"><Icon name="trash" /></button>
                </div>
              )}
            </header>
            <div className="workspace">
              <div className="workspace__left">
                <Viewer result={result} layers={layers} busyPreview={busy} activeMark={mark} />
                {result && <Details result={result} onResult={(r) => { setResult(r); refresh(); }} onError={fail} onInfo={info} />}
              </div>
              {result && <Verdict result={result} onMark={setMark} />}
            </div>
          </>
        ) : (
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
                    <h1 className="display">Is this image real?</h1>
                    <p>TrustLens checks photos, screenshots and posters for AI generation, edits and forged details,
                      shows where they are, and keeps a hash-stamped report you can hand to a proctor or the cyber cell.</p>
                  </div>
                  <label className="droptarget">
                    <span className="corner corner--tl" /><span className="corner corner--tr" />
                    <span className="corner corner--bl" /><span className="corner corner--br" />
                    <span>
                      <Icon name="open" />
                      <b>Drop an image here, or choose one</b>
                      JPEG, PNG, WebP or TIFF, up to 40 MB. The file stays on this computer.
                    </span>
                    <input type="file" accept="image/*" className="visually-hidden"
                           onChange={(e) => { const f = e.target.files?.[0]; if (f) openFile(f); }} />
                  </label>
                </div>
              </div>
            </section>
            <section className="uses" aria-label="What TrustLens checks">
              <div className="use">
                <h2>Photos and deepfakes</h2>
                <p>Reads signed Content Credentials, compares the photo with the preview the camera stored inside it,
                  maps error levels, finds cloned areas, and asks a vision model what it sees.</p>
              </div>
              <div className="use">
                <h2>Notices and circulars</h2>
                <p>Checks the dates a notice claims against your exam schedule and academic calendar from VTOP, fetched
                  with cli-top.</p>
              </div>
              <div className="use">
                <h2>Event and hackathon posters</h2>
                <p>Looks for the official listing, and flags fees paid to personal UPI IDs, look-alike links and
                  copies of real events.</p>
              </div>
            </section>
            <section>
              <h2 style={{ marginBottom: "0.6rem" }}>Or try a demo</h2>
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
      {toast && <Toast message={toast.message} kind={toast.kind} onClose={() => setToast(null)} />}
    </div>
  );
}
