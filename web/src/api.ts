// Typed client for server.py. Types describe only the fields the interface reads.

export type Severity = "high" | "medium" | "low" | "info";
export type Verdict = "fake" | "likely_fake" | "inconclusive" | "no_evidence";

export interface Signal {
  check: string;
  severity: Severity;
  detail: string;
  points_to: "ai" | "edited" | "none";
}

export interface VisualFinding {
  finding: string;
  location: string;
  evidence: string;
  severity: Exclude<Severity, "info">;
}

export interface Region {
  box: [number, number, number, number];
  coverage?: number;
  strength?: number;
}

export interface C2pa {
  source_types: string[];
  ingredients: string[];
  actions: string[];
  generator: string;
  signed_by: string[];
  watermark: string;
  verification?: { status: string; state?: string; failures?: string[]; detail?: string; issuer?: string; signed_at?: string };
}

export interface Segment { marker: string; offset: number; length: number }

export interface Structure {
  segments: Segment[];
  subsampling: string;
  progressive: boolean;
  quant_tables: Record<string, number[]>;
  standard_tables: boolean | null;
  encoder_hint: string | null;
}

export interface ToolStats {
  status?: string;
  detail?: string;
  experimental?: boolean;
  would_flag?: boolean;
  [key: string]: unknown;
}

export interface Advanced {
  ghost?: ToolStats & { region?: Region | null; image_best_quality?: number; region_quality?: number };
  copy_move?: ToolStats & { regions?: number[][]; inliers?: number; keypoints?: number; matches?: number };
  grid?: ToolStats & { offset?: number[]; strength?: number[] };
  median?: ToolStats & { equal_neighbour_ratio?: number };
  contrast?: ToolStats & { histogram_gaps?: number };
  structure?: Structure | null;
}

export interface NoticeClaim {
  type: string; course: string; date: string; statement: string;
  status: "confirmed" | "contradicted" | "not_checked"; official: string;
}

export interface OfficialCheck {
  overall: "contradicted" | "confirmed" | "not_verifiable";
  summary: string;
  claims: NoticeClaim[];
  data_source: Record<string, string>;
  vtop_errors: Record<string, string>;
  notice: { title: string; issuer: string; notice_date: string };
}

export interface EventFlag { flag: string; severity: Severity; detail: string }

export interface EventCheck {
  verdict: "verified" | "unverified" | "likely_scam";
  verdict_label: string;
  risk_score: number;
  summary: string;
  reasons: string[];
  red_flags: EventFlag[];
  links: { url: string; domain: string; verdict: string; findings: string[] }[];
  event: { event_name: string; organizer: string; dates: string; fee: string; event_type: string;
           payment_details: string[]; registration_links: string[]; contacts: string[] };
  web: { status: string; method?: string; found?: string; official_urls?: string[]; summary?: string; detail?: string };
  vtop: { status: string; source?: string; events_listed?: number; detail?: string; match?: Record<string, string> | null };
}

export interface Comparison {
  verdict: "same" | "edited" | "different";
  summary: string;
  hash_distance: Record<string, number>;
  changed_share: number;
  changed_region: number[] | null;
  other_name: string;
}

export type MediaKind = "image" | "video" | "audio";

export interface CaseMeta {
  id: string; sha256: string; name: string; source: "sample" | "upload" | "batch"; created: number; use_llm: boolean;
  media_kind?: MediaKind;
}

export interface Face {
  n: number; box: [number, number, number, number]; share_of_image: number;
  noise_vs_surroundings?: number; detail_vs_surroundings?: number; closeup: boolean;
  assessment?: "no visible sign" | "suspicious" | "likely manipulated"; evidence?: string;
}
export interface Faces { status: string; count?: number; faces: Face[]; detail?: string }

export interface TimelineFrame {
  label: string; t: number; index: number; faces: number[][]; flicker: number | null; ela_max_z: number;
  ai_score: number | null; ai_note: string; on_sheet: boolean; key: boolean;
}

export interface Speech {
  status: string; detail?: string; transcript?: string; language?: string; summary?: string; claimed_speaker?: string;
  requests?: string[]; scam_risk?: "low" | "medium" | "high"; scam_cues?: { cue: string; quote: string }[];
  speech_notes?: string;
}

export interface AudioTrack {
  status: string; detail?: string;
  measurements?: { duration: number; sample_rate: number; speech_share: number; digital_silence: { start: number; end: number }[];
                   background_jumps: { at: number; change_db: number }[]; bandwidth: { content_up_to_hz?: number; nyquist_hz?: number } };
  speech?: Speech;
}

export interface VideoInfo {
  duration: number; fps: number; frames_total: number; codec: string; container: string; tags: Record<string, string>;
  ai_tools_named: string[]; timeline: TimelineFrame[]; key_frame: string;
  face_findings: { face: string; assessment: string; evidence: string }[]; audio: AudioTrack | null;
}

export interface AudioInfo extends AudioTrack {
  tags: Record<string, string>; ai_tools_named: string[]; codec: string;
  marks: { box: number[]; title: string; detail: string }[];
}

export interface ScreenshotCheck {
  kind: string; app: string; overall: "contradicted" | "suspicious" | "no_contradiction" | "not_checkable";
  checks: { check: string; status: "ok" | "contradicted" | "unverified"; detail: string }[];
  visual_anomalies: { anomaly: string; where: string; severity: Exclude<Severity, "info"> }[];
}

export interface ReversePage {
  url: string; title: string; date: string; domain?: string; status: "match" | "unconfirmed" | "unreachable";
  best_distance: number | null; image_url: string;
}
export interface ReverseSearch {
  status: string; verdict: "found" | "found_earlier" | "not_found"; summary: string; method: string; errors: string[];
  description: { description: string; queries: string[]; visible_text: string; claimed_context: string };
  matches: ReversePage[]; unconfirmed: ReversePage[]; checked: number;
}

export interface CaseResult {
  case: CaseMeta;
  media_kind: MediaKind;
  headline: string;
  summary: { en: string[]; hi: string[] };
  faces?: Faces;
  video?: VideoInfo;
  audio?: AudioInfo;
  screenshot_check?: ScreenshotCheck;
  reverse_search?: ReverseSearch;
  verdict: Verdict;
  verdict_label: string;
  manipulation_score: number;
  fake_type: string;
  fake_type_label: string;
  confidence: "low" | "medium" | "high";
  image_kind: string;
  explanation: string;
  visual_findings: VisualFinding[];
  forensic_signals: Signal[];
  rule_notes: string[];
  heatmap_reading: string;
  limitations: string[];
  recommended_actions: string[];
  detector: { status: string; model?: string; fake_probability?: number; detail?: string };
  integrity: { filename: string; sha256: string; md5: string; size_bytes: number; format: string; width: number;
               height: number; mode: string; analysed_at: string; perceptual?: Record<string, string> };
  metadata: { exif: Record<string, string>; text_chunks: Record<string, string>; xmp_present: boolean;
              c2pa_present: boolean; c2pa?: C2pa | null };
  jpeg_quality: number | null;
  ela: { region: Region | null; mean_error: number; max_z: number };
  noise: { region: Region | null };
  gps?: { lat: number; lon: number; map: string } | null;
  thumbnail?: { thumbnail_size: number[]; changed_region?: number[]; max_local_difference?: number;
                median_difference?: number; note?: string } | null;
  advanced?: Advanced;
  llm_used: boolean;
  error: string | null;
  tool_version: string;
  official_check?: OfficialCheck;
  event_check?: EventCheck;
  comparison?: Comparison;
}

export interface CaseSummary extends CaseMeta {
  verdict: Verdict; verdict_label: string; score: number; fake_type_label: string; headline: string; llm_used: boolean;
}

export interface Sample { name: string; group: string; label: string; kind: MediaKind; ground_truth: boolean }

export interface BatchItem {
  n: number; file: string; kind: MediaKind | "unknown"; size: number; status: "queued" | "running" | "done" | "error";
  sender?: string; sent?: string; case_id?: string; verdict?: Verdict; verdict_label?: string; score?: number;
  fake_type_label?: string; headline?: string; media_kind?: MediaKind; error?: string;
}
export interface Batch {
  id: string; name: string; created: number; total: number; items: BatchItem[]; skipped: string[]; from_chat: boolean;
}
export interface BatchSummary { id: string; name: string; created: number; total: number; done: number }

export interface VerifyResult {
  valid: boolean; reason: string;
  payload?: { case: string; file: string; sha256: string; media: string; verdict: string; score: number; type: string;
              ai_review: boolean; custody_head: string; tool: string; issued: string; key: string; alg: string };
  case_now?: { exists: boolean; verdict?: string; score?: number; same_file?: boolean; changed_since?: boolean };
}

export interface CustodyEntry {
  seq: number; time: string; action: string; file_sha256: string; details: Record<string, unknown>;
  prev_hash: string; entry_hash: string;
}
export interface Chain { ok: boolean; entries: number; head: string | null; problem: string }

export interface Status {
  llm: { provider: string; configured: boolean; model: string };
  opencv: boolean;
  faces: boolean;
  ffmpeg: boolean;
  pdf: boolean;
  signing: string;
  c2pa_verification: boolean;
  vtop: { cli_top_found: boolean; snapshots: string[] };
  custody: Chain;
  version: string;
}

export interface Layers { available: string[]; inspection: Record<string, string>; faces: string[]; frames: string[] }

export class ApiError extends Error {}

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    throw new ApiError("Can't reach the TrustLens server. Check that `python server.py` is still running.");
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError((body as { error?: string }).error ?? `The server answered ${res.status}.`);
  return body as T;
}

const json = (data: unknown): RequestInit => ({
  method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(data),
});
const file = (f: File): RequestInit => {
  const fd = new FormData();
  fd.append("file", f);
  return { method: "POST", body: fd };
};

export const api = {
  status: () => call<Status>("/api/status"),
  samples: () => call<Sample[]>("/api/samples"),
  cases: () => call<CaseSummary[]>("/api/cases"),
  getCase: (id: string) => call<CaseResult>(`/api/cases/${id}`),
  openSample: (name: string, ai: boolean, reuse = false) =>
    call<CaseResult>(`/api/cases?ai=${ai ? 1 : 0}`, json({ sample: name, reuse })),
  upload: (f: File, ai: boolean) => call<CaseResult>(`/api/cases?ai=${ai ? 1 : 0}`, file(f)),
  reanalyse: (id: string) => call<CaseResult>(`/api/cases/${id}/reanalyse`, { method: "POST" }),
  remove: (id: string) => call<{ removed: string }>(`/api/cases/${id}`, { method: "DELETE" }),
  layers: (id: string) => call<Layers>(`/api/cases/${id}/layers`),
  histogram: (id: string) => call<Record<"r" | "g" | "b" | "l", number[]>>(`/api/cases/${id}/histogram`),
  noticeCheck: (id: string, live: boolean) => call<CaseResult>(`/api/cases/${id}/notice-check`, json({ live })),
  eventCheck: (id: string, live: boolean) => call<CaseResult>(`/api/cases/${id}/event-check`, json({ live })),
  compare: (id: string, f: File) => call<Comparison>(`/api/cases/${id}/compare`, file(f)),
  verifyFile: (id: string, f: File) => call<{ match: boolean; sha256: string }>(`/api/cases/${id}/verify-file`, file(f)),
  custody: (sha?: string) => call<{ chain: Chain; entries: CustodyEntry[] }>(`/api/custody${sha ? `?sha=${sha}` : ""}`),
  image: (id: string, kind: string, w = 2000, bust = "") => `/api/cases/${id}/image/${kind}?w=${w}${bust ? `&v=${bust}` : ""}`,
  sampleThumb: (name: string) => `/api/samples/${encodeURIComponent(name)}?w=160`,
  report: (id: string, download = false) => `/api/cases/${id}/report${download ? "?download=1" : ""}`,
  reportPdf: (id: string, download = false) => `/api/cases/${id}/report.pdf${download ? "?download=1" : ""}`,
  media: (id: string) => `/api/cases/${id}/media`,
  screenshotCheck: (id: string) => call<CaseResult>(`/api/cases/${id}/screenshot-check`, { method: "POST" }),
  reverseSearch: (id: string) => call<CaseResult>(`/api/cases/${id}/reverse-search`, { method: "POST" }),
  verifyToken: (token: string) => call<VerifyResult>("/api/verify-report", json({ token })),
  verifyPdf: (f: File) => call<VerifyResult>("/api/verify-report", file(f)),
  reportKey: () => call<{ key_id: string; algorithm: string; public_key_pem: string }>("/api/report-key"),
  batches: () => call<BatchSummary[]>("/api/batches"),
  batch: (id: string) => call<Batch>(`/api/batches/${id}`),
  createBatch: (files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return call<Batch>("/api/batches", { method: "POST", body: fd });
  },
};

export const ACCEPT = "image/*,video/*,audio/*,.opus,.ogg,.m4a,.amr,.zip";
export const isMedia = (f: File) =>
  /^(image|video|audio)\//.test(f.type) || /\.(opus|ogg|m4a|amr|heic|mkv|3gp)$/i.test(f.name);
