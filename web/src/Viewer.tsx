import { useEffect, useMemo, useRef, useState } from "react";
import { api, type CaseResult, type Layers } from "./api";
import { defaultLayer, evidenceMarks, LAYER_LABEL, VERDICT_LAYERS } from "./evidence";
import { Icon } from "./ui";

/** Ruler ticks drawn along the frame, like the scale placed beside evidence in forensic photos. */
export function Ruler({ vertical = false }: { vertical?: boolean }) {
  const ticks = [];
  for (let i = 0; i <= 100; i += 2) {
    const len = i % 10 === 0 ? 10 : i % 5 === 0 ? 7 : 4;
    ticks.push(vertical
      ? <line key={i} x1={26 - len} x2={26} y1={`${i}%`} y2={`${i}%`} />
      : <line key={i} y1={26 - len} y2={26} x1={`${i}%`} x2={`${i}%`} />);
  }
  const blocks = [];
  for (let i = 0; i < 10; i += 1) {
    if (i % 2 === 0) blocks.push(vertical
      ? <rect key={i} x={0} width={6} y={`${i * 10}%`} height="10%" fill="#F2C230" />
      : <rect key={i} y={0} height={6} x={`${i * 10}%`} width="10%" fill="#F2C230" />);
  }
  return (
    <svg preserveAspectRatio="none" aria-hidden="true">
      <g>{blocks}</g>
      <g stroke="currentColor" strokeWidth="1">{ticks}</g>
    </svg>
  );
}

interface Props {
  result: CaseResult | null;
  layers: Layers | null;
  busyPreview: string | null;
  activeMark: number | null;
}

export function Viewer({ result, layers, busyPreview, activeMark }: Props) {
  const id = result?.case.id ?? "";
  const available = layers?.available ?? [];
  const [layer, setLayer] = useState("ela");
  const [pos, setPos] = useState(50);
  const [showMarks, setShowMarks] = useState(true);
  const [showGt, setShowGt] = useState(true);
  const [loupeOn, setLoupeOn] = useState(false);
  const [loupe, setLoupe] = useState<{ x: number; y: number; px: number; py: number } | null>(null);
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null);
  const frame = useRef<HTMLDivElement>(null);
  const bust = result?.comparison ? result.comparison.other_name : "";

  useEffect(() => {
    if (result && layers) setLayer(defaultLayer(result, layers.available));
    setPos(50);
  }, [id, layers]); // eslint-disable-line react-hooks/exhaustive-deps

  const marks = useMemo(() => (result ? evidenceMarks(result) : []), [result]);

  // full-resolution size of the displayed (orientation-corrected) image, for mark coordinates
  const full = useMemo(() => {
    if (!result || !dims) return null;
    const { width: w, height: h } = result.integrity;
    const sameOrientation = Math.abs(dims.w / dims.h - w / h) < Math.abs(dims.w / dims.h - h / w);
    return sameOrientation ? { w, h } : { w: h, h: w };
  }, [result, dims]);

  if (!result) {
    return (
      <div className="viewer" aria-busy={!!busyPreview}>
        <div className="frame">
        <div className="scale scale--top"><Ruler /></div>
        <div className="scale scale--left"><Ruler vertical /></div>
        <div className="scale-corner"><span /></div>
        <div className="stage">
          {busyPreview && <div className="stage__frame"><img src={busyPreview} alt="Evidence being analysed" /></div>}
          <div className="scan" />
          <div className="stage__busy" role="status">Analysing: hashes, metadata, pixel tests{" "}
            and AI review. Usually 5–20 seconds.</div>
        </div>
        </div>
      </div>
    );
  }

  const isInspection = layer in (layers?.inspection ?? {});
  const layerDef = VERDICT_LAYERS.find((l) => l.id === layer);
  const layerName = layerDef?.label ?? LAYER_LABEL[layer] ?? layer;
  const caption = layerDef?.caption ?? layers?.inspection[layer] ?? "";
  const original = api.image(id, "original");
  const overlay = api.image(id, layer, 2000, bust);
  const hasGt = available.includes("ground_truth");

  const onMove = (e: React.MouseEvent) => {
    if (!loupeOn || !frame.current) return;
    const r = frame.current.getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top;
    if (x < 0 || y < 0 || x > r.width || y > r.height) return setLoupe(null);
    setLoupe({ x, y, px: (x / r.width) * 100, py: (y / r.height) * 100 });
  };

  const verdictLayers = VERDICT_LAYERS.filter((l) => available.includes(l.id));

  return (
    <div className="viewer">
      <div className="frame">
      <div className="scale scale--top"><Ruler /></div>
      <div className="scale scale--left"><Ruler vertical /></div>
      <div className="scale-corner"><span /></div>

      <div className="stage" onMouseMove={onMove} onMouseLeave={() => setLoupe(null)}>
        <div className="stage__frame" ref={frame}>
          <img src={original} alt={`Evidence: ${result.case.name}`} draggable={false}
               onLoad={(e) => setDims({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })} />
          <img className="stage__layer" src={overlay} alt={`${layerName} layer`} draggable={false}
               style={{ clipPath: `inset(0 0 0 ${pos}%)` }} />
          {hasGt && showGt && (
            <div className="stage__layer" aria-label="Ground truth: the area that was actually edited"
                 style={{ background: "rgba(255, 70, 70, 0.5)", WebkitMaskImage: `url(${api.image(id, "ground_truth")})`,
                          maskImage: `url(${api.image(id, "ground_truth")})`, WebkitMaskSize: "100% 100%",
                          maskSize: "100% 100%", maskMode: "luminance" } as React.CSSProperties} />
          )}
          {showMarks && full && marks.length > 0 && (
            <svg className="marks" viewBox={`0 0 ${full.w} ${full.h}`} preserveAspectRatio="none" aria-hidden="true">
              {marks.map((m) => {
                const [x0, y0, x1, y1] = m.box;
                return (
                  <g key={m.n} opacity={activeMark === null || activeMark === m.n ? 1 : 0.35}>
                    <rect x={x0} y={y0} width={x1 - x0} height={y1 - y0} className={m.alt ? "alt" : undefined} />
                  </g>
                );
              })}
            </svg>
          )}
          {showMarks && full && marks.map((m) => (
            <span key={m.n} className="tent" style={{
              position: "absolute", left: `${(m.box[0] / full.w) * 100}%`, top: `${(m.box[1] / full.h) * 100}%`,
              transform: "translate(-30%, -105%)", opacity: activeMark === null || activeMark === m.n ? 1 : 0.4,
            }} aria-hidden="true">{m.n}</span>
          ))}
          <input className="wipe-input" type="range" min={0} max={100} value={pos}
                 aria-label={`Drag to compare the photo with the ${layerName} layer`}
                 onChange={(e) => setPos(Number(e.target.value))} />
          <div className="wipe" style={{ left: `${pos}%` }}>
            <div className="wipe__grip"><Icon name="grip" /></div>
          </div>
          <span className="wipe__label" style={{ left: 8 }}>Photo</span>
          <span className="wipe__label" style={{ right: 8 }}>{layerName}</span>
          {loupeOn && loupe && (
            <div className="loupe" style={{
              left: loupe.x, top: loupe.y,
              backgroundImage: `url(${loupe.px > pos ? overlay : original})`,
              backgroundSize: `${(frame.current?.clientWidth ?? 0) * 3}px ${(frame.current?.clientHeight ?? 0) * 3}px`,
              backgroundPosition: `${loupe.px}% ${loupe.py}%`,
            }} />
          )}
        </div>
      </div>
      </div>

      <div className="viewer__bar">
        <div className="layer-picker" role="group" aria-label="Analysis layer">
          {verdictLayers.map((l) => (
            <button key={l.id} className="layer-btn" aria-pressed={layer === l.id} onClick={() => setLayer(l.id)}>
              {l.label}
            </button>
          ))}
          <select aria-label="Inspection layers" value={isInspection ? layer : ""}
                  onChange={(e) => e.target.value && setLayer(e.target.value)}>
            <option value="">More layers…</option>
            {Object.keys(layers?.inspection ?? {}).map((k) => <option key={k} value={k}>{LAYER_LABEL[k] ?? k}</option>)}
          </select>
        </div>
        <div className="viewer__tools">
          {marks.length > 0 && (
            <label className="toggle"><input type="checkbox" checked={showMarks} onChange={(e) => setShowMarks(e.target.checked)} /> Marks</label>
          )}
          {hasGt && (
            <label className="toggle"><input type="checkbox" checked={showGt} onChange={(e) => setShowGt(e.target.checked)} /> Ground truth</label>
          )}
          <label className="toggle"><input type="checkbox" checked={loupeOn} onChange={(e) => setLoupeOn(e.target.checked)} /> Magnifier</label>
        </div>
      </div>
      <p className="layer-caption">
        {caption}
        {hasGt && showGt && " Red: the area the dataset says was actually edited."}
      </p>
    </div>
  );
}
