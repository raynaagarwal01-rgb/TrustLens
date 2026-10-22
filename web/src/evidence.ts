import type { CaseResult } from "./api";

export interface Mark {
  n: number;
  box: number[];
  title: string;
  detail: string;
  alt?: boolean; // secondary style, e.g. the source side of a copy-move pair
}

/** Copy-move regions worth pointing at: a low-severity match (e.g. repeated letters in a document) isn't. */
function cloneRegions(r: CaseResult): number[][] | null {
  const cm = r.advanced?.copy_move?.regions;
  const sig = r.forensic_signals.find((s) => s.check === "Cloned area (copy-move)");
  return cm && cm.length === 2 && sig && sig.severity !== "low" && sig.severity !== "info" ? cm : null;
}

/** Regions on the image that tests point at, numbered like evidence markers. */
export function evidenceMarks(r: CaseResult): Mark[] {
  const marks: Omit<Mark, "n">[] = [];
  const th = r.thumbnail?.changed_region;
  if (th) marks.push({ box: th, title: "Differs from the camera's stored preview", detail: "Embedded thumbnail" });
  const cm = cloneRegions(r);
  if (cm) {
    marks.push({ box: cm[0], title: "Matching area A", detail: "Copy-move: A and B are copies of each other" });
    marks.push({ box: cm[1], title: "Matching area B", detail: "Copy-move: which one is the original can't be told", alt: true });
  }
  const cmp = r.comparison?.changed_region;
  if (cmp && r.comparison?.verdict === "edited") marks.push({ box: cmp, title: "Differs from the reference image", detail: "Comparison" });
  const ela = r.ela?.region?.box;
  if (ela) marks.push({ box: ela, title: "Reacts differently to re-compression", detail: "Error-level analysis" });
  const gh = r.advanced?.ghost?.region?.box;
  if (gh) marks.push({ box: gh, title: `Matches an earlier save at quality ${r.advanced?.ghost?.region_quality ?? "lower"}`, detail: "JPEG ghost" });
  return marks.map((m, i) => ({ ...m, n: i + 1 }));
}

export interface LayerDef { id: string; label: string; caption: string; experimental?: boolean }

export const VERDICT_LAYERS: LayerDef[] = [
  { id: "ela", label: "Error levels",
    caption: "Error-level analysis: bright areas react strongly to re-compression. Edges are naturally bright; look for one object or text field that differs from similar surroundings." },
  { id: "ghost", label: "JPEG ghost",
    caption: "JPEG ghost: bright where a lower save quality fits better than for the rest of the image, typical of content pasted from a lower-quality image." },
  { id: "copy_move", label: "Clone map",
    caption: "Copy-move: yellow lines join points that match exactly between two areas. One area was copied from the other; the test can't tell which." },
  { id: "compare", label: "Difference from reference",
    caption: "Comparison with the reference image you supplied: bright where the two differ." },
  { id: "thumbnail", label: "Camera preview",
    caption: "The small preview the camera stored inside the file, stretched to full size. Wipe across: anything present in the photo but not in the preview was changed later." },
  { id: "noise", label: "Noise map", experimental: true,
    caption: "Noise consistency (experimental): bright where noise differs from the rest. Smooth areas such as sky often light up too." },
];

export const LAYER_LABEL: Record<string, string> = {
  gradient: "Luminance gradient", echo: "Edge echo", frequency: "Frequency split", pca: "Colour PCA",
  minmax: "Min/max deviation", bitplane: "Bit plane", noise_residual: "Noise residual",
};

export function defaultLayer(r: CaseResult, available: string[]): string {
  if (r.comparison && available.includes("compare")) return "compare";
  if (cloneRegions(r) && available.includes("copy_move")) return "copy_move";
  if (r.thumbnail?.changed_region && available.includes("thumbnail")) return "thumbnail";
  if (r.advanced?.ghost?.region && available.includes("ghost")) return "ghost";
  return "ela";
}

export const verdictTone = (v: string) =>
  v === "fake" || v === "likely_fake" || v === "likely_scam" ? "bad" : v === "inconclusive" || v === "unverified" ? "warn" : "good";
