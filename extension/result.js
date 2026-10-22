// Result tab: sends the job to TrustLens on this computer and shows the answer.

const DEFAULT_SERVER = "http://127.0.0.1:8000";
const $ = (id) => document.getElementById(id);

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : String(kid));
  return el;
}

const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return ""; } };
const pct = (p) => `${Math.min(99, Math.round(p * 100))}%`;

async function server() {
  const { server } = await chrome.storage.sync.get("server");
  return (server || DEFAULT_SERVER).replace(/\/+$/, "");
}

function busy(text) {
  $("out").replaceChildren(h("div", { class: "busy", role: "status" }, h("b", {}, text), h("div", { class: "bar" }),
    h("p", { class: "muted" }, "TrustLens is working on your computer: nothing is sent anywhere except the AI review you set up.")));
}

function problem(title, ...lines) {
  $("out").replaceChildren(h("div", { class: "problem" }, h("h1", {}, title), ...lines.map((l) => h("p", {}, l)),
    h("div", { class: "actions" }, h("button", { class: "btn btn--primary", onclick: () => location.reload() }, "Try again"))));
}

async function call(base, path, init) {
  let res;
  try {
    res = await fetch(base + path, init);
  } catch {
    throw Object.assign(new Error("offline"), { offline: true });
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `TrustLens answered ${res.status}.`);
  return data;
}

function offline(base) {
  problem("TrustLens isn't running",
    h("span", {}, "Start it on this computer: open a terminal in the TrustLens folder and run ", h("code", {}, "python server.py"), "."),
    h("span", { class: "muted" }, `Looking for it at ${base}. Change the address in the extension's popup if you use another port.`));
}

// ---------------------------------------------------------------------------- images and videos

async function fileFor(job) {
  if (job.dataUrl) {
    const blob = await (await fetch(job.dataUrl)).blob();
    return new File([blob], `${job.kind}-from-${host(job.pageUrl) || "page"}.${(blob.type.split("/")[1] || "jpg").split(";")[0]}`, { type: blob.type });
  }
  if (job.grabError === "too_big") throw new Error("This file is larger than 6 MB inside the page. Download it and open it in TrustLens instead.");
  if (job.srcUrl.startsWith("blob:")) throw new Error("This page keeps the file in memory where the extension can't reach it. Download it and open it in TrustLens instead.");
  let res;
  try {
    res = await fetch(job.srcUrl, { credentials: "include" });
  } catch {
    throw new Error("Couldn't download the file from the page. Download it yourself and open it in TrustLens.");
  }
  if (!res.ok) throw new Error(`The website refused the download (${res.status}). Download it yourself and open it in TrustLens.`);
  const blob = await res.blob();
  let name = decodeURIComponent(new URL(job.srcUrl).pathname.split("/").pop() || "") || `${job.kind}-from-${host(job.pageUrl)}`;
  if (!/\.[a-z0-9]{2,4}$/i.test(name)) name += `.${(blob.type.split("/")[1] || (job.kind === "video" ? "mp4" : "jpg")).split(";")[0]}`;
  return new File([blob], name.slice(0, 80), { type: blob.type });
}

const caseTone = (r) => (r.verdict === "fake" || r.verdict === "likely_fake" ? "bad"
  : r.verdict === "inconclusive" || !r.llm_used || r.media_kind !== "image" ? "warn" : "good");

function caseView(r, base) {
  const tone = caseTone(r);
  const reasons = [...r.rule_notes,
    ...r.forensic_signals.filter((s) => s.points_to !== "none" && (s.severity === "high" || s.severity === "medium")
      && !r.rule_notes.some((n) => s.detail.startsWith(n))).map((s) => `${s.check}: ${s.detail}`),
    ...r.visual_findings.filter((f) => f.severity !== "low").map((f) => `${f.finding[0].toUpperCase()}${f.finding.slice(1)} (${f.location}).`)]
    .filter((x, i, a) => a.indexOf(x) === i).slice(0, 4);
  let lang = "en";
  const list = h("ol", { lang });
  const fill = () => list.replaceChildren(...r.summary[lang].map((l) => h("li", {}, l)));
  fill();
  const seg = h("div", { class: "seg", role: "group", "aria-label": "Language" });
  for (const [code, label] of [["en", "English"], ["hi", "हिंदी"]]) {
    seg.append(h("button", { "aria-pressed": String(code === lang), lang: code, onclick: (e) => {
      lang = code; list.lang = code; seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === e.currentTarget))); fill();
    } }, label));
  }
  const fs = r.face_swap;
  const swap = fs && fs.available && h("section", {},
    h("h2", {}, `Face-swap detector: ${pct(fs.score ?? 0)} ${(fs.score ?? 0) > 0.8 ? "swapped face" : (fs.score ?? 0) >= 0.5 ? "possible swap" : "not flagged"}`),
    h("p", { class: "muted" }, "EfficientNet-B7 that won Facebook's Deepfake Detection Challenge. It catches face swaps; a low score doesn't clear AI-generated faces."),
    fs.frames && fs.frames.length > 1 && h("div", { class: "swapbars", role: "img", "aria-label": fs.frames.map((f) => `${f.label} ${pct(f.p)}`).join(", ") },
      fs.frames.map((f) => h("i", { class: f.p > 0.8 ? "bad" : f.p >= 0.5 ? "warn" : "", style: `height:${Math.max(4, f.p * 100)}%`, title: `${f.label}: ${pct(f.p)}` }))));
  return [
    h("div", { class: `verdict verdict--${tone}` }, h("h1", {}, r.headline || r.verdict_label),
      h("p", {}, "Score ", h("b", {}, String(r.manipulation_score)), "/100, confidence ", h("b", {}, r.confidence),
        r.fake_type && r.fake_type !== "none" && r.fake_type !== "unknown" ? `, ${r.fake_type_label.toLowerCase()}` : "")),
    h("section", {}, seg, h("h2", {}, "In short"), list),
    reasons.length > 0 && h("section", {}, h("h2", {}, "Why"), h("ul", {}, reasons.map((x) => h("li", {}, x)))),
    swap,
    h("div", { class: "actions" },
      h("a", { class: "btn btn--primary", href: `${base}/#/case/${r.case.id}`, target: "_blank" }, "Open all the evidence"),
      h("a", { class: "btn", href: `${base}/api/cases/${r.case.id}/report.pdf?download=1` }, "Signed PDF report")),
    !r.llm_used && h("p", { class: "muted" }, "The AI review didn't run for this check, so the result rests on forensic tests only."),
  ];
}

async function checkMedia(job, base) {
  const thumb = job.kind === "video" ? h("video", { src: job.dataUrl || `${job.srcUrl}#t=0.5`, muted: true, preload: "metadata" })
    : h("img", { src: job.dataUrl || job.srcUrl, alt: "" });
  $("subject").replaceChildren(thumb, h("div", { class: "from" }, h("b", {}, job.kind === "video" ? "Video" : "Image"),
    `From ${host(job.pageUrl) || "this page"}`, h("br"), h("span", {}, (job.srcUrl || "").slice(0, 140))));
  busy(job.kind === "video" ? "Checking the video. Up to a minute." : "Checking the image. Usually 5–20 seconds.");
  let file;
  try {
    file = await fileFor(job);
  } catch (e) {
    return problem("Couldn't get the file", e.message);
  }
  const form = new FormData();
  form.append("file", file);
  const r = await call(base, "/api/cases?ai=1", { method: "POST", body: form });
  $("out").replaceChildren(...caseView(r, base).filter(Boolean));
}

// ---------------------------------------------------------------------------- text and pages

const TEXT_VERDICT = {
  false: ["False", "bad"], misleading: ["Misleading", "bad"], unverified: ["Unverified: don't forward yet", "warn"],
  likely_true: ["Likely true", "good"], true: ["True", "good"],
};
const CLAIM_TAG = {
  contradicted: ["Contradicted", "bad"], supported: ["Supported", "good"], partly_true: ["Partly true", "warn"], no_evidence: ["No evidence", "warn"],
};

function textView(r) {
  const [label, tone] = TEXT_VERDICT[r.verdict] || ["Unverified", "warn"];
  const s = r.credibility_score;
  const out = [
    h("div", { class: `verdict verdict--${tone}` }, h("h1", {}, label),
      h("p", {}, "Credibility ", h("b", {}, String(s)), "/100, confidence ", h("b", {}, r.confidence)),
      h("div", { class: "meter", "aria-hidden": "true" }, h("div", { class: "meter__track" }, h("span", { class: "meter__mark", style: `left:calc(${s}% - 1px)` })))),
  ];
  if (r.explanation) out.push(h("section", {}, h("h2", {}, "In short"), h("p", { style: "margin:0" }, r.explanation)));
  const why = [...(r.evidence_notes || [])];
  if (r.official_check && ["contradicted", "confirmed"].includes(r.official_check.status) && r.official_check.detail)
    why.unshift(`VTOP records: ${r.official_check.detail}`);
  if (why.length) out.push(h("section", {}, h("h2", {}, "Why"), h("ul", {}, why.map((x) => h("li", {}, x)))));
  if (r.claims?.length) {
    out.push(h("section", {}, h("h2", {}, "Each claim"), r.claims.map((c) => {
      const [t, tt] = CLAIM_TAG[c.status] || CLAIM_TAG.no_evidence;
      return h("div", { class: "claim" }, h("span", { class: `tag tag--${tt}` }, t), h("p", {}, c.claim, c.evidence && h("span", { class: "muted" }, c.evidence)));
    })));
  }
  if (r.fact_checks?.length) {
    out.push(h("section", {}, h("h2", {}, "Published fact-checks"), h("ul", {}, r.fact_checks.slice(0, 4).map((f) =>
      h("li", {}, h("b", {}, f.publisher), ` rated it “${f.rating}”: `, f.url ? h("a", { href: f.url, target: "_blank", rel: "noreferrer" }, f.claim.slice(0, 120)) : f.claim.slice(0, 120))))));
  }
  const tactics = r.manipulation_tactics?.length ? r.manipulation_tactics : (r.language_signals || []).map((x) => x.signal);
  if (tactics.length) out.push(h("section", {}, h("h2", {}, "Warning signs in the wording"), h("ul", {}, tactics.map((x) => h("li", {}, x)))));
  if (r.coverage?.length) {
    out.push(h("section", {}, h("h2", {}, "What the news says"), h("ul", {}, r.coverage.slice(0, 5).map((n) =>
      h("li", {}, h("a", { href: n.link, target: "_blank", rel: "noreferrer" }, n.title), h("span", { class: "muted" }, ` ${n.publisher}${n.tier === "reputable" ? ", reputable outlet" : n.tier === "fact_checker" ? ", fact-checker" : ""}`)))),
      h("p", { class: "muted", style: "margin:0.5rem 0 0" }, `${r.reputable_sources} reputable outlet${r.reputable_sources === 1 ? "" : "s"} covered this topic. Coverage of a topic isn't proof of the claim.`)));
  } else {
    out.push(h("section", {}, h("h2", {}, "What the news says"), h("p", { class: "muted", style: "margin:0" }, "No news coverage found. For a big claim, that alone is a warning sign.")));
  }
  if (r.what_to_do?.length) out.push(h("section", {}, h("h2", {}, "What to do"), h("ul", {}, r.what_to_do.map((x) => h("li", {}, x)))));
  const notes = [];
  if (r.checked_vtop) notes.push("Campus claim: also compared with your VTOP records (exam schedule, calendar, holidays).");
  if (!r.llm_used) notes.push("The AI review didn't run, so this is a quick check from wording, source and news coverage only.");
  if (notes.length) out.push(h("p", { class: "muted" }, notes.join(" ")));
  return out;
}

async function checkText(job, base) {
  const text = (job.text || "").trim();
  $("subject").replaceChildren(h("div", { class: "from", style: "grid-column:1/-1" },
    h("b", {}, job.kind === "page" ? (job.pageTitle || "This page") : "Selected text"),
    job.pageUrl ? `From ${host(job.pageUrl)}` : "Pasted message"), h("blockquote", {}, text.slice(0, 1200) + (text.length > 1200 ? "…" : "")));
  if (text.length < 12) return problem("Nothing to check", "Select at least a sentence of text, then right-click it again.");
  busy("Fact-checking: reading the claims, searching the news and published fact-checks. Usually 10–20 seconds.");
  const r = await call(base, "/api/check-text", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, url: job.pageUrl }) });
  $("out").replaceChildren(...textView(r).filter(Boolean));
}

// ---------------------------------------------------------------------------- start

(async () => {
  const base = await server();
  $("open-app").href = base + "/";
  const id = location.hash.slice(1);
  const job = id && (await chrome.storage.session.get(id))[id];
  if (!job) return problem("This check has expired", "Right-click the image or text again to start a new check.");
  $("what").textContent = { image: "Image check", video: "Video check", text: "Fact-check", page: "Page fact-check" }[job.kind] || "Check";
  document.title = `TrustLens: ${$("what").textContent}`;
  try {
    if (job.kind === "image" || job.kind === "video") await checkMedia(job, base);
    else await checkText(job, base);
  } catch (e) {
    if (e.offline) offline(base);
    else problem("The check didn't finish", e.message);
  }
})();
