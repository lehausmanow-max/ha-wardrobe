"use strict";
/* Wardrobe UI. No build step, no framework: plain modules of render functions.
   All URLs are relative so the app works under Home Assistant Ingress paths. */

// ------------------------------------------------------------------ basics
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : "");
const human = (s) => cap(String(s || "").replace(/_/g, " "));
const store = {
  get(k, d) { try { const v = localStorage.getItem("wardrobe." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("wardrobe." + k, JSON.stringify(v)); } catch { /* storage blocked */ } },
};
const money = (n) => n == null ? "" : new Intl.NumberFormat(undefined, { style: "currency", currency: "EUR" }).format(n);
const day = (iso) => iso ? new Date(iso + (iso.length === 10 ? "T12:00" : "")).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "";
const thumb = (f) => f ? `thumbs/${f}` : "";
const media = (f) => f ? `media/${f}` : "";

const S = {
  meta: null, profileId: null, garments: [], filter: store.get("filter", "all"), q: "",
  look: { occasion: store.get("occasion", "casual"), temp: "" }, anchor: null, suggestions: null, laundryAll: true,
};

async function api(method, path, data) {
  const opt = { method, headers: {} };
  if (data instanceof FormData) opt.body = data;
  else if (data !== undefined) { opt.body = JSON.stringify(data); opt.headers["content-type"] = "application/json"; }
  const res = await fetch(path, opt);
  const isJson = (res.headers.get("content-type") || "").includes("json");
  const body = isJson ? await res.json() : null;
  if (!res.ok) throw new Error((body && body.error) || `${res.status} ${res.statusText}`);
  return body;
}

let toastTimer;
function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast show" + (err ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.className = "toast"), err ? 5000 : 2600);
}
const fail = (e) => toast(e.message || String(e), true);

async function busy(btn, fn) {
  const old = btn ? btn.innerHTML : null;
  if (btn) { btn.disabled = true; btn.innerHTML = `<span class="spinner"></span>${btn.dataset.busy ? " " + esc(btn.dataset.busy) : ""}`; }
  try { return await fn(); } catch (e) { fail(e); } finally { if (btn && btn.isConnected) { btn.disabled = false; btn.innerHTML = old; } }
}

// ------------------------------------------------------------------ theme
// Inside Home Assistant the app follows the HA theme. Ingress serves the app from the same origin
// as the HA frontend around it, so the frame can read that theme's CSS variables and copy them
// onto its own tokens. Outside HA (local development) the app's own palette is used.
const HA_TOKENS = {
  "--rail": ["--primary-background-color"],
  "--tag": ["--ha-card-background", "--card-background-color"],
  "--card-border": ["--ha-card-border-color"],
  "--card-border-w": ["--ha-card-border-width"],
  "--card-shadow": ["--ha-card-box-shadow"],
  "--card-filter": ["--ha-card-backdrop-filter"],
  "--scrim": ["--mdc-dialog-scrim-color"],
  "--field": ["--ha-color-form-background"],
  "--ink": ["--primary-text-color"],
  "--muted": ["--secondary-text-color"],
  "--line": ["--divider-color"],
  "--indigo": ["--primary-color"],
  "--indigo-ink": ["--text-primary-color"],
  "--selvedge": ["--error-color"],
  "--ok": ["--success-color"],
  "--warn": ["--warning-color"],
  "--fav": ["--warning-color"],
  "--r": ["--ha-card-border-radius"],
  "--body": ["--ha-font-family-body", "--paper-font-body1_-_font-family", "--mdc-typography-font-family"],
};
const appearance = () => store.get("appearance", "ha");

// The nearest same-origin frame around this one that carries an HA theme, or null.
function haRoot() {
  let w = window;
  try {
    while (w !== w.parent) {
      w = w.parent;
      const root = w.document.documentElement; // throws once a frame is cross-origin
      if (w.getComputedStyle(root).getPropertyValue("--primary-text-color").trim()) return root;
    }
  } catch { /* cross-origin: no theme to follow */ }
  return null;
}

// Colours as [r, g, b, alpha], whatever CSS syntax the theme uses (rgb, hex, color-mix, oklch...).
let colourCtx = null;
function rgba(value) {
  value = (value || "").trim();
  if (!value) return null;
  try {
    colourCtx ||= Object.assign(document.createElement("canvas"), { width: 1, height: 1 }).getContext("2d", { willReadFrequently: true });
    colourCtx.fillStyle = "#010203";
    colourCtx.fillStyle = value;
    if (colourCtx.fillStyle !== "#010203" || /^#010203$/i.test(value)) {
      colourCtx.clearRect(0, 0, 1, 1);
      colourCtx.fillRect(0, 0, 1, 1);
      const d = colourCtx.getImageData(0, 0, 1, 1).data;
      return [d[0], d[1], d[2], d[3] / 255];
    }
  } catch { /* fall through to the computed-style probe */ }
  const probe = document.createElement("i");
  probe.style.color = value;
  if (!probe.style.color) return null;
  document.body.append(probe);
  const c = getComputedStyle(probe).color;
  probe.remove();
  let m = c.match(/^rgba?\(([\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)(?:[ ,/]+([\d.]+))?/);
  if (m) return [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]];
  m = c.match(/^color\(srgb ([\d.]+) ([\d.]+) ([\d.]+)(?: \/ ([\d.]+))?/);
  if (m) return [m[1] * 255, m[2] * 255, m[3] * 255, m[4] === undefined ? 1 : +m[4]];
  return null;
}
const over = (fg, bg) => fg[3] >= 1 || !bg ? fg : [0, 1, 2].map((i) => fg[i] * fg[3] + bg[i] * (1 - fg[3])).concat(1);
function luminance(c) {
  const [r, g, b] = c.slice(0, 3).map((v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const contrast = (a, b) => { const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

// Text on the primary colour: the theme's own choice when it's readable, otherwise white or near-black.
// (Some themes set text-primary-color to their body text colour, which can vanish on a light primary.)
function inkOn(primary, themeInk, base) {
  const bg = over(primary, base);
  const options = [themeInk, "#ffffff", "#101317"].map((v) => [v, rgba(v)]).filter(([, c]) => c);
  const ok = options.find(([, c]) => contrast(over(c, bg), bg) >= 4.5);
  if (ok) return ok[0];
  return options.sort((a, b) => contrast(over(b[1], bg), bg) - contrast(over(a[1], bg), bg))[0]?.[0] || "";
}

// url(...) in a theme value resolves against the HA page, not this frame.
const absoluteUrls = (value, base) => value.replace(/url\((['"]?)([^'")]+)\1\)/g, (_, q, u) => {
  try { return `url("${new URL(u, base).href}")`; } catch { return `url("${u}")`; }
});

// Set by applyHaTheme besides HA_TOKENS; cleared when the theme is switched off.
const HA_EXTRA = ["--surface", "--page-image"];

function applyHaTheme(root) {
  const cs = root.ownerDocument.defaultView.getComputedStyle(root);
  const read = (...names) => names.map((n) => cs.getPropertyValue(n).trim()).find(Boolean) || "";
  const de = document.documentElement;
  for (const [mine, theirs] of Object.entries(HA_TOKENS)) {
    const v = read(...theirs);
    if (v) de.style.setProperty(mine, v); else de.style.removeProperty(mine);
  }
  const base = rgba(read("--primary-background-color"));
  const dark = base ? luminance(base) < 0.18 : /dark/.test(cs.colorScheme || "");
  de.dataset.theme = dark ? "dark" : "light";
  de.dataset.ha = "";

  // An always-opaque surface for labels on photos: the theme's card colour if it's solid, else the page colour.
  const solid = [read("--card-background-color"), read("--ha-card-background")].find((v) => (rgba(v)?.[3] ?? 0) >= 0.95);
  if (solid) de.style.setProperty("--surface", solid);
  else if (base) de.style.setProperty("--surface", "var(--rail)");

  // Glass themes: see-through cards and/or a background picture on the dashboard.
  const card = rgba(read("--ha-card-background", "--card-background-color"));
  let image = read("--lovelace-background", "--background-image");
  if (/^(none|initial|unset|transparent)$/i.test(image)) image = "";
  if (image) de.style.setProperty("--page-image", absoluteUrls(image, root.ownerDocument.baseURI));
  else de.style.removeProperty("--page-image");
  const glass = !!image || (card ? card[3] < 0.95 : false);
  if (glass) de.dataset.glass = ""; else delete de.dataset.glass;

  const primary = rgba(read("--primary-color"));
  if (primary) {
    const ink = inkOn(primary, read("--text-primary-color"), base);
    if (ink) de.style.setProperty("--indigo-ink", ink);
  }
}

// HA's font (Roboto) is loaded by the HA page; copy its @font-face rules so the frame can use it too.
function borrowFonts(doc) {
  if (document.getElementById("ha-fonts")) return;
  const css = [];
  for (const sheet of doc.styleSheets) {
    let rules;
    try { rules = sheet.cssRules; } catch { continue; }
    const base = sheet.href || doc.baseURI;
    for (const r of rules) {
      if (r.type !== 5) continue; // CSSRule.FONT_FACE_RULE
      css.push(absoluteUrls(r.cssText, base));
    }
  }
  if (!css.length) return;
  const st = document.createElement("style");
  st.id = "ha-fonts"; st.textContent = css.join("\n");
  document.head.append(st);
}

// Re-apply when the HA theme changes: a theme switch, dark mode, or the device's light/dark setting.
let haWatch = null, haQueued = false;
function reapplyHaTheme() {
  if (haQueued) return;
  haQueued = true;
  requestAnimationFrame(() => {
    haQueued = false;
    const root = haWatch?.root;
    if (root && root.isConnected && appearance() === "ha") applyHaTheme(root);
  });
}
function watchHaTheme(root) {
  if (haWatch?.root === root) return;
  if (haWatch) haWatch.observer.disconnect();
  else matchMedia("(prefers-color-scheme: dark)").addEventListener("change", reapplyHaTheme);
  const observer = new MutationObserver(reapplyHaTheme);
  observer.observe(root, { attributes: true, attributeFilter: ["style", "class"] });
  if (root.ownerDocument.head) observer.observe(root.ownerDocument.head, { childList: true, subtree: true, characterData: true });
  haWatch = { root, observer };
}

function applyTheme() {
  const pref = appearance();
  const de = document.documentElement;
  for (const k of [...Object.keys(HA_TOKENS), ...HA_EXTRA]) de.style.removeProperty(k);
  delete de.dataset.ha;
  delete de.dataset.glass;
  const root = pref === "ha" ? haRoot() : null;
  if (root) {
    applyHaTheme(root);
    try { borrowFonts(root.ownerDocument); } catch { /* fonts fall back to the system's */ }
    watchHaTheme(root);
    return;
  }
  if (pref === "light" || pref === "dark") de.dataset.theme = pref;
  else delete de.dataset.theme;
}

// ------------------------------------------------------------------ sheets
const sheets = [];
const ICON_X = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>`;
const ICON_STAR = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3.6 2.6 5.3 5.8.8-4.2 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.2-4.1 5.8-.8Z"/></svg>`;
function openSheet(title, html) {
  const el = document.createElement("section");
  el.className = "sheet"; el.setAttribute("role", "dialog"); el.setAttribute("aria-modal", "true"); el.setAttribute("aria-label", title);
  el.innerHTML = `<div class="sheet-head"><h2>${esc(title)}</h2><span class="head-extra"></span><button class="icon-btn" data-action="close-sheet" aria-label="Close">${ICON_X}</button></div><div class="sheet-body">${html}</div>`;
  $("#sheets").append(el); sheets.push(el);
  $("#backdrop").hidden = false; document.body.style.overflow = "hidden";
  setTimeout(() => (el.querySelector("[autofocus]") || el.querySelector(".sheet-head button")).focus({ preventScroll: true }), 30);
  scheduleHistorySync();
  return el;
}
function fillSheet(el, title, html, headExtra = "") {
  $(".sheet-head h2", el).textContent = title;
  $(".sheet-head .head-extra", el).innerHTML = headExtra;
  $(".sheet-body", el).innerHTML = html;
}
function closeSheet() {
  const el = sheets.pop();
  if (el) { el.dispatchEvent(new Event("sheetclose")); el.remove(); }
  if (!sheets.length) { $("#backdrop").hidden = true; document.body.style.overflow = ""; }
  scheduleHistorySync();
}

// Each open sheet has its own browser history entry, so a back swipe (or the Android back button)
// closes the top sheet instead of leaving the app. history.state.ws is the number of sheets open at
// that entry; after any open or close, the history is brought in line with the sheets on screen.
let historyBusy = false, historySyncTimer = 0, historyBusyTimer = 0;
const historyDepth = () => (history.state && history.state.ws) || 0;
function scheduleHistorySync() { if (!historySyncTimer) historySyncTimer = setTimeout(syncHistory, 0); }
function syncHistory() {
  historySyncTimer = 0;
  if (historyBusy) return; // the popstate of our own history.go() syncs again
  const d = historyDepth(), n = sheets.length;
  if (n > d) for (let i = d + 1; i <= n; i++) history.pushState({ ws: i }, "");
  else if (n < d) {
    historyBusy = true;
    clearTimeout(historyBusyTimer);
    historyBusyTimer = setTimeout(() => { historyBusy = false; }, 1500); // never stay stuck
    history.go(n - d);
  }
}
window.addEventListener("popstate", () => {
  if (historyBusy) { historyBusy = false; clearTimeout(historyBusyTimer); scheduleHistorySync(); return; }
  const d = historyDepth();
  while (sheets.length > d) closeSheet(); // back: close sheets, one per step
  scheduleHistorySync(); // forward onto a sheet that's gone: step back again
});
function closeAllSheets() { while (sheets.length) closeSheet(); }
function confirmSheet(title, text, yes = "Delete") {
  return new Promise((resolve) => {
    const el = openSheet(title, `<p>${esc(text)}</p><div class="actions"><button class="btn danger" data-yes>${esc(yes)}</button><button class="btn" data-no>Cancel</button></div>`);
    let done = false;
    const finish = (v) => { if (!done) { done = true; resolve(v); } };
    el.addEventListener("sheetclose", () => finish(false));
    $("[data-yes]", el).onclick = () => { finish(true); closeSheet(); };
    $("[data-no]", el).onclick = () => { finish(false); closeSheet(); };
  });
}
const loading = (msg = "") => `<div class="loading"><span class="spinner"></span>${msg ? `&nbsp; ${esc(msg)}` : ""}</div>`;

// ------------------------------------------------------------------ small renderers
const profile = () => (S.meta?.profiles || []).find((p) => p.id === S.profileId);
const profileById = (id) => (S.meta?.profiles || []).find((p) => p.id === id);
const swatches = (cs = []) => `<span class="swatches">${cs.slice(0, 4).map((c) => `<span class="swatch" style="background:${esc(c)}"></span>`).join("")}</span>`;
const dots = (n, max = 5) => `<span class="dots" aria-label="${n} of ${max}">${Array.from({ length: max }, (_, i) => `<i class="${i < n ? "on" : ""}"></i>`).join("")}</span>`;
const pic = (g, cls = "") => g.photo ? `<img class="${cls}" src="${thumb(g.photo)}" alt="" loading="lazy">` : `<div class="none ${cls}">No photo</div>`;
const catLabel = (c) => S.meta.taxonomy.categories[c]?.label || cap(c);
const ownerDot = (pid) => { const p = profileById(pid); return p ? `<span class="owner" style="background:${esc(p.color)}" title="${esc(p.name)}">${esc(p.name[0])}</span>` : ""; };

function tagCard(g) {
  let flag = "";
  if (g.status === "laundry") flag = `<span class="flag">In the wash</span>`;
  else if (g.status === "repair") flag = `<span class="flag">At the tailor</span>`;
  else if (g.status === "stored") flag = `<span class="flag">Stored</span>`;
  else if (g.wash_due) flag = `<span class="flag due">Wash due</span>`;
  const dim = ["laundry", "repair", "stored", "archived"].includes(g.status) ? " dim" : "";
  return `<button class="tag${dim}" data-action="open-garment" data-id="${g.id}">
    <div class="hole"></div>
    <div class="pic">${pic(g)}</div>${flag}
    <div class="info"><div class="name">${esc(g.name)}</div>
      <div class="meta"><span>${esc(g.brand || cap(g.subcategory) || catLabel(g.category))}${g.size_label ? `, ${esc(g.size_label)}` : ""}</span>${swatches(g.colors)}</div>
    </div></button>`;
}

// ------------------------------------------------------------------ care symbols (ISO/GINETEX style, simplified)
function careIcons(c = {}) {
  const out = [];
  const tub = `<path d="M4 10 7 27h18l3-17"/><path d="M4 10c2-2.5 4-2.5 6 0s4 2.5 6 0 4-2.5 6 0 4 2.5 6 0"/>`;
  const cross = `<path d="M3 4l26 26M29 4 3 30"/>`;
  const sym = (svg, label) => out.push(`<div class="care-sym"><svg viewBox="0 0 32 34" role="img" aria-label="${esc(label)}">${svg}</svg><span>${esc(label)}</span></div>`);
  const w = c.wash || "machine";
  const bars = c.cycle === "delicate" ? `<path d="M6 30h20"/>` : c.cycle === "wool" ? `<path d="M6 30h20M6 33h20"/>` : "";
  if (w === "machine") sym(tub + `<text x="16" y="23" text-anchor="middle">${c.temp ?? 30}°</text>` + bars, `${c.temp ?? 30}°${c.cycle && c.cycle !== "normal" ? ", " + c.cycle : ""}`);
  else if (w === "hand") sym(tub + `<path d="M12 23v-6a1 1 0 0 1 2 0v3-5a1 1 0 0 1 2 0v5-5.5a1 1 0 0 1 2 0V20v-3a1 1 0 0 1 2 0v4c0 2-1.5 3.5-3.5 3.5h-1.5c-1.5 0-3-1-3-2.5"/>`, `Hand wash${c.temp ? " " + c.temp + "°" : ""}`);
  else if (w === "dry_clean") sym(tub + cross, "Don't wash, dry clean");
  else sym(tub + cross, w === "spot" ? "Spot clean only" : "Do not wash");
  // Bleach shows only when it was read from the care label; the server leaves it out otherwise.
  const tri = `<path d="M16 5 29 28H3Z"/>`;
  if (c.bleach === "any") sym(tri, "Any bleach");
  else if (c.bleach === "non_chlorine") sym(tri + `<path d="M13 25 18 15M17 25l5-10"/>`, "Oxygen bleach only");
  else if (c.bleach === "no") sym(tri + cross, "No bleach");
  const sq = `<rect x="4" y="5" width="24" height="24" rx="1"/>`;
  const d = c.dry || "line";
  if (d === "tumble_low") sym(sq + `<circle cx="16" cy="17" r="8"/><circle cx="16" cy="17" r="1.2" fill="currentColor"/>`, "Tumble low");
  else if (d === "tumble_normal") sym(sq + `<circle cx="16" cy="17" r="8"/><circle cx="13.5" cy="17" r="1.2" fill="currentColor"/><circle cx="18.5" cy="17" r="1.2" fill="currentColor"/>`, "Tumble normal");
  else if (d === "flat") sym(sq + `<path d="M8 17h16"/>`, "Dry flat");
  else if (d === "no_tumble") sym(sq + `<circle cx="16" cy="17" r="8"/>` + cross, "No tumble dryer");
  else sym(sq + `<path d="M4 11c6 4 18 4 24 0"/>`, "Line dry");
  const iron = `<path d="M4 25 7 14h15c4 0 6 4 6 11Z"/><path d="M10 14c0-3 2-5 5-5h8"/>`;
  const n = { low: 1, medium: 2, high: 3 }[c.iron];
  if (c.iron === "no") sym(iron + cross, "Do not iron");
  else sym(iron + Array.from({ length: n || 1 }, (_, i) => `<circle cx="${16 - (n - 1) * 2.5 + i * 5}" cy="20" r="1.2" fill="currentColor"/>`).join(""), `Iron ${c.iron || "low"}`);
  if (c.dry_clean && c.dry_clean !== "any") {
    const circ = `<circle cx="16" cy="17" r="11"/>`;
    if (c.dry_clean === "no") sym(circ + cross, "No dry cleaning");
    else sym(circ + `<text x="16" y="21" text-anchor="middle" style="font-size:11px">${esc(c.dry_clean)}</text>`, `Dry clean ${c.dry_clean}`);
  }
  return `<div class="care-row">${out.join("")}</div>`;
}

// ------------------------------------------------------------------ boot and routing
async function loadMeta() {
  S.meta = await api("GET", "api/meta");
  const ids = S.meta.profiles.map((p) => p.id);
  const saved = store.get("profile", null);
  S.profileId = ids.includes(saved) ? saved : (S.meta.matched_profile || ids[0] || null);
  renderProfiles();
}

function renderProfiles() {
  const el = $("#profiles");
  el.innerHTML = (S.meta.profiles || []).map((p) => `
    <button class="profile-pill" role="tab" aria-selected="${p.id === S.profileId}" data-action="profile" data-id="${p.id}">
      <span class="dot" style="background:${esc(p.color)}">${esc(p.name[0] || "?")}</span>${esc(p.name)}</button>`).join("");
}

function currentView() { return (location.hash.replace(/^#\/?/, "").split("/")[0]) || "wardrobe"; }

async function route() {
  const view = currentView();
  $$(".tabs a").forEach((a) => { if (a.dataset.tab === view) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
  $("#fab").hidden = !(view === "wardrobe" && S.profileId);
  const main = $("#main");
  if (route.last !== view) window.scrollTo(0, 0);
  route.last = view;
  if (!S.meta.profiles.length) return renderOnboarding(main);
  const views = { wardrobe: renderWardrobe, looks: renderLooks, fit: renderFit, care: renderCare, shop: renderShop };
  main.innerHTML = loading();
  try { await (views[view] || renderWardrobe)(main); } catch (e) { main.innerHTML = `<div class="empty"><h3>That didn't load</h3><p class="muted">${esc(e.message)}</p><button class="btn" data-action="reload">Try again</button></div>`; }
}

// ------------------------------------------------------------------ onboarding
function renderOnboarding(main) {
  $("#fab").hidden = true;
  main.innerHTML = `
    <h1>Set up your wardrobe</h1>
    <p class="lede">Add the people who share it. Each person gets their own garments, sizes and fit notes; laundry is shared.</p>
    <form class="panel form-grid" id="onboard">
      <div class="grid2"><label class="field"><span>Your name</span><input type="text" name="n1" required autofocus value="${esc(S.meta.ha_user?.display_name || "")}"></label>
      <label class="field"><span>Home Assistant username (optional)</span><input type="text" name="u1" value="${esc(S.meta.ha_user?.name || "")}"></label></div>
      <div class="grid2"><label class="field"><span>Second person</span><input type="text" name="n2"></label>
      <label class="field"><span>Their Home Assistant username</span><input type="text" name="u2"></label></div>
      <p class="small muted">With usernames filled in, the app opens on the right wardrobe for whoever is logged in to Home Assistant.</p>
      <button class="btn primary" type="submit">Create wardrobe</button>
    </form>`;
  $("#onboard").onsubmit = (ev) => {
    ev.preventDefault();
    const f = new FormData(ev.target);
    busy(ev.submitter, async () => {
      await api("POST", "api/profiles", { name: f.get("n1"), ha_user: f.get("u1"), color: "#2e3e73" });
      if ((f.get("n2") || "").trim()) await api("POST", "api/profiles", { name: f.get("n2"), ha_user: f.get("u2"), color: "#8a3b4a" });
      await loadMeta(); route();
    });
  };
}

// ------------------------------------------------------------------ wardrobe
async function loadGarments() {
  S.garments = await api("GET", `api/garments?profile_id=${S.profileId}`);
  return S.garments;
}

function filteredGarments() {
  const q = S.q.trim().toLowerCase();
  return S.garments.filter((g) => {
    if (S.filter === "laundry") { if (g.status !== "laundry") return false; }
    else if (S.filter === "stored") { if (!["stored", "archived"].includes(g.status)) return false; }
    else {
      if (["stored", "archived"].includes(g.status)) return false;
      if (S.filter !== "all" && g.category !== S.filter) return false;
    }
    if (!q) return true;
    return [g.name, g.brand, g.material, g.subcategory, g.notes, ...(g.color_names || [])].join(" ").toLowerCase().includes(q);
  });
}

async function renderWardrobe(main) {
  await loadGarments();
  const current = S.garments.filter((g) => !["stored", "archived"].includes(g.status));
  const count = (f) => f === "all" ? current.length : f === "laundry" ? S.garments.filter((g) => g.status === "laundry").length
    : f === "stored" ? S.garments.filter((g) => ["stored", "archived"].includes(g.status)).length : current.filter((g) => g.category === f).length;
  const filters = ["all", ...Object.keys(S.meta.taxonomy.categories), "laundry", "stored"];
  const labels = { all: "Everything", laundry: "In the wash", stored: "Stored" };
  main.innerHTML = `
    <h1>${esc(profile()?.name || "")}'s wardrobe</h1>
    <div class="toolbar"><input type="search" id="q" placeholder="Search name, brand, colour, fabric" value="${esc(S.q)}" aria-label="Search garments"></div>
    <div class="chips" role="toolbar" aria-label="Filter">${filters.filter((f) => count(f) || f === "all" || f === S.filter).map((f) =>
      `<button class="chip" aria-pressed="${S.filter === f}" data-action="filter" data-f="${f}">${esc(labels[f] || catLabel(f))}<span class="count">${count(f)}</span></button>`).join("")}</div>
    <div id="grid"></div>`;
  $("#q").oninput = (ev) => { S.q = ev.target.value; drawGrid(); };
  drawGrid();
}

function drawGrid() {
  const grid = $("#grid");
  if (!grid) return;
  const list = filteredGarments();
  if (!S.garments.length) {
    grid.innerHTML = `<div class="empty"><h3>Start with what you wear most</h3>
      <p class="muted">Tap Add and take a photo of a garment on a plain background. The app reads its colours${S.meta.ai.vision.enabled ? " and fills in the details" : ""}; you check and save.</p>
      <button class="btn" data-action="new-garment">Add one without a photo</button></div>`;
    return;
  }
  grid.innerHTML = (list.length ? `<div class="tags">${list.map(tagCard).join("")}</div>` : `<p class="muted">Nothing matches.</p>`)
    + `<p style="margin-top:18px"><button class="btn ghost" data-action="new-garment">Add a garment without a photo</button></p>`;
}

// ------------------------------------------------------------------ garment detail
async function openGarment(id, existing) {
  const el = existing || openSheet("Garment", loading());
  const g = await api("GET", `api/garments/${id}`);
  const t = S.meta.taxonomy;
  const photos = g.photos.map((p) => `<figure><img src="${media(p.filename)}" alt="">${p.kind !== "item" ? `<figcaption>${p.kind === "label" ? "Care label" : "Worn"}</figcaption>` : ""}</figure>`).join("");
  const statusSeg = [["active", "Wearing"], ["laundry", "In the wash"], ["repair", "Tailor"], ["stored", "Stored"]]
    .map(([v, l]) => `<label><input type="radio" name="status" value="${v}" ${g.status === v ? "checked" : ""} data-change="status" data-id="${g.id}">${l}</label>`).join("");
  const sinceWash = g.care?.wash_after ? `Wash after ${g.care.wash_after} wear${g.care.wash_after > 1 ? "s" : ""}; worn ${g.wears_since_wash} since the last wash.` : "";
  const verdicts = g.fit_verdicts.length ? `<div class="verdicts">${g.fit_verdicts.map((v) => {
      const pos = { tight: 6, snug: 21, good: 50, roomy: 79, loose: 94 }[v.band];
      return `<div class="verdict"><span>${esc(v.label)}</span><div class="ease" title="${v.ease > 0 ? "+" : ""}${v.ease} cm"><i style="left:${pos}%"></i></div><span class="band-${v.band}">${esc(cap(v.verdict))}</span></div>`;
    }).join("")}</div><p class="small muted">Garment minus body, for a ${esc(g.fit_type)} fit.</p>`
    : `<p class="muted small">Add the garment's measurements (Edit) and yours (Fit tab) to see how it should fit.</p>`;
  const logs = g.fit_logs.map((l) => `<li><div class="grow"><div class="title">${esc(human(l.overall))} <span class="muted small">${day(l.logged_on)}</span></div>
      ${Object.keys(l.areas || {}).length ? `<div class="small muted">${Object.entries(l.areas).map(([k, v]) => `${k} ${v < 0 ? "tight" : "loose"}`).join(", ")}</div>` : ""}
      ${l.notes ? `<div class="small">${esc(l.notes)}</div>` : ""}
      ${l.ai_critique ? `<div class="note small prose" style="margin-top:6px">${esc(l.ai_critique)}</div>` : ""}</div>
      <button class="icon-btn" data-action="del-fitlog" data-id="${l.id}" data-g="${g.id}" aria-label="Delete note">${ICON_X}</button></li>`).join("");

  fillSheet(el, g.name, `
    <div class="gallery">${photos}<button class="add-photo" data-action="add-photo" data-id="${g.id}" data-kind="item">Add photo</button></div>
    <p class="muted" style="margin:12px 0 0">${[g.brand, g.size_label && `size ${g.size_label}`, cap(g.subcategory) || catLabel(g.category), g.material].filter(Boolean).map(esc).join(", ")}</p>
    <div class="row" style="margin-top:8px">${swatches(g.colors)}<span class="small">${esc((g.color_names || []).join(", "))}${g.pattern && g.pattern !== "solid" ? `, ${esc(g.pattern)}` : ""}</span></div>
    <dl class="kv small" style="margin-top:10px"><dt>Formality</dt><dd>${dots(g.formality)}</dd><dt>Warmth</dt><dd>${dots(g.warmth)}</dd>
      ${g.seasons.length ? `<dt>Seasons</dt><dd>${esc(g.seasons.join(", "))}</dd>` : ""}${g.occasions.length ? `<dt>Occasions</dt><dd>${esc(g.occasions.join(", "))}</dd>` : ""}</dl>
    <div class="actions">
      <button class="btn primary" data-action="wear" data-id="${g.id}">Wore it today</button>
      <button class="btn" data-action="style-this" data-id="${g.id}" data-name="${esc(g.name)}">Style this</button>
      <button class="btn" data-action="fit-log" data-id="${g.id}">Log fit</button>
      <button class="btn" data-action="edit-garment" data-id="${g.id}">Edit</button>
    </div>
    <div class="section-title">Where it is</div>
    <div class="seg" role="radiogroup" aria-label="Status">${statusSeg}</div>
    <div class="section-title">Wear</div>
    <p class="small" style="margin:0">${g.wear_count ? `Worn ${g.wear_count} time${g.wear_count > 1 ? "s" : ""}, last on ${day(g.last_worn)}.` : "Not worn yet."}
      ${g.cost_per_wear != null && g.wear_count ? ` ${money(g.cost_per_wear)} per wear (paid ${money(g.price)}).` : g.price ? ` Paid ${money(g.price)}.` : ""}</p>
    <div class="section-title spread"><span>Care</span><button class="btn ghost" data-action="add-photo" data-id="${g.id}" data-kind="label">Read care label</button></div>
    ${careIcons(g.care)}
    ${g.care?.notes ? `<p class="small">${esc(g.care.notes)}</p>` : ""}${sinceWash ? `<p class="small muted">${sinceWash}</p>` : ""}
    <div class="section-title">Fit</div>
    ${g.fit_summary ? `<p class="small" style="margin-top:0">${esc(g.fit_summary)}</p>` : ""}${verdicts}
    ${logs ? `<ul class="list" style="margin-top:10px">${logs}</ul>` : ""}
    ${g.looks.length ? `<div class="section-title">In saved looks</div><p class="small">${g.looks.map((l) => esc(l.name || "Untitled look")).join(", ")}</p>` : ""}
    ${g.notes ? `<div class="section-title">Notes</div><p class="small prose">${esc(g.notes)}</p>` : ""}
    <div class="actions" style="margin-top:26px"><button class="btn danger" data-action="delete-garment" data-id="${g.id}">Delete garment</button>
      ${g.status !== "archived" ? `<button class="btn" data-action="archive" data-id="${g.id}">Archive (gave away, sold)</button>` : ""}</div>`,
    `<button class="icon-btn fav" data-action="favorite" data-id="${g.id}" aria-pressed="${!!g.favorite}" aria-label="Favourite" title="Favourite">${ICON_STAR}</button>`);
  el.dataset.garment = g.id;
  return g;
}

async function refreshAfterChange() {
  const top = sheets[sheets.length - 1];
  if (top?.dataset.garment) await openGarment(top.dataset.garment, top);
  if (currentView() === "wardrobe") { await loadGarments(); drawGrid(); }
}

// ------------------------------------------------------------------ edit form
function garmentForm(g, isNew) {
  const t = S.meta.taxonomy;
  const cat = g.category || "top";
  const opt = (list, val, labels = {}) => list.map((v) => `<option value="${esc(v)}" ${String(v) === String(val ?? "") ? "selected" : ""}>${esc(labels[v] || human(v))}</option>`).join("");
  const radios = (name, list, val, labels = {}) => list.map((v) => `<label><input type="radio" name="${name}" value="${v}" ${String(v) === String(val) ? "checked" : ""}>${esc(labels[v] || human(v))}</label>`).join("");
  const checks = (name, list, vals = []) => list.map((v) => `<label class="chip"><input type="checkbox" name="${name}" value="${v}" ${vals.includes(v) ? "checked" : ""}>${esc(human(v))}</label>`).join("");
  const dotsPick = (name, val) => [1, 2, 3, 4, 5].map((n) => `<label><input type="radio" name="${name}" value="${n}" ${n === Number(val || 3) ? "checked" : ""}>${n}</label>`).join("");
  const c = g.care || {};
  const careSel = (k, labels) => `<label class="field"><span>${esc(labels.title)}</span><select name="care_${k}"><option value="">-</option>${opt(t.care_fields[k], c[k], labels)}</select></label>`;
  return `
  <form class="form-grid" id="gform" data-id="${g.id || ""}" data-new="${isNew ? 1 : 0}">
    ${g.intake ? (g.intake.used ? `<div class="note small">Filled in from the photo by ${esc(g.intake.provider)}. Check it before saving.</div>`
      : g.intake.error ? `<div class="note warn small">The AI couldn't read the photo (${esc(g.intake.error)}). Colours came from the photo; fill in the rest.</div>`
      : `<div class="note small">Colours were read from the photo. Fill in the rest.</div>`) : ""}
    <div class="name-row">
      <label class="field"><span>Name</span><input type="text" name="name" required value="${esc(g.name === "New garment" ? "" : g.name)}" placeholder="Navy merino crewneck" autofocus></label>
      <label class="fav-toggle" title="Favourite"><input type="checkbox" name="favorite" aria-label="Favourite" ${g.favorite ? "checked" : ""}>${ICON_STAR}</label>
    </div>
    <div class="grid2">
      <label class="field"><span>Category</span><select name="category">${opt(Object.keys(t.categories), cat, Object.fromEntries(Object.entries(t.categories).map(([k, v]) => [k, v.label])))}</select></label>
      <label class="field"><span>Type</span><select name="subcategory"><option value="">-</option>${opt(t.categories[cat].sub, g.subcategory)}</select></label>
    </div>
    <div class="grid2">
      <label class="field"><span>Brand</span><input type="text" name="brand" value="${esc(g.brand)}"></label>
      <label class="field"><span>Size on label</span><input type="text" name="size_label" value="${esc(g.size_label)}" placeholder="M, 38, 32/32"></label>
    </div>
    <fieldset><legend>Intended fit</legend><div class="seg">${radios("fit_type", t.fit_types, g.fit_type || "regular")}</div></fieldset>
    <fieldset><legend>Colours, main colour first</legend><div class="colour-edit" id="colours">
      ${(g.colors?.length ? g.colors : ["#888888"]).map((hx) => `<label><input type="color" name="color" value="${esc(hx)}" aria-label="Colour"></label>`).join("")}
      <button type="button" class="btn ghost" data-action="add-colour">Add colour</button><button type="button" class="btn ghost" data-action="remove-colour">Remove last</button></div></fieldset>
    <div class="grid2">
      <label class="field"><span>Pattern</span><select name="pattern">${opt(t.patterns, g.pattern || "solid")}</select></label>
      <label class="field"><span>Fabric</span><input type="text" name="material" value="${esc(g.material)}" placeholder="80% wool, 20% nylon"></label>
    </div>
    <div class="grid2">
      <fieldset><legend>Formality (1 lounge, 5 formal)</legend><div class="dotpick">${dotsPick("formality", g.formality)}</div></fieldset>
      <fieldset><legend>Warmth (1 summer, 5 winter)</legend><div class="dotpick">${dotsPick("warmth", g.warmth)}</div></fieldset>
    </div>
    <fieldset><legend>Seasons (leave empty for all year)</legend><div class="chips wrap">${checks("seasons", t.seasons, g.seasons)}</div></fieldset>
    <fieldset><legend>Occasions</legend><div class="chips wrap">${checks("occasions", t.occasions, g.occasions)}</div></fieldset>

    <div class="section-title spread"><span>Care</span><button type="button" class="btn ghost" data-action="care-defaults">Use defaults for this fabric</button></div>
    <div class="grid2">
      ${careSel("wash", { title: "Washing", machine: "Machine", hand: "Hand wash", dry_clean: "Dry clean only", spot: "Spot clean", no_wash: "Do not wash" })}
      ${careSel("temp", { title: "Max temperature", 20: "20 °C", 30: "30 °C", 40: "40 °C", 60: "60 °C", 90: "90 °C" })}
      ${careSel("cycle", { title: "Programme" })}
      ${careSel("dry", { title: "Drying", tumble_normal: "Tumble normal", tumble_low: "Tumble low", no_tumble: "No tumble", line: "Line dry", flat: "Dry flat" })}
      ${careSel("iron", { title: "Ironing", no: "Do not iron" })}
      ${careSel("dry_clean", { title: "Dry cleaning", any: "Allowed", P: "P solvent", F: "F solvent", no: "Not allowed" })}
      <label class="field"><span>Wash after how many wears (0 = don't track)</span><input type="number" name="care_wash_after" min="0" max="50" value="${esc(c.wash_after ?? "")}"></label>
    </div>
    <label class="field"><span>Care notes</span><input type="text" name="care_notes" value="${esc(c.notes)}" placeholder="Inside out, no softener"></label>

    <div class="section-title">Measurements (cm)</div>
    <p class="small muted" style="margin:-4px 0 0">Lay it flat. For chest, waist and hips, double the flat width.</p>
    <div class="grid3" id="gmeasure">${measureInputs(cat, g.measurements)}</div>

    <div class="section-title">Purchase</div>
    <div class="grid2">
      <label class="field"><span>Price (€)</span><input type="number" step="0.01" min="0" name="price" value="${esc(g.price ?? "")}"></label>
      <label class="field"><span>Bought on</span><input type="date" name="purchase_date" value="${esc(g.purchase_date || "")}"></label>
    </div>
    <label class="field"><span>Notes</span><textarea name="notes">${esc(g.notes)}</textarea></label>
    <div class="actions"><button class="btn primary" type="submit">Save</button>
      ${isNew && g.id ? `<button class="btn danger" type="button" data-action="discard-draft" data-id="${g.id}">Discard</button>` : `<button class="btn" type="button" data-action="close-sheet">Cancel</button>`}</div>
  </form>`;
}

function measureInputs(cat, m = {}) {
  const keys = S.meta.taxonomy.garment_keys[cat] || [];
  if (!keys.length) return `<p class="small muted">No measurements for this category.</p>`;
  const label = { chest: "Chest", waist: "Waist", hips: "Hips", shoulder: "Shoulders", sleeve: "Sleeve", length: "Length", inseam: "Inseam", rise: "Rise", shoe_eu: "EU size" };
  return keys.map((k) => `<label class="field"><span>${label[k] || k}</span><input type="number" step="0.5" min="0" name="m_${k}" value="${esc(m?.[k] ?? "")}"></label>`).join("");
}

function editGarment(g, isNew = false, existing = null) {
  const title = isNew ? "New garment" : `Edit ${g.name}`;
  const el = existing || openSheet(title, "");
  fillSheet(el, title, garmentForm(g, isNew));
  delete el.dataset.garment;
  const form = $("#gform", el);
  form.category.onchange = () => {
    const cat = form.category.value;
    form.subcategory.innerHTML = `<option value="">-</option>` + S.meta.taxonomy.categories[cat].sub.map((s) => `<option value="${s}">${cap(s)}</option>`).join("");
    const m = Object.fromEntries($$("#gmeasure input", el).map((i) => [i.name.slice(2), i.value]));
    $("#gmeasure", el).innerHTML = measureInputs(cat, m);
  };
  form.onsubmit = (ev) => { ev.preventDefault(); busy(ev.submitter, () => saveGarment(form, g, isNew)); };
  if (isNew && g.id) el.addEventListener("sheetclose", () => { if (!el.dataset.saved) api("DELETE", `api/garments/${g.id}`).then(refreshAfterChange).catch(() => {}); });
}

function readGarmentForm(form) {
  const f = new FormData(form);
  const care = {};
  for (const k of ["wash", "temp", "cycle", "dry", "iron", "dry_clean"]) { const v = f.get("care_" + k); if (v) care[k] = k === "temp" ? Number(v) : v; }
  care.wash_after = Number(f.get("care_wash_after") || 0);
  care.notes = f.get("care_notes") || "";
  const measurements = {};
  for (const [k, v] of f.entries()) if (k.startsWith("m_") && v !== "") measurements[k.slice(2)] = Number(v);
  return {
    name: f.get("name"), category: f.get("category"), subcategory: f.get("subcategory"), brand: f.get("brand"),
    size_label: f.get("size_label"), fit_type: f.get("fit_type"), colors: f.getAll("color"), pattern: f.get("pattern"),
    material: f.get("material"), formality: Number(f.get("formality")), warmth: Number(f.get("warmth")),
    seasons: f.getAll("seasons"), occasions: f.getAll("occasions"), care, measurements,
    price: f.get("price") || null, purchase_date: f.get("purchase_date") || null, favorite: f.get("favorite") === "on",
    notes: f.get("notes"),
  };
}

async function saveGarment(form, g, isNew) {
  const data = readGarmentForm(form);
  const el = form.closest(".sheet");
  let saved;
  if (g.id) saved = await api("PUT", `api/garments/${g.id}`, data);
  else saved = await api("POST", "api/garments", { ...data, profile_id: S.profileId });
  el.dataset.saved = "1";
  toast(isNew ? "Garment added" : "Saved");
  closeSheet();
  if (currentView() === "wardrobe") { await loadGarments(); drawGrid(); }
  const top = sheets[sheets.length - 1];
  if (top?.dataset.garment) await openGarment(top.dataset.garment, top);
  else if (isNew) openGarment(saved.id);
}

// ------------------------------------------------------------------ photo intake
// Shrink on the phone before upload: faster over remote access, and EXIF (GPS) never leaves the device.
async function shrink(file, max = 2048) {
  try {
    if (!/^image\//.test(file.type) || !window.createImageBitmap) return file;
    const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
    const k = Math.min(1, max / Math.max(bmp.width, bmp.height));
    const c = document.createElement("canvas");
    c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
    c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
    const blob = await new Promise((r) => c.toBlob(r, "image/jpeg", 0.9));
    return blob ? new File([blob], "photo.jpg", { type: "image/jpeg" }) : file;
  } catch { return file; } // the server can still read and resize the original
}

async function intake(file) {
  file = await shrink(file);
  const el = openSheet("New garment", loading(S.meta.ai.vision.enabled ? "Reading the photo" : "Saving the photo"));
  const fd = new FormData(); fd.append("file", file); fd.append("profile_id", S.profileId);
  try {
    const g = await api("POST", "api/intake", fd);
    editGarment(g, true, el);
    $(".sheet-body", el).insertAdjacentHTML("afterbegin", `<div class="gallery" style="margin-bottom:14px"><figure><img src="${media(g.photo)}" alt=""></figure></div>`);
  } catch (e) { closeSheet(); fail(e); }
}

async function uploadPhoto(garmentId, kind, file) {
  file = await shrink(file, kind === "label" ? 2400 : 2048);
  const fd = new FormData(); fd.append("file", file); fd.append("kind", kind);
  if (kind === "label") {
    toast(S.meta.ai.vision.enabled ? "Reading the care label" : "Saving the label photo");
    const res = await api("POST", `api/garments/${garmentId}/care-label`, fd);
    if (res.read) toast(`Care read from the label (${res.read.confidence} confidence). Check it.`);
    else if (res.message) toast(res.message);
  } else {
    await api("POST", `api/garments/${garmentId}/photos`, fd);
    toast("Photo added");
  }
  await refreshAfterChange();
}

// ------------------------------------------------------------------ fit log
function fitLogSheet(gid) {
  const g = S.garments.find((x) => x.id === Number(gid)) || {};
  const areasByCat = { top: ["shoulders", "chest", "waist", "sleeves", "length"], knitwear: ["shoulders", "chest", "sleeves", "length"],
    outerwear: ["shoulders", "chest", "sleeves", "length"], dress: ["shoulders", "chest", "waist", "hips", "length"],
    bottom: ["waist", "hips", "rise", "length"], shoes: [], accessory: [] };
  const areas = areasByCat[g.category] || ["chest", "waist", "length"];
  const overall = S.meta.taxonomy.fit_overall;
  const names = { too_small: "Too small", slightly_small: "A bit small", right: "Right", slightly_big: "A bit big", too_big: "Too big" };
  const scale = [[-2, "Tight"], [-1, "Snug"], [0, "Fine"], [1, "Roomy"], [2, "Loose"]];
  const el = openSheet(`How does it fit?`, `
    <form class="form-grid" id="fitform">
      <fieldset><legend>Overall</legend><div class="seg">${overall.map((o) => `<label><input type="radio" name="overall" value="${o}" ${o === "right" ? "checked" : ""}>${names[o]}</label>`).join("")}</div></fieldset>
      ${areas.length ? `<fieldset><legend>Where (for length and sleeves: tight means short, loose means long)</legend><div class="area-grid">${areas.map((a) => `
        <div class="area"><span>${cap(a)}</span><div class="seg">${scale.map(([v, l]) => `<label><input type="radio" name="a_${a}" value="${v}" ${v === 0 ? "checked" : ""}>${l}</label>`).join("")}</div></div>`).join("")}</div></fieldset>` : ""}
      <label class="field"><span>Notes</span><input type="text" name="notes" placeholder="Pulls at the buttons when seated"></label>
      <label class="field"><span>Photo of you wearing it (optional)${S.meta.ai.vision.enabled ? ", for an AI fit check" : ""}</span><input type="file" name="file" accept="image/*"></label>
      <button class="btn primary" type="submit" data-busy="${S.meta.ai.vision.enabled ? "Checking fit" : ""}">Save fit note</button>
    </form><div id="fitresult"></div>`);
  $("#fitform", el).onsubmit = (ev) => {
    ev.preventDefault();
    const f = new FormData(ev.target);
    const out = new FormData();
    out.append("overall", f.get("overall"));
    const ar = {}; for (const a of areas) { const v = Number(f.get("a_" + a)); if (v) ar[a] = v; }
    out.append("areas", JSON.stringify(ar));
    out.append("notes", f.get("notes") || "");
    const file = f.get("file");
    busy(ev.submitter, async () => {
      if (file && file.size) out.append("file", await shrink(file));
      const log = await api("POST", `api/garments/${gid}/fit-log`, out);
      if (log.ai_critique || log.ai_error) {
        $("#fitform", el).remove();
        $("#fitresult", el).innerHTML = `${log.ai_critique ? `<div class="note prose">${esc(log.ai_critique)}</div>` : `<div class="note warn">AI fit check failed: ${esc(log.ai_error)}</div>`}
          <div class="actions"><button class="btn primary" data-action="close-sheet">Done</button></div>`;
        el.addEventListener("sheetclose", refreshAfterChange);
      } else { toast("Fit note saved"); closeSheet(); refreshAfterChange(); }
    });
  };
}

// ------------------------------------------------------------------ looks
function lookCard(lk, i, saved = false) {
  const items = lk.items.map((g) => `<figure>${g.photo ? `<img src="${thumb(g.photo)}" alt="">` : `<div class="none"></div>`}<figcaption>${esc(g.name)}</figcaption></figure>`).join("");
  const reasons = [...(lk.reasons || []).map((r) => `<li>${esc(r)}</li>`), ...(lk.warnings || []).map((w) => `<li class="warn">${esc(w)}</li>`)].join("");
  const sc = saved ? lk.score?.score : lk.score;
  return `<article class="look">
    <div class="spread"><div>${saved ? `<h3>${esc(lk.name || "Untitled look")}</h3><div class="small muted">${esc(cap(lk.occasion) || "Any occasion")}${lk.rating ? `, rated ${lk.rating}/5` : ""}</div>` : `<h3>${i === 0 ? "Best match" : `Option ${i + 1}`}</h3>`}</div>
      ${sc != null ? `<div class="score" title="Match score">${sc}<small>/100</small></div>` : ""}</div>
    <div class="strip">${items}</div>
    ${lk.ai ? `<div class="note ai-pick"><strong>Why:</strong> ${esc(lk.ai.why)}<br><strong>Tip:</strong> ${esc(lk.ai.tip)}</div>` : ""}
    ${reasons && !saved ? `<ul class="reasons">${reasons}</ul>` : ""}
    <div class="actions">${saved
      ? `<button class="btn" data-action="wear-look" data-id="${lk.id}">Wore this today</button><button class="btn" data-action="edit-look" data-id="${lk.id}">Edit</button><button class="btn ghost danger" data-action="delete-look" data-id="${lk.id}">Delete</button>`
      : `<button class="btn" data-action="wear-suggestion" data-i="${i}">Wore this today</button><button class="btn" data-action="save-suggestion" data-i="${i}">Save look</button>`}</div>
  </article>`;
}

async function renderLooks(main) {
  const t = S.meta.taxonomy;
  let weather = null;
  if (S.meta.weather_configured) weather = await api("GET", "api/weather").catch(() => null);
  if (S.look.temp === "" && weather?.temperature != null) S.look.temp = Math.round(weather.temperature);
  const saved = await api("GET", `api/looks?profile_id=${S.profileId}`);
  main.innerHTML = `
    <h1>Looks</h1>
    <p class="lede">${weather?.temperature != null ? `Outside: ${Math.round(weather.temperature)} °C, ${esc(human(weather.condition))}. ` : ""}Pick the occasion and temperature; the app puts together what works from clean clothes.</p>
    <div class="panel context">
      <div class="chips wrap" role="radiogroup" aria-label="Occasion">${t.occasions.map((o) => `<button class="chip" aria-pressed="${S.look.occasion === o}" data-action="occasion" data-o="${o}">${cap(o)}</button>`).join("")}</div>
      <div class="row"><label class="temp"><span class="small muted">Temperature</span><input type="number" id="temp" value="${esc(S.look.temp)}" placeholder="12" aria-label="Temperature in °C"><span class="small muted">°C</span></label></div>
      ${S.anchor ? `<div class="row"><span class="chip" aria-pressed="true">Built around: ${esc(S.anchor.name)}</span><button class="btn ghost" data-action="clear-anchor">Clear</button></div>` : ""}
      <div class="row"><button class="btn primary" data-action="suggest" data-busy="Matching">Suggest looks</button>
        ${S.meta.ai.text.enabled ? `<button class="btn" data-action="suggest-ai" data-busy="Asking ${esc(S.meta.ai.text.provider)}">Let AI pick</button>` : ""}
        <button class="btn ghost" data-action="build-look">Build your own</button></div>
    </div>
    <div id="suggestions">${S.suggestions ? suggestionsHtml(S.suggestions) : ""}</div>
    <h2>Saved looks</h2>
    ${saved.length ? saved.map((lk, i) => lookCard(lk, i, true)).join("") : `<p class="muted">Save a suggestion or build your own to keep it here.</p>`}`;
  $("#temp").oninput = (ev) => { S.look.temp = ev.target.value; };
  if (S.anchor && !S.suggestions) suggest($('[data-action="suggest"]'));
}

function suggestionsHtml(res) {
  if (!res.looks.length) return `<div class="empty" style="margin-top:14px"><h3>No good matches</h3><p class="muted">Add more clean pieces: at least a top, a bottom and shoes. Things in the wash are left out.</p></div>`;
  const aiNote = res.ai?.error ? `<div class="note warn small" style="margin-top:12px">AI pick failed: ${esc(res.ai.error)}. Showing the app's own ranking.</div>` : "";
  return `${aiNote}<div style="margin-top:14px">${res.looks.map((lk, i) => lookCard(lk, i)).join("")}</div>`;
}

async function suggest(btn, ai = false) {
  await busy(btn, async () => {
    const temp = S.look.temp === "" ? null : Number(S.look.temp);
    S.suggestions = await api("POST", "api/suggest", { profile_id: S.profileId, occasion: S.look.occasion, temp, anchor_id: S.anchor?.id, ai, use_weather: false });
    const box = $("#suggestions"); if (box) box.innerHTML = suggestionsHtml(S.suggestions);
  });
}

async function buildLook(existing) {
  const garments = (await loadGarments()).filter((g) => !["archived"].includes(g.status));
  const chosen = new Set(existing ? existing.items.map((g) => g.id) : []);
  const el = openSheet(existing ? "Edit look" : "Build a look", `
    <div class="panel" id="evalbox"><span class="muted small">Pick two or more pieces.</span></div>
    <div class="grid2" style="margin:12px 0"><label class="field"><span>Name</span><input type="text" id="lookname" value="${esc(existing?.name || "")}" placeholder="Friday office"></label>
      <label class="field"><span>Rating</span><select id="lookrating"><option value="">-</option>${[1, 2, 3, 4, 5].map((n) => `<option ${existing?.rating === n ? "selected" : ""}>${n}</option>`).join("")}</select></label></div>
    <div class="picker">${garments.map((g) => `<button aria-pressed="${chosen.has(g.id)}" data-pick="${g.id}">${pic(g)}<span>${esc(g.name)}</span></button>`).join("")}</div>
    <div class="actions"><button class="btn primary" id="savelook">Save look</button></div>`);
  const evaluate = async () => {
    const box = $("#evalbox", el);
    if (chosen.size < 2) { box.innerHTML = `<span class="muted small">Pick two or more pieces.</span>`; return; }
    const r = await api("POST", "api/evaluate", { garment_ids: [...chosen], occasion: S.look.occasion, temp: S.look.temp === "" ? null : Number(S.look.temp) }).catch(fail);
    if (!r) return;
    box.innerHTML = `<div class="spread"><strong>${chosen.size} pieces</strong><span class="score">${r.score}<small>/100</small></span></div>
      <ul class="reasons">${r.reasons.map((x) => `<li>${esc(x)}</li>`).join("")}${r.warnings.map((x) => `<li class="warn">${esc(x)}</li>`).join("")}</ul>`;
  };
  $(".picker", el).onclick = (ev) => {
    const b = ev.target.closest("[data-pick]"); if (!b) return;
    const id = Number(b.dataset.pick);
    chosen.has(id) ? chosen.delete(id) : chosen.add(id);
    b.setAttribute("aria-pressed", chosen.has(id));
    evaluate();
  };
  $("#savelook", el).onclick = (ev) => busy(ev.currentTarget, async () => {
    const body = { profile_id: S.profileId, name: $("#lookname", el).value, rating: $("#lookrating", el).value || null, garment_ids: [...chosen], occasion: existing?.occasion || S.look.occasion };
    if (existing) await api("PUT", `api/looks/${existing.id}`, body); else await api("POST", "api/looks", body);
    toast("Look saved"); closeSheet(); route();
  });
  evaluate();
}

// ------------------------------------------------------------------ fit tab
async function renderFit(main) {
  const [ov] = await Promise.all([api("GET", `api/fit/overview?profile_id=${S.profileId}`), loadGarments()]);
  const keys = S.meta.taxonomy.body_keys;
  main.innerHTML = `
    <h1>Fit</h1>
    <p class="lede">Your measurements against each garment's, plus what you've noted while wearing them. ${ov.measured_garments} garment${ov.measured_garments === 1 ? " has" : "s have"} measurements so far.</p>
    <form class="panel form-grid" id="bodyform">
      <div class="spread"><h3>${esc(profile()?.name)}'s measurements</h3><span class="small muted">cm, shoe size EU</span></div>
      <div class="grid3">${Object.entries(keys).map(([k, l]) => `<label class="field"><span>${esc(l)}</span><input type="number" step="0.5" min="0" name="${k}" value="${esc(ov.measurements[k] ?? "")}"></label>`).join("")}</div>
      <p class="small muted" style="margin:0">Measure over a thin layer. Chest at the fullest point, waist at the narrowest, hips at the widest. Shoulder: seam to seam across the back.</p>
      <button class="btn primary" type="submit" style="justify-self:start">Save measurements</button>
    </form>
    <h2>Check these</h2>
    ${ov.flagged.length ? `<ul class="list">${ov.flagged.map((f) => `<li><button class="linkish" data-action="open-garment" data-id="${f.id}">${f.photo ? `<img class="thumb" src="${thumb(f.photo)}" alt="">` : `<span class="thumb"></span>`}<span class="grow"><span class="title">${esc(f.name)}</span><br><span class="small muted">${esc(f.summary)}</span></span></button></li>`).join("")}</ul>`
      : `<p class="muted">Nothing flagged. Add garment measurements or log how things fit to fill this in.</p>`}
    <h2>How brands size you</h2>
    ${ov.brands.length ? `<ul class="list">${ov.brands.map((b) => `<li><div class="grow"><span class="title">${esc(b.brand)}</span> <span class="muted">size ${esc(b.size)}</span><br><span class="small">${esc(cap(b.advice))}</span></div><span class="small muted">${b.logs} note${b.logs > 1 ? "s" : ""}</span></li>`).join("")}</ul>`
      : `<p class="muted">Log fit on a few garments with a brand and size, and this shows which brands run small or large on you.</p>`}
    <h2>Recent fit notes</h2>
    ${ov.recent_logs.length ? `<ul class="list">${ov.recent_logs.map((l) => `<li><button class="linkish" data-action="open-garment" data-id="${l.garment_id}"><span class="grow"><span class="title">${esc(l.garment)}</span> <span class="small muted">${day(l.logged_on)}</span><br><span class="small">${esc(human(l.overall))}${l.notes ? `: ${esc(l.notes)}` : ""}</span>${l.ai_critique ? `<br><span class="small muted">${esc(l.ai_critique.slice(0, 140))}${l.ai_critique.length > 140 ? "..." : ""}</span>` : ""}</span></button></li>`).join("")}</ul>`
      : `<p class="muted">Open a garment and tap Log fit after wearing it.</p>`}`;
  $("#bodyform").onsubmit = (ev) => {
    ev.preventDefault();
    const f = new FormData(ev.target);
    const m = {}; for (const k of Object.keys(keys)) { const v = f.get(k); if (v) m[k] = Number(v); }
    busy(ev.submitter, async () => { await api("PUT", `api/profiles/${S.profileId}`, { measurements: m }); toast("Measurements saved"); route(); });
  };
}

// ------------------------------------------------------------------ care tab
async function renderCare(main) {
  const res = await api("GET", `api/laundry${S.laundryAll ? "" : `?profile_id=${S.profileId}`}`);
  const many = S.meta.profiles.length > 1;
  const itemRow = (g, action) => `<li>${g.photo ? `<img class="thumb" src="${thumb(g.photo)}" alt="">` : `<span class="thumb"></span>`}
      <button class="linkish grow" data-action="open-garment" data-id="${g.id}"><span class="grow"><span class="title">${esc(g.name)}</span><br><span class="small muted">${esc(careLine(g.care))}</span></span></button>
      ${many ? ownerDot(g.profile_id) : ""}${action}</li>`;
  main.innerHTML = `
    <h1>Care</h1>
    <p class="lede">The wash basket, sorted into loads by programme, temperature and colour. Everything washes at the lowest temperature in its load.</p>
    ${many ? `<div class="seg" style="max-width:320px;margin-bottom:12px"><label><input type="radio" name="scope" value="all" ${S.laundryAll ? "checked" : ""} data-change="scope">Everyone</label><label><input type="radio" name="scope" value="mine" ${S.laundryAll ? "" : "checked"} data-change="scope">Only ${esc(profile()?.name)}</label></div>` : ""}
    ${res.loads.length ? res.loads.map((l) => `<section class="panel"><div class="spread"><h3>${esc(l.title)}</h3><span class="small muted">${l.items.length} item${l.items.length > 1 ? "s" : ""}</span></div>
        <ul class="list" style="margin:10px 0">${l.items.map((g) => itemRow(g, "")).join("")}</ul>
        <button class="btn primary" data-action="washed" data-ids="${l.items.map((g) => g.id).join(",")}">${l.method === "machine" || l.method === "hand" ? "Mark load washed" : "Mark as cleaned"}</button></section>`).join("")
      : `<div class="empty"><h3>The basket is empty</h3><p class="muted">Put things in the wash from a garment's page, or from the list below. They drop out of look suggestions until washed.</p></div>`}
    <h2>Due for a wash</h2>
    ${res.due.length ? `<ul class="list">${res.due.map((g) => itemRow(g, `<button class="btn" data-action="to-laundry" data-id="${g.id}">To the wash</button>`)).join("")}</ul>`
      : `<p class="muted">Nothing is due. The count comes from wears since the last wash, set per garment under Care.</p>`}`;
}

function careLine(c = {}) {
  const parts = [];
  if (c.wash === "machine") parts.push(`${c.temp || 30} °C ${c.cycle && c.cycle !== "normal" ? c.cycle + " programme" : "machine"}`);
  else if (c.wash === "hand") parts.push("Hand wash");
  else if (c.wash) parts.push(human(c.wash));
  if (c.dry) parts.push(human(c.dry).toLowerCase());
  return parts.join(", ");
}

// ------------------------------------------------------------------ shop tab
async function renderShop(main) {
  const r = await api("GET", `api/shopping?profile_id=${S.profileId}`);
  const maxU = Math.max(1, ...r.buys.map((b) => b.unlocks));
  const garmentRow = (g, extra = "") => `<li><button class="linkish" data-action="open-garment" data-id="${g.id}"><span class="grow"><span class="title">${esc(g.name)}</span>${extra ? `<br><span class="small muted">${extra}</span>` : ""}</span></button></li>`;
  main.innerHTML = `
    <h1>Shop</h1>
    <p class="lede">${r.total_outfits} good outfits from what you own. Ranked by how many new ones each purchase would add, so you buy for what's already in the wardrobe.</p>
    <h2>Best next buys</h2>
    ${r.buys.length ? `<ul class="list">${r.buys.map((b) => `<li><span class="swatch" style="background:${esc(b.color)}"></span>
        <div class="grow"><div class="spread"><span class="title">${esc(b.name)}</span><span class="small">+${b.unlocks} outfit${b.unlocks > 1 ? "s" : ""}</span></div>
        <div class="bar" style="margin-top:6px"><i style="width:${Math.round((b.unlocks / maxU) * 100)}%"></i></div></div>
        <button class="btn ghost" data-action="wish-add" data-title="${esc(b.name)}" data-cat="${b.category}" data-color="${esc(b.color)}" data-reason="Adds ${b.unlocks} outfits">Want</button></li>`).join("")}</ul>`
      : `<p class="muted">Add a few more garments (with shoes) and this fills in.</p>`}
    ${r.gaps.length ? `<h2>Gaps</h2><div class="stack">${r.gaps.map((g) => `<div class="note">${esc(g)}</div>`).join("")}</div>` : ""}
    ${r.saturated.length ? `<h2>Stop buying</h2><div class="stack">${r.saturated.map((g) => `<div class="note warn">${esc(cap(g))}</div>`).join("")}</div>` : ""}
    ${S.meta.ai.text.enabled ? `<div class="actions"><button class="btn" data-action="shop-ai" data-busy="Thinking">Get written advice</button></div><div id="shopai"></div>` : ""}
    ${r.hard_to_style.length ? `<h2>Hard to style</h2><p class="small muted" style="margin-top:-4px">No good outfit with what you have. Find it a partner or let it go.</p><ul class="list">${r.hard_to_style.map((g) => garmentRow(g)).join("")}</ul>` : ""}
    ${r.underused.length ? `<h2>Not worn in three months</h2><ul class="list">${r.underused.map((g) => garmentRow(g, g.last_worn ? `Last worn ${day(g.last_worn)}` : "Never worn")).join("")}</ul>` : ""}
    ${r.cost_per_wear.length ? `<h2>Cost per wear</h2><ul class="list">${r.cost_per_wear.map((g) => garmentRow(g, `${money(g.cost_per_wear)} per wear, ${g.wears} wear${g.wears === 1 ? "" : "s"}`)).join("")}</ul>` : ""}
    <h2>Wishlist</h2>
    <form class="panel form-grid" id="wishform">
      <div class="grid2"><label class="field"><span>What</span><input type="text" name="title" placeholder="Grey flannel trousers" required></label>
      <label class="field"><span>Priority</span><select name="priority"><option value="1">High</option><option value="2" selected>Medium</option><option value="3">Low</option></select></label></div>
      <label class="field"><span>Why (optional)</span><input type="text" name="reason"></label>
      <button class="btn" type="submit" style="justify-self:start">Add to wishlist</button>
    </form>
    ${r.wishlist.length ? `<ul class="list" style="margin-top:12px">${r.wishlist.map((w) => `<li><div class="grow"><span class="title" style="${w.status !== "open" ? "text-decoration:line-through;opacity:.6" : ""}">${esc(w.title)}</span>
        <span class="small muted">${["", "high", "medium", "low"][w.priority]}${w.status !== "open" ? `, ${w.status}` : ""}</span>${w.reason ? `<br><span class="small">${esc(w.reason)}</span>` : ""}</div>
        ${w.status === "open" ? `<button class="btn ghost" data-action="wish-status" data-id="${w.id}" data-s="bought">Bought</button>` : ""}
        <button class="icon-btn" data-action="wish-delete" data-id="${w.id}" aria-label="Remove">${ICON_X}</button></li>`).join("")}</ul>` : ""}`;
  $("#wishform").onsubmit = (ev) => {
    ev.preventDefault();
    const f = new FormData(ev.target);
    busy(ev.submitter, async () => { await api("POST", "api/wishlist", { profile_id: S.profileId, title: f.get("title"), priority: Number(f.get("priority")), reason: f.get("reason") }); toast("Added to wishlist"); route(); });
  };
}

// ------------------------------------------------------------------ settings
function settingsSheet() {
  const ai = S.meta.ai;
  const aiLine = (k, what) => ai[k].enabled ? `${what}: ${cap(ai[k].provider)}${ai[k].model ? ` (${esc(ai[k].model)})` : ""}` : `${what}: off`;
  const look = appearance();
  const inHa = !!haRoot();
  const el = openSheet("Settings", `
    <h3>People</h3>
    <div class="stack" style="margin-top:10px">${S.meta.profiles.map((p) => `
      <form class="panel form-grid" data-profile="${p.id}">
        <div class="grid2"><label class="field"><span>Name</span><input type="text" name="name" value="${esc(p.name)}" required></label>
        <label class="field"><span>HA username</span><input type="text" name="ha_user" value="${esc(p.ha_user)}"></label></div>
        <label class="field"><span>Style notes, used by the AI stylist</span><textarea name="style_notes" placeholder="Smart casual, prefers muted colours, never skinny jeans">${esc(p.style_notes)}</textarea></label>
        <div class="row"><label class="row small"><input type="color" name="color" value="${esc(p.color)}" style="width:40px;height:32px;border:0;background:none"> Colour</label>
          <span style="flex:1"></span><button class="btn ghost danger" type="button" data-action="delete-profile" data-id="${p.id}" data-name="${esc(p.name)}">Delete</button><button class="btn" type="submit">Save</button></div>
      </form>`).join("")}
      <form class="row" id="addprofile"><input type="text" name="name" placeholder="Add a person" style="flex:1" required><button class="btn" type="submit">Add</button></form>
    </div>
    <h3 style="margin-top:24px">Appearance</h3>
    <div class="seg" style="margin-top:8px;max-width:400px">${[["ha", "HA theme"], ["auto", "Auto"], ["light", "Light"], ["dark", "Dark"]].map(([v, l]) => `<label><input type="radio" name="appearance" value="${v}" ${look === v ? "checked" : ""} data-change="appearance">${l}</label>`).join("")}</div>
    <p class="small muted">${inHa ? "HA theme follows the theme you use in Home Assistant, dark mode included." : "Not running inside Home Assistant here, so HA theme falls back to Auto."} Auto, Light and Dark use the app's own colours.</p>
    <h3 style="margin-top:24px">AI and Home Assistant</h3>
    <p class="small">${aiLine("vision", "Reading photos")}<br>${aiLine("text", "Styling and shopping advice")}<br>
      Weather: ${S.meta.weather_configured ? "from Home Assistant" : "not set"}${S.meta.ha_user?.name ? `<br>Signed in to Home Assistant as ${esc(S.meta.ha_user.display_name || S.meta.ha_user.name)}` : ""}</p>
    <p class="small muted">Change these in Home Assistant under Settings, Apps, Wardrobe, Configuration.</p>
    <h3 style="margin-top:24px">Backup</h3>
    <p class="small">Photos and data live in the app's data folder and are part of every Home Assistant backup. You can also <a href="api/export" download>download the data as JSON</a>.</p>
    <p class="small muted">Wardrobe ${esc(S.meta.version)}</p>`);
  $$("form[data-profile]", el).forEach((form) => {
    form.onsubmit = (ev) => {
      ev.preventDefault();
      const f = new FormData(form);
      busy(ev.submitter, async () => {
        await api("PUT", `api/profiles/${form.dataset.profile}`, { name: f.get("name"), ha_user: f.get("ha_user"), style_notes: f.get("style_notes"), color: f.get("color") });
        await loadMeta(); toast("Saved");
      });
    };
  });
  $("#addprofile", el).onsubmit = (ev) => {
    ev.preventDefault();
    const name = new FormData(ev.target).get("name");
    busy(ev.submitter, async () => { await api("POST", "api/profiles", { name, color: "#3f6a5a" }); await loadMeta(); closeSheet(); settingsSheet(); route(); });
  };
}

// ------------------------------------------------------------------ actions (event delegation)
const actions = {
  "close-sheet": () => closeSheet(),
  reload: () => route(),
  settings: () => settingsSheet(),
  profile: (b) => { S.profileId = Number(b.dataset.id); store.set("profile", S.profileId); S.suggestions = null; S.anchor = null; renderProfiles(); route(); },
  filter: (b) => { S.filter = b.dataset.f; store.set("filter", S.filter); $$(".chips .chip").forEach((c) => c.setAttribute("aria-pressed", c === b)); drawGrid(); },
  add: () => $("#intake-file").click(),
  "new-garment": () => editGarment({ name: "", category: S.filter in (S.meta.taxonomy.categories) ? S.filter : "top", colors: [], seasons: [], occasions: [], care: {} }, true),
  "open-garment": (b) => openGarment(b.dataset.id).catch((e) => { closeSheet(); fail(e); }),
  "edit-garment": async (b) => { const g = await api("GET", `api/garments/${b.dataset.id}`); editGarment(g); },
  "discard-draft": () => closeSheet(),
  "delete-garment": async (b) => {
    if (!(await confirmSheet("Delete this garment?", "Its photos, wear history and fit notes go too. To keep the history, archive it instead."))) return;
    await api("DELETE", `api/garments/${b.dataset.id}`); closeAllSheets(); toast("Deleted"); route();
  },
  archive: async (b) => { await api("PUT", `api/garments/${b.dataset.id}`, { status: "archived" }); closeAllSheets(); toast("Archived"); route(); },
  wear: (b) => busy(b, async () => { await api("POST", `api/garments/${b.dataset.id}/wear`, {}); toast("Logged for today"); await refreshAfterChange(); }),
  "style-this": (b) => { S.anchor = { id: Number(b.dataset.id), name: b.dataset.name }; S.suggestions = null; closeAllSheets(); if (currentView() === "looks") route(); else location.hash = "#/looks"; },
  favorite: async (b) => {
    const on = b.getAttribute("aria-pressed") !== "true";
    b.setAttribute("aria-pressed", on);
    try { await api("PUT", `api/garments/${b.dataset.id}`, { favorite: on }); }
    catch (e) { b.setAttribute("aria-pressed", !on); throw e; }
    const g = S.garments.find((x) => x.id === Number(b.dataset.id));
    if (g) g.favorite = on ? 1 : 0;
    toast(on ? "Marked as a favourite" : "No longer a favourite");
  },
  "fit-log": (b) => fitLogSheet(b.dataset.id),
  "del-fitlog": async (b) => { await api("DELETE", `api/fit-logs/${b.dataset.id}`); refreshAfterChange(); },
  "add-photo": (b) => { const inp = $("#photo-file"); inp.dataset.garment = b.dataset.id; inp.dataset.kind = b.dataset.kind; inp.click(); },
  "add-colour": () => { const box = $("#colours"); if ($$("input[type=color]", box).length >= 4) return; box.querySelector("button").insertAdjacentHTML("beforebegin", `<label><input type="color" name="color" value="#888888" aria-label="Colour"></label>`); },
  "remove-colour": () => { const all = $$("#colours label"); if (all.length > 1) all[all.length - 1].remove(); },
  "care-defaults": async () => {
    const form = $("#gform");
    const c = await api("GET", `api/care/defaults?material=${encodeURIComponent(form.material.value)}&category=${form.category.value}`);
    for (const k of ["wash", "temp", "cycle", "dry", "iron", "dry_clean"]) if (form["care_" + k]) form["care_" + k].value = c[k] ?? "";
    form.care_wash_after.value = c.wash_after ?? 0; form.care_notes.value = c.notes || "";
    toast(form.material.value ? `Care set for ${form.material.value}` : "Generic care set; add the fabric for better defaults");
  },
  occasion: (b) => { S.look.occasion = b.dataset.o; store.set("occasion", S.look.occasion); $$('[data-action="occasion"]').forEach((c) => c.setAttribute("aria-pressed", c === b)); },
  "clear-anchor": () => { S.anchor = null; S.suggestions = null; route(); },
  suggest: (b) => suggest(b, false),
  "suggest-ai": (b) => suggest(b, true),
  "build-look": () => buildLook(),
  "wear-suggestion": (b) => busy(b, async () => { const lk = S.suggestions.looks[b.dataset.i]; await api("POST", "api/wear", { garment_ids: lk.items.map((g) => g.id) }); toast("Logged for today"); }),
  "save-suggestion": (b) => busy(b, async () => {
    const lk = S.suggestions.looks[b.dataset.i];
    const name = `${cap(S.look.occasion)}${S.look.temp !== "" ? `, ${S.look.temp} °C` : ""}`;
    await api("POST", "api/looks", { profile_id: S.profileId, name, occasion: S.look.occasion, source: "suggested", garment_ids: lk.items.map((g) => g.id) });
    toast("Look saved"); b.textContent = "Saved"; b.disabled = true;
  }),
  "wear-look": (b) => busy(b, async () => { await api("POST", `api/looks/${b.dataset.id}/wear`, {}); toast("Logged for today"); }),
  "edit-look": async (b) => { const looks = await api("GET", `api/looks?profile_id=${S.profileId}`); buildLook(looks.find((l) => l.id === Number(b.dataset.id))); },
  "delete-look": async (b) => { if (await confirmSheet("Delete this look?", "The garments stay; only the saved combination goes.")) { await api("DELETE", `api/looks/${b.dataset.id}`); route(); } },
  washed: (b) => busy(b, async () => { await api("POST", "api/laundry/done", { ids: b.dataset.ids.split(",").map(Number) }); toast("Back in the wardrobe"); route(); }),
  "to-laundry": (b) => busy(b, async () => { await api("PUT", `api/garments/${b.dataset.id}`, { status: "laundry" }); route(); }),
  "wish-add": (b) => busy(b, async () => { await api("POST", "api/wishlist", { profile_id: S.profileId, title: b.dataset.title, category: b.dataset.cat, colors: [b.dataset.color], reason: b.dataset.reason }); toast("Added to wishlist"); route(); }),
  "wish-status": async (b) => { await api("PUT", `api/wishlist/${b.dataset.id}`, { status: b.dataset.s }); route(); },
  "wish-delete": async (b) => { await api("DELETE", `api/wishlist/${b.dataset.id}`); route(); },
  "shop-ai": (b) => busy(b, async () => { const r = await api("POST", "api/shopping/ai", { profile_id: S.profileId }); $("#shopai").innerHTML = `<div class="panel prose" style="margin-top:12px">${esc(r.advice)}</div>`; }),
  "delete-profile": async (b) => {
    if (!(await confirmSheet(`Delete ${b.dataset.name}?`, "All of their garments, photos, looks and fit notes are deleted. This can't be undone."))) return;
    await api("DELETE", `api/profiles/${b.dataset.id}`); store.set("profile", null); await loadMeta(); closeAllSheets(); route();
  },
};

document.addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-action]");
  if (!b || !actions[b.dataset.action]) return;
  ev.preventDefault();
  Promise.resolve(actions[b.dataset.action](b, ev)).catch(fail);
});

document.addEventListener("change", (ev) => {
  const el = ev.target;
  if (el.dataset.change === "status") {
    api("PUT", `api/garments/${el.dataset.id}`, { status: el.value })
      .then(() => { toast({ active: "Back in the wardrobe", laundry: "In the wash", repair: "At the tailor", stored: "Stored away" }[el.value]); return refreshAfterChange(); })
      .catch(fail);
  } else if (el.dataset.change === "scope") { S.laundryAll = el.value === "all"; route(); }
  else if (el.dataset.change === "appearance") { store.set("appearance", el.value); applyTheme(); }
});

$("#intake-file").addEventListener("change", (ev) => { const f = ev.target.files[0]; ev.target.value = ""; if (f) intake(f); });
$("#photo-file").addEventListener("change", (ev) => {
  const f = ev.target.files[0]; const { garment, kind } = ev.target.dataset; ev.target.value = "";
  if (f) uploadPhoto(garment, kind, f).catch(fail);
});
$("#backdrop").addEventListener("click", closeSheet);
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && sheets.length) closeSheet(); });
window.addEventListener("hashchange", () => { closeAllSheets(); route(); });

(async function boot() {
  applyTheme();
  if ("scrollRestoration" in history) history.scrollRestoration = "manual";
  if (historyDepth()) history.replaceState(null, "");
  try { await loadMeta(); } catch (e) { $("#main").innerHTML = `<div class="empty"><h3>Can't reach the wardrobe service</h3><p class="muted">${esc(e.message)}</p></div>`; return; }
  route();
})();
