import { loadRegistry, spriteImg } from "./sprites.js";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const LS = {
  get(k, d = null) { try { return localStorage.getItem("ddtmux." + k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem("ddtmux." + k, v); } catch {} },
  del(k) { try { localStorage.removeItem("ddtmux." + k); } catch {} },
};

const AGENT_LABEL = { claude: "Claude", codex: "Codex", gemini: "Gemini", aider: "Aider", opencode: "OpenCode",
  cursor: "Cursor", copilot: "Copilot", qwen: "Qwen", goose: "Goose", crush: "Crush", amp: "Amp", droid: "Droid",
  kiro: "Kiro", cline: "Cline", "other-agent": "Agent", shell: "Shell" };
const STATE_LABEL = { working: "working", idle: "resting", needs_input: "awaiting orders!", dead: "fallen" };
const LONG_IDLE_MS = 60_000;

const S = {
  ws: null, connected: false, gotHello: false, retry: 0,
  panes: new Map(),          // pane_id -> pane
  assignments: {},           // target -> character
  registry: { chars: {}, defaults: {} },
  selected: null,            // pane_id
  pick: null,                // character picked in the Character tab
  room: LS.get("room"),       // session shown full screen
  mapOpen: null,              // session whose map bubble is expanded
  showShells: LS.get("showShells") === "1",
  sound: LS.get("sound") !== "0",
  rpcId: 0, pending: new Map(),
  histBefore: null, histTop: null, histEvents: [],
};

// ================= WebSocket =================
function connect() {
  const token = LS.get("token");
  if (!token) return askToken();
  const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;
  const ws = new WebSocket(url, ["bearer." + token]);
  S.ws = ws; S.gotHello = false;
  ws.onmessage = (e) => onMessage(JSON.parse(e.data));
  ws.onclose = async () => {
    setConn(false);
    if (!S.gotHello && S.retry >= 1) {
      // bad token, or server down/restarting? The token is only cleared if the server answers.
      const up = await fetch("health", { cache: "no-store" }).then((r) => r.ok, () => false);
      if (up) { LS.del("token"); return askToken("Token rejected."); }
    }
    S.retry++;
    setTimeout(connect, Math.min(1000 * 2 ** S.retry, 15000));
  };
}

function rpc(msg) {
  const id = ++S.rpcId;
  return new Promise((resolve, reject) => {
    if (!S.ws || S.ws.readyState !== 1) return reject(new Error("not connected"));
    S.pending.set(id, { resolve, reject });
    S.ws.send(JSON.stringify({ ...msg, id }));
    setTimeout(() => S.pending.has(id) && (S.pending.delete(id), reject(new Error("timeout"))), 10000);
  });
}

function onMessage(m) {
  switch (m.type) {
    case "hello":
      S.gotHello = true; S.retry = 0; setConn(true);
      S.panes = new Map(m.panes.map((p) => [p.pane_id, p]));
      S.assignments = m.characters || {};
      if (S.selected && S.panes.has(S.selected)) rpc({ op: "subscribe", pane_id: S.selected }).catch(() => {});
      else if (S.selected) closePanel();
      renderAll();
      break;
    case "pane_open": case "pane_update":
      S.panes.set(m.pane.pane_id, { ...S.panes.get(m.pane.pane_id), ...m.pane });
      renderAll();
      break;
    case "pane_close":
      S.panes.delete(m.pane_id);
      if (S.selected === m.pane_id) closePanel();
      renderAll();
      break;
    case "state": {
      const p = S.panes.get(m.pane_id);
      if (!p) break;
      const wasAsking = p.state === "needs_input", wasWorking = p.state === "working";
      Object.assign(p, { state: m.state, tail: m.tail, agent: m.agent, prompt: m.prompt });
      if (m.state !== "idle") p.last_change = Date.now() / 1000;
      if (m.state === "working" && !wasWorking) p.work_since = Date.now();
      if (m.state === "needs_input" && !wasAsking) chime(ASK_NOTES);
      // finished a turn: only agents (shells flip on every keystroke) that worked for a while (not a flicker)
      else if (m.state === "idle" && wasWorking && p.agent !== "shell" && Date.now() - (p.work_since || 0) > DONE_MIN_MS) chime(DONE_NOTES);
      updateHero(p); updateRoomMood(p.session); updateAlerts();
      if (S.selected === p.pane_id) renderPanelHead();
      break;
    }
    case "characters":
      S.assignments = m.assignments;
      renderAll();
      if (S.selected) { renderPanelHead(); renderCharTab(); }
      break;
    case "screen":
      if (m.pane_id === S.selected) writeScreen(m.content);
      break;
    case "history": case "ack": case "error": {
      const p = S.pending.get(m.id);
      if (p) { S.pending.delete(m.id); m.type === "error" ? p.reject(new Error(m.error)) : p.resolve(m); }
      else if (m.type === "error") toast(m.error);
      break;
    }
  }
}

function setConn(on) {
  S.connected = on;
  $("#conn").classList.toggle("on", on);
  $("#conn span").textContent = on ? "connected" : "reconnecting…";
}

// ================= characters =================
function characterFor(p) {
  // first candidate that exists (an id removed from the manifest falls through to the next)
  const ids = [S.assignments[`slot:${p.slot}`], S.assignments[`agent:${p.agent}`],
               S.registry.defaults[p.agent], p.agent !== "shell" && S.registry.defaults["other-agent"]];
  return S.registry.chars[ids.find((id) => id && S.registry.chars[id])] || Object.values(S.registry.chars)[0];
}
function assignmentSource(p) {
  if (S.assignments[`slot:${p.slot}`]) return "assigned to this pane";
  if (S.assignments[`agent:${p.agent}`]) return `default for ${AGENT_LABEL[p.agent] || p.agent}`;
  return "game default";
}

// ================= rooms =================
function visiblePanes() {
  return [...S.panes.values()].filter((p) => S.showShells || p.agent !== "shell");
}

function renderAll() {
  const bySession = new Map();
  // every session is a room, even if it only has hidden shells
  for (const p of S.panes.values()) if (!bySession.has(p.session)) bySession.set(p.session, []);
  for (const p of visiblePanes()) bySession.get(p.session).push(p);

  const root = $("#rooms");
  $("#empty").hidden = bySession.size > 0;
  const seen = new Set();
  const bgs = S.registry.backgrounds;
  for (const [session, panes] of [...bySession].sort((a, b) => a[0].localeCompare(b[0]))) {
    seen.add(session);
    let room = root.querySelector(`.room[data-session="${CSS.escape(session)}"]`);
    if (!room) { room = buildRoom(session); root.appendChild(room); }
    if (bgs.length) setScene(room, bgs[(seen.size - 1) % bgs.length]); // neighbouring rooms get different backgrounds
    const agents = panes.filter((p) => p.agent !== "shell").length;
    $(".meta", room).textContent = agents ? `${agents} ${agents === 1 ? "agent" : "agents"}` : "no agents";
    const party = $(".party", room);
    const keep = new Set();
    panes.sort((a, b) => a.slot.localeCompare(b.slot, undefined, { numeric: true }));
    for (const p of panes) {
      keep.add(p.pane_id);
      let hero = party.querySelector(`.hero[data-pane="${CSS.escape(p.pane_id)}"]`);
      const ch = characterFor(p);
      if (!hero || hero.dataset.char !== ch.id) {
        const fresh = buildHero(p, ch);
        hero ? hero.replaceWith(fresh) : party.appendChild(fresh);
        hero = fresh;
      }
      party.appendChild(hero); // keeps order
      updateHero(p);
    }
    $$(".hero", party).forEach((h) => !keep.has(h.dataset.pane) && h.remove());
    updateRoomMood(session);
  }
  $$(".room", root).forEach((r) => !seen.has(r.dataset.session) && r.remove());
  const sessions = [...seen];
  if (!sessions.includes(S.room)) S.room = sessions[0] || null;
  $$(".room", root).forEach((r) => r.classList.toggle("current", r.dataset.session === S.room));
  updateAlerts();
  fitStage();
}

// ================= map =================
function goRoom(session) {
  S.room = session; LS.set("room", session);
  renderAll();
}

// TUI lines that say nothing: borders, empty prompts, key hints, status bars.
const NOISE = /^[\s─━│┃┌┐└┘├┤╭╮╰╯═║>›❯▶•·.…_-]*$|for shortcuts|to interrupt|esc to cancel|bypass permissions|auto-accept|shift\+tab|ctrl\+|update installed|restart to apply|auto-updat/i;
// What a working agent is doing: its last action ("⏺ Update(db.py)", "• Edited app/queue.py")…
const ACTION = /^\s*[⏺●•]\s+(\S.*)$/u;
// …or else its spinner line ("✻ Pondering… (12s · esc to interrupt)" -> "Pondering…").
const SPINNER = /^[^\p{L}]*(\p{L}[^(]*?)\s*\([^)]*\b(?:esc|ctrl\+c) to (?:interrupt|cancel)/iu;

function doing(tail) {
  const lines = [...tail].reverse();
  for (const l of lines) {
    const m = l.match(ACTION);
    if (m && !NOISE.test(m[1])) return m[1].replace(/\s{2,}/g, " ").trim().slice(0, 160);
  }
  for (const l of lines) {
    const m = l.match(SPINNER);
    if (m) return m[1].trim();
  }
  return null;
}

/** Last `n` lines with content from a pane: the question if it asks for permission; if it is working,
 *  what it is doing right now as the latest line. */
function activity(p, n) {
  if (p.state === "needs_input" && p.prompt) return [p.prompt.trim()];
  const now = p.state === "working" && doing(p.tail || []);
  const out = meaningful((p.tail || []).join("\n"), n);
  if (!now) return out;
  const rest = out.filter((l) => !l.includes(now));
  return [...rest, now].slice(-n);
}

/** Last `n` lines of terminal text that say something (no TUI borders or hints). */
function meaningful(text, n) {
  const out = [];
  const lines = text.split("\n");
  for (const line of lines.reverse()) {
    const t = line.replace(/\s{2,}/g, " ").trim();
    const letters = (t.match(/\p{L}/gu) || []).length;
    // real text: at least 3 letters and not mostly symbols (borders, bars…)
    if (letters >= 3 && letters / t.length > 0.3 && !NOISE.test(t)) out.unshift(t.length > 160 ? t.slice(0, 159) + "…" : t);
    if (out.length >= n) break;
  }
  return out;
}

function renderMap() {
  const map = $("#map");
  const rooms = $$(".room", $("#rooms")).map((r) => r.dataset.session);
  map.hidden = rooms.length < 2; // with a single room there is nowhere to go
  map.replaceChildren();
  rooms.forEach((session, i) => {
    if (i) map.insertAdjacentHTML("beforeend", "<span class='corr'><i></i><i></i><i></i></span>");
    const ps = [...S.panes.values()].filter((p) => p.session === session && p.agent !== "shell");
    const alert = ps.some((p) => p.state === "needs_input"), busy = ps.some((p) => p.state === "working");
    const stop = document.createElement("div");
    stop.className = "map-stop";
    const b = document.createElement("button");
    b.className = "map-room" + (session === S.room ? " current" : "")
      + (alert ? " alert" : busy ? " busy" : ps.length ? " resting" : "");
    b.title = `${session} — ${ps.length} ${ps.length === 1 ? "agent" : "agents"}`;
    b.innerHTML = "<span class='lbl'></span>";
    $(".lbl", b).textContent = session;
    b.onclick = () => goRoom(session);
    stop.append(b);
    if (alert || busy || S.mapOpen === session) stop.append(mapActivity(session, ps));
    map.append(stop);
  });
}

/** Bubble over the room: what it is doing (collapsed) or all its agents with their last lines (expanded). */
function mapActivity(session, ps) {
  const open = S.mapOpen === session;
  const box = document.createElement("div");
  box.className = "map-act" + (open ? " open" : "") + (ps.some((p) => p.state === "needs_input") ? " alert" : "");
  box.onclick = (e) => { e.stopPropagation(); S.mapOpen = open ? null : session; renderMap(); };
  const row = (p, lines) => {
    const r = document.createElement("div");
    r.className = `act-row ${p.state}`;
    const head = document.createElement("div");
    head.className = "act-head";
    head.textContent = `${characterFor(p).name} · ${AGENT_LABEL[p.agent] || p.agent} ${p.window_index}.${p.pane_index}`
      + ` — ${STATE_LABEL[p.state] || p.state}`;
    const body = document.createElement("div");
    body.className = "act-lines";
    body.textContent = activity(p, lines).join("\n") || "…";
    r.append(head, body);
    if (open) r.onclick = (e) => { e.stopPropagation(); S.mapOpen = null; goRoom(session); openPanel(p.pane_id); };
    return r;
  };
  if (open) {
    const t = document.createElement("div");
    t.className = "act-title"; t.textContent = session;
    box.append(t, ...ps.map((p) => row(p, 4)));
  } else { // collapsed: whoever asks for permission first, otherwise the first one working
    const p = ps.find((x) => x.state === "needs_input") || ps.find((x) => x.state === "working");
    box.append(row(p, 1));
  }
  return box;
}
document.addEventListener("click", (e) => { // click outside: collapse
  if (S.mapOpen && !e.target.closest(".map-act")) { S.mapOpen = null; renderMap(); }
});

const MAX_ZOOM = 1; // character size: 1 = small, whole background visible; 2, 3… = bigger

/** Zooms the visible room by a WHOLE factor (pixel art stays crisp), up to MAX_ZOOM, and stretches the stage
 *  to fill the window. If the heroes do not fit across it lowers the zoom; at 1x, as a last resort, fractional. */
function fitStage() {
  const room = $(".room.current"), main = $("#rooms");
  if (!room) return;
  const stage = $(".stage", room), party = $(".party", room);
  room.style.setProperty("--z", 1); stage.style.height = "";
  const base = stage.offsetHeight, avail = main.getBoundingClientRect().bottom - stage.getBoundingClientRect().top;
  const apply = (z) => { room.style.setProperty("--z", z); stage.style.height = avail / z + "px"; };
  // real width of the heroes (scrollWidth includes overhanging bits like the "z" and lies)
  const need = () => [...party.children].reduce((w, h) => w + h.offsetWidth + 8, -8);
  const tooWide = () => need() > party.clientWidth;
  let z = Math.max(1, Math.min(MAX_ZOOM, Math.floor(avail / base)));
  apply(z);
  while (z > 1 && tooWide()) apply(--z);
  if (tooWide()) apply(party.clientWidth / need());
}
new ResizeObserver(() => fitStage()).observe($("#rooms")); // window or side panel
document.addEventListener("keydown", (e) => { // ← → to change room (outside text fields and the terminal)
  if (!["ArrowLeft", "ArrowRight"].includes(e.key) || e.target.closest("input, textarea, select, #term")) return;
  const rooms = $$(".room", $("#rooms")).map((r) => r.dataset.session), i = rooms.indexOf(S.room);
  const next = rooms[i + (e.key === "ArrowRight" ? 1 : -1)];
  if (next) goRoom(next);
});

function buildRoom(session) {
  const room = document.createElement("section");
  room.className = "room";
  room.dataset.session = session;
  room.innerHTML = `
    <header class="plaque"><span class="name"></span><span class="meta"></span>
      <button class="btn ghost danger kill" title="Delete this room and stop its agents">Delete room</button></header>
    <div class="stage">
      <div class="torch l"><div class="fire"></div><div class="stick"></div></div>
      <div class="torch r"><div class="fire"></div><div class="stick"></div></div>
      <div class="party"></div>
    </div>`;
  $(".name", room).textContent = session;
  $(".kill", room).onclick = async () => {
    if (!await confirmDeleteRoom(session)) return;
    try { await rpc({ op: "kill_session", name: session }); } catch (e) { toast(e.message); }
  };
  return room;
}

function confirmDeleteRoom(session) {
  const dialog = $("#deleteRoomDialog");
  $("#deleteRoomName").textContent = `“${session}”`;
  dialog.returnValue = "";
  dialog.showModal();
  return new Promise((resolve) => dialog.addEventListener("close", () => resolve(dialog.returnValue === "delete"), { once: true }));
}

// ================= animated backgrounds =================
// Particles per mood: n = count; the rest are [min, max] ranges drawn per particle.
const FX = {
  storm:   { n: 70, d: [0.5, 0.9] },                                    // rain + lightning
  forest:  { n: 16, d: [4, 9], s: [2, 4], dx: [-40, 40], y: [30, 80] }, // fireflies
  dungeon: { n: 22, d: [5, 10], s: [2, 3], dx: [-30, 30] },             // rising embers
  ashes:   { n: 28, d: [8, 16], s: [2, 4], dx: [-60, 60] },             // falling ash
};
const rnd = ([a, b]) => a + Math.random() * (b - a);

function setScene(room, bg) {
  const stage = $(".stage", room);
  if (stage.dataset.bg === bg.src) return;
  stage.dataset.bg = bg.src;
  stage.classList.add("painted");
  $(".scene", stage)?.remove();
  const scene = document.createElement("div");
  scene.className = `scene fx-${bg.fx}`;
  scene.innerHTML = `<div class="bgimg"></div><div class="fog"></div><div class="fog b"></div>
                     <div class="parts"></div><div class="glow"></div>`;
  $(".bgimg", scene).style.backgroundImage = `url("${bg.src}")`;
  const cfg = FX[bg.fx] || { n: 0 }, parts = $(".parts", scene);
  for (let i = 0; i < cfg.n; i++) {
    const p = document.createElement("i");
    const d = rnd(cfg.d);
    p.style.cssText = `--x:${rnd([0, 100])}%;--d:${d}s;--dl:${-rnd([0, d])}s`
      + (cfg.s ? `;--s:${rnd(cfg.s).toFixed(1)}px` : "") + (cfg.dx ? `;--dx:${rnd(cfg.dx)}px` : "")
      + (cfg.y ? `;--y:${rnd(cfg.y)}%` : "");
    parts.append(p);
  }
  stage.prepend(scene);
}

function buildHero(p, ch) {
  const el = document.createElement("div");
  el.className = "hero";
  el.dataset.pane = p.pane_id;
  el.dataset.char = ch.id;
  el.innerHTML = `<div class="bubble"></div><div class="alert">!</div><div class="zzz">z</div>
                  <div class="spark"></div><div class="nameplate"></div><div class="shadow"></div>`;
  el.insertBefore(spriteImg(ch, p.state), $(".nameplate", el));
  el.onclick = () => openPanel(p.pane_id);
  return el;
}

function updateHero(p) {
  const el = document.querySelector(`.hero[data-pane="${CSS.escape(p.pane_id)}"]`);
  if (!el) return;
  const ch = characterFor(p);
  el.className = `hero state-${p.state}` + (S.selected === p.pane_id ? " selected" : "")
    + (p.state === "idle" && Date.now() / 1000 - (p.last_change || 0) > LONG_IDLE_MS / 1000 ? " long-idle" : "");
  if (ch.kind === "images") { // custom sprites: one image per state
    const img = $(".sprite", el), want = ch.images[p.state] || ch.images.idle;
    if (want && !img.src.endsWith(want)) img.src = want;
  }
  $(".bubble", el).textContent = activity(p, 1)[0]?.slice(0, 80) || "…";
  $(".nameplate", el).textContent = `${AGENT_LABEL[p.agent] || p.agent} · ${p.window_index}.${p.pane_index}`;
  el.title = `${ch.name} — ${STATE_LABEL[p.state] || p.state}\n${p.command} @ ${p.path}`;
}

function updateRoomMood(session) {
  const room = document.querySelector(`.room[data-session="${CSS.escape(session)}"]`);
  if (!room) return;
  const ps = [...S.panes.values()].filter((p) => p.session === session && p.agent !== "shell");
  const busy = ps.some((p) => p.state === "working" || p.state === "needs_input");
  room.classList.toggle("busy", busy);
  room.classList.toggle("resting", ps.length > 0 && !busy);
}

function updateAlerts() {
  const n = [...S.panes.values()].filter((p) => p.state === "needs_input").length;
  const a = $("#alerts");
  a.hidden = !n;
  a.textContent = `${n} awaiting orders`;
  document.title = (n ? `(${n}) ` : "") + "DD-tmux";
  renderMap();
}

setInterval(() => S.panes.forEach(updateHero), 15000); // refreshes "zzz"

// ================= panel =================
let term, fit;

function initTerm() {
  term = new window.Terminal({
    fontFamily: "ui-monospace, 'Cascadia Mono', Menlo, Consolas, monospace",
    fontSize: 13, scrollback: 2000, convertEol: false, cursorBlink: false,
    theme: { background: "#000000", foreground: "#e8dcc4", cursor: "#c9a24a", selectionBackground: "#c9a24a55" },
  });
  fit = new window.FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open($("#term"));
  term.onData(onTermData);
  new ResizeObserver(() => sizeTerm()).observe($(".term-wrap"));
}

function sizeTerm() {
  if (!term || !S.selected || $("#panel").hidden) return;
  const p = S.panes.get(S.selected);
  const box = $(".term-wrap").getBoundingClientRect();
  const cols = p?.width || 120;
  // fit the font so the pane's real columns fit
  const fs = Math.max(8, Math.min(14, Math.floor((box.width - 12) / (cols * 0.6))));
  if (term.options.fontSize !== fs) term.options.fontSize = fs;
  const dims = fit.proposeDimensions();
  if (dims) term.resize(cols, Math.max(5, dims.rows));
}

function writeScreen(content) {
  const body = content.replace(/\n$/, "").replace(/\n/g, "\r\n");
  term.write("\x1b[H\x1b[2J\x1b[3J" + body);
}

// direct typing in the terminal -> tmux
const KEYMAP = { "\r": "Enter", "\x7f": "BSpace", "\b": "BSpace", "\x1b": "Escape", "\t": "Tab",
  "\x03": "C-c", "\x04": "C-d", "\x0c": "C-l", "\x12": "C-r", "\x1a": "C-z",
  "\x1b[A": "Up", "\x1b[B": "Down", "\x1b[C": "Right", "\x1b[D": "Left", "\x1b[Z": "S-Tab",
  "\x1b[5~": "PageUp", "\x1b[6~": "PageDown", "\x1bOA": "Up", "\x1bOB": "Down", "\x1bOC": "Right", "\x1bOD": "Left" };
let typed = "", typedTimer = null;
function flushTyped() {
  clearTimeout(typedTimer);
  if (!typed || !S.selected) return;
  const text = typed; typed = "";
  rpc({ op: "send_text", pane_id: S.selected, text, enter: false }).catch((e) => toast(e.message));
}
function onTermData(d) {
  if (!S.selected) return;
  if (KEYMAP[d]) { flushTyped(); return sendKey(KEYMAP[d]); }
  if (d.startsWith("\x1b")) return; // unsupported sequence
  if (d.length > 1 && /[\r\n]/.test(d)) { flushTyped(); typed = d.replace(/\r\n?/g, "\n"); return flushTyped(); } // paste
  typed += d.replace(/[\x00-\x1f]/g, "");
  clearTimeout(typedTimer);
  typedTimer = setTimeout(flushTyped, 40);
}
function sendKey(key) {
  return rpc({ op: "send_key", pane_id: S.selected, key }).catch((e) => toast(e.message));
}

function openPanel(paneId) {
  const prev = S.selected;
  if (prev && prev !== paneId) rpc({ op: "unsubscribe", pane_id: prev }).catch(() => {});
  S.selected = paneId;
  S.pick = null;
  $("#panel").hidden = false;
  document.body.classList.add("panel-open");
  if (!term) initTerm();
  term.reset();
  renderPanelHead();
  renderCharTab();
  resetHistory();
  if ($('.tab[data-tab="code"]')?.classList.contains("on")) loadCode();
  S.panes.forEach(updateHero);
  rpc({ op: "subscribe", pane_id: paneId }).catch((e) => toast(e.message));
  requestAnimationFrame(sizeTerm);
}

function closePanel() {
  if (S.selected) rpc({ op: "unsubscribe", pane_id: S.selected }).catch(() => {});
  S.selected = null;
  $("#panel").hidden = true;
  document.body.classList.remove("panel-open");
  S.panes.forEach(updateHero);
}

function renderPanelHead() {
  const p = S.panes.get(S.selected);
  if (!p) return;
  const ch = characterFor(p);
  const portrait = $("#pPortrait");
  if (portrait.dataset.char !== ch.id || portrait.dataset.state !== p.state) {
    portrait.dataset.char = ch.id;
    portrait.dataset.state = p.state;
    portrait.replaceChildren(spriteImg(ch, p.state));
  }
  $("#pName").textContent = ch.name;
  $("#pMeta").innerHTML = "";
  const line1 = document.createElement("div");
  const pill = document.createElement("span");
  pill.className = `state-pill ${p.state}`;
  pill.textContent = STATE_LABEL[p.state] || p.state;
  line1.append(document.createTextNode(`${AGENT_LABEL[p.agent] || p.agent} · ${p.slot}`), pill);
  const path = document.createElement("div");
  path.className = "p-path";
  path.textContent = p.path;
  $("#pMeta").append(line1, path);
}

// ---------- character tab ----------
function renderCharTab() {
  const p = S.panes.get(S.selected);
  if (!p) return;
  const cur = characterFor(p);
  S.pick ??= cur.id;
  const grid = $("#charGrid");
  grid.replaceChildren();
  for (const ch of Object.values(S.registry.chars)) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "char-card" + (ch.id === S.pick ? " pick" : "") + (ch.id === cur.id ? " current" : "");
    card.append(spriteImg(ch, "idle"));
    const n = document.createElement("div"); n.className = "cn"; n.textContent = ch.name;
    const b = document.createElement("div"); b.className = "cb"; b.textContent = ch.blurb || "";
    card.append(n, b);
    card.onclick = () => { S.pick = ch.id; renderCharTab(); };
    grid.append(card);
  }
  $("#agentName").textContent = AGENT_LABEL[p.agent] || p.agent;
  $("#charSource").textContent = `Now: ${cur.name} (${assignmentSource(p)}).`;
}

async function assign(target, character) {
  try { await rpc({ op: "set_character", target, character }); toast("Assigned", true); }
  catch (e) { toast(e.message); }
}
$("#assignSlot").onclick = () => { const p = S.panes.get(S.selected); p && assign(`slot:${p.slot}`, S.pick); };
$("#assignAgent").onclick = () => { const p = S.panes.get(S.selected); p && assign(`agent:${p.agent}`, S.pick); };
$("#assignClear").onclick = async () => {
  const p = S.panes.get(S.selected); if (!p) return;
  S.pick = null;
  await assign(`slot:${p.slot}`, null);
};

// ---------- chronicle tab ----------
function resetHistory() { S.histBefore = S.histTop = null; S.histEvents = []; $("#hist").replaceChildren(); loadHistory(); }
async function loadHistory() {
  const p = S.panes.get(S.selected); if (!p) return;
  try {
    const r = await rpc({ op: "history", pane_id: p.pane_id, kinds: ["input", "output", "state", "key"], limit: 50, before_id: S.histBefore });
    S.histEvents.push(...r.events);
    if (r.events.length) S.histBefore = r.events.at(-1).id;
    S.histTop ??= r.events[0]?.id ?? 0;
    renderHistory();
    $("#histMore").hidden = r.events.length < 50;
  } catch (e) { toast(e.message); }
}
function renderHistory() {
  const visible = new Set($$(".hist-filters input:checked").map((i) => i.value));
  const groups = [];
  let group;
  for (const ev of S.histEvents) { // newest events first
    if (group?.order && ev.id < group.order.id) { groups.push(group); group = null; }
    if (!group) group = { order: null, events: [] };
    if (["input", "key"].includes(ev.kind)) group.order = ev;
    if (visible.has(ev.kind)) group.events.push(ev);
  }
  if (group) groups.push(group);
  const list = $("#hist");
  list.replaceChildren(...groups.map((g) => histTurn(g, visible)).filter(Boolean));
}
function histTurn(group, visible) {
  if (!group.events.length) return null;
  const li = document.createElement("li");
  li.className = "turn";
  const first = group.events[0];
  const result = group.events.find((ev) => ev.kind === "state" && ["idle", "needs_input", "dead"].includes(ev.data.to));
  const output = group.events.find((ev) => ev.kind === "output");
  const state = result?.data.to || output?.data.state || "working";
  const head = document.createElement("div");
  head.className = "turn-head";
  const ts = document.createElement("span");
  ts.className = "ts";
  ts.textContent = new Date((group.order || first).ts).toLocaleString("en-GB", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  const label = document.createElement("span");
  label.className = `turn-state ${state}`;
  label.textContent = group.order ? `Turn · ${STATE_LABEL[state] || state}` : `Activity · ${STATE_LABEL[state] || state}`;
  head.append(ts, label);
  li.append(head);
  if (group.order && visible.has(group.order.kind)) {
    const command = document.createElement("div");
    command.className = "turn-order";
    command.textContent = group.order.kind === "input" ? group.order.data.text : `Key: ${group.order.data.key}`;
    li.append(command);
  }
  const events = document.createElement("ol");
  events.className = "turn-events";
  for (const ev of group.events) if (ev !== group.order) events.append(histItem(ev));
  if (events.childElementCount) li.append(events);
  return li;
}
function histItem(ev) {
  const li = document.createElement("li");
  const ts = new Date(ev.ts);
  const head = document.createElement("span");
  head.innerHTML = `<span class="ts"></span><span class="k ${ev.kind}"></span>`;
  $(".ts", head).textContent = ts.toLocaleString("en-GB", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
  $(".k", head).textContent = { input: "order", output: "output", state: "state", key: "key" }[ev.kind] || ev.kind;
  const who = ` ${ev.pane_id || ""} ${ev.agent ? "· " + (AGENT_LABEL[ev.agent] || ev.agent) : ""}`;
  if (ev.kind === "output") {
    const det = document.createElement("details");
    const sum = document.createElement("summary");
    const last = meaningful(ev.data.screen || "", 1)[0] || "";
    sum.append(head, document.createTextNode(`${who} — ${last.slice(0, 90)}`));
    const pre = document.createElement("pre");
    pre.textContent = (ev.data.screen || "").trimEnd();
    det.append(sum, pre);
    li.append(det);
  } else {
    const txt = ev.kind === "input" ? ev.data.text : ev.kind === "key" ? ev.data.key
              : ev.kind === "state" ? `${STATE_LABEL[ev.data.from] || ev.data.from} → ${STATE_LABEL[ev.data.to] || ev.data.to}` : JSON.stringify(ev.data);
    li.append(head, document.createTextNode(`${who} — ${txt}`));
  }
  return li;
}
$("#histMore").onclick = loadHistory;

// Live chronicle: while the tab is open, new events are prepended every 3 s.
setInterval(async () => {
  const p = S.panes.get(S.selected), tab = $('.tab[data-tab="hist"]');
  if (!p || $("#panel").hidden || !tab?.classList.contains("on") || S.histTop == null) return;
  if (!$$(".hist-filters input:checked").length) return;
  try {
    const r = await rpc({ op: "history", pane_id: p.pane_id, kinds: ["input", "output", "state", "key"], limit: 50 });
    const fresh = r.events.filter((ev) => ev.id > S.histTop);
    if (!fresh.length) return;
    S.histTop = fresh[0].id;
    S.histEvents.unshift(...fresh);
    renderHistory();
  } catch { /* offline: it will retry */ }
}, 3000);
$$(".hist-filters input").forEach((i) => (i.onchange = renderHistory));

async function loadCode() {
  const p = S.panes.get(S.selected);
  if (!p) return;
  const status = $("#codeStatus"), diff = $("#codeDiff");
  const agent = AGENT_LABEL[p.agent] || p.agent || "agent";
  $("#codeTitle").textContent = `Edits by ${agent}`;
  $("#codePath").textContent = p.path || "";
  status.textContent = "Loading changes…";
  diff.hidden = true;
  try {
    const r = await fetch(`/api/panes/${encodeURIComponent(p.pane_id)}/agent-edits`, {
      headers: { Authorization: `Bearer ${LS.get("token")}` }, cache: "no-store",
    });
    const events = await r.json();
    if (!r.ok) throw new Error(events.detail || r.statusText);
    if (S.selected !== p.pane_id) return;
    if (!events.length) {
      status.textContent = ["claude", "codex", "gemini", "opencode", "copilot"].includes(p.agent)
        ? `No edits captured yet. Open a new ${agent} room from DD-tmux to enable edit tracking.`
        : `Edit tracking is not enabled for ${agent} yet.`;
      return;
    }
    status.textContent = `${events.length} captured edit${events.length === 1 ? "" : "s"}`;
    diff.replaceChildren(...events.map((event) => {
      const card = document.createElement("article");
      card.className = "agent-diff";
      const heading = document.createElement("header");
      heading.textContent = `${agent} · ${new Date(event.ts).toLocaleTimeString()}`;
      const pre = document.createElement("pre");
      pre.append(...event.data.diff.split("\n").map((line, i, all) => {
        const row = document.createElement("span");
        row.className = line.startsWith("+") && !line.startsWith("+++") ? "diff-add"
          : line.startsWith("-") && !line.startsWith("---") ? "diff-del"
          : line.startsWith("@@") || line.startsWith("---") || line.startsWith("+++") ? "diff-meta" : "";
        row.textContent = line + (i < all.length - 1 ? "\n" : "");
        return row;
      }));
      card.append(heading, pre);
      return card;
    }));
    diff.hidden = false;
  } catch (e) {
    if (S.selected === p.pane_id) status.textContent = e.message === "Not Found"
      ? "This backend does not have the Code API yet. Restart DD-tmux (dd-tmux stop && dd-tmux), then refresh."
      : `Could not read the diff: ${e.message}`;
  }
}
$("#codeRefresh").onclick = loadCode;
setInterval(() => {
  if (!$("#panel").hidden && $('.tab[data-tab="code"]')?.classList.contains("on")) loadCode();
}, 3000);

// ---------- tabs, sending, keys ----------
$$(".tabs button").forEach((b) => (b.onclick = () => {
  $$(".tabs button").forEach((x) => x.classList.toggle("on", x === b));
  $$(".tab").forEach((t) => t.classList.toggle("on", t.dataset.tab === b.dataset.tab));
  if (b.dataset.tab === "term") requestAnimationFrame(sizeTerm);
  if (b.dataset.tab === "code") loadCode();
  if (b.dataset.tab === "hist") resetHistory();
}));
$("#panelClose").onclick = closePanel;
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#panel").hidden && !$("#term").contains(document.activeElement)) closePanel(); });

$$(".keys button").forEach((b) => (b.onclick = () => {
  if (!S.selected) return;
  if (b.dataset.key) sendKey(b.dataset.key);
  else rpc({ op: "send_text", pane_id: S.selected, text: b.dataset.text, enter: false }).catch((e) => toast(e.message));
}));

$("#sendForm").onsubmit = async (e) => {
  e.preventDefault();
  const ta = $("#sendText"), text = ta.value;
  if (!text.trim() || !S.selected) return;
  try { await rpc({ op: "send_text", pane_id: S.selected, text, enter: true }); ta.value = ""; }
  catch (err) { toast(err.message); }
};
$("#sendText").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); $("#sendForm").requestSubmit(); }
});

// ---------- topbar ----------
$("#showShells").checked = S.showShells;
$("#showShells").onchange = (e) => { S.showShells = e.target.checked; LS.set("showShells", S.showShells ? "1" : "0"); renderAll(); };
const soundBtn = $("#soundBtn");
const syncSound = () => { soundBtn.classList.toggle("muted", !S.sound); };
soundBtn.onclick = () => { S.sound = !S.sound; LS.set("sound", S.sound ? "1" : "0"); syncSound(); if (S.sound) chime(DONE_NOTES); };
syncSound();

const ASK_NOTES = [523, 392];        // C5 → G4, falling: an agent wants you
const DONE_NOTES = [392, 523, 659];  // G4 → C5 → E5, rising: an agent finished its turn
const DONE_MIN_MS = 5000;
let actx;
function chime(notes) {
  if (!S.sound) return;
  try {
    actx ??= new AudioContext();
    notes.forEach((f, i) => {
      const o = actx.createOscillator(), g = actx.createGain();
      o.type = "square"; o.frequency.value = f;
      g.gain.setValueAtTime(0.05, actx.currentTime + i * 0.12);
      g.gain.exponentialRampToValueAtTime(0.001, actx.currentTime + i * 0.12 + 0.2);
      o.connect(g).connect(actx.destination);
      o.start(actx.currentTime + i * 0.12); o.stop(actx.currentTime + i * 0.12 + 0.22);
    });
  } catch {}
}

// new room
const dlg = $("#newRoom"), form = $("#newRoomForm");
$("#newRoomBtn").onclick = () => { form.reset(); $(".custom-cmd", form).hidden = true; dlg.showModal(); };
form.command.onchange = () => { $(".custom-cmd", form).hidden = form.command.value !== "__custom"; };
dlg.addEventListener("close", async () => {
  if (dlg.returnValue !== "ok") return;
  const cmd = form.command.value === "__custom" ? form.custom.value.trim() : form.command.value;
  try {
    await rpc({ op: "new_session", name: form.name.value.trim(), cwd: form.cwd.value.trim() || null, command: cmd || null });
    toast(`Room "${form.name.value}" opened`, true);
  } catch (e) { toast(e.message); }
});

// login
function askToken(msg) {
  const d = $("#login");
  if (msg) toast(msg);
  if (!d.open) d.showModal();
}
$("#login").addEventListener("close", () => {
  const t = $("#loginForm").token.value.trim();
  if (!t) return askToken();
  LS.set("token", t); S.retry = 0; connect();
});

// toast
let toastT;
function toast(msg, ok = false) {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast" + (ok ? " ok" : ""); t.hidden = false;
  clearTimeout(toastT); toastT = setTimeout(() => (t.hidden = true), 3200);
}

// ================= dungeon textures =================
function makeTiles() {
  let seed = 7;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const wall = document.createElement("canvas"); wall.width = 32; wall.height = 16;
  let c = wall.getContext("2d");
  c.fillStyle = "#0d0b0e"; c.fillRect(0, 0, 32, 16);
  const stones = [[0, 0, 15, 7], [16, 0, 15, 7], [-8, 8, 15, 7], [8, 8, 15, 7], [24, 8, 15, 7]];
  for (const [x, y, w, h] of stones) {
    const g = 24 + Math.floor(rnd() * 10);
    c.fillStyle = `rgb(${g},${g - 5},${g - 1})`; c.fillRect(x, y, w, h);
    c.fillStyle = `rgb(${g + 7},${g + 2},${g + 5})`; c.fillRect(x, y, w, 1);
    c.fillStyle = `rgb(${g - 10},${g - 13},${g - 10})`; c.fillRect(x, y + h - 1, w, 1);
    for (let i = 0; i < 5; i++) { c.fillStyle = `rgba(0,0,0,${0.15 + rnd() * 0.2})`; c.fillRect(x + Math.floor(rnd() * w), y + 1 + Math.floor(rnd() * (h - 2)), 1, 1); }
    if (rnd() > 0.6) { c.fillStyle = "#2e3a26"; c.fillRect(x + Math.floor(rnd() * (w - 3)), y + h - 2, 3, 1); } // moss
  }
  const floor = document.createElement("canvas"); floor.width = 16; floor.height = 16;
  c = floor.getContext("2d");
  c.fillStyle = "#0a0809"; c.fillRect(0, 0, 16, 16);
  [[0, 0, 7, 7], [8, 0, 7, 7], [0, 8, 7, 7], [8, 8, 7, 7]].forEach(([x, y, w, h]) => {
    const g = 20 + Math.floor(rnd() * 8);
    c.fillStyle = `rgb(${g + 5},${g},${g - 4})`; c.fillRect(x, y, w, h);
    c.fillStyle = `rgba(255,255,255,.04)`; c.fillRect(x, y, w, 1);
  });
  document.documentElement.style.setProperty("--wall", `url(${wall.toDataURL()})`);
  document.documentElement.style.setProperty("--floor", `url(${floor.toDataURL()})`);
}

// ================= startup =================
makeTiles();
S.registry = await loadRegistry();
connect();
