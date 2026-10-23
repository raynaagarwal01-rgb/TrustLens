const DEFAULT_SERVER = "http://127.0.0.1:8000";
const $ = (id) => document.getElementById(id);

async function base() {
  const { server } = await chrome.storage.sync.get("server");
  return (server || DEFAULT_SERVER).replace(/\/+$/, "");
}

function line(text, state) {
  const s = document.createElement("span");
  s.textContent = text;
  if (state) s.className = state;
  return s;
}

async function refresh() {
  const b = await base();
  $("server").value = b;
  $("app").href = b + "/";
  try {
    const st = await (await fetch(b + "/api/status")).json();
    $("status").replaceChildren(
      line("TrustLens is running", "on"),
      line(st.llm.configured ? `AI review: on (${st.llm.provider})` : "AI review: off (add a key to .env)", st.llm.configured ? "on" : "off"),
      line(st.face_swap_model ? "Face-swap model: on" : "Face-swap model: not installed", st.face_swap_model ? "on" : "off"));
  } catch {
    $("status").replaceChildren(line("TrustLens isn't running. Start it with: python server.py", "off"));
  }
}

$("go").addEventListener("click", () => {
  const text = $("msg").value.trim();
  if (text.length < 12) { $("msg").focus(); return; }
  chrome.runtime.sendMessage({ type: "factcheck", text }, () => window.close());
});

$("server").addEventListener("change", async (e) => {
  await chrome.storage.sync.set({ server: e.target.value.trim() || DEFAULT_SERVER });
  refresh();
});

refresh();
