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
      if (!r.ok) { var e = new Error(data.error || ("HTTP " + r.status)); e.data = data; throw e; }
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
// "14:30", "14:30 tomorrow" or "14:30 on Fri, 3 Oct" for a Unix time.
function restUntil(sec) {
  var until = new Date(sec * 1000), now = new Date();
  var days = Math.round((new Date(until.getFullYear(), until.getMonth(), until.getDate()) -
                         new Date(now.getFullYear(), now.getMonth(), now.getDate())) / 864e5);
  return until.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) +
    (days === 1 ? " tomorrow" : days > 1 ? " on " + until.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" }) : "");
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

var STATUS_TEXT = { ok: "reachable", error: "", warn: "", unsupported: "not supported yet",
                    unknown: "not checked yet", checking: "checking…",
                    login: "log in first: Manage Accounts" };
function statusText(s) {
  return s.status === "error" || s.status === "warn" ? (s.error || s.last_error || s.status) : STATUS_TEXT[s.status] || "";
}

// ---- settings that change the look ----------------------------------------

function applySettings() {
  var t = S.settings.theme;
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
  else delete document.documentElement.dataset.theme;
  setSize(+S.settings.card_size || DEFAULT_SIZE, false);
}

var sizeTimer = null;
function setSize(px, save) {
  px = Math.max(160, Math.min(800, Math.round(px / 10) * 10));
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

// One link per source, its dot saying how it fares; a click opens it in the browser.
function dotsHtml(a) {
  return '<div class="srcdots">' + a.sources.map(function (s) {
    return '<a href="' + esc(s.url) + '" data-act="link" data-url="' + esc(s.url) + '" title="' +
      esc(shortUrl(s.url) + " — " + statusText(s)) + '"><i class="dot ' + s.status + '"></i>' +
      esc(s.label) + "</a>";
  }).join("") + "</div>";
}

function cardHtml(a) {
  var c = colours(a.name);
  var cur = S.sync.current && S.sync.current.artist_id === a.id ? S.sync.current : null;
  var queued = (S.sync.queue || []).indexOf(a.id) >= 0;
  var thumbs = "";
  for (var i = 0; i < 4; i++) {
    thumbs += a.thumbs[i]
      ? '<img loading="lazy" src="' + a.thumbs[i].src + '" alt="">'
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
        '<button class="mini" data-act="gallery" aria-label="Browse" title="Browse: every source, straight from the sites (G)"' +
        (supported ? "" : " disabled") + ">" + icon("photo") + "</button>" +
        '<button class="mini" data-act="folder" aria-label="Open folder" title="Open the downloaded files (O)">' + icon("folder") + "</button>" +
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
  // A login that ran out stays in sight until it is renewed.
  (S.logins || []).forEach(function (l) {
    html += '<button class="pill warn" data-act="accounts" title="' + esc(l.why || "") + '">' + icon("alert") +
      esc(l.label) + ": log in again</button>";
  });
  // A site that said stop rests; Sourcerer asks it nothing until then.
  (S.pauses || []).filter(function (p) { return p.until * 1000 > Date.now(); }).forEach(function (p) {
    html += '<span class="pill rest" title="' + esc(p.why) + '">' + icon("clock") + esc(p.name) + " rests until " + esc(restUntil(p.until)) + "</span>";
  });
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
      (e.existing ? '<span class="badge plain">' + e.existing + " already there</span>" : "") +
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
    S.sep = d.sep; S.sites = d.sites; S.fields = d.fields; S.settings = d.settings; S.logins = d.logins || []; S.pauses = d.pauses || [];
    $("version").textContent = "v" + d.version;
    if (S.selected && !artistById(S.selected)) S.selected = null;
    $("btn-quit").classList.toggle("hidden", S.window);
    applySettings();
    render();
    if (S.view === "browse") { renderBrowseList(); renderBrowseHead(); }
    showUpdate();
    showAccounts();
  });
}

// A poll is a delay: quick while a sync runs, slow when nothing does. The
// cards are reloaded whenever the artist being synced changes, so counts,
// badges and thumbnails follow without reloading on every tick.
var lastKey = "";
function poll() {
  api("GET", "/api/sync").then(function (s) {
    var key = (s.current ? s.current.artist_id : "-") + "|" + s.running + "|" + (s.queue || []).join(",") +
      "|" + (s.log || []).length + "|" + (s.pauses || []).map(function (p) { return p.site; }).join(",") +
      "|" + s.previews;                        // new pictures found for a card: the cards load them
    S.sync = s;
    if (s.pauses) S.pauses = s.pauses;
    if (S.view === "browse") renderBrowseHead();
    if (key !== lastKey) { lastKey = key; return load(); }
    if (s.current) render(); else renderActivity();
  }).catch(function () {}).then(function () {
    setTimeout(poll, S.sync.running ? 700 : 3000);
  });
}

function sync(artistId) {
  api("POST", "/api/sync", artistId ? { artist_id: artistId } : {}).then(function () {
    lastKey = ""; return api("GET", "/api/sync");
  }).then(function (s) { S.sync = s; if (s.pauses) S.pauses = s.pauses; render(); }).catch(fail);
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
    case "gallery": openGallery(a); break;
    case "cancel": api("POST", "/api/sync/cancel", { artist_id: a.id }).then(function () { lastKey = ""; }); break;
    case "cancel-current":
      if (S.sync.current) api("POST", "/api/sync/cancel", { artist_id: S.sync.current.artist_id });
      break;
    case "log": toggleLog(); break;
    case "link":
      e.preventDefault();
      api("POST", "/api/open-url", { url: btn.dataset.url }).catch(fail);
      break;
    case "accounts": e.preventDefault(); openAccounts(); break;
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
  else if (btn.dataset.menu === "gallery") openGallery(a);
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
  if (S.view === "browse") {
    if (ctrl && low === "n") { e.preventDefault(); return openCard(null); }
    if ((ctrl && low === "f") || (k === "/" && !typing)) { e.preventDefault(); $("br-search").focus(); return $("br-search").select(); }
    return;
  }
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
  else if (low === "g") openGallery(a);
  else if (k === "Delete") removeArtist(a);
});

// ---- browse: the artists on the left, their posts on the right ---------------

// One artist's every source -- or every artist's, "All artists" -- in one stream,
// newest first, straight from the sites: nothing is saved unless asked for. The
// filter on top is by site (Pixiv, X, Booru ...) and stays when another artist is
// picked; a site switched off is not asked at all. The server lists a page per
// source only when the grid has scrolled near its end, and fetches through
// Sourcerer what a site wants a Referer or a login for; the rest the page
// loads itself, with no referrer.
var G = null;
var galSeen = new IntersectionObserver(function (entries) {
  if (entries.some(function (e) { return e.isIntersecting; })) moreGallery();
}, { root: $("gal-body"), rootMargin: "800px" });
galSeen.observe($("gal-end"));

// Pictures Sourcerer fetches wait in the site's polite lane, and the browser
// opens six connections to Sourcerer at most: fifty of them asked for at once
// held back the large view, the next page and the state poll. So GAL_AT_ONCE
// at a time (the server's lane for small pictures takes four), those near the screen only.
var GAL_AT_ONCE = 4;
var galQueue = [], galFlight = new Set();
var galNear = new IntersectionObserver(function (entries) {
  entries.forEach(function (e) {
    if (e.isIntersecting) { galNear.unobserve(e.target); e.target.dataset.q = "1"; galQueue.push(e.target); }
  });
  galPump();
}, { root: $("gal-body"), rootMargin: "400px" });

// An image is queued once (data-q) and counts as loading only while it is in
// galFlight: a second entry for one that already started, or a picture of a
// closed gallery finishing late, must not take or give back a slot.
function galPump() {
  while (galFlight.size < GAL_AT_ONCE && galQueue.length) {
    var img = galQueue.shift();
    delete img.dataset.q;
    if (!img.isConnected || img.hasAttribute("src")) continue;
    if (img.closest(".gal-tile.hidden")) { galNear.observe(img); continue; }   // when its source is shown again
    galFlight.add(img);
    img.addEventListener("load", galDone); img.addEventListener("error", galDone);
    // Lazy loading would hold back one that is off screen -- and its slot with it.
    img.loading = "eager";
    img.src = img.dataset.lazy;
  }
}

function galDone(e) {
  e.target.removeEventListener("load", galDone); e.target.removeEventListener("error", galDone);
  if (galFlight.delete(e.target)) galPump();
}

// Proxied thumbnails of the grid that nobody has queued yet.
function galWatch() {
  $("gal-grid").querySelectorAll("img[data-lazy]:not([src]):not([data-q])").forEach(function (img) { galNear.observe(img); });
}

var BR_HIDDEN = "sourcerer.browse.hidden";
S.view = "cards"; S.brArtist = 0;
try { S.brHidden = JSON.parse(localStorage.getItem(BR_HIDDEN) || "{}"); } catch (e) { S.brHidden = {}; }

function setView(view) {
  S.view = view;
  var browse = view === "browse";
  $$(".filterbar, #main").forEach(function (e) { e.classList.toggle("hidden", browse); });
  $("browse").classList.toggle("hidden", !browse);
  $("view-cards").classList.toggle("selected", !browse);
  $("view-browse").classList.toggle("selected", browse);
  if (browse) { renderBrowseList(); if (!G) browseOpen(S.brArtist); }
  else browseClose();
}

// From a card: Browse, with this artist picked.
function openGallery(a) {
  closeMenu();
  if (!a) return;
  S.brArtist = a.id;
  if (S.view === "browse") browseOpen(a.id); else setView("browse");
}

function browseClose() {
  if (G && G.id) api("POST", "/api/gallery/close", { gallery: G.id }).catch(function () {});
  G = null;
  galQueue = []; galFlight.clear(); galNear.disconnect();
  $("gal-grid").innerHTML = ""; $("gal-sources").innerHTML = "";
  closeView();
}

// The artists, "All artists" first; the one open is marked.
function renderBrowseList() {
  var q = $("br-search").value.trim().toLowerCase();
  var list = S.artists.slice().sort(function (x, y) { return x.name.localeCompare(y.name); })
    .filter(function (a) { return !q || a.name.toLowerCase().indexOf(q) >= 0; });
  $("br-list").innerHTML = (q ? "" : '<button type="button" class="br-item all' + (!S.brArtist ? " selected" : "") +
    '" data-id="0">' + icon("photo") + '<span class="br-name">All artists</span></button>') +
    list.map(function (a) {
      var n = a.sources.filter(function (s) { return s.supported; }).length;
      return '<button type="button" class="br-item' + (S.brArtist === a.id ? " selected" : "") + '" data-id="' + a.id + '">' +
        avatarHtml(a) + '<span class="br-name" title="' + esc(a.name) + '">' + esc(a.name) + "</span>" +
        '<span class="br-n">' + (n || "") + "</span></button>";
    }).join("");
}

function renderBrowseHead() {
  var cur = S.sync.current && G && G.artist && S.sync.current.artist_id === G.artist.id ? S.sync.current : null;
  var queued = G && G.artist && (S.sync.queue || []).indexOf(G.artist.id) >= 0;
  $("br-progress").textContent = cur ? (cur.phase === "scan" ? "Checking sources…" : "Downloading " + cur.done + " / " + cur.total)
    : queued ? "Queued" : "";
  $("br-download").classList.toggle("hidden", !G || G.all);
}

function browseOpen(id) {
  closeMenu();
  var a = id ? artistById(id) : null;
  if (id && !a) return;
  S.brArtist = id || 0;
  if (G && G.id) api("POST", "/api/gallery/close", { gallery: G.id }).catch(function () {});
  G = { artist: a, all: !id, id: null, items: [], busy: false, done: false, hidden: S.brHidden, view: -1, sources: null, downloading: {} };
  galQueue = []; galFlight.clear(); galNear.disconnect();
  $("gal-title").textContent = a ? a.name : "All artists";
  $("gal-grid").innerHTML = ""; $("gal-sources").innerHTML = "";
  $("gal-body").scrollTop = 0;
  $("gal-end").textContent = "Asking the sites…";
  closeView();
  renderBrowseList(); renderBrowseHead();
  var g = G;
  api("POST", "/api/gallery/open", { artist_id: id || 0 }).then(function (d) {
    if (g !== G) return api("POST", "/api/gallery/close", { gallery: d.gallery });
    g.id = d.gallery; g.sources = d.sources;
    galSources(d.sources);
    moreGallery();
  }).catch(function (e) { $("gal-end").textContent = e.message; });
}

// The ids of the sources whose site the filter has switched off.
function offIds(g) {
  return (g.sources || []).filter(function (s) { return g.hidden[s.label]; }).map(function (s) { return s.id; });
}

function moreGallery() {
  var g = G;
  if (!g || !g.id || g.busy || g.done) return;
  // Only hidden sources have more: nothing to show for the requests it would take.
  if (g.sources && !g.sources.some(function (s) { return !g.hidden[s.label] && s.state === "more"; })) return;
  g.busy = true;
  $("gal-end").textContent = "Asking the sites…";
  // The first page is only what the window shows: it is there as soon as one source answered.
  api("POST", "/api/gallery/more", { gallery: g.id, n: g.items.length ? 60 : 24, off: offIds(g) }).then(function (d) {
    if (g !== G) return;
    g.busy = false; g.done = d.done; g.sources = d.sources;
    var start = g.items.length;
    g.items = g.items.concat(d.items);
    $("gal-grid").insertAdjacentHTML("beforeend", d.items.map(function (it, k) { return tileHtml(it, start + k); }).join(""));
    galWatch();
    galSources(d.sources);
    $("gal-end").textContent = !g.done ? "" : g.items.length ? plural(g.items.length, "picture") + " – that is all" : "Nothing found.";
    // The observer fires on a change only: while the end is still in sight, ask on.
    if (!g.done && d.items.length) {
      var end = $("gal-end").getBoundingClientRect(), box = $("gal-body").getBoundingClientRect();
      if (end.top < box.bottom + 800) setTimeout(moreGallery, 50);
    }
  }).catch(function (e) { g.busy = false; $("gal-end").textContent = e.message; });
}

// Sourcerer's own fetch of an item, for one the page could not load itself;
// "" for one that already comes through Sourcerer.
function proxyOf(it, size) {
  var url = size === "thumb" ? it.thumb : it.large;
  if (!G || !G.id || /^\/api\/gallery\/[0-9a-f]{32}\//.test(url || "")) return "";
  return "/api/gallery/" + G.id + "/" + it.id + "/" + size;
}

function tileHtml(it, i) {
  var proxied = /^\/api\/gallery\//.test(it.thumb || "");
  var picture = it.thumb
    ? '<img loading="lazy" decoding="async" referrerpolicy="no-referrer" ' + (proxied ? "data-lazy" : "src") + '="' + esc(it.thumb) + '" alt="">'
    : '<span class="gal-noimg">' + icon(it.video ? "play" : "photo") + "</span>";
  var who = G.all ? it.artist + " · " + it.source : it.source;
  return '<button type="button" class="gal-tile' + (G.hidden[it.source] ? " hidden" : "") + '" data-i="' + i +
    '" data-src="' + esc(it.source) + '" title="' + esc(who + (it.posted ? " · " + it.posted.slice(0, 10) : "")) + '">' +
    picture + (it.video && it.thumb ? '<span class="gal-play">' + icon("play") + "</span>" : "") +
    '<span class="gal-tag">' + esc(who) + "</span>" +
    (it.saved ? '<span class="gal-saved" title="Downloaded">' + icon("check") + "</span>" : "") + "</button>";
}

// One chip per site the open gallery has a source of: switching it off hides its posts and
// stops asking it; the choice is kept for the next artist.
function galSources(list) {
  var sites = [];
  list.forEach(function (s) { if (sites.indexOf(s.label) < 0) sites.push(s.label); });
  $("gal-sources").innerHTML = sites.map(function (label) {
    var of = list.filter(function (s) { return s.label === label; });
    var bad = of.filter(function (s) { return s.error; });
    var tip = bad.length ? label + ": " + bad[0].error : "Show or hide " + label + (G.all ? " (" + plural(of.length, "source") + ")" : "");
    return '<button type="button" class="chip' + (G.hidden[label] ? " off" : "") + '" data-galsrc="' + esc(label) +
      '" title="' + esc(tip) + '"><i class="dot ' + (bad.length ? "warn" : of.every(function (s) { return s.state === "done"; }) ? "ok" : "blank") +
      '"></i>' + esc(label) + "</button>";
  }).join("");
}

function viewItem(i) {
  if (!G || !G.items[i]) return;
  var it = G.items[i];
  G.view = i;
  // The grid's picture stands in while the large one comes (a proxied one can
  // wait a few seconds for its site's turn) -- only when it is already loaded,
  // so the stand-in costs no request of its own.
  var small = $("gal-grid").querySelector('.gal-tile[data-i="' + i + '"] img');
  small = small && small.complete && small.naturalWidth && small.currentSrc !== it.large ? small.currentSrc : "";
  $("gal-stage").innerHTML = it.video
    ? '<video controls autoplay loop src="' + esc(it.large) + '"' + (it.thumb ? ' poster="' + esc(it.thumb) + '"' : "") + "></video>"
    : (small ? '<img class="gal-ph" referrerpolicy="no-referrer" src="' + esc(small) + '" alt="">' : "") +
      '<img referrerpolicy="no-referrer"' + (small ? ' class="gal-big"' : "") + ' src="' + esc(it.large || it.thumb) + '" alt="">';
  var img = $("gal-stage").querySelector("img:last-child");
  if (img) {
    // What to try next when one will not load: Sourcerer's own fetch, then the small one.
    var next = [proxyOf(it, "large"), small ? "" : it.thumb].filter(function (u) { return u && u !== img.getAttribute("src"); });
    img.onload = function () {
      if (!img.isConnected) return;                // the view moved on: not this item's stand-in any more
      var ph = $("gal-stage").querySelector(".gal-ph"); if (ph) ph.remove(); img.classList.remove("gal-big");
    };
    img.onerror = function () {
      if (!img.isConnected) return;
      if (next.length) img.src = next.shift();
      else { img.onerror = null; if (small) img.remove(); }
    };
  }
  $("gal-info").textContent = [G.all ? it.artist : "", it.source, it.posted ? new Date(it.posted).toLocaleString() : "",
    it.w ? it.w + " × " + it.h : "", (i + 1) + " / " + G.items.length + (G.done ? "" : "+")].filter(Boolean).join(" · ");
  var busy = !!G.downloading[it.id];
  $("gal-download").disabled = it.saved || busy;
  $("gal-download").querySelector("span").textContent = it.saved ? "Downloaded" : busy ? "Downloading…" : "Download";
  $("gal-view").classList.remove("hidden");
  // Near the end of what is listed: the next page, before it is needed.
  if (i > G.items.length - 8) moreGallery();
}

function step(by) {
  if (!G) return;
  var i = G.view;
  do { i += by; } while (G.items[i] && G.hidden[G.items[i].source]);
  if (G.items[i]) viewItem(i);
}

function closeView() {
  $("gal-view").classList.add("hidden");
  $("gal-stage").innerHTML = "";                  // stops a video
  if (G) G.view = -1;
}

$("gal-grid").addEventListener("click", function (e) {
  var tile = e.target.closest(".gal-tile");
  if (tile) viewItem(+tile.dataset.i);
});
// A picture the browser was not handed (a CDN's bot check, a hotlink rule):
// once more through Sourcerer, then a placeholder instead of a broken image.
$("gal-grid").addEventListener("error", function (e) {
  if (e.target.tagName !== "IMG") return;
  var tile = e.target.closest(".gal-tile"), it = G && G.items[+tile.dataset.i];
  var via = it && proxyOf(it, "thumb");
  if (via && !e.target.dataset.lazy) {
    e.target.removeAttribute("src"); e.target.dataset.lazy = via;
    galQueue.push(e.target);
    setTimeout(galPump);                 // after this event: listeners added now would hear it
    return;
  }
  e.target.outerHTML = '<span class="gal-noimg">' + icon(it && it.video ? "play" : "photo") + "</span>";
}, true);
$("gal-sources").addEventListener("click", function (e) {
  var chip = e.target.closest("[data-galsrc]");
  if (!chip || !G) return;
  var label = chip.dataset.galsrc;
  G.hidden[label] = !G.hidden[label];
  try { localStorage.setItem(BR_HIDDEN, JSON.stringify(G.hidden)); } catch (e2) {}
  chip.classList.toggle("off", !!G.hidden[label]);
  $$("#gal-grid .gal-tile").forEach(function (t) { if (t.dataset.src === label) t.classList.toggle("hidden", !!G.hidden[label]); });
  if (!G.hidden[label]) { G.done = false; galWatch(); }
  moreGallery();
});
$("gal-view").addEventListener("click", function (e) {
  var b = e.target.closest("[data-gal]");
  if (!b || !G) return;
  var it = G.items[G.view];
  if (b.dataset.gal === "prev") step(-1);
  else if (b.dataset.gal === "next") step(1);
  else if (b.dataset.gal === "back") closeView();
  else if (b.dataset.gal === "post" && it && it.post) api("POST", "/api/open-url", { url: it.post }).catch(fail);
  else if (b.dataset.gal === "download" && it && !it.saved) {
    var g = G, i = G.view;
    g.downloading[it.id] = true;
    b.disabled = true;
    b.querySelector("span").textContent = "Downloading…";
    api("POST", "/api/gallery/download", { gallery: g.id, item: it.id }).then(function (d) {
      if (g !== G) return;
      delete g.downloading[it.id];
      g.items[i] = d.item;
      var tile = document.querySelector('#gal-grid .gal-tile[data-i="' + i + '"]');
      if (tile) { tile.outerHTML = tileHtml(d.item, i); galWatch(); }
      if (g.view === i) viewItem(i);
      toast(d.kept ? "Saved in " + d.item.artist + "'s folder" : "Not saved: the same picture is already in the folder");
      load();
    }).catch(function (err) {
      fail(err);
      if (g !== G) return;
      delete g.downloading[it.id];
      if (g.view === i) viewItem(i);
    });
  }
});
$("gal-size").addEventListener("input", function () { $("gal-grid").style.setProperty("--gal", this.value + "px"); });
// The large view: arrows step, Esc closes it (the keys of the card grid do not apply here).
document.addEventListener("keydown", function (e) {
  if (S.view !== "browse" || document.querySelector("dialog[open]")) return;
  var open = !$("gal-view").classList.contains("hidden");
  if (e.key === "Escape" && open) { e.preventDefault(); e.stopPropagation(); closeView(); }
  else if (open && e.key === "ArrowLeft") { e.preventDefault(); step(-1); }
  else if (open && e.key === "ArrowRight") { e.preventDefault(); step(1); }
}, true);
$("view-cards").addEventListener("click", function () { setView("cards"); });
$("view-browse").addEventListener("click", function () { setView("browse"); });
$("br-search").addEventListener("input", renderBrowseList);
$("br-list").addEventListener("click", function (e) {
  var b = e.target.closest("[data-id]");
  if (b) browseOpen(+b.dataset.id);
});
// Download all: the card is synced, but only through the sources that are switched on.
$("br-download").addEventListener("click", function () {
  if (!G || G.all) return;
  var ids = (G.sources || []).filter(function (s) { return !G.hidden[s.label]; }).map(function (s) { return s.id; });
  if (!ids.length) return toast("Switch on at least one source first.", true);
  var b = this;
  b.disabled = true;
  api("POST", "/api/sync", { artist_id: G.artist.id, sources: ids }).then(function (d) {
    toast(d.added ? "Downloading from " + plural(ids.length, "source") + "…" : "This card is syncing or queued already.");
    lastKey = ""; return api("GET", "/api/sync");
  }).then(function (s) { S.sync = s; renderBrowseHead(); }).catch(fail).then(function () { b.disabled = false; });
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
           status: "", error: "", handle: "", checked: "", account: null };
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
  var first = document.querySelector(".srcinput");
  (a || !first ? f.name : first).focus();
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
                            status: d.status, error: d.error || "", handle: d.handle || "",
                            account: d.account || null });
    // A name the site states beats one read from a link; one typed beats both.
    var name = $("form-card").name, fromSite = !!d.from_site;
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
  // A site is listed once there is a login for it, or a link already on the card:
  // saving must never drop a source because its login is gone.
  var html = F.rows.map(function (r, i) {
    var filled = !!r.url.trim(), field = S.fields.filter(function (f) { return f.label === r.field; })[0];
    if (!filled && !(field && field.logged_in)) return "";
    var isMaster = filled && master && r.url === master;
    var mark = filled && r.supported
      ? '<button type="button" data-src="master" data-i="' + i + '" title="' + (isMaster ? "Master source" : "Make this the master source") + '">' +
        (isMaster ? icon("crown", "crown") : icon("point", "point")) + "</button>"
      : '<button type="button" disabled>' + icon("point", "point") + "</button>";
    var state = !filled ? ""
      : r.status === "checking" ? '<span class="state">checking…</span>'
      : r.status === "unsupported" ? '<span class="badge warning">not supported yet</span>'
      : r.status === "login" && r.account ? '<span class="state warn">needs a login</span>'
      : r.status === "login" ? '<button type="button" class="badge warning" data-src="login" data-i="' + i + '" title="' + esc(r.error) + '">log in first</button>'
      : '<span class="state' + (r.status === "error" || r.status === "warn" ? " " + r.status : "") + '" title="' + esc(statusText(r)) + '">' +
        esc(r.status === "ok" && r.handle ? r.handle : statusText(r)) + "</span>";
    return '<div class="srcrow' + (r.field ? "" : " extra") + '">' + mark +
      '<span class="site"><i class="dot ' + (filled ? r.status : "blank") + '" title="' + esc(filled ? statusText(r) : "") + '"></i>' +
      esc(r.field || (filled && r.label !== "…" ? r.label : "Link")) + "</span>" +
      '<input type="text" class="srcinput" data-row="' + i + '" value="' + esc(r.url) + '" autocomplete="off" spellcheck="false" placeholder="' +
      esc(field ? field.example : "Link") + '">' + state +
      (r.field ? "" : '<button type="button" data-src="remove" data-i="' + i + '" title="Remove">' + icon("x") + "</button>") + "</div>" +
      (filled ? loginNote(r, i) : "");
  }).join("");
  $("src-list").innerHTML = html || '<div class="srcempty">You are not logged in to any site yet. ' +
    '<button type="button" class="mini primary" data-act="accounts">Manage Accounts</button></div>';
  if (at != null) {
    var again = document.querySelector('.srcinput[data-row="' + at + '"]');
    if (again) { again.focus(); try { again.setSelectionRange(pos, pos); } catch (e) {} }
  }
  renderForm();
}

// Under a link whose site wants a login that is missing or ran out: what
// comes without it, and the way to it.
function loginNote(r, i) {
  var a = r.account;
  if (!a || r.status === "checking") return "";
  var text = a.expired ? "The " + (a.kind === "window" ? r.label : a.label) + " login has run out; Sourcerer gets only what visitors see."
    : a.why || "This site shows more to logged-in accounts.";
  var hard = a.expired || a.need === "required";
  return '<div class="srcnote' + (hard ? "" : " soft") + '">' + icon(hard ? "alert" : "info") + "<span>" + esc(text) + "</span>" +
    '<button type="button" class="mini' + (hard ? " primary" : "") + '" data-src="account" data-i="' + i + '">' +
    (a.expired ? "Log in again" : "Log in") + "</button></div>";
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
  if (next) next.focus();
});
$("src-list").addEventListener("click", function (e) {
  var btn = e.target.closest("[data-src]");
  if (!btn) return;
  var r = F.rows[+btn.dataset.i];
  if (btn.dataset.src === "login") return r && r.account ? loginFor(r.account, r.url) : openAccounts();
  if (btn.dataset.src === "account") return loginFor(r.account, r.url);
  if (btn.dataset.src === "remove") F.rows.splice(+btn.dataset.i, 1);
  else { F.master = r.url; F.dedupe = "master"; }
  renderSources();
});
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

// Manage your accounts: one row per login that exists -- saved, or being made in a
// window -- and an "Add account" button at the end. A site without a login has no row:
// it is added by choosing its type. Bluesky and the boorus log in with fields, the
// others in a window of Sourcerer's own.
var accTimer = null;
// What the add panel asks for besides the type: a Mastodon server or a forum is typed in,
// a booru is chosen from the list, Bluesky takes its fields. X, Pixiv and Patreon need nothing.
var ADD = {
  mastodon: { field: "server", label: "Server", placeholder: "mastodon.social" },
  xenforo: { field: "forum", label: "Forum", placeholder: "forum.example.com" }
};
S.accFocus = ""; S.accScroll = false; S.accHtml = ""; S.accData = null; S.accWaiting = false; S.accWant = "";
S.accAdding = false; S.accType = ""; S.accBooru = ""; S.accPre = ""; S.importBody = null; S.importAdd = false;
S.accBusy = {}; S.accError = {}; S.accChecking = {};     // per box: sending, what the site said, being asked

function accState(a) {
  var expired = a.logged_in && a.state === "expired";
  return a.pending === "waiting" ? "Waiting for you to log in in the other window…"
    : expired ? "The login has run out" + (a.checked ? " (noticed " + ago(a.checked) + ")" : "") + " – log in again."
    : a.logged_in && a.rest ? "Works, but the site rests until " + restUntil(a.rest.until) + ": " + a.rest.why
    : a.logged_in ? "Logged in" + (a.user ? " as " + a.user : "") + (a.checked ? " · checked " + ago(a.checked) : "")
    : a.pending.indexOf("failed: ") === 0 ? a.pending.slice(8)
    : a.pending === "cancelled" ? "Login window closed before the login was finished."
    : "Not logged in";
}

function accHelp(url, text) {
  return url ? '<a href="#" data-acc="help" data-url="' + esc(url) + '">' + text + "</a>" : "";
}

// The fields a login takes (Bluesky, a booru), or "" for a login made in a window.
function accFields(a) {
  if (a.kind === "password") {
    return '<input name="handle" type="text" placeholder="Handle: name.bsky.social" aria-label="Handle" autocomplete="off" spellcheck="false">' +
      '<input name="password" type="password" placeholder="App password: xxxx-xxxx-xxxx-xxxx" aria-label="App password" autocomplete="off">' +
      '<p class="hint">Not your account\'s password: ' + accHelp("https://bsky.app/settings/app-passwords", "create an app password") +
      " in Bluesky. Sourcerer keeps the session it opens, not the password.</p>";
  }
  if (a.kind === "api_key") {
    return '<input name="user" type="text" placeholder="' + esc(a.user_label || "User name") + '" aria-label="' + esc(a.user_label || "User name") + '" autocomplete="off" spellcheck="false">' +
      '<input name="api_key" type="password" placeholder="' + esc(a.key_hint || "API key") + '" aria-label="API key" autocomplete="off">' +
      '<p class="hint">' + accHelp(a.help, "Where is my API key?") + " It stays on this computer.</p>";
  }
  return "";
}

function accBox(a, win) {
  var expired = a.logged_in && a.state === "expired", waiting = a.pending === "waiting";
  var key = esc(a.key), need = !a.logged_in || expired, fields = need && !waiting ? accFields(a) : "";
  var byWindow = a.kind === "window" || a.kind === "oauth";
  // Green: the login works. Orange: it works but the site rests. Red: it ran out. Hollow: not logged in.
  var dot = waiting || S.accChecking[a.key] ? "checking" : expired ? "error" : a.logged_in && a.rest ? "warn" : a.logged_in ? "ok" : "blank";
  var btns = "";
  if (!waiting) {
    if (need) {
      btns += fields
        ? '<button type="submit" class="primary"' + (S.accBusy[a.key] ? " disabled" : "") + ">" + (expired ? "Log in again" : "Log in") + "</button>"
        : '<button type="button" class="primary" data-acc="login"' +
          (byWindow && !win ? ' disabled title="Needs Sourcerer\'s own window"' : "") + ">" + (expired ? "Log in again" : "Log in") + "</button>";
    }
    if (a.logged_in) {
      btns += '<button type="button" data-acc="check" title="Ask the site whether the login still works"' +
        (S.accChecking[a.key] ? " disabled" : "") + ">Check</button>" + '<button type="button" data-acc="logout">Log out</button>';
    } else {
      btns += '<button type="button" data-acc="drop" title="Forget this attempt">Remove</button>';   // a login that failed or was closed
    }
    if (a.kind === "window" && !win) btns += '<button type="button" data-acc="import" title="Import a cookies.txt">Import&hellip;</button>';
  }
  return '<form class="accbox' + (expired ? " expired" : "") + (a.key === S.accFocus ? " focus" : "") + '" data-key="' + key + '" data-kind="' + a.kind + '">' +
    accId(dot, a.group || a.label, a.group ? a.label : "", accState(a), dot === "warn" ? "warn" : expired ? "bad" : "") +
    (fields ? '<div class="acc-fields">' + fields + "</div>" : "") +
    '<div class="acc-btns">' + btns + "</div>" +
    '<p class="error">' + esc(S.accError[a.key] || "") + "</p></form>";
}

var ACC_DOT = { ok: "Works", warn: "Works, but needs attention", error: "Ran out: log in again", blank: "Not logged in", checking: "Checking…" };

// The left of a row: the status dot, the name and what is known about the login.
function accId(dot, name, sub, state, tone) {
  return '<div class="acc-id"><i class="dot ' + dot + '" title="' + ACC_DOT[dot] + '"></i><div class="acc-text">' +
    '<div class="acc-top"><b>' + esc(name) + "</b>" + (sub ? '<span class="muted small">' + esc(sub) + "</span>" : "") + "</div>" +
    '<p class="hint acc-state' + (tone ? " " + tone : "") + '">' + esc(state) + "</p></div></div>";
}

// The end of the list: the Add account button, or -- once it is pressed -- the row that adds one.
// The type and, for a booru, the site start empty: nothing is chosen for the user.
function accAdd(d) {
  if (!S.accAdding) {
    return '<button type="button" class="accadd" data-acc="add"><svg class="ic"><use href="#i-plus"/></svg> Add account</button>';
  }
  var types = d.types.filter(function (t) { return t.many || !d.accounts.some(function (a) { return a.key === t.type; }); });
  var t = types.filter(function (x) { return x.type === S.accType; })[0], fields = "", go = !!t;
  var window_ = t && (t.kind === "window" || t.kind === "oauth");
  if (t && t.type === "bluesky") fields = accFields({ kind: "password" });
  else if (t && ADD[t.type]) {
    var f = ADD[t.type];
    fields = '<input name="' + f.field + '" type="text" placeholder="' + esc(f.label + ": " + f.placeholder) + '" aria-label="' + esc(f.label) +
      '" value="' + esc(S.accPre) + '" autocomplete="off" spellcheck="false">';
  } else if (t && t.type === "booru") {
    var b = d.boorus.filter(function (x) { return x.host === S.accBooru; })[0];
    fields = '<select name="booru" aria-label="Booru"><option value="">Choose a booru…</option>' + d.boorus.map(function (x) {
      return '<option value="' + esc(x.host) + '"' + (x.host === S.accBooru ? " selected" : "") + ">" + esc(x.name) + "</option>"; }).join("") + "</select>" +
      (b ? accFields({ kind: "api_key", user_label: b.user_label, key_hint: b.key_hint, help: b.help }) : "");
    go = !!b;
  } else if (t) {
    fields = '<p class="hint">' + (S.window ? "A window of Sourcerer's own opens: log in to " + esc(t.label) + " there."
      : "Sourcerer's own window is needed for this login. Import the site's cookies.txt instead.") + "</p>";
  }
  var needsWindow = window_ && !S.window;
  var btns = '<button type="submit" class="primary"' + (!go || S.accBusy.add || needsWindow ? " disabled" : "") +
    (needsWindow ? ' title="Needs Sourcerer\'s own window"' : "") + ">Log in</button>";
  if (t && t.kind === "window" && !S.window) btns += '<button type="button" data-acc="import-add" title="Import a cookies.txt">Import&hellip;</button>';
  btns += '<button type="button" data-acc="cancel">Cancel</button>';
  return '<form class="accbox adding' + (S.accFocus === "add" ? " focus" : "") + '" data-key="add" data-add="1" data-kind="' + (t ? t.kind : "") + '">' +
    '<div class="acc-id"><i class="dot blank"></i><div class="acc-text"><div class="acc-top"><b>Add account</b></div>' +
    '<select name="type" aria-label="Type of account"><option value="">Choose the type of account…</option>' +
    types.map(function (x) { return '<option value="' + x.type + '"' + (x.type === S.accType ? " selected" : "") + ">" + esc(x.label) + "</option>"; }).join("") +
    "</select></div></div>" + (fields ? '<div class="acc-fields">' + fields + "</div>" : "") +
    '<div class="acc-btns">' + btns + "</div>" +
    '<p class="error">' + esc(S.accError.add || "") + "</p></form>";
}

// One row per account there is, then the end of the list.
function accBoxes(d) {
  return d.accounts.map(function (a) { return accBox(a, d.window); }).join("") + accAdd(d);
}

function openAccounts(key) {
  closeMenu();
  S.accWant = key || "";
  S.accHtml = "";
  $("acc-browser").classList.toggle("hidden", S.window);
  if (!$("dlg-accounts").open) $("dlg-accounts").showModal();
  loadAccounts();
}

function loadAccounts() {
  clearTimeout(accTimer);
  return api("GET", "/api/accounts").then(function (d) {
    S.accData = d;
    drawAccounts();
  }).catch(fail);
}

// A login a card's link asks for: its row when there is one, else the add panel with the
// type (and server, forum or booru) of that link already in -- only because the link named it.
function accWanted(d) {
  var key = S.accWant;
  S.accWant = "";
  if (!key) return;
  if (d.accounts.some(function (a) { return a.key === key; })) { S.accFocus = key; S.accScroll = true; return; }
  var type = key.split(":")[0], host = key.split(":").slice(1).join(":");
  S.accAdding = true; S.accType = type; S.accFocus = "add"; S.accScroll = true;
  S.accPre = type === "mastodon" || type === "xenforo" ? host : "";
  S.accBooru = type === "booru" ? host : "";
}

function drawAccounts() {
  var d = S.accData;
  if (!d) return;
  accWanted(d);
  var html = accBoxes(d);
  // Asked every 1.5 s while a login window is open: redrawn only when
  // something changed, and then what is typed meanwhile stays.
  if (html !== S.accHtml) redrawAccounts(html);
  var logged = d.accounts.filter(function (a) { return a.logged_in; });
  $("btn-acc-check").disabled = !logged.length || Object.keys(S.accChecking).length > 0;
  if (S.accFocus && S.accScroll) {
    S.accScroll = false;
    var box = document.querySelector('#acc-grid .accbox[data-key="' + S.accFocus + '"]');
    if (box) box.scrollIntoView({ block: "nearest" });
  }
  // While a login window is open, follow it; the row turns green by itself, and
  // when the window is gone the cards and the links learn what the login gave.
  var waiting = d.accounts.some(function (a) { return a.pending === "waiting"; });
  if (S.accWaiting && !waiting) afterAccounts();
  S.accWaiting = waiting;
  clearTimeout(accTimer);
  if (waiting) accTimer = setTimeout(loadAccounts, 1500);      // also with the dialog closed: the window may finish later
}

function redrawAccounts(html) {
  S.accHtml = html;
  var typed = {}, focused = document.activeElement, at = null, grid = $("acc-grid");
  var id = function (i) { var box = i.closest("[data-key]"); return (box ? box.dataset.key : "") + "/" + (i.name || ""); };
  Array.prototype.forEach.call(grid.querySelectorAll("input, select"), function (i) {
    typed[id(i)] = i.value;
    if (i === focused) at = id(i);
  });
  grid.innerHTML = html;
  Array.prototype.forEach.call(grid.querySelectorAll("input, select"), function (i) {
    if (typed[id(i)] !== undefined) i.value = typed[id(i)];
    if (id(i) === at) i.focus();
  });
}

function addClosed() { S.accAdding = false; S.accType = ""; S.accBooru = ""; S.accPre = ""; S.accError.add = ""; }

// Back from a login: the cards, the badge and the links of an open card dialog catch up.
function afterAccounts() {
  return load().then(function () { if ($("dlg-card").open && F) renderSources(); });
}

function showAccounts() {
  var n = (S.logins || []).length, b = $("btn-accounts");
  b.classList.toggle("warn", n > 0);
  $("acc-count").textContent = n;
  $("acc-count").classList.toggle("hidden", !n);
  b.title = n ? S.logins.map(function (l) { return l.label + ": log in again"; }).join("\n")
              : "Log in to your sites and keep the logins working";
}

function accLogin(body) {
  return api("POST", "/api/accounts/login", body).then(function (d) {
    S.accFocus = d.key; S.accScroll = true;
    return loadAccounts();
  });
}

// Asks the sites, one after the other, whether the logins still work.
function accCheck(keys) {
  keys = keys.filter(function (k) { return !S.accChecking[k]; });
  if (!keys.length) return Promise.resolve();
  keys.forEach(function (k) { S.accChecking[k] = true; });
  drawAccounts();
  return keys.reduce(function (p, k) {
    return p.then(function () { return api("POST", "/api/accounts/check", { key: k }); })
      .catch(fail)
      .then(function () { delete S.accChecking[k]; return loadAccounts(); });
  }, Promise.resolve()).then(afterAccounts);
}

// From the card dialog: the login a link needs, at once where a window does it; else the add
// panel with what the link names already in (the fields are typed there).
function loginFor(acc, url) {
  var inWindow = (acc.kind === "window" || acc.kind === "oauth") && S.window;
  openAccounts(inWindow ? "" : acc.key);
  if (inWindow) accLogin({ key: acc.key, url: url }).catch(fail);
}

$("acc-grid").addEventListener("click", function (e) {
  var b = e.target.closest("[data-acc]");
  if (!b) return;
  e.preventDefault();
  var box = b.closest("[data-key]"), key = box ? box.dataset.key : "", act = b.dataset.acc;
  if (act === "help") return api("POST", "/api/open-url", { url: b.dataset.url }).catch(fail);
  if (act === "add") {
    S.accAdding = true; S.accType = ""; S.accFocus = "add"; S.accScroll = true;
    drawAccounts();
    var sel = $("acc-grid").querySelector("select[name=type]");
    return sel && sel.focus();
  }
  if (act === "cancel") { addClosed(); return drawAccounts(); }
  if (act === "import") { S.importBody = { key: key }; S.importAdd = false; $("acc-file").value = ""; return $("acc-file").click(); }
  if (act === "import-add") {
    var f = b.form, type = f.elements.type.value;
    if (type === "xenforo") {
      if (!f.elements.forum.value.trim()) return f.elements.forum.focus();
      S.importBody = { forum: f.elements.forum.value };
    } else S.importBody = { key: type };
    S.importAdd = true;
    $("acc-file").value = "";
    return $("acc-file").click();
  }
  if (act === "check") return accCheck([key]);
  if (act === "login") {
    b.disabled = true;
    return accLogin({ key: key }).catch(fail).then(function () { b.disabled = false; });
  }
  if (act === "logout" || act === "drop") {
    if (act === "logout" && !confirm("Log out? Sourcerer forgets what it kept for this login.")) return;
    b.disabled = true;
    api("POST", "/api/accounts/logout", { key: key }).then(function () {
      return loadAccounts();
    }).then(afterAccounts).catch(fail).then(function () { b.disabled = false; });
  }
});
$("acc-grid").addEventListener("change", function (e) {
  var add = e.target.form && e.target.form.dataset.add;
  if (add && e.target.name === "type") { S.accType = e.target.value; S.accPre = ""; S.accBooru = ""; S.accError.add = ""; drawAccounts(); }
  else if (add && e.target.name === "booru") { S.accBooru = e.target.value; drawAccounts(); }
});
$("acc-grid").addEventListener("submit", function (e) {
  e.preventDefault();
  var f = e.target, key = f.dataset.key, add = !!f.dataset.add, type = add ? f.elements.type.value : "";
  if (S.accBusy[key]) return;
  var body = add ? (ADD[type] || type === "booru" ? {} : { key: type }) : { key: key };
  Array.prototype.forEach.call(f.elements, function (i) { if (i.name && i.name !== "type") body[i.name] = i.value; });
  // A server or a forum is typed in; a booru is chosen: nothing is guessed for the user.
  var needed = add ? (ADD[type] ? f.elements[ADD[type].field] : type === "booru" ? f.elements.booru : null) : null;
  if (add && !type) return f.elements.type.focus();
  if (needed && !needed.value.trim()) return needed.focus();
  // The grid may be redrawn meanwhile: the box is found again by its key.
  var show = function () {
    var box = document.querySelector('#acc-grid .accbox[data-key="' + key + '"]');
    if (!box) return;
    var go = box.querySelector("button[type=submit]");
    if (go) go.disabled = !!S.accBusy[key];
    box.querySelector("p.error").textContent = S.accError[key] || "";
  };
  S.accBusy[key] = true; S.accError[key] = ""; show();
  // Bluesky and the boorus are logged in when the answer comes; the others open a window.
  var instant = f.dataset.kind === "password" || f.dataset.kind === "api_key";
  (instant ? api("POST", "/api/accounts/login", body).then(function (d) {
    S.accFocus = d.key; S.accScroll = true;
    toast("Logged in");
    if (add) addClosed();
    return loadAccounts().then(afterAccounts);
  }) : accLogin(body).then(function () { if (add) addClosed(); return loadAccounts(); })).then(function () {
    delete S.accBusy[key]; show();
  }, function (err) {
    delete S.accBusy[key]; S.accError[key] = err.message; show();
  });
});
$("acc-file").addEventListener("change", function () {
  var file = this.files[0];
  if (!file || !S.importBody) return;
  file.text().then(function (text) {
    return api("POST", "/api/accounts/import", Object.assign({ text: text }, S.importBody));
  }).then(function (d) {
    toast("Imported: " + plural(d.cookies, "cookie"));
    if (S.importAdd) addClosed();
    S.accFocus = d.key || ""; S.accScroll = true;
    return loadAccounts().then(afterAccounts);
  }).catch(fail);
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
    $("gdl-version").textContent = d.gallery_dl ? "v" + d.gallery_dl : "(not installed)";
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
$("btn-gdl").addEventListener("click", function () {
  var b = this;
  b.disabled = true; b.textContent = "Updating…";
  api("POST", "/api/update/gallery-dl").then(function (d) {
    toast("gallery-dl is now v" + d.version); loadInfo();
  }).catch(fail).then(function () { b.disabled = false; b.textContent = "Update now"; });
});

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

$("dlg-accounts").addEventListener("close", function () {
  // An unfinished add is dropped; a login window that is still open is followed on.
  addClosed(); S.accFocus = ""; S.accHtml = "";
  $("acc-grid").innerHTML = "";      // what was typed belongs to this visit: not put back into the next one
  if (S.accWaiting) loadAccounts(); else clearTimeout(accTimer);
  afterAccounts().then(function () {
    // Back from a login: the links that wanted one say what they get now.
    if ($("dlg-card").open && F) F.rows.forEach(function (r) { if (r.status === "login" || r.account) check(r, true); });
  });
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
$("btn-accounts").addEventListener("click", function () { openAccounts(); });
$("btn-acc-check").addEventListener("click", function () {
  accCheck(((S.accData || {}).accounts || []).filter(function (a) { return a.logged_in; }).map(function (a) { return a.key; }));
});
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
