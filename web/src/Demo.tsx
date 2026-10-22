import { useEffect, useState } from "react";
import { Icon } from "./ui";

export interface DemoStep { sample: string; title: string; caption: string; tab?: string }

/** About 90 seconds: six cases, 15 seconds each. */
export const DEMO_STEPS: DemoStep[] = [
  { sample: "Edited_iphone_photo_demo.jpg", title: "An edited phone photo",
    caption: "Flowers were cloned over part of this iPhone photo. The camera's own stored preview still shows the original, and the clone map joins the copied areas." },
  { sample: "AI_student_05.jpg", title: "A realistic AI 'student'",
    caption: "Looks like a campus photo. Its Content Credentials, signed by Google, declare it AI-generated, so TrustLens says so with high confidence." },
  { sample: "Tp_D_CRN_S_N_nat00033_cha00086_11502.jpg", title: "A spliced photo from a research dataset",
    caption: "From the CASIA forgery dataset. Error levels light up the pasted child; red is the true edit from the dataset, so you can see the test is right." },
  { sample: "Video_ai_talking_head_demo.mp4", title: "A deepfake talking head",
    caption: "Animated from a single AI image. TrustLens samples 12 frames, finds the face in each, and sends a contact sheet and face close-ups to the AI review." },
  { sample: "Voice_note_edited_demo.wav", title: "An edited voice note",
    caption: "A sentence was cut out and the gap is perfect digital silence, which no microphone records. TrustLens marks the spot on the spectrogram." },
  { sample: "Screenshot_payment_demo.png", title: "A fake payment receipt",
    caption: "With the AI review on, TrustLens reads the receipt and code checks it: an 11-digit UPI reference, a weekday that doesn't match the date, two different amounts." },
];

export const STEP_SECONDS = 15;

interface Props {
  step: number;
  total: number;
  playing: boolean;
  preparing: { done: number; total: number } | null;
  onPrev: () => void;
  onNext: () => void;
  onToggle: () => void;
  onExit: () => void;
}

export function DemoBar({ step, total, playing, preparing, onPrev, onNext, onToggle, onExit }: Props) {
  const s = DEMO_STEPS[step];
  const [startedAt, setStartedAt] = useState(() => Date.now());
  useEffect(() => setStartedAt(Date.now()), [step, playing]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onExit();
      else if (e.key === "ArrowRight") onNext();
      else if (e.key === "ArrowLeft") onPrev();
      else if (e.key === " " && (e.target as HTMLElement)?.tagName !== "INPUT") { e.preventDefault(); onToggle(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onExit, onNext, onPrev, onToggle]);

  if (preparing) {
    return (
      <div className="demo-bar" role="status">
        <div className="demo-bar__text">
          <span className="demo-bar__step">Demo</span>
          <b>Preparing the demo cases ({preparing.done} of {preparing.total})</b>
          <p>Each one is analysed once; replays open instantly.</p>
        </div>
        <div className="demo-bar__controls">
          <button className="btn btn--quiet" onClick={onExit} aria-label="Exit demo"><Icon name="close" /></button>
        </div>
        <span className="demo-bar__progress" style={{ width: `${(preparing.done / Math.max(1, preparing.total)) * 100}%`, transition: "width 0.3s" }} />
      </div>
    );
  }
  return (
    <div className="demo-bar" role="region" aria-label="Demo">
      <div className="demo-bar__text" aria-live="polite">
        <span className="demo-bar__step">{step + 1} / {total}</span>
        <b>{s.title}</b>
        <p>{s.caption}</p>
      </div>
      <div className="demo-bar__controls">
        <button className="btn btn--quiet" onClick={onPrev} disabled={step === 0} aria-label="Previous case"><Icon name="prev" /></button>
        <button className="btn btn--quiet" onClick={onToggle} aria-label={playing ? "Pause" : "Play"}><Icon name={playing ? "pause" : "play"} /></button>
        <button className="btn btn--quiet" onClick={onNext} aria-label={step === total - 1 ? "Finish" : "Next case"}><Icon name="next" /></button>
        <button className="btn btn--quiet" onClick={onExit} aria-label="Exit demo"><Icon name="close" /></button>
      </div>
      <span key={`${step}-${playing}-${startedAt}`} className={`demo-bar__progress ${playing ? "is-playing" : ""}`}
            style={{ animationDuration: `${STEP_SECONDS}s` }} />
    </div>
  );
}
