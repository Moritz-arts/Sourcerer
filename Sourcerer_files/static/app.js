// Sourcerer's window: artist cards, the card dialog, settings, the activity bar.
// Plain DOM code, no framework, no build step -- the same as TrackImage.

var S = {
  artists: [], sync: {}, library: "", window: false, sep: "/", sites: [], fields: [], settings: {},
  selected: null, menuFor: null, logFilter: "all", logSeen: "", update: null
};
var F = null;   // the card dialog's working copy: {id, sources, layout, dedupe, master, autoName}
var DEFAULT_SIZE = 230;

function $(id) { return document.getElementById(id); }
function $$(sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)); }
function esc(text) {
  return String(text == null ? "" : text).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}
function icon(name, cls) {
  return '<svg class="ic' + (cls ? " " + cls : "") + '"><use href="#i-' + name + '"/></svg>';
}

function api(method, path, body) {
  return fetch(path, {
    method: method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined
  }).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (data) {
      if (!r.ok) throw new Error(data.error || ("HTTP " + r.status));
      return data;
    });
  });
}

function toast(text, error) {
  var t = document.createElement("div");
  t.className = "toast" + (error ? " error" : "");
  t.innerHTML = icon(error ? "alert" : "check") + "<span>" + esc(text) + "</span>";
  $("toasts").appendChild(t);
  setTimeout(function () { t.remove(); }, error ? 6000 : 2500);
}
function fail(e) { toast(e.message || String(e), true); }

// ---- small formatters ------------------------------------------------------

function utc(iso) {
  // SQLite's datetime('now') is UTC without a zone mark.
  return iso ? new Date(iso.replace(" ", "T") + (/[zZ+]/.test(iso.slice(10)) ? "" : "Z")) : null;
}
function ago(iso) {
  var d = utc(iso);
  if (!d || isNaN(d)) return "never";
  var s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return Math.floor(s / 60) + " min ago";
  if (s < 86400) return Math.floor(s / 3600) + " h ago";
  var days = Math.floor(s / 86400);
  return days === 1 ? "yesterday" : days + " days ago";
}
function clock(iso) {
  var d = utc(iso);
  return d && !isNaN(d) ? d.toTimeString().slice(0, 5) : "";
}
function bytes(n) {
  if (!n) return "0 B";
  var units = ["B", "KB", "MB", "GB"], i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return (i ? n.toFixed(1) : n) + " " + units[i];
}
function plural(n, one, many) { return n + " " + (n === 1 ? one : (many || one + "s")); }
function shortUrl(url) { return url.replace(/^https?:\/\/(www\.)?/, ""); }
// The end of a path is what tells folders apart: …/Library/Inkwell.
function shortPath(path) {
  var parts = path.split(/[\\\/]/).filter(Boolean);
  return parts.length > 2 ? "…" + S.sep + parts.slice(-2).join(S.sep) : path;
}
function hoursText(h) {
  h = +h;
  return h === 1 ? "hour" : h === 24 ? "day" : h === 168 ? "week" : h + " hours";
}

// Avatar colours from the mockups: a pale fill and a deep text of one hue.
var PALETTE = [["#EEEDFE", "#3C3489", "#CECBF6", "#AFA9EC"], ["#E1F5EE", "#085041", "#9FE1CB", "#5DCAA5"],
               ["#FAECE7", "#712B13", "#F5C4B3", "#F0997B"], ["#E6F1FB", "#0C447C", "#B5D4F4", "#85B7EB"],
               ["#FBEAF0", "#72243E", "#F4C0D1", "#ED93B1"], ["#FAEEDA", "#633806", "#FAC775", "#EF9F27"]];
function colours(name) {
  var h = 0;
  for (var i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return PALETTE[h % PALETTE.length];
}
function initials(name) {
  var words = name.trim().split(/[\s_\-.]+/).filter(Boolean);
  var s = words.length > 1 ? words[0][0] + words[1][0] : (words[0] || "?").slice(0, 2);
  return s.toUpperCase();
}
// The profile picture when Sourcerer found one, the coloured initials otherwise.
function avatarHtml(a, cls, id) {
  var name = (a && a.name) || "?", attr = (id ? ' id="' + id + '"' : "");
  cls = "avatar" + (cls ? " " + cls : "");
  if (a && a.avatar && a.id) {
    return "<img" + attr + ' class="' + cls + '" alt="" src="/api/avatar/' + a.id + "?v=" +
      encodeURIComponent(a.avatar_checked || "") + '">';
  }
  var c = colours(name);
  return "<div" + attr + ' class="' + cls + '" style="background:' + c[0] + ";color:" + c[1] + '">' +
    esc(initials(name)) + "</div>";
}

var STATUS_TEXT = { ok: "reachable", error: "", unsupported: "not supported yet",
                    unknown: "not checked yet", checking: "checking…",
                    login: "log in first: Settings › Accounts" };
function statusText(s) { return s.status === "error" ? (s.error || s.last_error || "error") : STATUS_TEXT[s.status] || ""; }

// ---- settings that change the look ----------------------------------------

function applySettings() {
  var t = S.settings.theme;
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
  else delete document.documentElement.dataset.theme;
  setSize(+S.settings.card_size || DEFAULT_SIZE, false);
}

var sizeTimer = null;
function setSize(px, save) {
  px = Math.max(160, Math.min(420, Math.round(px / 10) * 10));
  document.documentElement.style.setProperty("--card", px + "px");
  $("size").value = px; $("set-size").value = px;
  if (save && String(px) !== String(S.settings.card_size)) {
    S.settings.card_size = String(px);
    clearTimeout(sizeTimer);
    sizeTimer = setTimeout(function () { api("PUT", "/api/settings", { card_size: px }).catch(fail); }, 400);
  }
}

// ---- cards -----------------------------------------------------------------

function artistById(id) { return S.artists.filter(function (a) { return a.id === id; })[0]; }

function visibleArtists() {
  var q = $("search").value.trim().toLowerCase();
  var list = S.artists.filter(function (a) {
    return !q || a.name.toLowerCase().indexOf(q) >= 0 ||
      a.sources.some(function (s) { return s.url.toLowerCase().indexOf(q) >= 0; });
  });
  var by = $("sort").value;
  list.sort(function (a, b) {
    if (by === "files" && a.file_count !== b.file_count) return b.file_count - a.file_count;
    if (by === "activity") {
      var ta = a.last_activity || a.last_sync || a.created || "", tb = b.last_activity || b.last_sync || b.created || "";
      if (ta !== tb) return ta < tb ? 1 : -1;
    }
    return a.name.localeCompare(b.name);
  });
  return list;
}

function render() {
  var list = visibleArtists();
  $("empty").classList.toggle("hidden", S.artists.length > 0);
  $("nomatch").classList.toggle("hidden", !S.artists.length || list.length > 0);
  $("cards").classList.toggle("hidden", !S.artists.length);
  $("cards").innerHTML = list.map(cardHtml).join("") +
    '<button class="add-tile" data-act="add" title="New card (Ctrl+N)">' + icon("plus") + "New card</button>";
  renderActivity();
}

function dotsHtml(a) {
  return '<div class="srcdots">' + a.sources.map(function (s) {
    return '<span title="' + esc(shortUrl(s.url) + " — " + statusText(s)) + '"><i class="dot ' + s.status + '"></i>' +
      esc(s.label) + "</span>";
  }).join("") + "</div>";
}

function cardHtml(a) {
  var c = colours(a.name);
  var cur = S.sync.current && S.sync.current.artist_id === a.id ? S.sync.current : null;
  var queued = (S.sync.queue || []).indexOf(a.id) >= 0;
  var thumbs = "";
  for (var i = 0; i < 4; i++) {
    thumbs += a.thumbs[i]
      ? '<img loading="lazy" src="/api/thumb/' + a.thumbs[i] + '" alt="">'
      : '<div style="background:' + (i % 2 ? c[3] : c[2]) + ';opacity:.45"></div>';
  }
  var html = '<div class="card' + (cur ? " busy" : "") + (S.selected === a.id ? " selected" : "") +
    '" data-id="' + a.id + '" tabindex="-1">' +
    '<div class="card-head">' + avatarHtml(a) +
    '<div class="who"><p class="card-name" title="' + esc(a.name) + '">' + esc(a.name) + "</p>" +
    '<p class="card-path" data-act="folder" title="Open folder: ' + esc(a.path) + '">' + esc(shortPath(a.path)) + "</p></div></div>" +
    '<div class="thumbs">' + thumbs + "</div>" + dotsHtml(a);

  if (cur) {
    var text, pct = 0;
    if (cur.phase === "scan") text = "Checking sources · " + cur.found + " new found";
    else {
      text = (cur.first ? "First sync · " : "") + "downloading " + cur.done + " / " + cur.total;
      pct = cur.total ? Math.round(100 * cur.done / cur.total) : 100;
    }
    return html + '<div class="progress-text">' + esc(text) + "</div>" +
      '<div class="bar' + (cur.phase === "scan" ? " indeterminate" : "") + '"><div style="width:' + pct + '%"></div></div>' +
      '<div class="card-foot"><span class="badges">' +
      (cur.phase === "scan" ? "" : "<span>" + esc(plural(cur.new, "new file") +
        (cur.duplicates ? " · " + plural(cur.duplicates, "duplicate") + " skipped" : "")) + "</span>") +
      '</span><button class="mini" data-act="cancel">Cancel</button></div></div>';
  }
  var supported = a.sources.some(function (s) { return s.supported; });
  var badges = queued ? '<span class="badge accent">Queued</span>'
    : "<span>" + esc(plural(a.file_count, "file") + " · " + ago(a.last_activity || a.last_sync)) + "</span>" +
      (a.last_new ? '<span class="badge accent">+' + a.last_new + " new</span>" : "") +
      (a.last_failed ? '<span class="badge warning">' + a.last_failed + " failed</span>" : "");
  return html + '<div class="card-foot"><span class="badges">' + badges + "</span>" +
    (queued
      ? '<button class="mini" data-act="cancel">Cancel</button>'
      : '<button class="mini" data-act="sync" aria-label="Sync now" title="Sync now (U)"' +
        (supported ? "" : " disabled") + ">" + icon("refresh") + "</button>" +
        '<button class="mini" data-act="folder" aria-label="Open gallery" title="Open the downloaded gallery (O)">' + icon("folder") + "</button>" +
        '<button class="mini" data-act="more" aria-label="More" title="More">' + icon("dots") + "</button>") +
    "</div></div>";
}

// ---- activity bar and log ---------------------------------------------------

var KIND_ICON = { start: "play", done: "check", warn: "alert", error: "error", cancelled: "ban", info: "info" };

function problems() {
  return (S.sync.log || []).filter(function (e) {
    return (e.kind === "warn" || e.kind === "error") && e.time > S.logSeen;
  }).length;
}

function renderActivity() {
  var s = S.sync || {}, cur = s.current, q = s.queue || [], html;
  if (cur) {
    var a = artistById(cur.artist_id) || { name: cur.name };
    var scan = cur.phase === "scan", pct = cur.total ? 100 * cur.done / cur.total : 0;
    html = '<div class="state">' + avatarHtml(a, "xs") + "<b>" + esc(cur.name) + "</b>" +
      '<span class="num">' + (scan ? "Checking sources · " + cur.found + " new"
                                   : "Downloading " + cur.done + " / " + cur.total) + "</span>" +
      '<div class="bar' + (scan ? " indeterminate" : "") + '"><div style="width:' + pct + '%"></div></div>' +
      (!scan && cur.speed ? '<span class="num">' + bytes(cur.speed) + "/s</span>" : "") +
      (cur.file ? '<span class="file" title="' + esc(cur.file) + '">' + esc(cur.file) + "</span>" : "") + "</div>";
    if (q.length) {
      html += '<span class="queue" title="Waiting: ' + esc(q.map(function (id) {
        return (artistById(id) || {}).name; }).join(", ")) + '">' +
        q.slice(0, 4).map(function (id) { return avatarHtml(artistById(id) || { name: "?" }, "xs"); }).join("") +
        (q.length > 4 ? '<span class="more">+' + (q.length - 4) + "</span>" : "") + "</span>";
    }
    html += '<button class="mini" data-act="cancel-current">' + icon("stop") + " Cancel</button>";
  } else {
    html = '<div class="state">' + icon("check", "ok") + "<b>Ready</b>" +
      (s.finished ? "<span>· last sync " + esc(ago(s.finished)) + "</span>" : "") + "</div>";
  }
  if (S.settings.auto_sync === "1") {
    html += '<span class="pill" title="Settings › Sync">' + icon("clock") + "Auto-sync every " +
      esc(hoursText(S.settings.auto_hours)) + "</span>";
  }
  var open = !$("logpanel").classList.contains("hidden"), n = open ? 0 : problems();
  html += '<button id="btn-log" class="mini' + (open ? " open" : "") + '" data-act="log" title="Activity log (Ctrl+L)">' +
    icon("list") + " Activity" + (n ? '<span class="count">' + n + "</span>" : "") + icon("chevron-up", "chev") + "</button>";
  $("activity").innerHTML = html;
  $("btn-sync-all").disabled = !S.artists.length;
  if (open) renderLog();
}

function renderLog() {
  var list = (S.sync.log || []).slice().reverse();
  if (S.logFilter === "problems") list = list.filter(function (e) { return e.kind === "warn" || e.kind === "error"; });
  if (list.length) S.logSeen = (S.sync.log || []).slice(-1)[0].time;
  $("log").innerHTML = list.length ? list.map(function (e) {
    var chips = (e.new ? '<span class="badge accent">+' + e.new + " new</span>" : "") +
      (e.duplicates ? '<span class="badge plain">' + plural(e.duplicates, "duplicate") + "</span>" : "") +
      (e.failed ? '<span class="badge warning">' + e.failed + " failed</span>" : "");
    return '<li class="k-' + e.kind + '"><span class="time">' + clock(e.time) + "</span>" +
      icon(KIND_ICON[e.kind] || "info") +
      (e.artist ? '<span class="who">' + esc(e.artist) + "</span>" : "") +
      '<span class="text" title="' + esc(e.text) + '">' + esc(e.text) + "</span>" + chips + "</li>";
  }).join("") : '<li class="logempty">' + (S.logFilter === "problems" ? "No problems." : "Nothing happened yet.") + "</li>";
}

function toggleLog() {
  $("logpanel").classList.toggle("hidden");
  renderActivity();
}

// ---- loading and polling ---------------------------------------------------

function load() {
  return api("GET", "/api/state").then(function (d) {
    S.artists = d.artists; S.sync = d.sync; S.library = d.library; S.window = d.window;
    S.sep = d.sep; S.sites = d.sites; S.fields = d.fields; S.settings = d.settings;
    $("version").textContent = "v" + d.version;
    if (S.selected && !artistById(S.selected)) S.selected = null;
    $("btn-quit").classList.toggle("hidden", S.window);
    applySettings();
    render();
  });
}

// A poll is a delay: quick while a sync runs, slow when nothing does. The
// cards are reloaded whenever the artist being synced changes, so counts,
// badges and thumbnails follow without reloading on every tick.
var lastKey = "";
function poll() {
  api("GET", "/api/sync").then(function (s) {
    var key = (s.current ? s.current.artist_id : "-") + "|" + s.running + "|" + (s.queue || []).join(",") +
      "|" + (s.log || []).length;
    S.sync = s;
    if (key !== lastKey) { lastKey = key; return load(); }
    if (s.current) render(); else renderActivity();
  }).catch(function () {}).then(function () {
    setTimeout(poll, S.sync.running ? 700 : 3000);
  });
}

function sync(artistId) {
  api("POST", "/api/sync", artistId ? { artist_id: artistId } : {}).then(function () {
    lastKey = ""; return api("GET", "/api/sync");
  }).then(function (s) { S.sync = s; render(); }).catch(fail);
}

function removeArtist(a) {
  if (!confirm('Delete the card "' + a.name + '"? The downloaded files stay in the library.')) return;
  api("DELETE", "/api/artists/" + a.id).then(load).catch(fail);
}

function openFolder(a) { api("POST", "/api/open", { target: "artist", artist_id: a.id }).catch(fail); }

// ---- selection, mouse and the card menu ------------------------------------

function select(id, scroll) {
  S.selected = id;
  $$(".card").forEach(function (c) { c.classList.toggle("selected", +c.dataset.id === id); });
  var el = document.querySelector('.card[data-id="' + id + '"]');
  if (el && scroll) el.scrollIntoView({ block: "nearest" });
}

function closeMenu() { $("menu").classList.add("hidden"); S.menuFor = null; }
function openMenu(a, x, y) {
  var m = $("menu");
  S.menuFor = a.id;
  select(a.id);
  m.classList.remove("hidden");
  m.style.top = Math.min(y, innerHeight - m.offsetHeight - 8) + "px";
  m.style.left = Math.min(x, innerWidth - m.offsetWidth - 8) + "px";
}

document.addEventListener("click", function (e) {
  if (!e.target.closest("#menu") && !e.target.closest("[data-act=more]")) closeMenu();
  var card = e.target.closest(".card");
  if (card) select(+card.dataset.id);
  var btn = e.target.closest("[data-act]");
  if (!btn) return;
  var a = card && artistById(+card.dataset.id);
  switch (btn.dataset.act) {
    case "add": openCard(null); break;
    case "sync": sync(a.id); break;
    case "folder": openFolder(a); break;
    case "cancel": api("POST", "/api/sync/cancel", { artist_id: a.id }).then(function () { lastKey = ""; }); break;
    case "cancel-current":
      if (S.sync.current) api("POST", "/api/sync/cancel", { artist_id: S.sync.current.artist_id });
      break;
    case "log": toggleLog(); break;
    case "more":
      var r = btn.getBoundingClientRect();
      openMenu(a, r.right - 190, r.bottom + 4);
      break;
  }
});
$("cards").addEventListener("dblclick", function (e) {
  var card = e.target.closest(".card");
  if (card && !e.target.closest("button, [data-act]")) openCard(artistById(+card.dataset.id));
});
$("cards").addEventListener("contextmenu", function (e) {
  var card = e.target.closest(".card");
  if (!card) return;
  e.preventDefault();
  openMenu(artistById(+card.dataset.id), e.clientX, e.clientY);
});
$("menu").addEventListener("click", function (e) {
  var btn = e.target.closest("[data-menu]");
  if (!btn) return;
  var a = artistById(S.menuFor);
  closeMenu();
  if (!a) return;
  if (btn.dataset.menu === "edit") openCard(a);
  else if (btn.dataset.menu === "sync") sync(a.id);
  else if (btn.dataset.menu === "delete") removeArtist(a);
});

// Ctrl + wheel sizes the cards instead of zooming the page.
$("main").addEventListener("wheel", function (e) {
  if (!e.ctrlKey) return;
  e.preventDefault();
  setSize(+$("size").value + (e.deltaY < 0 ? 10 : -10), true);
}, { passive: false });
$("size").addEventListener("input", function () { setSize(+this.value, true); });
$("btn-smaller").addEventListener("click", function () { setSize(+$("size").value - 20, true); });
$("btn-larger").addEventListener("click", function () { setSize(+$("size").value + 20, true); });

// ---- keyboard --------------------------------------------------------------

function moveSelection(key) {
  var cards = $$(".card");
  if (!cards.length) return;
  var ids = cards.map(function (c) { return +c.dataset.id; });
  var i = ids.indexOf(S.selected);
  if (i < 0) return select(ids[0], true);
  var top = cards[0].offsetTop, cols = cards.filter(function (c) { return c.offsetTop === top; }).length || 1;
  var next = { ArrowLeft: i - 1, ArrowRight: i + 1, ArrowUp: i - cols, ArrowDown: i + cols,
               Home: 0, End: ids.length - 1 }[key];
  select(ids[Math.max(0, Math.min(ids.length - 1, next))], true);
}

document.addEventListener("keydown", function (e) {
  var k = e.key, low = k.toLowerCase(), ctrl = e.ctrlKey || e.metaKey;
  var t = e.target, typing = (t.tagName === "INPUT" && !/^(range|checkbox)$/.test(t.type)) ||
    t.tagName === "SELECT" || t.tagName === "TEXTAREA";
  var dialog = document.querySelector("dialog[open]");
  if (k === "Escape") {
    closeMenu();
    if (!dialog && t === $("search")) { t.value = ""; t.blur(); render(); }
    return;                                   // an open dialog closes itself
  }
  if (ctrl && (k === "+" || k === "=")) { e.preventDefault(); return setSize(+$("size").value + 20, true); }
  if (ctrl && k === "-") { e.preventDefault(); return setSize(+$("size").value - 20, true); }
  if (ctrl && k === "0") { e.preventDefault(); return setSize(DEFAULT_SIZE, true); }
  if (dialog) return;
  if (ctrl && low === "n") { e.preventDefault(); return openCard(null); }
  if ((ctrl && low === "f") || (k === "/" && !typing)) { e.preventDefault(); $("search").focus(); return $("search").select(); }
  if (k === "F5" || (ctrl && low === "r")) { e.preventDefault(); return sync(null); }
  if (ctrl && k === ",") { e.preventDefault(); return openSettings(); }
  if (ctrl && low === "l") { e.preventDefault(); return toggleLog(); }
  if (typing || ctrl || e.altKey) return;
  if (/^(Arrow(Left|Right|Up|Down)|Home|End)$/.test(k)) { e.preventDefault(); return moveSelection(k); }
  var a = artistById(S.selected);
  if (!a) return;
  if (k === "Enter") { e.preventDefault(); openCard(a); }
  else if (low === "u") sync(a.id);
  else if (low === "o") openFolder(a);
  else if (k === "Delete") removeArtist(a);
});

// ---- the card dialog -------------------------------------------------------

var DEDUPE_HINT = {
  keep_all: "Every site keeps its own copy, even when the picture is already there from another one.",
  best: "When the same picture comes from several sites, only the version with the highest resolution is kept.",
  master: "When a picture exists on {m}, that version is kept. Pictures found only elsewhere are kept once, in the best quality."
};

function safeName(name) {
  return name.replace(/[<>:"\/\\|?*\x00-\x1f]/g, "_").trim().replace(/\.+$/, "").slice(0, 120) || "Unnamed";
}
function defaultFolder() {
  var name = $("form-card").name.value.trim();
  return S.library + S.sep + safeName(name || "Name");
}

function blankRow(field) {
  return { field: field || null, url: "", label: field || "Link", supported: false,
           status: "", error: "", handle: "", checked: "" };
}
function filledRows() { return F.rows.filter(function (r) { return r.url.trim(); }); }

function openCard(a) {
  closeMenu();
  F = {
    id: a ? a.id : null, artist: a || null, autoName: "",
    // One fixed field per site Sourcerer knows, then any further links.
    rows: S.fields.map(function (f) { return blankRow(f.label); }),
    layout: a ? a.layout : "together",
    dedupe: a ? a.dedupe : "best",
    master: a ? (a.sources.filter(function (s) { return s.master; })[0] || {}).url || "" : ""
  };
  (a ? a.sources : []).forEach(function (s) {
    var slot = F.rows.filter(function (r) { return r.field === s.label && !r.url; })[0] || blankRow(null);
    if (F.rows.indexOf(slot) < 0) F.rows.push(slot);
    Object.assign(slot, { url: s.url, label: s.label, supported: s.supported, status: s.status,
                          error: s.last_error || "", checked: s.url });
  });
  var f = $("form-card");
  f.name.value = a ? a.name : "";
  $("card-folder").value = a ? a.folder : "";
  $("card-title").textContent = a ? "Edit artist card" : "New artist card";
  $("btn-card-save").textContent = a ? "Save" : "Create";
  $("btn-card-sync").querySelector("span").textContent = a ? "Save & sync" : "Create & sync";
  $("btn-card-browse").classList.toggle("hidden", !S.window);
  $("card-error").textContent = "";
  renderSources();
  $("dlg-card").showModal();
  (a ? f.name : document.querySelector(".srcinput")).focus();
  // The dots say what the last sync found; ask again now, so they are current.
  filledRows().forEach(function (r) { if (r.supported) check(r, true); });
}

// Normalises the row's link, says whether it answers, and moves a link pasted
// into another site's field to that site's own field when it is free.
function check(row, force) {
  var form = F, url = row.url.trim();
  if (!url) { Object.assign(row, blankRow(row.field)); return Promise.resolve(renderSources()); }
  if (url === row.checked && !force) return Promise.resolve();
  row.checked = url; row.status = "checking";
  renderSources();
  return api("POST", "/api/detect", { url: url }).then(function (d) {
    if (form !== F || row.url.trim() !== url) return;              // typed on meanwhile
    var drop = function (r) {
      if (r.field) Object.assign(r, blankRow(r.field)); else F.rows.splice(F.rows.indexOf(r), 1);
    };
    if (F.rows.some(function (o) { return o !== row && o.url === d.url; })) {
      drop(row);
      toast("That link is on the card already.");
      return renderSources();
    }
    var target = row;
    if (row.field !== d.label) {
      var own = F.rows.filter(function (r) { return r.field === d.label && !r.url.trim(); })[0];
      if (own) { drop(row); target = own; }
    }
    Object.assign(target, { url: d.url, checked: d.url, label: d.label, supported: d.supported,
                            status: d.status, error: d.error || "", handle: d.handle || "" });
    // A name the site states beats one read from a link; one typed beats both.
    var name = $("form-card").name, fromSite = d.status === "ok";
    if (d.name && (!name.value.trim() || (name.value === F.autoName && fromSite && !F.autoFromSite))) {
      name.value = F.autoName = d.name; F.autoFromSite = fromSite;
    }
    renderSources();
  }).catch(function (e) {
    if (form !== F) return;
    row.status = "error"; row.error = e.message;
    renderSources();
  });
}

function renderSources() {
  // Re-drawn while somebody types in another field: keep the cursor where it was.
  var el = document.activeElement, at = el && el.dataset ? el.dataset.row : null;
  var pos = at != null ? el.selectionStart : 0;
  var master = F.dedupe === "master" ? F.master : "";
  $("src-list").innerHTML = F.rows.map(function (r, i) {
    var filled = !!r.url.trim(), field = S.fields.filter(function (f) { return f.label === r.field; })[0];
    var isMaster = filled && master && r.url === master;
    var mark = filled && r.supported
      ? '<button type="button" data-src="master" data-i="' + i + '" title="' + (isMaster ? "Master source" : "Make this the master source") + '">' +
        (isMaster ? icon("crown", "crown") : icon("point", "point")) + "</button>"
      : '<button type="button" disabled>' + icon("point", "point") + "</button>";
    var state = !filled ? ""
      : r.status === "checking" ? '<span class="state">checking…</span>'
      : r.status === "unsupported" ? '<span class="badge warning">not supported yet</span>'
      : r.status === "login" ? '<button type="button" class="badge warning" data-src="login" title="' + esc(r.error) + '">log in first</button>'
      : '<span class="state' + (r.status === "error" ? " error" : "") + '" title="' + esc(statusText(r)) + '">' +
        esc(r.status === "ok" && r.handle ? r.handle : statusText(r)) + "</span>";
    return '<div class="srcrow' + (r.field ? "" : " extra") + '">' + mark +
      '<span class="site"><i class="dot ' + (filled ? r.status : "blank") + '" title="' + esc(filled ? statusText(r) : "") + '"></i>' +
      esc(r.field || (filled && r.label !== "…" ? r.label : "Link")) + "</span>" +
      '<input type="text" class="srcinput" data-row="' + i + '" value="' + esc(r.url) + '" autocomplete="off" spellcheck="false" placeholder="' +
      esc(field ? field.example : "Any other link – a second account, another site") + '">' + state +
      (r.field ? "" : '<button type="button" data-src="remove" data-i="' + i + '" title="Remove">' + icon("x") + "</button>") + "</div>";
  }).join("");
  if (at != null) {
    var again = document.querySelector('.srcinput[data-row="' + at + '"]');
    if (again) { again.focus(); try { again.setSelectionRange(pos, pos); } catch (e) {} }
  }
  renderForm();
}

function renderForm() {
  var name = $("form-card").name.value.trim(), rows = filledRows();
  $("card-avatar").outerHTML = avatarHtml(F.artist && F.artist.avatar ? F.artist : { name: name || "?" }, "lg", "card-avatar");

  var base = $("card-folder").value.trim() || defaultFolder(), sep = S.sep;
  $("card-folder").placeholder = defaultFolder();
  var labels = rows.filter(function (r) { return r.supported; }).map(function (r) { return r.label; })
    .filter(function (l, i, all) { return all.indexOf(l) === i; });
  if (!labels.length) labels = ["Bluesky", "Mastodon"];
  var leaf = base.split(/[\\\/]/).filter(Boolean).pop() || base;
  $("layout-together").textContent = leaf + sep;
  $("layout-per-source").textContent = labels.slice(0, 2).map(function (l) { return leaf + sep + l + sep; }).join(" · ");
  $$("[data-layout]").forEach(function (b) { b.classList.toggle("selected", b.dataset.layout === F.layout); });

  $$("[data-dedupe]").forEach(function (b) { b.classList.toggle("selected", b.dataset.dedupe === F.dedupe); });
  var options = rows.filter(function (r) { return r.supported; });
  $("master-row").classList.toggle("hidden", F.dedupe !== "master");
  $("master-select").innerHTML = options.length
    ? options.map(function (r) {
        return '<option value="' + esc(r.url) + '"' + (r.url === F.master ? " selected" : "") + ">" +
          esc(r.label + " – " + shortUrl(r.url)) + "</option>";
      }).join("")
    : '<option value="">Add a supported source first</option>';
  if (F.dedupe === "master" && options.length && !options.some(function (r) { return r.url === F.master; })) {
    F.master = options[0].url;
  }
  var masterLabel = (options.filter(function (r) { return r.url === F.master; })[0] || {}).label || "the master source";
  $("dedupe-hint").textContent = DEDUPE_HINT[F.dedupe].replace("{m}", masterLabel);
}

// Several links pasted at once: the first stays in the field, the rest get rows of their own.
function takeLinks(input) {
  var row = F.rows[+input.dataset.row], parts = input.value.split(/\s+/).filter(Boolean);
  if (!row) return;
  row.url = parts.shift() || "";
  var more = parts.filter(function (u) { return !F.rows.some(function (r) { return r.url === u; }); })
    .map(function (u) { var r = blankRow(null); r.url = u; F.rows.push(r); return r; });
  check(row);
  more.forEach(function (r) { check(r); });
}

function addRow() {
  F.rows.push(blankRow(null));
  renderSources();
  var inputs = $$(".srcinput");
  inputs[inputs.length - 1].focus();
}

$("src-list").addEventListener("input", function (e) {
  var row = e.target.dataset && F.rows[+e.target.dataset.row];
  if (!row) return;
  row.url = e.target.value;
  var dot = e.target.parentNode.querySelector(".dot");
  if (dot) dot.className = "dot" + (row.url.trim() ? "" : " blank");   // not "empty": the empty-state class
});
$("src-list").addEventListener("change", function (e) { if (e.target.classList.contains("srcinput")) takeLinks(e.target); });
$("src-list").addEventListener("paste", function (e) {
  if (e.target.classList.contains("srcinput")) setTimeout(function () { takeLinks(e.target); }, 0);
});
$("src-list").addEventListener("keydown", function (e) {
  if (e.key !== "Enter" || !e.target.classList.contains("srcinput")) return;
  e.preventDefault();                       // Enter in a link field moves on; it does not save
  var inputs = $$(".srcinput"), next = inputs[inputs.indexOf(e.target) + 1];
  takeLinks(e.target);
  if (next) next.focus(); else addRow();
});
$("src-list").addEventListener("click", function (e) {
  var btn = e.target.closest("[data-src]");
  if (!btn) return;
  var r = F.rows[+btn.dataset.i];
  if (btn.dataset.src === "login") return openSettings("accounts");
  if (btn.dataset.src === "remove") F.rows.splice(+btn.dataset.i, 1);
  else { F.master = r.url; F.dedupe = "master"; }
  renderSources();
});
$("btn-src-add").addEventListener("click", addRow);
$("form-card").name.addEventListener("input", renderForm);
$("card-folder").addEventListener("input", renderForm);
$("btn-card-browse").addEventListener("click", function () {
  api("POST", "/api/pick-folder", { start: $("card-folder").value || S.library }).then(function (d) {
    if (d.path) { $("card-folder").value = d.path; renderForm(); }
  }).catch(fail);
});
$$("[data-layout]").forEach(function (b) {
  b.addEventListener("click", function () { F.layout = b.dataset.layout; renderForm(); });
});
$$("[data-dedupe]").forEach(function (b) {
  b.addEventListener("click", function () { F.dedupe = b.dataset.dedupe; renderSources(); });
});
$("master-select").addEventListener("change", function () { F.master = this.value; renderSources(); });

$("form-card").addEventListener("submit", function (e) {
  e.preventDefault();
  var syncNow = !!(e.submitter && e.submitter.value === "sync");
  // A link typed but not left yet is checked first, so it is saved normalised.
  Promise.all(filledRows().filter(function (r) { return r.url.trim() !== r.checked; })
    .map(function (r) { return check(r); })).then(function () {
    var body = {
      name: e.target.name.value, folder: $("card-folder").value,
      sources: filledRows().map(function (r) { return r.url.trim(); }),
      layout: F.layout, dedupe: F.dedupe, master: F.dedupe === "master" ? F.master : "", sync_now: syncNow
    };
    return F.id ? api("PUT", "/api/artists/" + F.id, body) : api("POST", "/api/artists", body);
  }).then(function (d) {
    $("dlg-card").close(); lastKey = "";
    if (d.id) S.selected = d.id;
    load();
    // The dots and the profile picture arrive a moment later, from the background.
    setTimeout(load, 2500);
  }).catch(function (err) { $("card-error").textContent = err.message; });
});

// ---- settings --------------------------------------------------------------

function showPane(name) {
  $$(".rail [data-pane]").forEach(function (b) { b.classList.toggle("selected", b.dataset.pane === name); });
  $$(".panes section").forEach(function (s) { s.classList.toggle("shown", s.dataset.pane === name); });
  if (name === "updates" && !S.update) checkUpdate(false);
  if (name === "about" || name === "updates") loadInfo();
  if (name === "accounts") loadAccounts();
}

function fillSettings() {
  var st = S.settings;
  $("set-library").value = S.library;
  $("btn-browse").classList.toggle("hidden", !S.window);
  $("set-auto").checked = st.auto_sync === "1";
  $("set-hours").value = st.auto_hours; $("set-hours").disabled = st.auto_sync !== "1";
  $("set-parallel").value = st.parallel;
  $("set-perhost").value = st.per_host;
  $("set-pace").value = st.pace_ms;
  $$("[data-set]").forEach(function (b) { b.classList.toggle("selected", st[b.dataset.set] === b.dataset.value); });
  $("filename-example").textContent = "For example: " + (st.filenames === "dated" ? "2025-03-14_" : "") +
    "a6f1c09b2e7d4f31.png" + " — the name the file has on the site, wherever it has one.";
}

function openSettings(pane) {
  closeMenu();
  fillSettings();
  showPane(pane || "library");
  $("dlg-settings").showModal();
}

function saveSetting(change) {
  return api("PUT", "/api/settings", change).then(function (d) {
    S.settings = d.settings; S.library = d.library;
    applySettings(); fillSettings(); renderActivity();
    toast("Saved");
  }).catch(function (e) { fail(e); fillSettings(); });
}

$$(".rail [data-pane]").forEach(function (b) { b.addEventListener("click", function () { showPane(b.dataset.pane); }); });
$$("[data-set]").forEach(function (b) {
  b.addEventListener("click", function () {
    var change = {};
    change[b.dataset.set] = b.dataset.value;
    saveSetting(change).then(function () {
      if (b.dataset.set === "channel") { S.update = null; checkUpdate(false); }
    });
  });
});
$("set-library").addEventListener("change", function () { saveSetting({ library: this.value }).then(load); });
$("btn-browse").addEventListener("click", function () {
  api("POST", "/api/pick-folder", { start: $("set-library").value }).then(function (d) {
    if (d.path) return saveSetting({ library: d.path }).then(load);
  }).catch(fail);
});
$("set-auto").addEventListener("change", function () { saveSetting({ auto_sync: this.checked ? "1" : "0" }); });
$("set-hours").addEventListener("change", function () { saveSetting({ auto_hours: this.value }); });
$("set-parallel").addEventListener("change", function () { saveSetting({ parallel: this.value }); });
$("set-perhost").addEventListener("change", function () { saveSetting({ per_host: this.value }); });
$("set-pace").addEventListener("change", function () { saveSetting({ pace_ms: this.value }); });
$("set-size").addEventListener("input", function () { setSize(+this.value, true); });
$("btn-settings").addEventListener("click", function () { openSettings(S.update && S.update.available ? "updates" : null); });
$$("[data-open]").forEach(function (b) {
  b.addEventListener("click", function () { api("POST", "/api/open", { target: b.dataset.open }).catch(fail); });
});

// ---- accounts ----------------------------------------------------------------

var accTimer = null;
function loadAccounts() {
  clearTimeout(accTimer);
  return api("GET", "/api/accounts").then(function (d) {
    $("acc-list").innerHTML = d.accounts.map(function (a) {
      var state = a.pending === "waiting" ? "Waiting for you to log in in the other window…"
        : a.logged_in ? "Logged in" + (a.how ? " (" + a.how + ")" : "") + (a.saved ? " · " + ago(a.saved) : "")
        : a.pending.indexOf("failed: ") === 0 ? a.pending.slice(8)
        : a.pending === "cancelled" ? "Login window closed before the login was finished."
        : "Not logged in";
      var key = ' data-key="' + esc(a.key) + '"';
      return '<div class="row"><div><div class="row-title"><i class="dot ' + (a.logged_in ? "ok" : "blank") + '"></i> ' +
        esc(a.label) + (a.forum ? ' <span class="muted small">XenForo</span>' : "") + '</div><p class="hint">' + esc(state) + "</p></div>" +
        (a.logged_in ? '<button type="button" data-acc="logout"' + key + ">Log out</button>"
          : '<button type="button" class="primary" data-acc="login"' + key + (d.window ? "" : ' disabled title="Needs Sourcerer\'s own window"') + ">Log in</button>") +
        '<button type="button" data-acc="import"' + key + ">Import&hellip;</button></div>";
    }).join("");
    $("btn-acc-forum").disabled = !d.window;
    // While a login window is open, follow it; the row turns green by itself.
    if (d.accounts.some(function (a) { return a.pending === "waiting"; }) && $("dlg-settings").open) {
      accTimer = setTimeout(loadAccounts, 1500);
    }
  }).catch(fail);
}

$("acc-list").addEventListener("click", function (e) {
  var b = e.target.closest("[data-acc]");
  if (!b) return;
  var key = b.dataset.key;
  if (b.dataset.acc === "import") { S.importKey = key; $("acc-file").value = ""; return $("acc-file").click(); }
  if (b.dataset.acc === "logout" && !confirm("Log out? Sourcerer forgets the cookies it kept for this site.")) return;
  api("POST", "/api/accounts/" + b.dataset.acc, { key: key }).then(loadAccounts).catch(fail);
});
$("btn-acc-forum").addEventListener("click", function () {
  var forum = $("acc-forum").value.trim();
  if (!forum) return $("acc-forum").focus();
  api("POST", "/api/accounts/login", { forum: forum }).then(function () { $("acc-forum").value = ""; loadAccounts(); }).catch(fail);
});
$("acc-file").addEventListener("change", function () {
  var file = this.files[0];
  if (!file) return;
  file.text().then(function (text) {
    return api("POST", "/api/accounts/import", { key: S.importKey, text: text });
  }).then(function (d) { toast("Imported: " + plural(d.cookies, "cookie")); loadAccounts(); }).catch(fail);
});

function loadInfo() {
  api("GET", "/api/info").then(function (d) {
    $("about-version").textContent = "v" + d.version;
    $("upd-current").textContent = "v" + d.version;
    $("about-repo").textContent = d.repo.replace("https://", ""); $("about-repo").href = d.repo;
    $("about-facts").innerHTML = [["Version", "v" + d.version], ["Python", d.python], ["System", d.system],
      ["Program", d.program], ["User data", d.userdata], ["Library", d.library],
      ["Window", d.window ? "app window" : "browser"]].map(function (r) {
      return "<tr><td>" + esc(r[0]) + '</td><td class="mono">' + esc(r[1]) + "</td></tr>";
    }).join("");
    $("upd-log-box").classList.toggle("hidden", !d.update_log.length);
    $("upd-log").textContent = d.update_log.join("\n");
  }).catch(fail);
}

// ---- updates and repair ----------------------------------------------------

function showUpdate() {
  var u = S.update, has = !!(u && u.available);
  $("update-dot").classList.toggle("hidden", !has);
  $("update-dot-2").classList.toggle("hidden", !has);
  $("btn-install").classList.toggle("hidden", !has);
  if (!u) return;
  if (u.error) $("upd-status").textContent = u.error;
  else if (has) $("upd-status").textContent = "v" + u.version + " is available.";
  else if (!u.version) $("upd-status").textContent = "Nothing published on this channel yet.";
  else $("upd-status").textContent = "Up to date. Newest " + (u.channel === "beta" ? "build" : "release") + ": v" + u.version + ".";
  $("btn-install").querySelector("span").textContent = has ? "Install v" + u.version : "Install";
  $("upd-notes").textContent = has ? u.notes : "";
  $("upd-notes").classList.toggle("hidden", !has || !u.notes);
}

function checkUpdate(loud) {
  $("upd-status").textContent = "Asking GitHub…";
  return api("GET", "/api/update/check?channel=" + (S.settings.channel || "stable")).then(function (u) {
    S.update = u; showUpdate();
  }).catch(function (e) {
    S.update = { error: e.message }; showUpdate();
    if (loud) fail(e);
  });
}
$("btn-check").addEventListener("click", function () { checkUpdate(true); });

function restarting(title, text) {
  $("overlay-title").textContent = title;
  $("overlay-text").textContent = text + (S.window
    ? " The window closes and opens again by itself."
    : " A new browser tab opens by itself; you can close this one.");
  $("overlay").classList.remove("hidden");
  $$("dialog[open]").forEach(function (d) { d.close(); });
}

$("btn-install").addEventListener("click", function () {
  var u = S.update;
  if (!u || !u.available || !confirm("Install v" + u.version + " and restart Sourcerer?")) return;
  $("btn-install").disabled = true;
  $("upd-status").textContent = "Downloading v" + u.version + "…";
  api("POST", "/api/update/install", { channel: u.channel }).then(function () {
    restarting("Updating to v" + u.version, "Sourcerer restarts in a moment.");
  }).catch(function (e) { $("upd-status").textContent = e.message; fail(e); })
    .then(function () { $("btn-install").disabled = false; });
});

var REPAIR_ASK = {
  venv: "Rebuild the Python environment? Sourcerer restarts, and the next start takes a minute.",
  reinstall: "Download this version again and replace the program files? Sourcerer restarts.",
  restart: "Restart Sourcerer?"
};
$$("[data-repair]").forEach(function (b) {
  b.addEventListener("click", function () {
    var action = b.dataset.repair;
    if (REPAIR_ASK[action] && !confirm(REPAIR_ASK[action])) return;
    b.disabled = true;
    api("POST", "/api/repair", { action: action }).then(function (d) {
      if (REPAIR_ASK[action]) restarting(action === "reinstall" ? "Reinstalling" : "Restarting", d.message);
      else { toast(d.message); setTimeout(load, 3000); }
    }).catch(fail).then(function () { b.disabled = false; });
  });
});

// ---- the rest --------------------------------------------------------------

$("dlg-settings").addEventListener("close", function () {
  if ($("dlg-card").open) F.rows.forEach(function (r) { if (r.status === "login") check(r, true); });
});
$$("[data-close]").forEach(function (b) {
  b.addEventListener("click", function () { b.closest("dialog").close(); });
});
$$("[data-log]").forEach(function (b) {
  b.addEventListener("click", function () {
    S.logFilter = b.dataset.log;
    $$("[data-log]").forEach(function (o) { o.classList.toggle("selected", o === b); });
    renderLog();
  });
});
$("btn-add").addEventListener("click", function () { openCard(null); });
// Only in the browser: there the page is all there is, no window to close.
$("btn-quit").addEventListener("click", function () {
  if (!confirm("Quit Sourcerer? A running sync stops.")) return;
  api("POST", "/api/quit").then(function () {
    $("overlay-title").textContent = "Sourcerer has stopped";
    $("overlay-text").textContent = "You can close this tab. The start file starts it again.";
    $("overlay").classList.remove("hidden");
  }).catch(fail);
});
$("btn-sync-all").addEventListener("click", function () { sync(null); });
$("search").addEventListener("input", render);
$("sort").addEventListener("change", render);

load().then(function () {
  poll();
  checkUpdate(false);        // once per start: a dot on the settings button when there is one
});
