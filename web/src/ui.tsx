import type { ReactNode } from "react";
import type { Severity } from "./api";

type IconName = "open" | "camera" | "report" | "compare" | "trash" | "menu" | "close" | "grip" | "check" | "warn" | "link" | "lens"
  | "play" | "pause" | "stack" | "shield" | "download" | "prev" | "next" | "search" | "chat";

const PATHS: Record<IconName, ReactNode> = {
  open: <path d="M4 20h16M12 15V4m0 0L7.5 8.5M12 4l4.5 4.5" />,
  camera: <><path d="M4 8h3l2-3h6l2 3h3v11H4z" /><circle cx="12" cy="13" r="3.5" /></>,
  report: <><path d="M7 3h7l5 5v13H7z" /><path d="M14 3v5h5M10 13h6M10 17h6" /></>,
  compare: <><path d="M12 3v18" /><rect x="3" y="6" width="6.5" height="12" /><rect x="14.5" y="6" width="6.5" height="12" strokeDasharray="2 2" /></>,
  trash: <path d="M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13" />,
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  close: <path d="M6 6l12 12M18 6 6 18" />,
  grip: <path d="M10 8v8M14 8v8" />,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  warn: <><path d="M12 4 2.5 20h19z" /><path d="M12 10v4.5M12 17.5v.5" /></>,
  link: <path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1" />,
  lens: <><circle cx="10.5" cy="10.5" r="6" /><path d="M15 15l5.5 5.5" /></>,
  play: <path d="M8 5.5v13l10-6.5z" />,
  pause: <path d="M8.5 5.5v13M15.5 5.5v13" />,
  stack: <><rect x="4" y="9" width="16" height="11" /><path d="M6.5 6h11M9 3h6" /></>,
  shield: <><path d="M12 3 5 6v5.5c0 4.3 3 7.8 7 9.5 4-1.7 7-5.2 7-9.5V6z" /><path d="M9 12l2.2 2.2L15.5 10" /></>,
  download: <path d="M12 4v11m0 0-4.5-4.5M12 15l4.5-4.5M4 20h16" />,
  prev: <path d="M15 5l-7 7 7 7" />,
  next: <path d="M9 5l7 7-7 7" />,
  search: <><circle cx="10.5" cy="10.5" r="6" /><path d="M15 15l5.5 5.5M8 10.5h5" /></>,
  chat: <><path d="M4 5h16v11H9l-5 4z" /><path d="M8 9.5h8M8 12.5h5" /></>,
};

export function Icon({ name, title }: { name: IconName; title?: string }) {
  return (
    <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round"
         strokeLinejoin="round" aria-hidden={title ? undefined : true} role={title ? "img" : undefined}>
      {title && <title>{title}</title>}
      {PATHS[name]}
    </svg>
  );
}

/** Evidence-marker tent: the brand mark, also used to number marks on the image. */
export function BrandMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="6" fill="#F2C230" />
      <path d="M7 25 16 7l9 18z" fill="#14202B" />
      <path d="M13.4 20.5h5.2" stroke="#F2C230" strokeWidth="2.2" />
    </svg>
  );
}

const SEV_LABEL: Record<Severity, string> = { high: "Strong", medium: "Moderate", low: "Hint", info: "Note" };

export function Sev({ level }: { level: Severity }) {
  return <span className={`sev sev--${level}`}>{SEV_LABEL[level]}</span>;
}

export function Tent({ n, plain = false }: { n: number | string; plain?: boolean }) {
  return <span className={`tent${plain ? " tent--plain" : ""}`} aria-label={`Mark ${n}`}>{n}</span>;
}

export const fmtBytes = (n: number) =>
  n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`;

export const fmtTime = (t: number | string) => {
  const d = typeof t === "number" ? new Date(t * 1000) : new Date(t);
  return d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
};

export const shortHash = (h: string, n = 10) => `${h.slice(0, n)}…${h.slice(-4)}`;

export function Toast({ message, kind, onClose }: { message: string; kind: "error" | "info"; onClose: () => void }) {
  return (
    <div className={`toast toast--${kind}`} role={kind === "error" ? "alert" : "status"}>
      <span>{message}</span>
      <button onClick={onClose} aria-label="Dismiss"><Icon name="close" /></button>
    </div>
  );
}
