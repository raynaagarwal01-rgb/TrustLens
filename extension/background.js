// TrustLens for Chrome: right-click menus that hand an image, video, selection or page to TrustLens
// running on this computer, and open the answer in a new tab.

const MENUS = [
  { id: "image", title: "Check this image with TrustLens", contexts: ["image"] },
  { id: "video", title: "Check this video with TrustLens", contexts: ["video"] },
  { id: "text", title: "Fact-check “%s” with TrustLens", contexts: ["selection"] },
  { id: "page", title: "Fact-check this page with TrustLens", contexts: ["page"] },
];

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => MENUS.forEach((m) => chrome.contextMenus.create(m)));
});

// runs inside the page: blob: images (WhatsApp Web, Telegram) only exist there
async function grabInPage(src) {
  try {
    const blob = await (await fetch(src)).blob();
    if (blob.size > 6e6) return { error: "too_big", size: blob.size };
    return await new Promise((done) => {
      const r = new FileReader();
      r.onload = () => done({ dataUrl: r.result, type: blob.type, size: blob.size });
      r.readAsDataURL(blob);
    });
  } catch (e) {
    return { error: String(e) };
  }
}

function readSelection() {
  return String(window.getSelection() || "");
}

function readPage() {
  const main = document.querySelector("article") || document.querySelector("main") || document.body;
  return { text: (main.innerText || "").replace(/\n{3,}/g, "\n\n").slice(0, 6000), title: document.title };
}

async function inTab(tab, frameId, func, args = []) {
  try {
    const [res] = await chrome.scripting.executeScript({
      target: { tabId: tab.id, frameIds: frameId ? [frameId] : undefined }, func, args,
    });
    return res?.result;
  } catch {
    return undefined; // chrome:// pages, the Web Store and PDFs can't be scripted
  }
}

async function startJob(job, tab) {
  job.id = crypto.randomUUID();
  await chrome.storage.session.set({ [job.id]: job });
  chrome.tabs.create({ url: chrome.runtime.getURL(`result.html#${job.id}`), index: tab ? tab.index + 1 : undefined });
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const job = { kind: info.menuItemId, pageUrl: info.pageUrl || tab?.url || "", pageTitle: tab?.title || "" };
  if (job.kind === "image" || job.kind === "video") {
    job.srcUrl = info.srcUrl || "";
    if (job.srcUrl.startsWith("blob:")) {
      const got = await inTab(tab, info.frameId, grabInPage, [job.srcUrl]);
      if (got?.dataUrl) Object.assign(job, { dataUrl: got.dataUrl, mime: got.type });
      else job.grabError = got?.error === "too_big" ? "too_big" : "blob";
    }
  } else if (job.kind === "text") {
    job.text = (await inTab(tab, info.frameId, readSelection)) || info.selectionText || "";
  } else if (job.kind === "page") {
    const page = await inTab(tab, 0, readPage);
    job.text = page?.text || "";
    job.pageTitle = page?.title || job.pageTitle;
  }
  startJob(job, tab);
});

// the popup's "Fact-check a message" box
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg?.type === "factcheck") {
    chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) =>
      startJob({ kind: "text", text: msg.text, pageUrl: "", pageTitle: "" }, tab).then(() => reply(true)));
    return true;
  }
});
