import type { CheckStep } from "./api";

/** The circular check, step by step: what was read, what VTOP returned, how each claim was compared. */
export function Trace({ steps, compact = false }: { steps: CheckStep[]; compact?: boolean }) {
  return (
    <ol className={`trace ${compact ? "trace--compact" : ""}`} aria-label="How this circular was checked">
      {steps.map((s, i) => (
        <li key={i} className={`trace__step trace__step--${s.tone}`} style={{ animationDelay: `${i * 180}ms` }}>
          <span className="trace__mark" aria-hidden="true">{s.tone === "bad" ? "✕" : s.tone === "good" ? "✓" : s.tone === "warn" ? "!" : i + 1}</span>
          <div>
            <p className="trace__title"><b>{s.title}</b>{s.command && <code>{s.command}</code>}</p>
            <p className="trace__detail">{s.detail}</p>
            {!compact && s.lines.length > 0 && <ul>{s.lines.map((l, j) => <li key={j}>{l}</li>)}</ul>}
          </div>
        </li>
      ))}
    </ol>
  );
}
