import { useEffect, useState } from "react";
import { Icon } from "./ui";

interface Info { on: boolean; url?: string; ip?: string; port?: number; how?: string }

/** QR code that opens TrustLens on a phone on the same Wi-Fi (server started with --lan). */
export function PhoneDialog({ onClose }: { onClose: () => void }) {
  const [info, setInfo] = useState<Info | null>(null);
  useEffect(() => {
    fetch("/api/phone").then((r) => r.json()).then(setInfo).catch(() => setInfo({ on: false }));
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal" role="dialog" aria-modal="true" aria-labelledby="phone-title" onClick={onClose}>
      <div className="modal__box" onClick={(e) => e.stopPropagation()}>
        <div className="modal__head">
          <h2 id="phone-title">Use TrustLens on a phone</h2>
          <button className="btn btn--quiet" onClick={onClose} aria-label="Close"><Icon name="close" /></button>
        </div>
        {!info && <p className="muted">Checking…</p>}
        {info?.on && (
          <div className="phone">
            <img src={`/api/phone/qr.png?t=${Date.now()}`} alt="QR code that opens TrustLens on a phone" width={260} height={260} />
            <div>
              <ol>
                <li>Connect the phone to the same Wi-Fi as this computer, or to this computer's hotspot.</li>
                <li>Scan the code with the phone camera.</li>
                <li>The phone opens a simple “Check a file” page: pick a photo, video or voice note and the verdict appears on the phone (and in this locker).</li>
              </ol>
              <p className="muted" style={{ fontSize: 12 }}>The link carries a secret code, so only people who scan it can use TrustLens.
                Address: <span className="mono">{info.ip}:{info.port}</span></p>
            </div>
          </div>
        )}
        {info && !info.on && (
          <div className="callout callout--warn">
            <p><b>Phone access is off.</b> Stop TrustLens (Ctrl+C) and start it with <span className="mono">python server.py --lan</span>,
              then press this button again. If Windows asks whether Python may use networks, choose <b>Allow</b>.</p>
          </div>
        )}
      </div>
    </div>
  );
}
