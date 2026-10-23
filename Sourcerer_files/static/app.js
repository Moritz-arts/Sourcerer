// Sourcerer's window: the artists and their posts (Browse), the card dialog, settings, the activity bar.
// Plain DOM code, no framework, no build step -- the same as TrackImage.

var S = {
  artists: [], sync: {}, library: "", window: false, sep: "/", sites: [], fields: [], settings: {},
  menuFor: null, logFilter: "all", logSeen: "", update: null
};
var F = null;   // the card dialog's working copy: {id, sources, layout, dedupe, master, autoName}
var DEFAULT_GAL = 200;

// What the page keeps for itself (`sourcerer.*` in localStorage) is mirrored into Userdata: the window's origin changes with its port at
// every start, so the browser's own copy was gone at the next start or update. The server's copy is put back first (/api/ui.js, before
// this file), keys only the browser has are sent once, and every later change is sent as it happens.
(function () {
  var ls, kept = window.UI_PREFS || {}, queue = {}, timer = 0, mine = /^sourcerer\./;
  try { ls = window.localStorage; Object.keys(kept).forEach(function (k) { ls.setItem(k, kept[k]); }); } catch (e) { return; }
  function flush() {
    clearTimeout(timer); timer = 0;
    var body = JSON.stringify(queue); queue = {};
    if (body !== "{}") fetch("/api/ui", { method: "POST", headers: { "Content-Type": "application/json" }, body: body, keepalive: true }).catch(function () {});
  }
  function note(k, v) { queue[k] = v; if (!timer) timer = setTimeout(flush, 400); }
  var put = Storage.prototype.setItem, drop = Storage.prototype.removeItem;
  Storage.prototype.setItem = function (k, v) { put.call(this, k, v); if (this === ls && mine.test(k)) note(k, String(v)); };
  Storage.prototype.removeItem = function (k) { drop.call(this, k); if (this === ls && mine.test(k)) note(k, null); };
  try { Object.keys(ls).forEach(function (k) { if (mine.test(k) && !(k in kept)) note(k, ls.getItem(k)); }); } catch (e) {}
  window.addEventListener("pagehide", flush);
})();

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
      if (!r.ok && r.status === 401 && data.locked) lockedNow();          // the master password is asked for again
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
    // The picture comes from the site, through memory (nothing is kept); when it does not come, the initials stand in.
    return "<img" + attr + ' class="' + cls + '" alt="" loading="lazy" decoding="async" data-name="' + esc(name) + '" onerror="avatarFail(this)" src="/api/avatar/' + a.id + "?v=" +
      encodeURIComponent(a.avatar_checked || "") + '">';
  }
  return initialsHtml(name, cls, attr);
}
function initialsHtml(name, cls, attr) {
  var c = colours(name);
  return "<div" + (attr || "") + ' class="' + cls + '" style="background:' + c[0] + ";color:" + c[1] + '">' +
    esc(initials(name)) + "</div>";
}
function avatarFail(img) {
  var box = document.createElement("div");
  box.innerHTML = initialsHtml(img.dataset.name || "?", img.className, img.id ? ' id="' + img.id + '"' : "");
  img.replaceWith(box.firstChild);
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
  document.documentElement.classList.toggle("no-tile-logo", S.settings.tile_logo === "0");
}

// ---- artists ---------------------------------------------------------------

// By id from a map that is built again only when the list is a new one (it is asked for per log entry and per queued card).
var byIdOf = null, byId = null;
function artistById(id) {
  if (byIdOf !== S.artists) { byIdOf = S.artists; byId = {}; S.artists.forEach(function (a) { byId[a.id] = a; }); }
  return byId[id];
}

// When something last happened on a card: a download, else a sync, else its making.
// When an artist last did something, as one string to compare ("YYYY-MM-DD HH:MM:SS", UTC): the newest post a look at
// their sources saw, else the last download or look. "" is nothing known -- a card that was only just listed -- and
// it goes last: its "created" says when it was imported, not when the artist posted (it once put them all first).
function activityKey(a) {
  var latest = a.sources.reduce(function (m, s) { return s.latest && s.latest > m ? s.latest : m; }, "");
  return latest || a.last_activity || a.last_sync || "";
}

function renderAll() {
  $("empty").classList.toggle("hidden", S.artists.length > 0);
  $("browse").classList.toggle("blank", !S.artists.length);
  renderBrowseList(); renderBrowseHead(); renderActivity(); renderArtists();
}

// The star: the artist stands among the favorites (first in the list when it is ordered so).
function setFavorite(a, on) {
  a.favorite = on ? 1 : 0;
  renderBrowseList();
  api("POST", "/api/artists/" + a.id + "/favorite", { on: on }).then(function () {
    toast(on ? a.name + " is a favorite now" : a.name + " is no favorite any more");
  }).catch(function (err) { fail(err); a.favorite = on ? 0 : 1; renderBrowseList(); });
}

// The card's switch: a sync of it also downloads what it finds.
function setAuto(a, on) {
  a.auto_download = on ? 1 : 0;
  renderBrowseList(); renderBrowseHead();
  api("POST", "/api/artists/" + a.id + "/auto-download", { on: on }).then(function () {
    toast("Auto-download " + (on ? "on" : "off") + " for " + a.name);
  }).catch(function (err) { fail(err); a.auto_download = on ? 0 : 1; renderBrowseList(); renderBrowseHead(); });
}

// ---- activity bar and log ---------------------------------------------------

var KIND_ICON = { start: "play", done: "check", warn: "alert", error: "error", cancelled: "ban", info: "info" };

function problems() {
  return (S.sync.log || []).filter(function (e) {
    return (e.kind === "warn" || e.kind === "error") && e.time > S.logSeen;
  }).length;
}

var activityHtml = "";
function renderActivity() {
  var s = S.sync || {}, cur = s.current, q = s.queue || [], html;
  // What changes at every poll of a running download -- the text, the bar, the speed, the file -- is written into the bar in place
  // (data-dyn): rebuilding the markup for it swallowed a click that began before the poll (the Cancel button).
  var dyn = {};
  if (cur) {
    var a = artistById(cur.artist_id) || { name: cur.name };
    var scan = cur.phase === "scan", pct = cur.total ? 100 * cur.done / cur.total : 0;
    dyn = { text: cur.mode === "refresh" || cur.mode === "scan" ? "Looking for new posts · " + cur.found + " found"
                  : scan ? "Checking sources · " + cur.found + " new"
                  : "Downloading " + cur.done + " / " + cur.total,
            bar: pct, speed: cur.speed ? bytes(cur.speed) + "/s" : "", file: cur.file || "" };
    html = '<div class="state">' + avatarHtml(a, "xs") + "<b>" + esc(cur.name) + "</b>" +
      '<span class="num" data-dyn="text"></span>' +
      '<div class="bar' + (scan ? " indeterminate" : "") + '"><div data-dyn="bar" style="width:0%"></div></div>' +
      (!scan && cur.speed ? '<span class="num" data-dyn="speed"></span>' : "") +
      (cur.file ? '<span class="file" data-dyn="file"></span>' : "") + "</div>";
    if (q.length) {
      html += '<span class="queue" title="Waiting: ' + esc(q.slice(0, 20).map(function (id) {
        return (artistById(id) || {}).name; }).join(", ") + (q.length > 20 ? ", … (" + q.length + " in all)" : "")) + '">' +
        q.slice(0, 4).map(function (id) { return avatarHtml(artistById(id) || { name: "?" }, "xs"); }).join("") +
        (q.length > 4 ? '<span class="more">+' + (q.length - 4) + "</span>" : "") + "</span>";
    }
    var others = (s.active || []).length - 1;                  // cards that run at once, on other sites
    if (others > 0) html += '<span class="num" title="' + esc((s.active || []).slice(1).map(function (c) { return c.name; }).join(", ")) + '">+' + others + " more</span>";
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
  // Only when the markup changed: it is drawn at every poll (0.7 s) and a click whose press and release straddle a rebuild is lost.
  if (html !== activityHtml) { activityHtml = html; $("activity").innerHTML = html; }
  ["text", "speed", "file"].forEach(function (k) {
    var el = $("activity").querySelector('[data-dyn="' + k + '"]');
    if (el && el.textContent !== dyn[k]) { el.textContent = dyn[k]; if (k === "file") el.title = dyn[k]; }
  });
  var barEl = $("activity").querySelector('[data-dyn="bar"]');
  if (barEl) barEl.style.width = (dyn.bar || 0) + "%";
  $("btn-sync-all").disabled = !S.artists.length;
  if (open) renderLog();
}

function renderLog() {
  var list = (S.sync.log || []).slice().reverse();
  if (S.logFilter === "problems") list = list.filter(function (e) { return e.kind === "warn" || e.kind === "error"; });
  if (list.length) S.logSeen = (S.sync.log || []).slice(-1)[0].time;
  S.logList = list;
  $("log").innerHTML = list.length ? list.map(function (e) {
    var chips = (e.new ? '<span class="badge accent">+' + e.new + " new</span>" : "") +
      (e.duplicates ? '<span class="badge plain">' + plural(e.duplicates, "duplicate") + "</span>" : "") +
      (e.existing ? '<span class="badge plain">' + e.existing + " already there</span>" : "") +
      (e.failed ? '<span class="badge warning">' + e.failed + " failed</span>" : "");
    // A file that failed says which: a click jumps to its picture in the artist's gallery, the arrow to its post.
    var jump = e.key && e.artist_id && artistById(e.artist_id);
    return '<li class="k-' + e.kind + (jump ? " jump" : "") + '" data-n="' + S.logList.indexOf(e) + '"><span class="time">' + clock(e.time) + "</span>" +
      icon(KIND_ICON[e.kind] || "info") +
      (e.artist ? '<span class="who">' + esc(e.artist) + "</span>" : "") +
      '<span class="text" title="' + esc(jump ? "Show this picture in " + e.artist + "'s gallery\n" + e.text : e.text) + '"' + (jump ? ' data-log="show"' : "") + ">" + esc(e.text) + "</span>" + chips +
      (e.post ? '<button type="button" class="mini flat logpost" data-log="post" title="Open the post on the site">' + icon("external") + "</button>" : "") + "</li>";
  }).join("") : '<li class="logempty">' + (S.logFilter === "problems" ? "No problems." : "Nothing happened yet.") + "</li>";
}

$("log").addEventListener("click", function (e) {
  var b = e.target.closest("[data-log]"), li = b && b.closest("li[data-n]");
  var entry = li && (S.logList || [])[+li.dataset.n];
  if (!entry) return;
  if (b.dataset.log === "post") return api("POST", "/api/open-url", { url: entry.post }).catch(fail);
  // The picture in the gallery of its artist: the gallery is opened (or shown again), asked for more pages until the
  // picture is among them -- the newest come first -- and scrolled to; it flashes. Not found: its post is the way.
  var a = artistById(entry.artist_id);
  if (!a) return;
  toggleLog();
  browseOpen(a.id);
  var g = G, tries = 0;
  (function seek() {
    if (g !== G) return;
    var i = g.items.findIndex(function (it) { return it.key === entry.key; });
    if (i >= 0) return galReveal(i);
    if (g.done || ++tries > 120) {
      toast("That picture is not in the gallery" + (entry.post ? " – its post is opened." : "."));
      if (entry.post) api("POST", "/api/open-url", { url: entry.post }).catch(fail);
      return;
    }
    moreGallery();
    setTimeout(seek, 300);
  })();
});

function galReveal(i) {
  var tile = document.querySelector('#gal-grid .gal-tile[data-i="' + i + '"]');
  if (!tile) return;
  if (tile.classList.contains("hidden")) { toast("That picture's site is switched off in the gallery."); return; }
  tile.scrollIntoView({ block: "center", behavior: "smooth" });
  tile.classList.add("flash");
  setTimeout(function () { tile.classList.remove("flash"); }, 3000);
}

function toggleLog() {
  $("logpanel").classList.toggle("hidden");
  renderActivity();
}

// ---- loading and polling ---------------------------------------------------

var lastLoad = 0, loadTimer = 0, LOAD_GAP = 4000;
function load() {
  lastLoad = Date.now();
  return api("GET", "/api/state").then(function (d) {
    S.artists = d.artists; S.apart = apartSet(d.apart); S.sync = d.sync; S.library = d.library; S.window = d.window;
    S.frame = d.frame; applyFrame();
    S.sep = d.sep; S.sites = d.sites; S.fields = d.fields; S.settings = d.settings; S.logins = d.logins || []; S.pauses = d.pauses || [];
    $("version").textContent = "v" + d.version;
    $("btn-quit").classList.toggle("hidden", S.window);
    applySettings();
    Object.keys(GS).forEach(function (k) { if (+k && !artistById(+k)) galDrop(k); });      // a deleted card's gallery
    if (S.brArtist && !artistById(S.brArtist)) {          // deleted: All artists instead
      S.brArtist = 0;
      if (G && !G.all) browseClose();
    }
    if (G && G.artist) { G.artist = artistById(G.artist.id) || G.artist; $("gal-title").textContent = G.artist.name; }
    renderAll();
    if (!G && S.view === "gallery") browseOpen(S.brArtist);      // (the other views open it when they are asked to)
    showUpdate();
    showAccounts();
  });
}

// A running sync changes the key at nearly every poll (a card done, a line in the log), and every reload is the whole
// state -- a thousand cards, 1.5 MB, redrawn: the window stopped answering. While a sync runs the cards are
// reloaded every LOAD_GAP at most; the activity bar, which the poll itself feeds, follows at once.
function loadSoon() {
  var wait = S.sync.running ? LOAD_GAP - (Date.now() - lastLoad) : 0;
  if (wait <= 0) return load();
  renderActivity();
  if (!loadTimer) loadTimer = setTimeout(function () { loadTimer = 0; load(); }, wait);
  return Promise.resolve();
}

// A poll is a delay: quick while a sync runs, slow when nothing does. The
// artists are reloaded whenever the artist being synced changes, so counts
// and badges follow without reloading on every tick.
var lastKey = "";
function poll() {
  api("GET", "/api/sync").then(function (s) {
    var key = (s.active || []).map(function (c) { return c.artist_id; }).join("+") + "|" + s.running + "|" + (s.queue || []).join(",") +
      "|" + (s.log || []).length + "|" + s.follows + "|" + (s.pauses || []).map(function (p) { return p.site; }).join(",");
    // A sync that ended may have saved files: the open gallery asks the library again (the green buttons appear), and one kept
    // aside does it when it comes back (galResume) -- nothing is thrown away, so a switch still finds the artist where it was.
    var syncEnded = S.sync.finished !== s.finished;
    S.sync = s;
    if (syncEnded) galSavedRefresh();
    if (s.pauses) S.pauses = s.pauses;
    if (key !== lastKey) { lastKey = key; return loadSoon(); }
    renderBrowseList(); renderBrowseHead(); renderActivity();
  }).catch(function () {}).then(function () {
    setTimeout(poll, S.sync.running ? 700 : 3000);
  });
}

// Sync looks for new posts (a card with auto-download downloads them too); download
// fetches what is not in the library yet. One card, or every card without an id.
function sync(artistId, download) {
  // Refresh all (no artist): every artist, down the list as it is shown now.
  var body = artistId ? { artist_id: artistId } : { order: S.brOrderIds || [] };
  if (download) body.mode = "download";
  api("POST", "/api/sync", body).then(function () {
    lastKey = ""; return api("GET", "/api/sync");
  }).then(function (s) { S.sync = s; if (s.pauses) S.pauses = s.pauses; renderAll(); }).catch(fail);
}

function removeArtist(a) {
  api("DELETE", "/api/artists/" + a.id).then(function () {
    galDrop(a.id);
    galDrop(0);                                    // All artists listed this card
    if (G && G.all) G.stale = true;
    return load();
  }).catch(fail);
}

// ---- merge: cards become one ----------------------------------------------------------

// Accounts the sites did not show to be one artist (the follows come in as one card each): the open card and the ones
// ticked here become one. The card marked "Stays" gets every source and file, the others are gone. There is no further
// question -- the button at the bottom is the confirmation, so several cards go in one go.
var M = { from: 0, picked: [], keep: 0, me: null, suggested: [], why: {} };

// Two names are one when only what is no letter or digit differs: emoji, spaces, marks, width, case
// ("👹 青林檎テル" is "青林檎テル"). The base leaves out a "(handle)" at the end, which a card gets when another had its name.
function nameKey(name) { return String(name || "").normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ""); }
function baseKey(name) { return nameKey(String(name || "").replace(/\s*[(\[（【][^)\]）】]*[)\]）】]\s*$/, "")); }
// Every name a card is known by, as keys: its own, which is the artist's @name, and what the sites show for its accounts (`alias`).
// The list's search finds a card by any of them. `shown` (when given) keeps the text each key came from: the dialogs say why
// two cards look alike in the artist's own words ("both go by «小也暁也»"), not in keys.
function nameHit(a, q) {
  return a.name.toLowerCase().indexOf(q) >= 0 || a.sources.some(function (s) { return s.alias && String(s.alias).toLowerCase().indexOf(q) >= 0; });
}
function namesOf(a, shown) {
  var out = [];
  [a.name].concat(a.sources.map(function (s) { return s.alias; })).forEach(function (n) {
    [nameKey(n), baseKey(n)].forEach(function (k) {
      if (k.length >= 2 && out.indexOf(k) < 0) { out.push(k); if (shown && n) shown[k] = String(n).trim(); }
    });
  });
  return out;
}
function shortUrl(u) { var t = String(u).replace(/^https?:\/\/(www\.)?/i, "").replace(/\/+$/, ""); return t.length > 44 ? t.slice(0, 43) + "…" : t; }
// The account names in a card's links: "foo" in bsky.app/profile/foo.bsky.social, x.com/foo, mastodon.social/@foo and
// foo.fanbox.cc -- what a display name is not (an artist known as "Mew" is @Mewnet). Numbers (pixiv's ids) and short ones
// say nothing. (`follows.handle_key` does the same for the automatic combining, with a longer minimum.) `at` (when given)
// keeps the address each came from.
var HANDLE_KINDS = ["bluesky", "mastodon", "misskey", "x", "patreon", "fanbox", "xenforo"];
var NOT_NAMES = ["index", "user", "users", "profile", "profiles", "members", "member", "u", "c", "media", "m", "creator"];     // follows._NOT_NAMES
function handlesOf(a, at) {
  var out = [];
  a.sources.forEach(function (s) {
    if (HANDLE_KINDS.indexOf(s.kind) < 0) return;
    var last = "";
    try {
      var u = new URL(s.url);
      // A forum that routes through "index.php?" has the member in the query (index.php?media/users/name.12), not the path.
      var where = s.kind === "xenforo" && u.search.indexOf("/") >= 0 ? u.search.slice(1) : u.pathname;
      last = /\.fanbox\.cc$/i.test(u.hostname) ? u.hostname.split(".")[0] : decodeURIComponent(where.replace(/\/+$/, "").split("/").pop());
    } catch (e) { return; }
    var h = nameKey(last.replace(/^@/, "").split("@")[0].split(".")[0]);
    if (h.length >= 3 && !/^\d+$/.test(h) && NOT_NAMES.indexOf(h) < 0 && out.indexOf(h) < 0) { out.push(h); if (at) at[h] = shortUrl(s.url); }
  });
  return out;
}
// The same without the digits at the end: @Blackmoon, @blackmoon_77 and @BlackMoon1985 are one artist's accounts (the number is
// whatever was free on each site). (`follows.stem_key`.)
function stemOf(h) { return h.replace(/\d+$/, ""); }
function stemsOf(handles) {
  var out = [];
  handles.forEach(function (h) { var t = stemOf(h); if (t !== h && t.length >= 5 && out.indexOf(t) < 0) out.push(t); });
  return out;
}
// The accounts a card's profiles name themselves (pixiv's declared twitter, a Mastodon field, Fanbox's links), lower-cased.
function linksOf(a) {
  var out = [];
  a.sources.forEach(function (s) {
    try { (JSON.parse(s.links || "[]") || []).forEach(function (u) { out.push(String(u).toLowerCase()); }); } catch (e) {}
  });
  return out;
}
// The accounts a card's bios name (sources.bio_links), lower-cased: only a hint -- a bio names friends as often as the artist.
function mentionsOf(a) {
  var out = [];
  a.sources.forEach(function (s) {
    try { (JSON.parse(s.mentions || "[]") || []).forEach(function (u) { out.push(String(u).toLowerCase()); }); } catch (e) {}
  });
  return out;
}
function urlsOf(a) { return a.sources.map(function (s) { return String(s.url).toLowerCase(); }); }
// Everything the evidence below needs of one card, made once.
function profileOf(a) {
  var shown = {}, at = {}, names = namesOf(a, shown), handles = handlesOf(a, at);
  return { a: a, key: nameKey(a.name), names: names, shown: shown, handles: handles, at: at, stems: stemsOf(handles),
           links: linksOf(a), mentions: mentionsOf(a), urls: urlsOf(a) };
}

// ---- why two cards look like one artist ---------------------------------------------------
// evidence(p, q) = {s, why}: how likely (6 a profile names the other's account, 5.5 the bios name each other, 5 a name in common --
// the name a site shows counts --, 4.5 one bio names the other, 4 the same account name, 3 the same but for the digits at its end or
// names a letter or two apart, 2 a name that is the other's account name or sits inside the other's name, 1 a similar card name; 0
// nothing) and `why`, the reason in words with the names and addresses that caused it -- both dialogs show it under each card.
var CJK = /[぀-ヿ㐀-鿿가-힯]/;
function common(xs, ys) { for (var i = 0; i < xs.length; i++) if (ys.indexOf(xs[i]) >= 0) return xs[i]; return ""; }
function quote(s) { return "«" + s + "»"; }
function stemMatch(p, q) {
  for (var i = 0; i < p.handles.length; i++) for (var j = 0; j < q.handles.length; j++) {
    var x = p.handles[i], y = q.handles[j], sx = stemOf(x), sy = stemOf(y);
    if (x !== y && (sx === sy || sx === y || x === sy) && Math.min(sx.length, sy.length) >= 5) return [x, y];
  }
  return null;
}
// A name that is another's with a letter or two more ("tinyshoya", "tinyshoyac": close = true), or one that sits inside another's
// ("小也暁也" in "小也暁也 | commissions": close = false). The names of the cards' accounts count, not only the cards' own.
function nameInside(p, q, close) {
  for (var i = 0; i < p.names.length; i++) for (var j = 0; j < q.names.length; j++) {
    var x = p.names[i], y = q.names[j], lo = x.length <= y.length ? x : y, hi = lo === x ? y : x, extra = hi.length - lo.length;
    if (!extra || hi.indexOf(lo) < 0) continue;
    var cjk = CJK.test(lo);
    if (close ? !(extra <= 2 && lo.length >= 6) : !(lo.length >= (cjk ? 3 : 5) && lo.length * (cjk ? 3 : 2) >= hi.length)) continue;
    var small = lo === x ? p : q, big = small === p ? q : p;
    return close ? "the names are a letter or two apart: " + quote(small.shown[lo] || lo) + " and " + quote(big.shown[hi] || hi)
      : quote(small.shown[lo] || lo) + " is part of " + quote(big.shown[hi] || hi);
  }
  return "";
}
function evidence(p, q) {
  var A = quote(p.a.name), B = quote(q.a.name), u, k, st, w;
  if ((u = common(p.links, q.urls))) return { s: 6, why: A + "'s own profile links to " + B + "'s account (" + shortUrl(u) + ")" };
  if ((u = common(q.links, p.urls))) return { s: 6, why: B + "'s own profile links to " + A + "'s account (" + shortUrl(u) + ")" };
  var pm = common(p.mentions, q.urls), qm = common(q.mentions, p.urls);
  if (pm && qm) return { s: 5.5, why: "their bios name each other's accounts" };
  if ((k = common(p.names, q.names))) return { s: 5, why: "both go by " + quote(p.shown[k] || q.shown[k] || k) };
  if (pm || qm) return { s: 4.5, why: "the bio of " + (pm ? A : B) + " names the other's account (" + shortUrl(pm || qm) + ")" };
  if ((k = common(p.handles, q.handles))) return { s: 4, why: "the same account name " + quote(k) + " (" + p.at[k] + " and " + q.at[k] + ")" };
  if ((st = stemMatch(p, q))) return { s: 3, why: "the account names differ only by numbers: " + quote(st[0]) + " and " + quote(st[1]) };
  if ((w = nameInside(p, q, true))) return { s: 3, why: w };
  if ((k = common(p.names, q.handles))) return { s: 2, why: quote(p.shown[k] || k) + " is the account name of " + B + " (" + q.at[k] + ")" };
  if ((k = common(q.names, p.handles))) return { s: 2, why: quote(q.shown[k] || k) + " is the account name of " + A + " (" + p.at[k] + ")" };
  if ((w = nameInside(p, q, false))) return { s: 2, why: w };
  var lo = p.key.length < q.key.length ? p.key : q.key, hi = lo === p.key ? q.key : p.key;
  return lo.length >= 3 && lo.length * 2 >= hi.length && hi.indexOf(lo) >= 0 ? { s: 1, why: "similar names" } : { s: 0, why: "" };
}

// "These two are not the same artist" (/api/apart): kept in the database, never offered again. S.apart is a Set of "low,high" ids.
function apartSet(list) { return new Set((list || []).map(function (p) { return p[0] + "," + p[1]; })); }
function isApart(x, y) { return !!S.apart && S.apart.has(Math.min(x, y) + "," + Math.max(x, y)); }
function markApart(pairs) {
  return api("POST", "/api/apart", { pairs: pairs, apart: true }).then(function (d) { S.apart = apartSet(d.apart); });
}
function forgetApart() {
  return api("POST", "/api/apart", { clear: true }).then(function (d) { S.apart = apartSet(d.apart); });
}
function apartNote(id) {
  var n = S.apart ? S.apart.size : 0;
  $(id).innerHTML = n ? plural(n, "pair") + " marked as not the same artist. <button type=\"button\" class=\"mini\" data-apart-clear>Offer them again</button>" : "";
}
// The sites a card has accounts on, as their marks (a site without one shows its name).
function siteMarks(a) {
  var seen = {}, out = "";
  a.sources.forEach(function (s) {
    var k = s.site || s.label;
    if (!k || seen[k]) return;
    seen[k] = 1;
    out += siteLogo(k, s.kind, s.host) || '<span class="mk-name">' + esc(k) + "</span>";
  });
  return out;
}
// One card in a merge list: tick, picture, name with the sites it is on, the reason under it, and the buttons at the right.
function mergeRow(a, on, why, acts, plain) {
  return '<div class="merge-row' + (on ? " on" : "") + '">' +
    (plain ? '<div class="br-item">' : '<button type="button" class="br-item" data-id="' + a.id + '" aria-pressed="' + on + '">' +
      '<span class="tick">' + (on ? icon("tick") : "") + "</span>") + avatarHtml(a) +
    '<span class="merge-text"><span class="merge-top"><span class="br-name" title="' + esc(a.name) + '">' + esc(a.name) + "</span>" +
    '<span class="merge-sites">' + siteMarks(a) + "</span></span>" + (why ? '<small class="why">' + esc(why) + "</small>" : "") + "</span>" +
    '<span class="br-n">' + (a.sources.filter(function (s) { return s.supported; }).length || "") + (plain ? "</span></div>" : "</span></button>") +
    (acts ? '<span class="merge-acts">' + acts + "</span>" : "") + "</div>";
}

function suggest() {
  var scored = S.artists.filter(function (b) { return b.id !== M.from && !isApart(M.from, b.id); })
    .map(function (b) { return [evidence(M.me, profileOf(b)), b]; }).filter(function (x) { return x[0].s; })
    .sort(function (x, y) { return y[0].s - x[0].s || x[1].name.localeCompare(y[1].name); }).slice(0, 10);
  M.suggested = scored.map(function (x) { return x[1].id; });
  M.why = {};
  scored.forEach(function (x) { M.why[x[1].id] = x[0].why; });
}
function openMerge(a) {
  closeMenu();
  M = { from: a.id, picked: [], keep: 0, me: profileOf(a), suggested: [], why: {} };
  suggest();
  $("merge-title").textContent = "Merge " + a.name + " with…";
  $("merge-hint").textContent = "Tick the cards that are the same artist. They become one card: the one marked Stays keeps " +
    "every source and downloaded file, the others go away. Under a suggestion Sourcerer says why it thinks they belong together.";
  $("merge-search").value = "";
  renderMerge();
  $("dlg-merge").showModal();
  $("merge-search").focus();
}
// The card that stays: the one asked for, else the first ticked (so a single tick merges the open card into it).
function mergeKeeper() { return [M.from].concat(M.picked).indexOf(M.keep) >= 0 ? M.keep : (M.picked[0] || 0); }
function renderMerge() {
  var q = $("merge-search").value.trim().toLowerCase(), box = $("merge-list"), top = box.scrollTop;
  var keeper = mergeKeeper(), group = M.picked.length > 0;
  function row(a, fixed) {
    var on = fixed || M.picked.indexOf(a.id) >= 0, why = !fixed && M.why[a.id] || "";
    return mergeRow(a, on, why,
      (why ? '<button type="button" class="keep" data-apart="' + a.id + '" title="Do not offer these two again">Not the same</button>' : "") +
      (on && group ? (keeper === a.id ? '<span class="keeps">Stays</span>' : '<button type="button" class="keep" data-keep="' + a.id + '">Keep this one</button>') : ""));
  }
  var me = artistById(M.from), others = S.artists.filter(function (a) { return a.id !== M.from && (!q || nameHit(a, q)); });
  var sug = M.suggested.map(artistById).filter(function (a) { return a && others.indexOf(a) >= 0; });
  var rest = others.filter(function (a) { return sug.indexOf(a) < 0; }).sort(function (x, y) { return x.name.localeCompare(y.name); });
  box.innerHTML = (me ? row(me, true) : "") +
    (sug.length ? '<div class="br-group">Possibly the same artist</div>' + sug.map(function (a) { return row(a); }).join("") : "") +
    (rest.length ? (sug.length ? '<div class="br-group">All artists</div>' : "") + rest.map(function (a) { return row(a); }).join("") : "") +
    (others.length ? "" : '<p class="hint">No other artist.</p>');
  box.scrollTop = top;
  apartNote("merge-apart");
  var n = M.picked.length, stay = artistById(keeper), gone = [M.from].concat(M.picked).filter(function (id) { return id !== keeper; }).map(function (id) { return (artistById(id) || {}).name; });
  $("merge-go").disabled = !n;
  $("merge-go").textContent = n ? "Merge " + plural(n + 1, "card") : "Merge";
  $("merge-sum").textContent = n ? "Stays: " + stay.name + " · goes away: " + (gone.length > 3 ? gone.slice(0, 3).join(", ") + " +" + (gone.length - 3) : gone.join(", "))
    : "Nothing ticked yet.";
}
$("merge-search").addEventListener("input", renderMerge);
$("merge-list").addEventListener("click", function (e) {
  var k = e.target.closest("[data-keep]"), b = e.target.closest("[data-id]"), n = e.target.closest("[data-apart]");
  if (n) {                                          // not the same artist: kept for good, and gone from the suggestions
    var no = +n.dataset.apart;
    markApart([[M.from, no]]).then(function () {
      M.suggested = M.suggested.filter(function (id) { return id !== no; });
      M.picked = M.picked.filter(function (id) { return id !== no; });
      delete M.why[no];
      renderMerge();
    }).catch(fail);
    return;
  }
  if (k) M.keep = +k.dataset.keep;
  else if (b && +b.dataset.id !== M.from) {
    var id = +b.dataset.id, i = M.picked.indexOf(id);
    if (i < 0) M.picked.push(id); else M.picked.splice(i, 1);
    if (M.keep === id) M.keep = 0;
  } else return;
  renderMerge();
});
$("merge-apart").addEventListener("click", function (e) {
  if (!e.target.closest("[data-apart-clear]")) return;
  forgetApart().then(function () { suggest(); renderMerge(); }).catch(fail);
});
$("merge-go").addEventListener("click", function () {
  var keep = mergeKeeper(), into = artistById(keep), ids = [M.from].concat(M.picked).filter(function (id) { return id !== keep; }), done = [];
  if (!into || !ids.length) return;
  $("merge-go").disabled = true;
  ids.reduce(function (p, id) {                    // one after the other: a card that is syncing says so, and the ones before it stay merged
    return p.then(function () { return api("POST", "/api/artists/" + id + "/merge", { into: keep }).then(function () { done.push(id); }); });
  }, Promise.resolve()).catch(fail).then(function () {
    done.concat(keep, 0).forEach(galDrop);
    if (G && !G.all && (done.indexOf(G.key) >= 0 || G.key === keep)) browseClose();
    if (G && G.all) G.stale = true;
    if (done.indexOf(S.brArtist) >= 0) S.brArtist = keep;
    lastKey = "";
    return load();
  }).then(function () {
    $("dlg-merge").close();
    if (done.length) toast(plural(done.length, "card") + " merged into " + into.name + ".");
  });
});

// ---- merge sources: every likely twin at once --------------------------------------------
// The same evidence as above, over all cards: groups of cards that look like one artist, each with the card that stays, the ones that
// go into it and the reason for each. **Every card is merged on its own button, one pair at a time** (the user's rule, 2026-10-23: "so no
// mistake can happen") -- no ticks, no button that merges many, nothing happens by itself. Two cards with an account on the same
// site (two pixiv accounts are more likely two people, whatever their names say) are offered too, with that said, because a main and
// a second account of one artist look exactly so. *Open* shows an artist in Sourcerer to compare with your own eyes (the dialog waits
// behind a button), *Not the same* is kept for good.
var ONE_PER_SITE = ["bluesky", "x", "pixiv", "patreon", "fanbox", "fantia"];
var KIND_NAMES = { bluesky: "Bluesky", x: "X", pixiv: "pixiv", patreon: "Patreon", fanbox: "Fanbox", fantia: "Fantia" };
var MAX_SHARERS = 8;
var C = { groups: [], parked: false };
function oneKinds(a) { return a.sources.map(function (s) { return s.kind; }).filter(function (k) { return ONE_PER_SITE.indexOf(k) >= 0; }); }
// Who stays: a card the user made over one that came with a list, then the one with most downloads, auto-download, most accounts.
function stayRank(a) { return [a.listed ? 0 : 1, a.file_count || 0, a.auto_download ? 1 : 0, a.sources.length]; }
function stayOrder(x, y) {
  var rx = stayRank(x), ry = stayRank(y);
  for (var i = 0; i < rx.length; i++) if (rx[i] !== ry[i]) return ry[i] - rx[i];
  return x.name.localeCompare(y.name);
}
// Names that sit inside another card's name ("tinyshoya" in "tinyshoyac", "小也暁也" in "小也暁也 | commissions"): all names in one
// string, each searched in it -- native indexOf, no walk over every pair of cards. A name many cards contain says nothing.
function insidePairs(ps, pair) {
  var big = "", starts = [], owner = [];
  ps.forEach(function (p, i) { p.names.forEach(function (k) { starts.push(big.length); owner.push(i); big += k + "\n"; }); });
  function whose(at) {
    var lo = 0, hi = starts.length - 1;
    while (lo < hi) { var mid = (lo + hi + 1) >> 1; if (starts[mid] <= at) lo = mid; else hi = mid - 1; }
    return owner[lo];
  }
  ps.forEach(function (p, i) {
    p.names.forEach(function (lo) {
      if (lo.length < (CJK.test(lo) ? 3 : 5)) return;
      var hits = [], at = big.indexOf(lo), steps = 0;
      while (at >= 0 && hits.length <= MAX_SHARERS && steps++ < 400) {
        var o = whose(at);
        if (o !== i && hits.indexOf(o) < 0) hits.push(o);
        at = big.indexOf(lo, at + 1);
      }
      if (hits.length <= MAX_SHARERS) hits.forEach(function (o) { pair(i, o); });
    });
  });
}
function findTwins() {
  var ps = S.artists.map(profileOf), at = Object.create(null), owner = Object.create(null), pairs = Object.create(null);
  ps.forEach(function (p, i) {
    p.kinds = oneKinds(p.a);
    p.urls.forEach(function (u) { owner[u] = i; });
    p.names.concat(p.handles, p.stems).forEach(function (k) { var l = at[k] || (at[k] = []); if (l.indexOf(i) < 0) l.push(i); });
  });
  function pair(i, j) { if (i !== j) pairs[Math.min(i, j) + "," + Math.max(i, j)] = 1; }
  Object.keys(at).forEach(function (k) {
    var ids = at[k];
    if (ids.length < 2 || ids.length > MAX_SHARERS) return;              // a name many cards have says nothing
    for (var x = 0; x < ids.length; x++) for (var y = x + 1; y < ids.length; y++) pair(ids[x], ids[y]);
  });
  insidePairs(ps, pair);
  ps.forEach(function (p, i) { p.links.concat(p.mentions).forEach(function (u) { if (u in owner) pair(i, owner[u]); }); });
  var edges = [], parent = ps.map(function (_, i) { return i; });
  function root(i) { while (parent[i] !== i) { parent[i] = parent[parent[i]]; i = parent[i]; } return i; }
  Object.keys(pairs).forEach(function (k) {
    var ij = k.split(","), i = +ij[0], j = +ij[1];
    if (isApart(ps[i].a.id, ps[j].a.id)) return;
    var e = evidence(ps[i], ps[j]);
    if (e.s < 2) return;
    edges.push({ i: i, j: j, s: e.s, why: e.why, warn: ps[i].kinds.filter(function (x) { return ps[j].kinds.indexOf(x) >= 0; })[0] || "" });
    parent[root(i)] = root(j);
  });
  var by = Object.create(null);
  edges.forEach(function (e) { (by[root(e.i)] = by[root(e.i)] || []).push(e); });
  return Object.keys(by).map(function (r) {
    var es = by[r], ids = [];
    es.forEach(function (e) { [e.i, e.j].forEach(function (i) { if (ids.indexOf(i) < 0) ids.push(i); }); });
    var cards = ids.map(function (i) { return ps[i].a; }).sort(stayOrder), keep = cards[0];
    var members = cards.slice(1).map(function (a) {
      var mine = es.filter(function (e) { return ps[e.i].a === a || ps[e.j].a === a; })
        .sort(function (x, y) { return (x.warn ? 1 : 0) - (y.warn ? 1 : 0) || y.s - x.s; })[0];
      var other = ps[ps[mine.i].a === a ? mine.j : mine.i].a;
      return { id: a.id, s: mine.s, warn: mine.warn,
        why: mine.why + (other === keep ? "" : " (to " + quote(other.name) + ")") +
          (mine.warn ? ". Both have a " + KIND_NAMES[mine.warn] + " account, which is usually two people" : "") };
    }).sort(function (x, y) { return y.s - x.s; });
    return { keep: keep.id, members: members, best: members.reduce(function (m, x) { return Math.max(m, x.warn ? 1 : x.s); }, 0) };
  }).sort(function (x, y) { return y.best - x.best || artistById(x.keep).name.localeCompare(artistById(y.keep).name); });
}
function openTwins() {
  if (C.parked) return resumeTwins();
  C = { groups: findTwins(), parked: false };
  renderTwins();
  $("dlg-twins").showModal();
}
// Back from comparing an artist: what was merged or deleted meanwhile is gone from the groups, the keepers stay.
function resumeTwins() {
  C.parked = false;
  C.groups = C.groups.filter(function (g) {
    g.members = g.members.filter(function (m) { return artistById(m.id); });
    return artistById(g.keep) && g.members.length;
  });
  renderTwins();
  $("dlg-twins").showModal();
}
function twinsOpen(id) {
  if (!artistById(id)) return;
  C.parked = true;
  $("dlg-twins").close();                            // (its close event shows the way back)
  avOpen(id);
}
function renderTwins() {
  var box = $("twins-list"), top = box.scrollTop, cards = 0;
  var open = function (a) { return '<button type="button" class="keep" data-open="' + a.id + '" title="Look at this artist in Sourcerer, then come back here">Open</button>'; };
  box.innerHTML = C.groups.map(function (g, gi) {
    var stay = artistById(g.keep);
    cards += g.members.length;
    return '<div class="twin" data-g="' + gi + '">' + mergeRow(stay, true, "", open(stay) + '<span class="keeps">Stays</span>', true) +
      g.members.map(function (m) {
        var a = artistById(m.id);
        return mergeRow(a, false, m.why, open(a) + '<button type="button" class="keep" data-keep="' + a.id + '" title="This card stays, the other one goes into it">Keep this one</button>' +
          '<button type="button" class="keep no" data-apart="' + a.id + '" title="Do not offer this card with these again">Not the same</button>' +
          '<button type="button" class="keep primary" data-merge="' + a.id + '" title="' + esc(a.name + " goes into " + stay.name + " and is gone; " + stay.name + " stays") + '">Merge into ' + esc(stay.name) + "</button>", true);
      }).join("") + "</div>";
  }).join("") || '<p class="hint">No cards that look like one artist.</p>';
  box.scrollTop = top;
  apartNote("twins-apart");
  $("twins-sum").textContent = C.groups.length ? plural(C.groups.length, "group") + " · " + plural(cards, "card") + " to look at" : "";
}
// One card into the one that stays -- a single /merge call, then the list goes on without it. (A card that syncs says so and stays.)
function twinsMerge(g, id) {
  var keep = artistById(g.keep), gone = artistById(id);
  if (!keep || !gone || C.busy) return;
  C.busy = true;
  api("POST", "/api/artists/" + id + "/merge", { into: g.keep }).then(function () {
    [id, g.keep, 0].forEach(galDrop);
    if (G && !G.all && G.key === id) browseClose();
    if (G && G.all) G.stale = true;
    if (S.brArtist === id) S.brArtist = g.keep;
    g.members = g.members.filter(function (m) { return m.id !== id; });
    if (!g.members.length) C.groups.splice(C.groups.indexOf(g), 1);
    lastKey = "";
    return load().then(function () { toast(gone.name + " is part of " + keep.name + " now."); });
  }).catch(fail).then(function () { C.busy = false; renderTwins(); });
}
$("twins-list").addEventListener("click", function (e) {
  var g = e.target.closest("[data-g]"), k = e.target.closest("[data-keep]"), mg = e.target.closest("[data-merge]"),
      o = e.target.closest("[data-open]"), no = e.target.closest("[data-apart]");
  if (!g) return;
  g = C.groups[+g.dataset.g];
  if (o) { twinsOpen(+o.dataset.open); return; }
  if (mg) { twinsMerge(g, +mg.dataset.merge); return; }
  if (no) {                                          // this card is not one of these: kept for good, and out of the group
    var id = +no.dataset.apart, was = artistById(id), others = [g.keep].concat(g.members.map(function (x) { return x.id; })).filter(function (x) { return x !== id; });
    markApart(others.map(function (x) { return [id, x]; })).then(function () {
      g.members = g.members.filter(function (x) { return x.id !== id; });
      if (!g.members.length) C.groups.splice(C.groups.indexOf(g), 1);
      renderTwins();
      toast((was ? was.name : "The card") + " will not be offered with these again.");
    }).catch(fail);
    return;
  }
  if (k) {                                           // another card stays: the old keeper takes its place among those that go
    var kid = +k.dataset.keep, prev = g.keep, m = g.members.filter(function (x) { return x.id === kid; })[0];
    if (!m) return;
    g.members[g.members.indexOf(m)] = { id: prev, s: m.s, warn: m.warn, why: m.why };
    g.keep = kid;
  } else return;
  renderTwins();
});
$("twins-apart").addEventListener("click", function (e) {
  if (!e.target.closest("[data-apart-clear]")) return;
  forgetApart().then(function () { C.groups = findTwins(); renderTwins(); }).catch(fail);
});
$("dlg-twins").addEventListener("close", function () { $("twins-back").classList.toggle("hidden", !C.parked); });
$("twins-back-go").addEventListener("click", function () { $("twins-back").classList.add("hidden"); resumeTwins(); });
$("twins-back-x").addEventListener("click", function () { C.parked = false; $("twins-back").classList.add("hidden"); });
$("br-combine").addEventListener("click", openTwins);

function openFolder(a) { api("POST", "/api/open", { target: "artist", artist_id: a.id }).catch(fail); }

// ---- the artist's menu, mouse and keyboard ------------------------------------

function closeMenu() { $("menu").classList.add("hidden"); $("picmenu").classList.add("hidden"); S.menuFor = null; }
function openMenu(a, x, y) {
  var m = $("menu");
  S.menuFor = a.id;
  $("menu-auto").textContent = a.auto_download ? "Turn auto-download off" : "Turn auto-download on";
  $("menu-favorite").textContent = a.favorite ? "Remove from favorites" : "Add to favorites";
  m.classList.remove("hidden");
  m.style.top = Math.max(4, Math.min(y, innerHeight - m.offsetHeight - 8)) + "px";
  m.style.left = Math.max(4, Math.min(x, innerWidth - m.offsetWidth - 8)) + "px";
}

// The open artist's actions: from the menu, the header's buttons and the keys.
function artistAct(act, a) {
  if (!a) return;
  if (act === "edit") openCard(a);
  else if (act === "auto") setAuto(a, !a.auto_download);
  else if (act === "favorite") setFavorite(a, !a.favorite);
  else if (act === "sync") sync(a.id);
  else if (act === "download") downloadSelected(a);
  else if (act === "folder") openFolder(a);
  else if (act === "merge") openMerge(a);
  else if (act === "delete") removeArtist(a);
}

document.addEventListener("click", function (e) {
  if (!e.target.closest("#menu, #picmenu")) closeMenu();
  var btn = e.target.closest("[data-act]");
  if (!btn) return;
  switch (btn.dataset.act) {
    case "add": openCard(null); break;
    case "cancel-current":
      api("POST", "/api/sync/cancel", { all: true });          // what runs and what waits
      break;
    case "log": toggleLog(); break;
    case "accounts": e.preventDefault(); openAccounts(); break;
  }
});
$("menu").addEventListener("click", function (e) {
  var btn = e.target.closest("[data-menu]");
  if (!btn) return;
  var a = artistById(S.menuFor);
  closeMenu();
  artistAct(btn.dataset.menu, a);
});
$("empty-add").addEventListener("click", function () { openCard(null); });

// ---- keyboard --------------------------------------------------------------

// Up / Down / Home / End pick the previous or next artist in the list. The gallery opens a moment
// after the last key, so holding a key down does not open a gallery per artist it passes.
var pickTimer = 0;
function pickArtist(key) {
  var items = $$("#br-list .br-item[data-id]"), ids = items.map(function (b) { return +b.dataset.id; });
  if (!ids.length) return;
  var i = items.indexOf($("br-list").querySelector(".br-item.selected"));          // (an artist can stand in several groups: the marked one is where we are)
  if (i < 0) i = ids.indexOf(S.brArtist);
  var next = Math.max(0, Math.min(ids.length - 1, { ArrowUp: i - 1, ArrowDown: i + 1, Home: 0, End: ids.length - 1 }[key]));
  S.brArtist = ids[next]; S.brAt = items[next].dataset.site || "";
  renderBrowseList();
  var el = $("br-list").querySelector(".br-item.selected");
  if (el) el.scrollIntoView({ block: "nearest" });
  clearTimeout(pickTimer);
  pickTimer = setTimeout(function () { browseOpen(S.brArtist); }, 250);
}

// Picture size: the gallery's slider, in steps of its own.
function galSize(px) {
  var r = $("gal-size");
  px = Math.max(+r.min, Math.min(+r.max, Math.round(px / 20) * 20));
  r.value = px;
  $("gal-grid").style.setProperty("--gal", px + "px");
  try { localStorage.setItem(BR_SIZE, String(px)); } catch (e) {}
  galLayout();
}

document.addEventListener("keydown", function (e) {
  var k = e.key, low = k.toLowerCase(), ctrl = e.ctrlKey || e.metaKey;
  var t = e.target, typing = (t.tagName === "INPUT" && !/^(range|checkbox)$/.test(t.type)) ||
    t.tagName === "SELECT" || t.tagName === "TEXTAREA";
  var dialog = document.querySelector("dialog[open]");
  if (k === "Escape") {
    closeMenu();
    if (!dialog && G && G.sel && (G.sel.size || S.brSelect) && $("gal-view").classList.contains("hidden")) {
      S.brSelect = false; G.sel.clear(); selPaint();
    }
    if (!dialog && t === $("br-search")) { t.value = ""; t.blur(); renderBrowseList(); }
    if (!dialog && t === $("av-search")) { t.value = ""; t.blur(); renderArtists(); }
    return;                                   // an open dialog closes itself
  }
  if (!dialog && ctrl && (k === "+" || k === "=")) { e.preventDefault(); return galSize(+$("gal-size").value + 20); }
  if (!dialog && ctrl && k === "-") { e.preventDefault(); return galSize(+$("gal-size").value - 20); }
  if (!dialog && ctrl && k === "0") { e.preventDefault(); return galSize(DEFAULT_GAL); }
  if (dialog) return;
  if (ctrl && low === "a" && !typing && G && S.view === "gallery" && $("gal-view").classList.contains("hidden")) { e.preventDefault(); return selAll(); }
  if ((ctrl && low === "n") || (!ctrl && !e.altKey && !typing && low === "n")) { e.preventDefault(); return openCard(null); }
  if ((ctrl && low === "f") || (k === "/" && !typing)) {
    var box = $(S.view === "artists" ? "av-search" : "br-search");
    e.preventDefault(); box.focus(); return box.select();
  }
  if (k === "F5" || (ctrl && low === "r")) { e.preventDefault(); return sync(null); }
  if (ctrl && k === ",") { e.preventDefault(); return openSettings(); }
  if (ctrl && low === "l") { e.preventDefault(); return toggleLog(); }

  if (typing || ctrl || e.altKey || t.type === "range" || S.view !== "gallery" || !$("gal-view").classList.contains("hidden")) return;   // (a picture open: its own keys; the other views have none of the artist's)
  if (/^(Arrow(Up|Down)|Home|End)$/.test(k)) { e.preventDefault(); return pickArtist(k); }
  var a = artistById(S.brArtist);
  if (!a) return;
  // Enter on a button presses it; in the artist list it edits the card instead.
  if (k === "Enter" && t.tagName === "BUTTON" && !t.closest("#br-list")) return;
  var act = k === "Enter" ? "edit" : k === "Delete" ? "delete" : { a: "auto", f: "favorite", u: "sync", d: "download", o: "folder", m: "merge" }[low];
  if (act) { e.preventDefault(); artistAct(act, a); }
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
}, { root: $("gal-body"), rootMargin: "800px" });

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
var BR_FIT = "sourcerer.browse.fit", BR_SIZE = "sourcerer.browse.size", BR_FOLDED = "sourcerer.browse.folded";
var BR_SORT = "sourcerer.browse.sort", BR_COUNT = "sourcerer.browse.count", BR_LAST = "sourcerer.browse.last";
function brOrder(v) { return v === "logo" ? "source" : /^(activity|favorites|source)$/.test(v) ? v : "name"; }      // ("logo" was Source's twin; the numbers are the second choice's)
function brNumber(v) { return v === "files" ? "images" : /^(images|downloads|percent|logos)$/.test(v) ? v : "sources"; }
S.brArtist = 0; S.brAt = ""; S.brFit = "square"; S.brSort = "name"; S.brCount = "sources";
try {
  S.brSort = brOrder(localStorage.getItem(BR_SORT));
  S.brCount = brNumber(localStorage.getItem(BR_COUNT));   // ("files" was the images; "auto" is gone: the cloud is always shown)
  S.brArtist = +localStorage.getItem(BR_LAST) || 0;                              // the artist that was open when Sourcerer was closed
} catch (e) {}
$("br-sort").value = S.brSort; $("br-count").value = S.brCount;
try { S.brHidden = JSON.parse(localStorage.getItem(BR_HIDDEN) || "{}"); } catch (e) { S.brHidden = {}; }
try { S.brFolded = JSON.parse(localStorage.getItem(BR_FOLDED) || "{}"); } catch (e) { S.brFolded = {}; }      // the list's folded groups
try { S.brFit = localStorage.getItem(BR_FIT) === "full" ? "full" : "square"; } catch (e) {}

// A gallery the user has left stays: it keeps loading on the server, its posts stay here, and picking the artist
// again shows it at once, where it was -- no new request to any site. (The filter never asks a site: it only hides.)
// Kept aside at most GS_KEEP of them, each for GS_AGE: after that its posts are too old to trust (a link may have
// expired, a download may have changed what is saved) and the gallery opens again, from its snapshots.
var GS = {}, GS_KEEP = 6, GS_AGE = 15 * 60 * 1000;

function galDrop(key) {
  var g = GS[key];
  delete GS[key];
  if (g && g.id) api("POST", "/api/gallery/close", { gallery: g.id }).catch(function () {});
}

// Leaves the open gallery without closing it -- unless it is out of date or never opened: then it is closed.
function galStash() {
  if (!G) return;
  if (G.stale || (!G.id && !G.loading)) { var old = G; G = null; if (old.id) api("POST", "/api/gallery/close", { gallery: old.id }).catch(function () {}); return; }
  G.scroll = $("gal-body").scrollTop; G.at = Date.now(); G.polling = false;
  GS[G.key] = G;
  Object.keys(GS).sort(function (x, y) { return GS[x].at - GS[y].at; }).slice(0, -GS_KEEP).forEach(galDrop);
  G = null;
}

function browseClose() {
  if (G && G.id) api("POST", "/api/gallery/close", { gallery: G.id }).catch(function () {});
  G = null;
  galQueue = []; galFlight.clear(); galNear.disconnect();
  $("gal-grid").innerHTML = ""; $("gal-sources").innerHTML = "";
  closeView();
}

// The artists, "All artists" first; the one open is marked. Alphabetic, the latest activity first, or grouped by source
// (under each site's logo and a line; an artist stands once, under its master source, else its first one Sourcerer can read),
// and the number beside a name is what the second choice says: the sources Sourcerer tracks or the images in the library.
// The cloud at the end is the card's auto-download: green when it is on, dark grey when it is off. A card that
// is syncing shows a ring instead of its number. The list is only replaced when its markup changed: it is
// redrawn on every poll while a sync runs, and replacing it would swallow a click that began before.
var brHtml = "";
function siteSrc(a) {
  return a.sources.filter(function (x) { return x.master; })[0] || a.sources.filter(function (x) { return x.supported; })[0] || a.sources[0];
}
// The website the card's main account is on, by its own name: a Mastodon server, a forum and a booru are told apart (describe's `site`).
function siteOf(a) {
  var s = siteSrc(a);
  return s ? s.site || s.label : "";
}
// The sites an artist has an account on, one source for each (Source order lists the artist under every one of them: Avocado on X, pixiv and
// Mastodon stands in three groups). A card with no readable source stands once, where its main account is.
function siteSources(a) {
  var from = supportedOf(a), seen = {};
  if (!from.length) from = [siteSrc(a)];
  return from.filter(function (s) { var k = s ? s.site || s.label : ""; return seen[k] ? false : (seen[k] = true); });
}
// The numbers an artist has: the images posted (per source: what the library has of it, a duplicate not kept included, and what the
// last look found waiting -- at least what the newest posts showed, and what the site itself says where its answer carries it:
// pixiv's works, X's media), the ones downloaded, and their share. A source that was never walked to its end has more behind
// what is known, which a "+" says; one the site's own count covers, or a download walked all of, is exact.
function srcTotal(s) { return Math.max((s.files_all || 0) + (s.pending || 0), s.seen || 0, s.posted || 0); }
function srcExact(s) { return !!s.complete || ((s.posted || 0) > 0 && s.posted >= (s.files_all || 0) + (s.pending || 0) && s.posted >= (s.seen || 0)); }
function supportedOf(a) { return a.sources.filter(function (s) { return s.supported; }); }
function totalOf(a) {
  var sum = 0;
  supportedOf(a).forEach(function (s) { sum += srcTotal(s); });
  return Math.max(sum, (a.file_count || 0) + (a.pending || 0));
}
function downloadsOf(a) { return a.file_count || 0; }
function shareOf(a) { var t = totalOf(a); return t ? Math.min(1, downloadsOf(a) / t) : 0; }
function cutOff(a) { return supportedOf(a).some(function (s) { return !srcExact(s); }); }
function countText(a) {
  if (S.brCount === "images") return totalOf(a) ? totalOf(a) + (cutOff(a) ? "+" : "") : "";
  if (S.brCount === "downloads") return downloadsOf(a) || "";
  if (S.brCount === "percent") return totalOf(a) ? Math.round(100 * shareOf(a)) + "%" : "";
  if (S.brCount === "logos") return siteMarks(a);                 // the marks of the sites its accounts are on
  return a.sources.filter(function (s) { return s.supported; }).length || "";
}
// "All artists" gets the same number for the whole list: how many artists, how many images, how many downloaded, what share.
function allText() {
  var tot = 0, done = 0, plus = false;
  S.artists.forEach(function (a) { tot += totalOf(a); done += downloadsOf(a); plus = plus || cutOff(a); });
  if (S.brCount === "images") return tot ? tot + (plus ? "+" : "") : "";
  if (S.brCount === "downloads") return done || "";
  if (S.brCount === "percent") return tot ? Math.round(100 * done / tot) + "%" : "";
  return S.artists.length || "";
}
function renderBrowseList() {
  var q = $("br-search").value.trim().toLowerCase(), bySite = S.brSort === "source", sites = {}, srcOf = {};
  var byStar = S.brSort === "favorites", stars = 0;
  var found = S.artists.filter(function (a) { return !q || nameHit(a, q); });
  // Source order: one entry per site an artist is on, so the artist stands in each group; every other order has one entry per artist.
  var list = bySite ? [].concat.apply([], found.map(function (a) {
    return siteSources(a).map(function (s) { return { a: a, site: s ? s.site || s.label : "", src: s || {} }; });
  })) : found.map(function (a) { return { a: a }; });
  list.sort(function (ex, ey) {
    var x = ex.a, y = ey.a;
    if (byStar && !x.favorite !== !y.favorite) return x.favorite ? -1 : 1;
    if (S.brSort === "activity") { var tx = activityKey(x), ty = activityKey(y); if (tx !== ty) return !tx ? 1 : !ty ? -1 : tx < ty ? 1 : -1; }
    if (bySite && ex.site !== ey.site) return !ex.site ? 1 : !ey.site ? -1 : ex.site.localeCompare(ey.site);
    return x.name.localeCompare(y.name);
  });
  var ids = [];                                                            // what Refresh all follows: every artist once, as the list shows them
  list.forEach(function (e) { if (ids.indexOf(e.a.id) < 0) ids.push(e.a.id); });
  S.brOrderIds = ids;
  if (bySite) list.forEach(function (e) { sites[e.site] = (sites[e.site] || 0) + 1; srcOf[e.site] = srcOf[e.site] || e.src; });
  if (byStar) list.forEach(function (e) { if (e.a.favorite) stars++; });
  // The artist who is open is marked once -- in the group clicked last, else in the first it stands in.
  var mark = "";
  list.forEach(function (e) { if (e.a.id === S.brArtist && (!mark || e.site === S.brAt)) mark = e.site; });
  var active = new Set((S.sync.active || []).map(function (c) { return c.artist_id; })), queue = new Set(S.sync.queue || []);
  function count(a) {
    var on = active.has(a.id);
    if (on || queue.has(a.id)) return '<i class="spin" title="' + (on ? "Working…" : "Queued") + '"></i>';
    return countText(a);
  }
  // A group (a site, or Favorites / Others) folds under its head; a search shows everything it finds.
  var grouped = byStar && stars && stars < list.length;
  function groupOf(e, i) { return bySite ? "s:" + e.site : grouped ? (i < stars ? "f:fav" : "f:rest") : ""; }
  function groupHead(g, inner) {
    var open = q || !S.brFolded[g];
    return '<div class="br-group fold" role="button" data-grp="' + esc(g) + '" aria-expanded="' + open + '">' + icon("chevron-right", "fold-ic") + inner + "</div>";
  }
  var html = (q ? "" : '<button type="button" class="br-item all' + (!S.brArtist ? " selected" : "") +
    '" data-id="0">' + icon("photo") + '<span class="br-name">All artists</span><span class="br-n">' + allText() + "</span></button>") +
    list.map(function (e, i) {
      var a = e.a, g = groupOf(e, i), head = "";
      if (g && (!i || groupOf(list[i - 1], i - 1) !== g)) {
        var site = e.site, src = e.src || {};
        head = groupHead(g, bySite ? (siteLogo(site, src.kind, src.host) || "") + "<span>" + esc(site || "No source") + '</span><span class="num">' + sites[site] + "</span>"
          : g === "f:fav" ? '<svg class="ic star"><use href="#i-star"/></svg><span>Favorites</span><span class="num">' + stars + "</span>"
          : '<span>Others</span><span class="num">' + (list.length - stars) + "</span>");
      }
      if (g && !q && S.brFolded[g]) return head;
      return head + '<button type="button" class="br-item' + (S.brArtist === a.id && (!bySite || e.site === mark) ? " selected" : "") + '" data-id="' + a.id + '" data-site="' + esc(e.site || "") + '">' +
        avatarHtml(a) + '<span class="br-name" title="' + esc(a.name) + '">' + esc(a.name) + "</span>" +
        '<span class="br-n' + (S.brCount === "logos" ? " marks" : "") + '">' + count(a) + "</span>" +
        (a.auto_download ? '<span class="br-auto" title="Auto-download on">' + icon("cloud-down") + "</span>" : "") +
        (a.favorite ? '<span class="br-fav" title="Favorite">' + icon("star") + "</span>" : "") + "</button>";
    }).join("");
  if (html !== brHtml) { brHtml = html; $("br-list").innerHTML = html; }
}

var brAvatar = "";
function renderBrowseHead() {
  var a = G && G.artist, sup = !!a && a.sources.some(function (s) { return s.supported; });
  var cur = a && (S.sync.active || []).filter(function (c) { return c.artist_id === a.id; })[0] || null;
  var queued = a && (S.sync.queue || []).indexOf(a.id) >= 0;
  $("br-progress").textContent = cur ? (cur.mode === "refresh" || cur.mode === "scan" ? "Looking for new posts…" : cur.phase === "scan" ? "Checking sources…"
    : "Downloading " + cur.done + " / " + cur.total) : queued ? "Queued" : a && a.pending ? a.pending + (a.pending >= 120 ? "+" : "") + " to download" : "";
  // The artist's picture beside the name (not for "All artists"); replaced only when it changed, or it would blink on every poll.
  var av = a ? avatarHtml(a) : "";
  if (av !== brAvatar) { brAvatar = av; $("gal-avatar").innerHTML = av; }
  ["br-download", "br-edit", "br-refresh", "br-folder", "br-auto"].forEach(function (id) { $(id).classList.toggle("hidden", !a); });
  $("br-select").classList.toggle("hidden", !G);
  renderSelBar();
  $("br-auto").classList.toggle("on", !!(a && a.auto_download));
  $("br-auto").setAttribute("aria-checked", a && a.auto_download ? "true" : "false");
  $("br-download").disabled = $("br-refresh").disabled = !sup;
  galHead();
}

// The spinner while a site is still being asked, and the count of new posts a check found
// (they join when the gallery is opened again, so the pictures keep their places meanwhile).
function galLoading(g) {
  return !!(g && g.loading && (!g.sources || g.sources.some(function (s) { return s.loading; })));
}

function galHead() {
  var loading = galLoading(G), n = G && G.newPosts || 0;
  $("gal-spin").classList.toggle("hidden", !loading);
  $("gal-new").classList.toggle("hidden", !n);
  $("gal-new").textContent = n ? plural(n, "new post") + " · show" : "";
}

// The state of the sources while the page waits for them: a spinner per site, green once asked.
// It asks nobody and only runs while the gallery is shown; it slows down the longer a site takes.
// A gallery that comes back from being kept aside is asked once, even when nothing was loading: the server
// may have closed it meanwhile.
function galPoll(g) {
  if (g.polling) return;
  g.polling = true;
  var n = 0;
  (function tick() {
    if (g !== G || !g.id) { g.polling = false; return; }      // left: galResume starts it again
    api("POST", "/api/gallery/state", { gallery: g.id }).then(function (d) {
      if (g !== G) return;
      g.sources = d.sources; g.loading = d.loading; g.newPosts = d.new_posts;
      galSources(d.sources); galHead();
      if (galLoading(g)) setTimeout(tick, Math.min(3000, 600 + 100 * n++)); else g.polling = false;
    }).catch(function (e) {
      g.polling = false;
      // Closed by the server (a long rest, a restart): open it again.
      if (g === G && /was closed/.test(e.message)) browseOpen(S.brArtist, true);
      else if (g === G) { g.loading = false; galHead(); galSources(g.sources || []); }
    });
  })();
}

// Opens an artist's gallery -- or shows the one kept aside, as it was. fresh: open it again whatever is kept.
function browseOpen(id, fresh) {
  closeMenu();
  var a = id ? artistById(id) : null;
  if (id && !a) id = 0;                         // the artist is gone: All artists
  S.brArtist = id || 0;
  try { localStorage.setItem(BR_LAST, String(S.brArtist)); } catch (e) {}
  if (G && G.key === S.brArtist) {              // the open one again: only to show it fresh
    if (!fresh) return;
    browseClose();
  } else galStash();
  galQueue = []; galFlight.clear(); galNear.disconnect();
  var kept = GS[S.brArtist];
  if (kept && (fresh || kept.stale || Date.now() - kept.at > GS_AGE)) { galDrop(S.brArtist); kept = null; }
  if (kept) { delete GS[S.brArtist]; return galResume(kept, a); }
  G = { key: S.brArtist, artist: a, all: !id, id: null, items: [], busy: false, done: false, hidden: S.brHidden, view: -1, sources: null,
        downloading: {}, loading: true, newPosts: 0, polling: false, sel: new Set(), last: -1 };
  $("gal-title").textContent = a ? a.name : "All artists";
  $("gal-grid").innerHTML = ""; $("gal-sources").innerHTML = "";
  $("gal-body").scrollTop = 0;
  $("gal-end").textContent = "Asking the sites…";
  closeView();
  renderBrowseList(); renderBrowseHead();
  if (!id && !S.artists.length) { G.loading = false; galHead(); $("gal-end").textContent = "No cards yet: create a card first."; return; }
  var g = G;
  if (id && S.sync && (S.sync.running || (S.sync.queue || []).length)) api("POST", "/api/sync/focus", { artist_id: id }).catch(function () {});
  api("POST", "/api/gallery/open", { artist_id: id || 0 }).then(function (d) {
    if (g !== G && GS[g.key] !== g) return api("POST", "/api/gallery/close", { gallery: d.gallery });
    g.id = d.gallery; g.sources = d.sources;
    g.loading = d.sources.some(function (s) { return s.loading; });
    if (g !== G) return;                        // left before it opened: it is kept aside, and shown again from here
    galSources(d.sources); galHead();
    moreGallery();
    if (g.loading) galPoll(g);
  }).catch(function (e) { g.loading = false; if (g === G) { galHead(); $("gal-end").textContent = e.message; } });
}

// A gallery kept aside, shown again: its posts from memory, then one look at the server's state.
function galResume(g, a) {
  G = g;
  g.artist = a; g.hidden = S.brHidden; g.polling = false;
  $("gal-title").textContent = a ? a.name : "All artists";
  closeView();
  renderBrowseList(); renderBrowseHead();
  $("gal-grid").innerHTML = g.items.map(function (it, i) { return tileHtml(it, i); }).join("");
  $("gal-sources").innerHTML = "";
  if (g.sources) galSources(g.sources);
  galEnd(g);
  galWatch(); galLayout();
  $("gal-body").scrollTop = g.scroll || 0;
  if (!g.id) return;                            // still waiting for its opening: the answer shows it
  galSavedRefresh();                            // what the library has may have changed while it was aside
  galPoll(g);
  if (!g.busy && !g.done && galEndNear()) moreGallery();
}

// The line at the end of the grid. All artists reaches back a time window (Settings) and stops there with a button for older posts.
function galEnd(g) {
  var el = $("gal-end");
  if (g.older) {
    var since = new Date(g.since * 1000).toLocaleDateString();
    el.innerHTML = esc(g.items.length ? plural(g.items.length, "picture") + " since " + since : "Nothing posted since " + since) +
      ' <button type="button" class="mini" id="gal-older">Load older posts</button>';
  } else el.textContent = !g.done ? "" : g.items.length ? plural(g.items.length, "picture") + " – that is all" : "Nothing found.";
}
$("gal-end").addEventListener("click", function (e) {
  var g = G;
  if (!e.target.closest("#gal-older") || !g || !g.id) return;
  e.target.closest("#gal-older").disabled = true;
  api("POST", "/api/gallery/older", { gallery: g.id }).then(function (d) {
    g.since = d.since; g.older = false; g.done = false;
    if (g === G) { $("gal-end").textContent = "Asking the sites…"; moreGallery(); }
  }).catch(fail);
});

// The end of the grid is in sight, so more is wanted. (The observer only fires on a change.)
function galEndNear() {
  var end = $("gal-end").getBoundingClientRect(), box = $("gal-body").getBoundingClientRect();
  return end.top < box.bottom + 800;
}

function moreGallery() {
  var g = G;
  if (!g || !g.id || g.busy || g.done) return;
  // Only hidden sources have more: nothing to show for the requests it would take.
  if (g.sources && !g.sources.some(function (s) { return !g.hidden[s.label] && s.state === "more"; })) {
    if (!g.items.length) {
      var bad = g.sources.filter(function (s) { return s.error; })[0];
      $("gal-end").textContent = !g.sources.length ? "No source here that Sourcerer can read."
        : g.sources.every(function (s) { return g.hidden[s.label]; }) ? "Every site is switched off."
        : bad ? "Could not read " + bad.label + ": " + bad.error : "Nothing found.";
    }
    return;
  }
  g.busy = true;
  $("gal-end").textContent = "Asking the sites…";
  // The first page is only what the window shows: it is there as soon as one source answered.
  api("POST", "/api/gallery/more", { gallery: g.id, n: g.items.length ? 60 : 24 }).then(function (d) {
    // What the server handed out is kept even when the gallery was left meanwhile: it will not hand it out again.
    g.busy = false; g.done = d.done || d.older; g.older = d.older && !d.done; g.since = d.since; g.sources = d.sources;
    g.loading = d.loading; g.newPosts = d.new_posts;
    var start = g.items.length;
    g.items = g.items.concat(d.items);
    if (g !== G) return;                        // kept aside: shown from memory when it comes back
    $("gal-grid").insertAdjacentHTML("beforeend", d.items.map(function (it, k) { return tileHtml(it, start + k); }).join(""));
    galWatch(); galLayout();
    galSources(d.sources); galHead();
    if (g.loading) galPoll(g);
    galEnd(g);
    // The observer fires on a change only: while the end is still in sight, ask on.
    if (!g.done && d.items.length && galEndNear()) setTimeout(moreGallery, 50);
  }).catch(function (e) {
    g.busy = false;
    if (g !== G) return;
    // Closed by the server after a long rest (or a restart): open it again where it was.
    if (/was closed/.test(e.message)) return browseOpen(S.brArtist, true);
    $("gal-end").textContent = e.message;
  });
}

// Sourcerer's own fetch of an item, for one the page could not load itself;
// "" for one that already comes through Sourcerer.
function proxyOf(it, size) {
  var url = size === "thumb" ? it.thumb : it.large;
  if (!G || !G.id || /^\/api\/gallery\/[0-9a-f]{32}\//.test(url || "")) return "";
  return "/api/gallery/" + G.id + "/" + it.id + "/" + size;
}

// A site's mark instead of its name; "" for a site without one (the caller writes the name then).
var SITE_LOGOS = { Bluesky: "bluesky", Mastodon: "mastodon", Misskey: "misskey", Pixiv: "pixiv", Patreon: "patreon", X: "x", Fanbox: "fanbox", Fantia: "fantia", XenForo: "xenforo", Booru: "booru" };
var MARKS = { bluesky: 1, mastodon: 1, misskey: 1, pixiv: 1, patreon: 1, x: 1, fanbox: 1, fantia: 1, xenforo: 1, booru: 1 };
var MANY_KINDS = { mastodon: 1, misskey: 1, xenforo: 1, booru: 1 };      // software many sites run: each wears its own icon (sources.MANY)
var ICON_FAILED = {};                                                     // hosts whose site gave no icon: the software's mark stands in
// label: the site's name (a server or forum is told by its own), kind and host say which software and where its icon is.
function siteLogo(label, kind, host) {
  var mark = SITE_LOGOS[label] || (MARKS[kind] ? kind : "");
  var svg = mark ? '<svg class="ic logo" role="img" aria-label="' + esc(label) + '"><use href="#l-' + mark + '"/></svg>' : "";
  if (!MANY_KINDS[kind] || !host || ICON_FAILED[host]) return svg;
  return '<img class="ic logo fav" referrerpolicy="no-referrer" alt="' + esc(label) + '" data-host="' + esc(host) + '" data-mark="' + mark +
    '" src="/api/site-icon/' + encodeURIComponent(host) + '">';
}
// A site without an icon (or one that does not load): the software's mark, or the name, in its place -- and not asked for again.
document.addEventListener("error", function (e) {
  var img = e.target;
  if (!img || img.tagName !== "IMG" || !img.classList.contains("fav")) return;
  ICON_FAILED[img.dataset.host] = true;
  var t = document.createElement("template");
  t.innerHTML = img.dataset.mark ? '<svg class="ic logo" role="img" aria-label="' + esc(img.alt) + '"><use href="#l-' + img.dataset.mark + '"/></svg>'
    : '<span class="gal-site">' + esc(img.alt) + "</span>";
  img.replaceWith(t.content.firstChild);
}, true);

function tileHtml(it, i) {
  var proxied = /^\/api\/gallery\//.test(it.thumb || "");
  var picture = it.thumb
    ? '<img loading="lazy" decoding="async" referrerpolicy="no-referrer" ' + (proxied ? "data-lazy" : "src") + '="' + esc(it.thumb) + '" alt="">'
    : '<span class="gal-noimg">' + icon(it.video ? "play" : "photo") + "</span>";
  var who = G.all ? it.artist + " · " + it.source : it.source;
  var name = G.all ? '<span class="gal-name">' + esc(it.artist) + "</span>" : "";      // "All artists": whose picture it is, beside the mark
  return '<button type="button" class="gal-tile' + (G.hidden[it.source] ? " hidden" : "") + (G.sel && G.sel.has(i) ? " sel" : "") +
    (G.downloading[it.id] ? " busy" : "") + '" data-i="' + i +
    (it.w && it.h ? '" data-ar="' + galRatio(it.w, it.h) : "") +
    '" data-src="' + esc(it.source) + '" title="' + esc(who + (it.posted ? " · " + it.posted.slice(0, 10) : "") + (it.fname ? " · " + it.fname : "")) + '">' +
    picture + (it.fname ? '<span class="gal-fname">' + esc(it.fname) + "</span>" : "") + (it.video && it.thumb ? '<span class="gal-play">' + icon("play") + "</span>" : "") +
    '<span class="gal-tag">' + (siteLogo(it.source, it.kind, it.host) || '<span class="gal-site">' + esc(it.source) + "</span>") + name + "</span>" +
    // The download button's own place and shape: grey (blue under the pointer) while the picture is not in the library, green
    // for good once it is -- however it got there. It is gone again when the file is deleted (galSavedRefresh).
    (it.saved ? '<span class="gal-dl saved" title="Downloaded">' + icon("download") + "</span>"
              : '<span class="gal-dl" data-dl title="Download this picture">' + icon("download") + "</span>") +
    '<span class="gal-pick" data-pick title="Select">' + icon("tick") + "</span>" +
    (it.gif || it.anim ? '<span class="gal-badge">GIF</span>' : "") + "</button>";
}

// One chip per site the open gallery has a source of: switching it off hides its posts and
// stops asking it; the choice is kept for the next artist.
function galSources(list) {
  var sites = [];
  list.forEach(function (s) { if (sites.indexOf(s.label) < 0) sites.push(s.label); });
  $("gal-sources").innerHTML = sites.map(function (label) {
    var of = list.filter(function (s) { return s.label === label; });
    var bad = of.filter(function (s) { return s.error; }), off = !!G.hidden[label];
    var busy = of.some(function (s) { return s.loading; });
    // All artists never asks a login site: its posts are what the last looks saved (Refresh all reads the sites).
    var stored = of.every(function (s) { return s.offline; }), unlooked = of.filter(function (s) { return s.offline && !s.cached; }).length;
    var ready = !busy && !bad.length && !stored && of.every(function (s) { return s.checked || s.state === "done"; });
    var news = of.reduce(function (n, s) { return n + (s.new || 0); }, 0);
    var tip = bad.length ? label + ": " + bad[0].error : off ? "Show " + label
      : stored ? label + ": from the last look, the site is not asked here. Refresh all (F5) reads it" +
        (unlooked ? " · " + plural(unlooked, "account") + " not looked at yet" : "")
      : busy ? label + ": asking the site…" + (of.length > 1 ? " (" + of.filter(function (s) { return !s.loading; }).length + " of " + of.length + " accounts answered)" : "") : "Hide " + label + (G.all ? " (" + plural(of.length, "source") + ")" : "") +
        (of.every(function (s) { return s.fresh; }) ? " · from a look a few minutes ago, asked again at the end of what is shown" : "") +
        (news ? " · " + plural(news, "new post") : "");
    // A spinner while the site is asked, green when it answered, orange when it did not.
    var state = busy ? '<i class="spin"></i>' : '<i class="dot ' + (bad.length ? "warn" : ready ? "ok" : "blank") + '"></i>';
    var mark = siteLogo(label, of[0].kind, of[0].host);
    return '<button type="button" class="chip' + (mark ? " logo" : "") + (off ? " off" : "") + '" data-galsrc="' + esc(label) +
      '" title="' + esc(tip) + '">' + (mark ? '<span class="mark">' + mark + state + "</span>" : state + esc(label)) + "</button>";
  }).join("");
}

function viewItem(i) {
  if (!G || !G.items[i]) return;
  var it = G.items[i];
  G.view = i;
  zoomReset();
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
      galPrefetch(i);
    };
    img.onerror = function () {
      if (!img.isConnected) return;
      if (next.length) img.src = next.shift();
      else { img.onerror = null; if (small) img.remove(); }
    };
  }
  // Top left the site's mark; bottom left who it is -- picture and name -- and what is known of the file.
  $("gal-source").innerHTML = siteLogo(it.source, it.kind, it.host) || '<b>' + esc(it.source) + "</b>";
  $("gal-source").title = it.source;
  $("gal-who").innerHTML = avatarHtml(artistById(it.artist_id) || { name: it.artist }) + "<span>" + esc(it.artist) + "</span>";
  galInfoLine(i);
  galAbout(it);
  galDlState(it);
  $("gal-view").classList.remove("hidden");
  // Near the end of what is listed: the next page, before it is needed.
  if (i > G.items.length - 8) moreGallery();
}

function galInfoLine(i) {
  var it = G.items[i];
  $("gal-info").textContent = [it.posted ? new Date(it.posted).toLocaleString() : "",
    it.w ? it.w + " × " + it.h : "", it.fname || "", (i + 1) + " / " + G.items.length + (G.done ? "" : "+")].filter(Boolean).join(" · ");
}

// What the site knows of the picture beyond its listing -- a forum's title, description, who and when, size, views -- asked when the
// viewer opens it (one request; a listing page holds a title only). Quietly: the picture is what matters, a failure shows nothing.
function galAbout(it) {
  var box = $("gal-about");
  box.classList.add("hidden");
  if (!it.info) return;
  if (it.about) return galAboutShow(it);
  var g = G;
  api("POST", "/api/gallery/info", { gallery: g.id, n: it.id }).then(function (d) {
    it.about = d;
    if (d.posted && !it.posted) it.posted = d.posted;
    if (g === G && G.items[G.view] === it) { galInfoLine(G.view); galAboutShow(it); }
  }).catch(function () { it.about = {}; });
}
function galAboutShow(it) {
  var a = it.about || {}, bits = [];
  if (a.author) bits.push("by " + a.author);
  if (a.posted) bits.push(new Date(a.posted).toLocaleString());
  if (a.width) bits.push(a.width + " × " + a.height);
  if (a.size) bits.push(a.size);
  ["views", "likes", "comments"].forEach(function (k) { if (a[k]) bits.push(a[k] + " " + k); });
  var box = $("gal-about");
  box.innerHTML = (a.title ? "<b>" + esc(a.title) + "</b>" : "") + (a.description ? "<p>" + esc(a.description) + "</p>" : "") +
    (bits.length ? "<small>" + esc(bits.join(" · ")) + "</small>" : "");
  box.classList.toggle("hidden", !box.innerHTML);
}

// The viewer's Download button: green "Downloaded" once the picture is in the library.
function galDlState(it) {
  var b = $("gal-download"), busy = !!G.downloading[it.id];
  b.disabled = it.saved || busy;
  b.classList.toggle("done", !!it.saved);
  b.querySelector("svg use").setAttribute("href", "#i-download");
  b.querySelector("span").textContent = it.saved ? "Downloaded" : busy ? "Downloading…" : "Download";
}

// The next two pictures are fetched while this one is looked at, once it has arrived (not before: it
// comes first): stepping on finds them in the browser's cache -- or in Sourcerer's memory, for a site
// whose pictures go through it. A gallery that closed meanwhile simply fails them.
var galPre = [];
function galPrefetch(i) {
  galPre = [];                                    // held until the next call so the browser does not drop them
  for (var n = i + 1, left = 2; G && G.items[n] && left; n++) {
    var it = G.items[n];
    if (G.hidden[it.source]) continue;            // step() skips those too
    left--;
    if (it.video || !it.large) continue;
    var im = new Image();
    im.referrerPolicy = "no-referrer";
    im.src = it.large;
    galPre.push(im);
  }
}

function step(by) {
  if (!G) return;
  var i = G.view;
  do { i += by; } while (G.items[i] && G.hidden[G.items[i].source]);
  if (G.items[i]) viewItem(i);
}

function closeView() {
  zoomReset();
  $("gal-about").classList.add("hidden");
  $("gal-view").classList.add("hidden");
  $("gal-stage").innerHTML = "";                  // stops a video
  if (G) G.view = -1;
}

$("gal-grid").addEventListener("click", function (e) {
  var tile = e.target.closest(".gal-tile");
  if (!tile) return;
  var i = +tile.dataset.i;
  if (e.target.closest("[data-dl]")) return void galDownload(i);                      // the arrow on the tile: this one picture
  // Select mode, the tile's own tick, Ctrl or Shift: select instead of opening (Shift: everything in between).
  if (S.brSelect || e.ctrlKey || e.metaKey || e.shiftKey || e.target.closest("[data-pick]")) return selToggle(i, e.shiftKey);
  viewItem(i);
});
// A picture the browser was not handed (a CDN's bot check, a hotlink rule):
// once more through Sourcerer, then a placeholder instead of a broken image.
$("gal-grid").addEventListener("error", function (e) {
  if (e.target.tagName !== "IMG") return;
  if (e.target.classList.contains("sharp")) { e.target.remove(); return; }       // the small picture stays
  var tile = e.target.closest(".gal-tile"), it = G && G.items[+tile.dataset.i];
  var via = it && proxyOf(it, "thumb");
  if (via && !e.target.dataset.lazy) {
    e.target.removeAttribute("src"); e.target.dataset.lazy = via;
    galQueue.push(e.target);
    setTimeout(galPump);                 // after this event: listeners added now would hear it
    return;
  }
  if (e.target.dataset.lazy && !e.target.dataset.retried) {      // one dropped connection must not leave a hole in the grid
    var img = e.target;
    img.dataset.retried = "1"; img.removeAttribute("src");
    setTimeout(function () { if (img.isConnected) { galQueue.push(img); galPump(); } }, 1500);
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
  // The filter only hides: every site is asked whatever it says, so showing one again needs no request.
  if (!G.hidden[label]) galWatch();
  if (galEndNear()) moreGallery();
  galLayout();
});
$("gal-view").addEventListener("click", function (e) {
  var b = e.target.closest("[data-gal]");
  if (!b && G && !Z.moved && Date.now() - zoomLast.toggled > 700 && outsidePicture(e)) closeView();          // the dark around the picture closes it too
  if (!b || !G) return;
  var it = G.items[G.view];
  if (b.dataset.gal === "prev") step(-1);
  else if (b.dataset.gal === "next") step(1);
  else if (b.dataset.gal === "back") closeView();
  else if (b.dataset.gal === "post" && it && it.post) api("POST", "/api/open-url", { url: it.post }).catch(fail);
  else if (b.dataset.gal === "download") galDownload();
});
// ---- the open picture: double-click and wheel zoom it, a drag moves it ----------------
// The picture is the stage's whole box with object-fit: contain, so the dark around it is part of the img
// element: a click is "outside" by the picture's own shape (outsidePicture). Zoom is a transform on the
// images about the box's centre: Z.x / Z.y move it, Z.s scales it (1 = fitted, no zoom).
var Z = { s: 1, x: 0, y: 0, drag: null, moved: false }, ZOOM_MAX = 8;
function zoomApply() {
  var st = $("gal-stage");
  st.style.setProperty("--zs", Z.s); st.style.setProperty("--zx", Z.x + "px"); st.style.setProperty("--zy", Z.y + "px");
  st.classList.toggle("zoomed", Z.s > 1);
}
function zoomReset() { Z.s = 1; Z.x = Z.y = 0; Z.drag = null; zoomApply(); }
// The image's box (the stage without its padding): its size and where its centre is on the screen.
function zoomBox() {
  var st = $("gal-stage"), r = st.getBoundingClientRect(), c = getComputedStyle(st);
  var l = parseFloat(c.paddingLeft), t = parseFloat(c.paddingTop);
  var w = st.clientWidth - l - parseFloat(c.paddingRight), h = st.clientHeight - t - parseFloat(c.paddingBottom);
  return { w: w, h: h, cx: r.left + st.clientLeft + l + w / 2, cy: r.top + st.clientTop + t + h / 2 };
}
function zoomClamp(box) {
  var mx = (Z.s - 1) * box.w / 2, my = (Z.s - 1) * box.h / 2;
  Z.x = Math.max(-mx, Math.min(mx, Z.x)); Z.y = Math.max(-my, Math.min(my, Z.y));
}
// Scale to s2 so that the point under the cursor (clientX/Y) stays where it is.
function zoomAt(s2, clientX, clientY) {
  s2 = Math.max(1, Math.min(ZOOM_MAX, s2));
  if (s2 < 1.03) return zoomReset();
  var box = zoomBox(), px = clientX - box.cx, py = clientY - box.cy, r = s2 / Z.s;
  Z.x = px - (px - Z.x) * r; Z.y = py - (py - Z.y) * r; Z.s = s2;
  zoomClamp(box); zoomApply();
}
function stageImage() { return $("gal-stage").querySelector("img:last-child"); }
// Whether a click landed on the dark around the picture (never while zoomed: the picture fills the screen then).
function outsidePicture(e) {
  if (Z.s > 1) return false;
  if (e.target === $("gal-view") || e.target === $("gal-stage")) return true;
  var img = e.target.tagName === "IMG" && e.target.closest("#gal-stage") ? e.target : null;
  if (!img || !img.naturalWidth) return false;
  var box = zoomBox(), f = Math.min(box.w / img.naturalWidth, box.h / img.naturalHeight);
  return Math.abs(e.clientX - box.cx) > img.naturalWidth * f / 2 || Math.abs(e.clientY - box.cy) > img.naturalHeight * f / 2;
}
// A double-click zooms in, and on a picture that is zoomed (by this or the wheel) it puts the picture back to the fitted
// size. Found from the mouse-downs as well as from the browser's dblclick: a window's engine may not send that one
// for a press that was taken as the start of a drag. Whichever comes first acts; the other, within 600 ms, does not.
var zoomLast = { at: 0, x: 0, y: 0, toggled: 0 };
function zoomToggle(e) {
  if (!stageImage() || !e.target.closest || !e.target.closest("#gal-stage") || e.target.tagName === "VIDEO") return;
  if (Date.now() - zoomLast.toggled < 600) return;
  zoomLast.toggled = Date.now();
  if (Z.s > 1) zoomReset(); else zoomAt(2.5, e.clientX, e.clientY);
}
$("gal-stage").addEventListener("dblclick", zoomToggle);
$("gal-stage").addEventListener("mousedown", function (e) {
  if (e.button !== 0) return;
  var now = Date.now(), twice = now - zoomLast.at < 450 && Math.abs(e.clientX - zoomLast.x) < 12 && Math.abs(e.clientY - zoomLast.y) < 12;
  zoomLast.at = twice ? 0 : now; zoomLast.x = e.clientX; zoomLast.y = e.clientY;
  if (twice) zoomToggle(e);
}, true);
$("gal-stage").addEventListener("wheel", function (e) {
  if (!stageImage()) return;
  e.preventDefault();
  zoomAt(Z.s * Math.exp(-e.deltaY * (e.deltaMode === 1 ? 16 : 1) * 0.0025), e.clientX, e.clientY);
}, { passive: false });
$("gal-stage").addEventListener("mousedown", function (e) {
  if (Z.s <= 1 || e.button !== 0) return;
  Z.drag = { x: e.clientX, y: e.clientY, tx: Z.x, ty: Z.y }; Z.moved = false;
  e.preventDefault();
});
$("gal-stage").addEventListener("dragstart", function (e) { e.preventDefault(); });
document.addEventListener("mousemove", function (e) {
  if (!Z.drag) return;
  var dx = e.clientX - Z.drag.x, dy = e.clientY - Z.drag.y;
  if (Math.abs(dx) + Math.abs(dy) > 3) Z.moved = true;
  Z.x = Z.drag.tx + dx; Z.y = Z.drag.ty + dy;
  zoomClamp(zoomBox()); zoomApply();
});
document.addEventListener("mouseup", function () {
  if (!Z.drag) return;
  Z.drag = null;
  setTimeout(function () { Z.moved = false; }, 0);              // after the click that ends a drag
});

// The one place a picture is saved from the gallery: the viewer's button and key, the arrow on a tile, the menu and
// the selection all come here. Resolves to the answer ({item, kept}), rejects with the failure.
function galFetch(i) {
  var g = G, it = g && g.items[i];
  if (!it || it.saved || g.downloading[it.id]) return Promise.reject(new Error("Already downloaded or on its way."));
  g.downloading[it.id] = true;
  var tile = g === G && document.querySelector('#gal-grid .gal-tile[data-i="' + i + '"]');
  if (tile) tile.classList.add("busy");
  if (g.view === i) galDlState(it);
  galProgress(g);
  return api("POST", "/api/gallery/download", { gallery: g.id, item: it.id }).then(function (d) {
    delete g.downloading[it.id];
    g.items[i] = d.item;
    if (g === G) {                               // (left meanwhile: it shows the file saved when it comes back)
      var t = document.querySelector('#gal-grid .gal-tile[data-i="' + i + '"]');
      if (t) { t.outerHTML = tileHtml(d.item, i); galWatch(); galLayout(); }
      if (g.view === i) viewItem(i);
    }
    return d;
  }, function (err) {
    delete g.downloading[it.id];
    if (g === G) {
      var t = document.querySelector('#gal-grid .gal-tile[data-i="' + i + '"]');
      if (t) t.classList.remove("busy");
      if (g.view === i) galDlState(it);
    }
    throw err;
  });
}
// What the library has changes behind the page's back -- a sync saves pictures, the user deletes files in the file manager --
// so the open gallery asks again when the window comes back, when a sync ended, and every 20 s while it is shown: the tiles
// whose "downloaded" changed are drawn again (the green button appears or goes). Asks no site.
function galSavedRefresh() {
  var g = G;
  if (!g || !g.id || g.refreshing || document.hidden) return;
  g.refreshing = true;
  api("POST", "/api/gallery/saved", { gallery: g.id }).then(function (d) {
    g.refreshing = false;
    var changed = false;
    Object.keys(d.items).forEach(function (n) {
      var i = g.items.findIndex(function (x) { return x.id === +n; });
      if (i < 0) return;
      g.items[i] = d.items[n];
      changed = true;
      if (g !== G) return;
      var t = document.querySelector('#gal-grid .gal-tile[data-i="' + i + '"]');
      if (t) t.outerHTML = tileHtml(d.items[n], i);
      if (g.view === i) viewItem(i);
    });
    if (changed && g === G) { galWatch(); galLayout(); }
  }).catch(function () { g.refreshing = false; });
}
window.addEventListener("focus", galSavedRefresh);
document.addEventListener("visibilitychange", galSavedRefresh);
setInterval(galSavedRefresh, 20000);

// The ring round a tile's download button: how much of the file has come (0-100 %), asked of the server every 350 ms
// while any download of the open gallery is on its way; a site that does not say how big the file is shows a turning arc.
function galProgress(g) {
  if (g.progressing) return;
  g.progressing = true;
  (function tick() {
    if (!g.id || !Object.keys(g.downloading).length) { g.progressing = false; return; }
    api("POST", "/api/gallery/progress", { gallery: g.id }).then(function (d) {
      if (g === G) Object.keys(d.progress).forEach(function (n) { galRing(g, +n, d.progress[n]); });
    }).catch(function () {}).then(function () { setTimeout(tick, 350); });
  })();
}
function galRing(g, id, p) {
  var i = g.items.findIndex(function (x) { return x.id === id; });
  if (i < 0) return;
  var pct = p[1] ? Math.min(100, Math.round(100 * p[0] / p[1])) : -1;
  var dl = document.querySelector('#gal-grid .gal-tile[data-i="' + i + '"] .gal-dl');
  if (dl) { dl.style.setProperty("--p", pct < 0 ? 0 : pct); dl.classList.toggle("indet", pct < 0); }
  if (g.view === i) $("gal-download").querySelector("span").textContent = pct < 0 ? "Downloading…" : "Downloading " + pct + "%";
}
function galDownload(i) {
  if (i === undefined) i = G && G.view;               // the viewer's button and key: the picture open
  if (!G || !G.items[i] || G.items[i].saved) return;
  galFetch(i).then(function (d) {
    toast(d.kept ? "Saved in " + d.item.artist + "'s folder" : "Not saved: the same picture is already in the folder");
    load();
  }).catch(fail);
}
// Several pictures, three at a time (each one is a request to its site: the site's own lane still sets the pace).
function galDownloadMany(ids) {
  var g = G, todo = ids.filter(function (i) { var it = g.items[i]; return it && !it.saved && !g.downloading[it.id]; });
  if (!todo.length) return toast("Those are in the library already.");
  var n = todo.length, done = 0, kept = 0, failed = 0, lastError = "";
  S.brBusy = "Downloading 0 / " + n;
  renderSelBar();
  function next() {
    var i = todo.shift();
    if (i === undefined) return Promise.resolve();
    return galFetch(i).then(function (d) { if (d.kept) kept++; }, function (e) { failed++; lastError = e.message; })
      .then(function () { done++; S.brBusy = "Downloading " + done + " / " + n; renderSelBar(); return next(); });
  }
  Promise.all([next(), next(), next()]).then(function () {
    S.brBusy = "";
    if (g.sel) g.sel.clear();
    S.brSelect = false;
    selPaint();
    toast(plural(kept, "picture") + " saved" + (n - kept - failed ? ", " + (n - kept - failed) + " already there" : "") +
          (failed ? ", " + failed + " failed (" + lastError + ")" : ""), !!failed && !kept);
    load();
  });
}

// ---- selecting pictures: Select button, Ctrl / Shift click, the tick on a tile ----------------
function selToggle(i, range) {
  var g = G, it = g && g.items[i];
  if (!it || g.hidden[it.source]) return;
  if (range && g.last !== undefined && g.last >= 0) {
    var lo = Math.min(g.last, i), hi = Math.max(g.last, i), on = !g.sel.has(i);
    for (var k = lo; k <= hi; k++) {
      var t = g.items[k];
      if (!t || g.hidden[t.source]) continue;
      if (on) g.sel.add(k); else g.sel.delete(k);
    }
  } else if (g.sel.has(i)) g.sel.delete(i); else g.sel.add(i);
  g.last = i;
  selPaint();
}
function selPaint() {
  $$("#gal-grid .gal-tile").forEach(function (t) { t.classList.toggle("sel", !!(G && G.sel && G.sel.has(+t.dataset.i))); });
  $("gal-grid").classList.toggle("selecting", !!S.brSelect || !!(G && G.sel && G.sel.size));
  $("br-select").classList.toggle("on", !!S.brSelect);
  $("br-select").setAttribute("aria-pressed", S.brSelect ? "true" : "false");
  renderSelBar();
}
function renderSelBar() {
  var n = G && G.sel ? G.sel.size : 0, on = !!G && (S.brSelect || n > 0);
  $("sel-bar").classList.toggle("hidden", !on);
  if (!on) return;
  $("sel-text").textContent = S.brBusy || (n ? plural(n, "picture") + " selected" : "Click pictures to select them");
  $("sel-download").disabled = !n || !!S.brBusy;
}
function selAll() {
  if (!G) return;
  G.items.forEach(function (it, i) { if (it && !it.saved && !G.hidden[it.source]) G.sel.add(i); });
  selPaint();
}
$("br-select").addEventListener("click", function () {
  S.brSelect = !S.brSelect;
  if (!S.brSelect && G && G.sel) G.sel.clear();
  selPaint();
});
$("sel-download").addEventListener("click", function () {
  if (G && G.sel.size) galDownloadMany(Array.from(G.sel).sort(function (a, b) { return a - b; }));
});
$("sel-all").addEventListener("click", selAll);
$("sel-clear").addEventListener("click", function () { if (G) G.sel.clear(); selPaint(); });
$("sel-done").addEventListener("click", function () { S.brSelect = false; if (G) G.sel.clear(); selPaint(); });
// Right-click on a picture: the grid's offers to download it, the viewer's also to copy it (as a PNG, the one
// format every program takes from the clipboard). The copy is fetched through Sourcerer -- a CDN's picture
// would taint the canvas -- like the viewer's own fallback.
var picAt = -1;
function openPicMenu(i, viewer, x, y) {
  var it = G && G.items[i], m = $("picmenu");
  if (!it) return;
  picAt = i;
  m.querySelector('[data-pic="copy"]').classList.toggle("hidden", !!it.video);
  var d = m.querySelector('[data-pic="download"]');
  d.disabled = !!it.saved || !!G.downloading[it.id];
  d.querySelector("span").textContent = it.saved ? "Already downloaded" : "Download this picture";
  m.classList.remove("hidden");
  m.style.top = Math.max(4, Math.min(y, innerHeight - m.offsetHeight - 8)) + "px";
  m.style.left = Math.max(4, Math.min(x, innerWidth - m.offsetWidth - 8)) + "px";
}
$("gal-grid").addEventListener("contextmenu", function (e) {
  var tile = e.target.closest(".gal-tile");
  if (!tile) return;
  e.preventDefault();
  openPicMenu(+tile.dataset.i, false, e.clientX, e.clientY);
});
$("gal-stage").addEventListener("contextmenu", function (e) {
  if (!G || G.view < 0) return;
  e.preventDefault();
  openPicMenu(G.view, true, e.clientX, e.clientY);
});
$("picmenu").addEventListener("click", function (e) {
  var b = e.target.closest("[data-pic]");
  if (!b || b.disabled) return;
  var i = picAt;
  closeMenu();
  if (b.dataset.pic === "download") galDownload(i); else galCopy(i);
});
function galCopy(i) {
  var it = G && G.items[i];
  if (!it || it.video) return;
  if (!navigator.clipboard || !window.ClipboardItem) return toast("This window cannot copy pictures.", true);
  var url = G.id ? "/api/gallery/" + G.id + "/" + it.id + "/large" : it.large;
  fetch(url).then(function (r) {
    if (!r.ok) throw new Error("The picture did not load (" + r.status + ").");
    return r.blob();
  }).then(function (blob) {
    return blob.type === "image/png" ? blob : createImageBitmap(blob).then(function (bmp) {
      var c = document.createElement("canvas");
      c.width = bmp.width; c.height = bmp.height;
      c.getContext("2d").drawImage(bmp, 0, 0);
      return new Promise(function (ok, no) { c.toBlob(function (b) { b ? ok(b) : no(new Error("The picture could not be converted.")); }, "image/png"); });
    });
  }).then(function (png) {
    return navigator.clipboard.write([new ClipboardItem({ "image/png": png })]);
  }).then(function () { toast("Picture copied."); }).catch(fail);
}
$("gal-size").addEventListener("input", function () { galSize(+this.value); });
try { var savedSize = +localStorage.getItem(BR_SIZE); if (savedSize) $("gal-size").value = savedSize; } catch (e) {}
$("gal-grid").style.setProperty("--gal", $("gal-size").value + "px");

// ---- squares or whole pictures -----------------------------------------------
// Squares: a grid of square tiles, cropped to fill. Full: rows of whole pictures, each row as
// high as it must be to fill the width -- TrackImage's "ratio" layout. The shape of a picture is
// what the listing said, or what the browser found when it loaded; until then it counts as square.
// Extremes are clamped so a banner or a strip does not take a whole row or a whole column.
var GAL_GAP = 8, GAL_LAST = 1.35, GAL_RATIO = [0.3, 4];
function galRatio(w, h) {
  var r = w > 0 && h > 0 ? w / h : 1;
  return Math.round(Math.max(GAL_RATIO[0], Math.min(GAL_RATIO[1], r)) * 1000) / 1000;
}

// Full mode spreads a wide picture over a whole row, and the size slider enlarges every tile: the grid's
// small picture stretched that far is the pixelated one. Where the site has a screen-sized rendition
// (item.mid: cheap, unlike an original) it is laid over the small one once the tile needs it, through
// the same queue as the grid's pictures, and only for tiles near the screen (galNear).
var galSharpTimer = 0;
function galSharpenSoon() { clearTimeout(galSharpTimer); galSharpTimer = setTimeout(galSharpen, 250); }
function galSharpen() {
  if (!G) return;
  var dpr = window.devicePixelRatio || 1;
  Array.prototype.forEach.call($("gal-grid").children, function (tile) {
    var img = tile.firstElementChild, it = G.items[+tile.dataset.i];
    if (!it || !it.mid || tile.dataset.sharp || tile.classList.contains("hidden")) return;
    if (!img || img.tagName !== "IMG" || !img.complete || !img.naturalWidth) return;          // its own picture first
    if (tile.clientWidth * dpr <= img.naturalWidth * 1.2 || (it.w && it.w <= img.naturalWidth * 1.05)) return;
    tile.dataset.sharp = "1";
    var big = document.createElement("img");
    big.className = "sharp"; big.alt = ""; big.decoding = "async"; big.referrerPolicy = "no-referrer";
    big.dataset.lazy = it.mid;
    big.addEventListener("load", function () { big.classList.add("in"); });
    img.after(big);
    galNear.observe(big);
  });
}

function galLayout() {
  galSharpenSoon();
  var grid = $("gal-grid"), full = S.brFit === "full";
  grid.classList.toggle("justified", full);
  var width = Math.floor(grid.clientWidth);
  if (!full || width < 60) return;                                        // squares need no help; or the gallery is not shown
  var cols = Math.max(1, Math.round((width + GAL_GAP) / (+$("gal-size").value + GAL_GAP)));
  var target = (width - GAL_GAP * (cols - 1)) / cols;                    // a row is about as high as a cell is wide
  var row = [], sum = 0;
  function shape(t) { return parseFloat(t.dataset.ar || "1"); }        // not written back: a loaded picture says its own
  function place(last) {
    var avail = width - GAL_GAP * (row.length - 1), scale = avail / (sum * target);
    if (last) scale = Math.min(scale, GAL_LAST);                          // the last row does not stretch to fill
    var h = target * scale, w = row.map(function (t) { return Math.floor(shape(t) * h); });
    var spare = last ? 0 : Math.max(0, avail - w.reduce(function (a, b) { return a + b; }, 0));
    row.forEach(function (t, i) {                                         // the leftover pixels go to the first tiles
      t.style.width = (w[i] + (i < spare ? 1 : 0)) + "px"; t.style.height = Math.floor(h) + "px";
    });
    row = []; sum = 0;
  }
  Array.prototype.forEach.call(grid.children, function (t) {
    if (t.classList.contains("hidden")) return;
    row.push(t); sum += shape(t);
    if (sum * target + GAL_GAP * (row.length - 1) >= width) place(false);
  });
  if (row.length) place(true);
}
var galLayoutTimer = 0;
function galLayoutSoon(ms) { clearTimeout(galLayoutTimer); galLayoutTimer = setTimeout(galLayout, ms); }
new ResizeObserver(function () { if (S.brFit === "full") galLayoutSoon(60); }).observe($("gal-grid"));
// A picture that arrived tells its true shape; the rows follow a moment later, not once per picture.
$("gal-grid").addEventListener("load", function (e) {
  var img = e.target, tile = img.tagName === "IMG" && img.closest(".gal-tile");
  if (tile && !img.classList.contains("sharp")) galSharpenSoon();
  if (!tile || tile.dataset.ar || !img.naturalWidth) return;
  tile.dataset.ar = galRatio(img.naturalWidth, img.naturalHeight);
  if (S.brFit === "full") galLayoutSoon(150);
  else galSharpenSoon();
}, true);

function galFit(fit, save) {
  S.brFit = fit;
  if (save) { try { localStorage.setItem(BR_FIT, fit); } catch (e) {} }
  $$("#gal-fit [data-fit]").forEach(function (b) { b.classList.toggle("selected", b.dataset.fit === fit); });
  if (fit !== "full") {
    Array.prototype.forEach.call($("gal-grid").children, function (t) { t.style.width = t.style.height = ""; });
  }
  galLayout();
}
$("gal-fit").addEventListener("click", function (e) {
  var b = e.target.closest("[data-fit]");
  if (b && b.dataset.fit !== S.brFit) galFit(b.dataset.fit, true);
});
galFit(S.brFit, false);
$("br-edit").addEventListener("click", function () { artistAct("edit", G && G.artist); });
$("br-refresh").addEventListener("click", function () { artistAct("sync", G && G.artist); });
$("br-folder").addEventListener("click", function () { artistAct("folder", G && G.artist); });
$("gal-new").addEventListener("click", function () { browseOpen(S.brArtist, true); });
// A picture open: arrows step, Esc closes it, D downloads it and O opens its post. Ahead of the page's own keys.
document.addEventListener("keydown", function (e) {
  if (document.querySelector("dialog[open]") || $("gal-view").classList.contains("hidden")) return;
  var t = e.target, low = e.key.toLowerCase();
  var typing = (t.tagName === "INPUT" && !/^(range|checkbox)$/.test(t.type)) || t.tagName === "SELECT" || t.tagName === "TEXTAREA";
  var it = G && G.items[G.view], plain = !typing && !e.ctrlKey && !e.metaKey && !e.altKey;
  if (e.key === "Escape") closeView();
  else if (plain && e.key === "ArrowLeft") step(-1);
  else if (plain && e.key === "ArrowRight") step(1);
  else if (plain && low === "d") galDownload();
  else if (plain && low === "o" && it && it.post) api("POST", "/api/open-url", { url: it.post }).catch(fail);
  else return;
  e.preventDefault(); e.stopPropagation();
}, true);
$("br-search").addEventListener("input", renderBrowseList);
$("br-add").addEventListener("click", function () { openCard(null); });
$("br-sort").addEventListener("change", function () {
  S.brSort = brOrder(this.value);
  try { localStorage.setItem(BR_SORT, S.brSort); } catch (e) {}
  renderBrowseList();
});
$("br-count").addEventListener("change", function () {
  S.brCount = brNumber(this.value);
  try { localStorage.setItem(BR_COUNT, S.brCount); } catch (e) {}
  renderBrowseList();
});
// Right-click on an artist: the card's menu (auto-download, delete ... among it).
$("br-list").addEventListener("contextmenu", function (e) {
  var b = e.target.closest("[data-id]"), a = b && artistById(+b.dataset.id);
  if (!a) return;
  e.preventDefault();
  openMenu(a, e.clientX, e.clientY);
});
$("br-list").addEventListener("click", function (e) {
  var grp = e.target.closest("[data-grp]");
  if (grp) {                                         // a group head folds or opens its artists
    var key = grp.dataset.grp;
    if (S.brFolded[key]) delete S.brFolded[key]; else S.brFolded[key] = 1;
    try { localStorage.setItem(BR_FOLDED, JSON.stringify(S.brFolded)); } catch (e2) {}
    return renderBrowseList();
  }
  var b = e.target.closest("[data-id]");
  if (!b) return;
  S.brAt = b.dataset.site || "";
  if (+b.dataset.id !== S.brArtist) browseOpen(+b.dataset.id); else renderBrowseList();      // (the same artist in another group: the mark moves)
});
// Download: the card is synced, but only through the sources that are switched on. Another artist's
// card (from the menu) is downloaded whole.
function downloadSelected(a) {
  var open = G && G.artist && G.artist.id === a.id;
  var on = open ? (G.sources || []).filter(function (s) { return !G.hidden[s.label]; }) : [];
  if (open && !on.length) return toast("Switch on at least one source first.", true);
  var body = { artist_id: a.id, mode: "download" };
  if (open && on.length < G.sources.length) body.sources = on.map(function (s) { return s.id; });
  var b = $("br-download");
  b.disabled = true;
  api("POST", "/api/sync", body).then(function (d) {
    toast(d.added ? "Downloading " + a.name + (body.sources ? " from " + plural(on.length, "source") : "") + "…" : a.name + " is syncing or queued already.");
    lastKey = ""; return api("GET", "/api/sync");
  }).then(function (s) { S.sync = s; renderBrowseHead(); }).catch(fail).then(function () { b.disabled = false; renderBrowseHead(); });
}
$("br-download").addEventListener("click", function () { artistAct("download", G && G.artist); });
$("br-auto").addEventListener("click", function () { var a = G && G.artist; if (a) setAuto(a, !a.auto_download); });

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
    auto: a ? !!a.auto_download : false,
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
  $("btn-card-sync").querySelector("span").textContent = a ? "Save & download" : "Create & download";
  $("card-auto").checked = F.auto;
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
  var downloadNow = !!(e.submitter && e.submitter.value === "download");
  // A link typed but not left yet is checked first, so it is saved normalised.
  Promise.all(filledRows().filter(function (r) { return r.url.trim() !== r.checked; })
    .map(function (r) { return check(r); })).then(function () {
    var body = {
      name: e.target.name.value, folder: $("card-folder").value,
      sources: filledRows().map(function (r) { return r.url.trim(); }),
      layout: F.layout, dedupe: F.dedupe, master: F.dedupe === "master" ? F.master : "",
      auto_download: $("card-auto").checked, download_now: downloadNow
    };
    return F.id ? api("PUT", "/api/artists/" + F.id, body) : api("POST", "/api/artists", body);
  }).then(function (d) {
    var edited = F.id;
    $("dlg-card").close(); lastKey = "";
    // The sources changed: every gallery kept aside that lists this card is out of date; an open one opens again.
    if (edited) galDrop(edited);
    galDrop(0);
    if (G && (G.all || G.key === edited)) G.stale = true;
    load().then(function () {
      if (d.id && !edited) browseOpen(d.id);                       // a new card: its posts
      else if (G && (G.all || (edited && G.artist && G.artist.id === edited))) browseOpen(S.brArtist, true);
    });
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
  fillSecurity();
  $("set-follows").checked = st.import_follows === "1";
  $("set-scanstart").checked = st.scan_on_start !== "0";
  $("set-tilelogo").checked = st.tile_logo !== "0";
  $("set-auto").checked = st.auto_sync === "1";
  $("set-hours").value = st.auto_hours; $("set-hours").disabled = st.auto_sync !== "1";
  $("set-parallel").value = st.parallel;
  $("set-perhost").value = st.per_host;
  $("set-pace").value = st.pace_ms;
  $("set-logingap").value = st.login_gap;
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
$("set-tilelogo").addEventListener("change", function () { saveSetting({ tile_logo: this.checked ? "1" : "0" }); });
$("set-scanstart").addEventListener("change", function () { saveSetting({ scan_on_start: this.checked ? "1" : "0" }); });
$("set-follows").addEventListener("change", function () { saveSetting({ import_follows: this.checked ? "1" : "0" }); });
$("set-auto").addEventListener("change", function () { saveSetting({ auto_sync: this.checked ? "1" : "0" }); });
$("set-hours").addEventListener("change", function () { saveSetting({ auto_hours: this.value }); });
$("set-parallel").addEventListener("change", function () { saveSetting({ parallel: this.value }); });
$("set-perhost").addEventListener("change", function () { saveSetting({ per_host: this.value }); });
$("set-pace").addEventListener("change", function () { saveSetting({ pace_ms: this.value }); });
$("set-logingap").addEventListener("change", function () { saveSetting({ login_gap: this.value }); });
$("btn-settings").addEventListener("click", function () { openSettings(S.update && S.update.available ? "updates" : null); });
// ---- log files ----------------------------------------------------------------
var LG = { files: [], name: "", problems: false, timer: 0 };
function openLogs() {
  $("dlg-logs").showModal();
  api("GET", "/api/logs").then(function (d) {
    LG.files = d.files;
    if (!d.files.some(function (f) { return f.name === LG.name; })) LG.name = d.files.length ? d.files[0].name : "";
    drawLogTabs(); loadLog();
  }).catch(fail);
}
function drawLogTabs() {
  $("logs-tabs").innerHTML = LG.files.map(function (f) {
    return '<button type="button" class="chip' + (f.name === LG.name ? " selected" : "") + '" data-logfile="' + esc(f.name) + '">' + esc(f.title) + "</button>";
  }).join("");
  var f = LG.files.filter(function (x) { return x.name === LG.name; })[0];
  $("logs-about").textContent = f ? f.name + " -- " + f.about : "There is no log file yet.";
  $("logs-problems").classList.toggle("selected", LG.problems);
}
function loadLog() {
  if (!LG.name) { $("logs-text").textContent = ""; $("logs-sum").textContent = ""; return; }
  api("GET", "/api/logs/" + encodeURIComponent(LG.name) + "?problems=" + (LG.problems ? 1 : 0) + "&q=" + encodeURIComponent($("logs-q").value)).then(function (d) {
    var box = $("logs-text");
    box.innerHTML = d.lines.map(function (l) {
      var cls = /^[\d-]{10} [\d:,]{8,12} (ERROR|CRITICAL)/.test(l) ? "le" : /^[\d-]{10} [\d:,]{8,12} WARNING/.test(l) ? "lw" : "";
      return cls ? '<span class="' + cls + '">' + esc(l) + "</span>" : esc(l);
    }).join("\n");
    box.scrollTop = box.scrollHeight;                    // the newest is at the end
    $("logs-sum").textContent = d.total > d.lines.length ? "The last " + d.lines.length + " of " + d.total + " lines" : plural(d.total, "line");
  }).catch(fail);
}
$("btn-logs").addEventListener("click", openLogs);
$("logs-tabs").addEventListener("click", function (e) {
  var b = e.target.closest("[data-logfile]");
  if (!b) return;
  LG.name = b.dataset.logfile; drawLogTabs(); loadLog();
});
$("logs-problems").addEventListener("click", function () { LG.problems = !LG.problems; drawLogTabs(); loadLog(); });
$("logs-q").addEventListener("input", function () { clearTimeout(LG.timer); LG.timer = setTimeout(loadLog, 250); });
$("logs-copy").addEventListener("click", function () {
  var text = $("logs-text").textContent;
  (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(function () { toast("Copied."); }, function () {
    var r = document.createRange(); r.selectNodeContents($("logs-text")); var sel = getSelection(); sel.removeAllRanges(); sel.addRange(r);
    toast("Selected: press Ctrl+C.");
  });
});
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
  misskey: { field: "misskey", label: "Server", placeholder: "misskey.io" },
  xenforo: { field: "forum", label: "Forum", placeholder: "forum.example.com" }
};
S.accFocus = ""; S.accScroll = false; S.accHtml = ""; S.accData = null; S.accWaiting = false; S.accWant = "";
S.accAdding = false; S.accType = ""; S.accBooru = ""; S.accPre = ""; S.importBody = null; S.importAdd = false;
S.accBusy = {}; S.accError = {}; S.accChecking = {};     // per box: sending, what the site said, being asked

// What the site was asked today, as Sourcerer counted it (real requests; the budget is Sourcerer's own caution, not a limit of the site's).
function accUsage(a) { return a.usage && a.usage.budget ? " · " + a.usage.used + " of " + a.usage.budget + " requests today" : ""; }

function accState(a) {
  var expired = a.logged_in && a.state === "expired";
  return a.pending === "waiting" ? "Waiting for you to log in in the other window…"
    : expired ? "The login has run out" + (a.checked ? " (noticed " + ago(a.checked) + ")" : "") + " – log in again."
    : a.logged_in && a.rest ? "Works, but the site rests until " + restUntil(a.rest.until) + ": " + a.rest.why + accUsage(a)
    : a.logged_in ? "Logged in" + (a.user ? " as " + a.user : "") + (a.checked ? " · checked " + ago(a.checked) : "") + accUsage(a)
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
    // A forum may refuse the embedded window (403): its cookies.txt from a normal browser is the way in.
    if (a.kind === "window" && (!win || a.key.indexOf("xenforo:") === 0)) btns +='<button type="button" data-acc="import" title="Import a cookies.txt">Import&hellip;</button>';
  }
  return '<form class="accbox' + (expired ? " expired" : "") + (a.key === S.accFocus ? " focus" : "") + '" data-key="' + key + '" data-kind="' + a.kind + '">' +
    accId(a.key.split(":")[0], dot, a.group || a.label, a.group ? a.label : "", accState(a), dot === "warn" ? "warn" : expired ? "bad" : "") +
    (fields ? '<div class="acc-fields">' + fields + "</div>" : "") +
    '<div class="acc-btns">' + btns + "</div>" +
    '<p class="error">' + esc(S.accError[a.key] || "") + "</p></form>";
}

var ACC_DOT = { ok: "Works", warn: "Works, but needs attention", error: "Ran out: log in again", blank: "Not logged in", checking: "Checking…" };

// A login's site mark with its status dot in the corner (the same as Browse's chips); the bare dot for a
// type without a mark. The account types are the sites' own names.
var ACC_LOGOS = { bluesky: "bluesky", mastodon: "mastodon", misskey: "misskey", pixiv: "pixiv", fanbox: "fanbox", fantia: "fantia", patreon: "patreon", x: "x", xenforo: "xenforo", booru: "booru" };
function accMark(type, dot) {
  var d = '<i class="dot ' + dot + '" title="' + ACC_DOT[dot] + '"></i>';
  return ACC_LOGOS[type] ? '<span class="mark"><svg class="ic logo" aria-hidden="true"><use href="#l-' + ACC_LOGOS[type] + '"/></svg>' + d + "</span>" : d;
}

// The left of a row: the site's mark and status dot, the name and what is known about the login.
function accId(type, dot, name, sub, state, tone) {
  return '<div class="acc-id">' + accMark(type, dot) + '<div class="acc-text">' +
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
  if (t && t.kind === "window" && (!S.window || t.type === "xenforo")) btns +='<button type="button" data-acc="import-add" title="Import a cookies.txt">Import&hellip;</button>';
  btns += '<button type="button" data-acc="cancel">Cancel</button>';
  return '<form class="accbox adding' + (S.accFocus === "add" ? " focus" : "") + '" data-key="add" data-add="1" data-kind="' + (t ? t.kind : "") + '">' +
    '<div class="acc-id">' + accMark(t ? t.type : "", "blank") + '<div class="acc-text"><div class="acc-top"><b>Add account</b></div>' +
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
  if (!key && !S.accAdding) { S.accAdding = true; S.accType = ""; }    // opens on the add row: nothing to press first
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
  S.accPre = type === "mastodon" || type === "misskey" || type === "xenforo" ? host : "";
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
    // The standalone exe has no Python environment to rebuild, no pip for gallery-dl and no helper
    // to swap its files: those three rows are not offered there.
    S.frozen = !!d.frozen; S.updatable = !!d.updatable;
    $$('#btn-gdl, [data-repair="venv"], [data-repair="reinstall"]').forEach(function (b) {
      b.closest(".row").classList.toggle("hidden", S.frozen);
    });
    $$('[data-set="channel"]')[0].closest(".field").classList.toggle("hidden", S.frozen);   // releases only: no binary of main exists
    $("upd-hint").textContent = !S.frozen || S.updatable
      ? "An update replaces the program files, removes the ones the new version no longer has, and keeps your cards, settings and library. Sourcerer restarts by itself."
      : "Download the new version for your system. macOS: drag the app into Applications again, replacing the old one. Linux AppImage, portable zip or tar.gz: replace the one file. Close Sourcerer first; your cards, settings and library stay.";
    $("upd-log-box").classList.toggle("hidden", !d.update_log.length);
    $("upd-log").textContent = d.update_log.join("\n");
  }).catch(fail);
}

// ---- updates and repair ----------------------------------------------------

var UPD_EVERY = 60000, UPD_TRIES = 15;     // GitHub allows 60 anonymous requests an hour: one a minute, and not for ever

function showUpdate() {
  var u = S.update, has = !!(u && u.available), waiting = !!(u && u.newer && !has && !u.error);
  $("update-dot").classList.toggle("hidden", !has);
  $("update-dot-2").classList.toggle("hidden", !has);
  // The button is there as soon as a newer version is, greyed until its file is attached: a hidden
  // button looked like a missing one while the installers were still being built.
  $("btn-install").classList.toggle("hidden", !has && !waiting);
  $("btn-install").disabled = !has;
  if (!u) return;
  if (u.error) $("upd-status").textContent = u.error;
  else if (has) $("upd-status").textContent = "v" + u.version + " is available.";
  else if (!u.version) $("upd-status").textContent = "Nothing published on this channel yet.";
  else if (u.newer) {
    // Its file is still being attached -- or never will be (a failed build keeps a system's files off the release):
    // the release page is where to look.
    var st = $("upd-status"), a = document.createElement("a");
    st.textContent = "v" + u.version + " is out, its file for this system is still being built. Install unlocks by itself; or ";
    a.href = "#"; a.textContent = "open the release page";
    a.addEventListener("click", function (e) { e.preventDefault(); api("POST", "/api/open-url", { url: u.page }).catch(fail); });
    st.appendChild(a); st.appendChild(document.createTextNode("."));
  } else $("upd-status").textContent = "Up to date. Newest " + (u.channel === "beta" ? "version on the main branch" : "release") + ": v" + u.version + ".";
  $("btn-install").querySelector("span").textContent = has ? (u.manual ? "Download v" : "Install v") + u.version
    : waiting ? "Install v" + u.version : "Install";
  $("upd-notes").textContent = has ? u.notes : "";
  $("upd-notes").classList.toggle("hidden", !has || !u.notes);
}

function checkUpdate(loud) {
  $("upd-status").textContent = "Asking GitHub…";
  return api("GET", "/api/update/check?channel=" + (S.settings.channel || "stable")).then(function (u) {
    S.update = u; showUpdate();
    clearTimeout(S.updTimer);       // showUpdate runs on every state refresh; only a real answer re-arms the wait
    if (u.newer && !u.available && (S.updTries = (S.updTries || 0) + 1) <= UPD_TRIES)
      S.updTimer = setTimeout(function () { checkUpdate(false); }, UPD_EVERY);
  }).catch(function (e) {
    S.update = { error: e.message }; showUpdate();
    if (loud) fail(e);
  });
}
$("btn-check").addEventListener("click", function () { S.updTries = 0; checkUpdate(true); });
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
  if (u && u.available && u.manual) return api("POST", "/api/open-url", { url: u.url }).catch(fail);   // the exe: by hand
  if (!u || !u.available) return;      // pressing Install is the decision: no second question
  $("btn-install").disabled = true;
  $("upd-status").textContent = "Downloading v" + u.version + "…";
  api("POST", "/api/update/install", { channel: u.channel }).then(function () {
    restarting("Updating to v" + u.version, "Sourcerer restarts in a moment.");
  }).catch(function (e) { $("upd-status").textContent = e.message; fail(e); })
    .then(function () { $("btn-install").disabled = false; });
});

// The repairs that restart Sourcerer. No dialog asks first (the user's rule: no warning boxes at all).
var REPAIR_ASK = { venv: 1, reinstall: 1, restart: 1 };
$$("[data-repair]").forEach(function (b) {
  b.addEventListener("click", function () {
    var action = b.dataset.repair;
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
$("btn-accounts").addEventListener("click", function () { openAccounts(); });
$("btn-acc-check").addEventListener("click", function () {
  accCheck(((S.accData || {}).accounts || []).filter(function (a) { return a.logged_in; }).map(function (a) { return a.key; }));
});
// Only in the browser: there the page is all there is, no window to close.
$("btn-quit").addEventListener("click", function () {
  api("POST", "/api/quit").then(function () {
    $("overlay-title").textContent = "Sourcerer has stopped";
    $("overlay-text").textContent = "You can close this tab. The start file starts it again.";
    $("overlay").classList.remove("hidden");
  }).catch(fail);
});
$("btn-sync-all").addEventListener("click", function () { sync(null); });

// ---- the window's own title bar (Windows) ------------------------------------------------
// desktop.py takes the native title bar off and says so (frame: "custom"): the page's bar is then the top of the
// window -- it drags it (pywebview's drag region, on the bar itself, not on its buttons), a double-click maximizes
// -- and draws minimize, maximize and close at the right edge. Anything else keeps its native bar.
function applyFrame() {
  var custom = S.frame === "custom";
  document.documentElement.classList.toggle("frameless", custom);
  $("winctl").classList.toggle("hidden", !custom);
  $$("#toolbar, #toolbar .logo, #toolbar .brand, #toolbar #version, #toolbar .grow").forEach(function (el) {
    el.classList.toggle("pywebview-drag-region", custom);
  });
}
function windowAct(action) {
  api("POST", "/api/window", { action: action }).then(function (d) {
    $("win-max").querySelector("use").setAttribute("href", d.maximized ? "#i-copy" : "#i-square");
    $("win-max").title = $("win-max").ariaLabel = d.maximized ? "Restore" : "Maximize";
  }).catch(fail);
}
$("win-min").addEventListener("click", function () { windowAct("minimize"); });
$("win-max").addEventListener("click", function () { windowAct("maximize"); });
$("win-close").addEventListener("click", function () { windowAct("close"); });
$("toolbar").addEventListener("dblclick", function (e) {
  if (S.frame === "custom" && e.target.classList.contains("pywebview-drag-region")) windowAct("maximize");
});

// ---- the master password, and the reset ------------------------------------------------
// The server answers 401 "locked" to everything until the password was given (security.py): the page asks
// for it before it loads anything, and again whenever an answer says it is locked.

function showLock(then) {
  S.afterUnlock = then || null;
  $$("dialog[open]").forEach(function (d) { d.close(); });
  $("lock-msg").textContent = ""; $("lock-pass").value = "";
  $("lock").classList.remove("hidden");
  setTimeout(function () { $("lock-pass").focus(); }, 50);
}
function lockedNow() {
  if (!$("lock").classList.contains("hidden")) return;           // (the poll keeps asking: do not clear what is typed)
  S.lock = { enabled: true, locked: true };
  showLock(null);
}
$("lock-form").addEventListener("submit", function (e) {
  e.preventDefault();
  api("POST", "/api/unlock", { password: $("lock-pass").value }).then(function () {
    $("lock").classList.add("hidden"); $("lock-pass").value = "";
    var then = S.afterUnlock;
    S.afterUnlock = null;
    if (then) then(); else location.reload();                     // locked while it ran: what it shows is stale
  }).catch(function (err) { $("lock-msg").textContent = err.message; $("lock-pass").select(); });
});
$("lock-forgot").addEventListener("click", function () { $("lock-reset").classList.toggle("hidden"); $("lock-reset-confirm").focus(); });

function fillSecurity() {
  var on = !!(S.lock && S.lock.enabled);
  $("sec-state").textContent = on ? "A master password is set: Sourcerer asks for it every time it is opened."
    : "No master password: Sourcerer opens straight away.";
  $("sec-current").classList.toggle("hidden", !on);
  $("sec-save").textContent = on ? "Change password" : "Set password";
  $("sec-remove").classList.toggle("hidden", !on);
  $("sec-lock").classList.toggle("hidden", !on);
}
function securityDone(d, text) {
  S.lock = { enabled: d.enabled, locked: false };
  ["sec-current", "sec-new", "sec-repeat"].forEach(function (id) { $(id).value = ""; });
  fillSecurity();
  toast(text);
}
$("sec-save").addEventListener("click", function () {
  var on = !!(S.lock && S.lock.enabled), pw = $("sec-new").value;
  if (!pw) return toast("Type the new password.", true);
  if (pw !== $("sec-repeat").value) return toast("The two new passwords differ.", true);
  api("POST", "/api/security/password", { current: $("sec-current").value, new: pw })
    .then(function (d) { securityDone(d, on ? "Password changed" : "Master password set"); }).catch(fail);
});
$("sec-remove").addEventListener("click", function () {
  api("POST", "/api/security/password", { current: $("sec-current").value, new: "" })
    .then(function (d) { securityDone(d, "Master password removed"); }).catch(fail);
});
$("sec-lock").addEventListener("click", function () {
  api("POST", "/api/security/lock").then(function () { location.reload(); }).catch(fail);
});
$("reset-confirm").addEventListener("input", function () { $("reset-go").disabled = this.value !== "RESET"; });

// Starts over: the server wipes and restarts itself; what the page kept for itself goes too.
function resetEverything(word, button) {
  button.disabled = true;
  api("POST", "/api/reset", { confirm: word }).then(function (d) {
    try { Object.keys(localStorage).filter(function (k) { return k.indexOf("sourcerer.") === 0; }).forEach(function (k) { localStorage.removeItem(k); }); } catch (e) {}
    $("lock").classList.add("hidden");
    restarting("Sourcerer was reset", d.message || "It starts again as if it had just been installed.");
  }).catch(function (e) { fail(e); button.disabled = false; });
}
$("reset-go").addEventListener("click", function () { resetEverything($("reset-confirm").value, this); });
$("lock-reset-form").addEventListener("submit", function (e) {
  e.preventDefault();
  resetEverything($("lock-reset-confirm").value, e.target.querySelector("button"));
});

// TrackImage's card in the settings.
$("promo-go").addEventListener("click", function () {
  api("POST", "/api/open-url", { url: "https://github.com/Moritz-arts/TrackImage" }).catch(fail);
});

// ---- the three views: Artists | Gallery | Recommended ---------------------------------------------------------------------------
// Gallery is Browse as it was. Artists is every card as a wide row with its newest pictures (from the snapshots the looks saved and
// the library: no site is asked); a click opens the artist in the gallery. Recommended is not built yet: a page that says so.

var VIEW_KEY = "sourcerer.view", AV_SORT = "sourcerer.artists.sort";
S.view = "gallery"; S.avSort = "activity";
try {
  var v0 = localStorage.getItem(VIEW_KEY), a0 = localStorage.getItem(AV_SORT);
  if (/^(artists|gallery|recommended)$/.test(v0)) S.view = v0;
  if (/^(activity|name|favorites)$/.test(a0)) S.avSort = a0;
} catch (e) {}
$("av-sort").value = S.avSort;

// Which of the three is shown (no more than that: the start sets it before anything is loaded).
function showView(v) {
  if (!/^(artists|gallery|recommended)$/.test(v)) v = "gallery";
  S.view = v;
  document.querySelectorAll("#views button").forEach(function (b) {
    var on = b.dataset.view === v;
    b.classList.toggle("selected", on); b.setAttribute("aria-selected", on ? "true" : "false");
  });
  $("artists-view").classList.toggle("hidden", v !== "artists");
  $("recommended-view").classList.toggle("hidden", v !== "recommended");
  $("browse").classList.toggle("hidden", v !== "gallery");
  return v;
}
function setView(v) {
  v = showView(v);
  try { localStorage.setItem(VIEW_KEY, v); } catch (e) {}
  closeMenu();
  if (v === "artists") renderArtists();
  else if (v === "recommended") renderRecommended();
  else if (G) requestAnimationFrame(galLayout);          // (laid out for a width of nothing while it was hidden)
  else if (S.artists.length || S.brArtist === 0) browseOpen(S.brArtist);
}
$("views").addEventListener("click", function (e) {
  var b = e.target.closest("[data-view]");
  if (b) setView(b.dataset.view);
});

function renderRecommended() {
  var on = (S.fields || []).filter(function (f) { return f.logged_in; }).map(function (f) { return f.label; });
  $("rec-sites").textContent = on.length ? "Logged in now: " + on.join(", ") + "." : "No site is logged in yet (Manage Accounts).";
}

// One card per artist, wide, with the artist's eight newest pictures. The list is built again only when what it shows changed
// (its order, the names, the marks); the numbers beside a name are written in place, and a picture once asked for stays.
var avKey = "", avPics = {}, avWant = new Set(), avTimer = 0, AV_AT_ONCE = 4, AV_BATCH = 24, AV_PICS = 8;      // (AV_PICS: gallery.OVERVIEW)
var avQueue = [], avFlight = new Set();
var avNear = new IntersectionObserver(function (entries) {
  entries.forEach(function (e) {
    if (!e.isIntersecting) return;
    avNear.unobserve(e.target);
    var id = +e.target.dataset.id;
    if (!avPics[id]) { avWant.add(id); avPics[id] = "asking"; }
  });
  if (avWant.size && !avTimer) avTimer = setTimeout(avAsk, 60);
}, { root: $("av-list"), rootMargin: "700px" });

function avOrder() {
  var q = $("av-search").value.trim().toLowerCase();
  return S.artists.filter(function (a) { return !q || nameHit(a, q); }).sort(function (x, y) {
    if (S.avSort === "favorites" && !x.favorite !== !y.favorite) return x.favorite ? -1 : 1;
    if (S.avSort !== "name") { var tx = activityKey(x), ty = activityKey(y); if (tx !== ty) return !tx ? 1 : !ty ? -1 : tx < ty ? 1 : -1; }
    return x.name.localeCompare(y.name);
  });
}
// The artist's sites as big marks (one per site, its name on hover), and under them what is known of the artist in words.
function avSites(a) {
  var seen = {}, marks = "";
  a.sources.forEach(function (s) {
    var k = s.site || s.label;
    if (!k || seen[k]) return;
    seen[k] = 1;
    marks += '<span class="av-site" title="' + esc(k) + '">' + (siteLogo(k, s.kind, s.host) || "<span>" + esc(k) + "</span>") + "</span>";
  });
  return marks;
}
function avMeta(a) {
  var n = totalOf(a), bits = [];
  if (n) bits.push("<span>" + n + (cutOff(a) ? "+" : "") + " images</span>");
  if (a.auto_download) bits.push('<span class="cloud" title="Auto-download on">' + icon("cloud-down") + "</span>");
  if (a.favorite) bits.push('<svg class="ic star" role="img" aria-label="Favorite"><use href="#i-star"/></svg>');
  return bits.join("");
}
function avCard(a) {
  return '<article class="av-card" tabindex="0" role="button" data-id="' + a.id + '" aria-label="' + esc(a.name) + '">' +
    '<div class="av-who">' + avatarHtml(a, "lg") + '<div class="av-text"><div class="av-name" title="' + esc(a.name) + '">' + esc(a.name) +
    '</div><div class="av-sites">' + avSites(a) + '</div><div class="av-meta">' + avMeta(a) + "</div></div></div>" +
    '<div class="av-pics">' + new Array(AV_PICS + 1).join('<span class="av-pic"></span>') + "</div></article>";
}
function renderArtists() {
  if (S.view !== "artists") return;
  var list = avOrder();
  $("av-count").textContent = plural(list.length, "artist");
  var key = S.avSort + "|" + list.map(function (a) { return a.id + ":" + a.name + ":" + (a.avatar_checked || "") + ":" + a.sources.length; }).join(",");
  if (key !== avKey) {
    avKey = key;
    avNear.disconnect(); avQueue = []; avFlight.clear();
    $("av-list").innerHTML = list.length ? list.map(avCard).join("")
      : '<div class="av-empty">' + (S.artists.length ? "No artist matches." : "No artists yet: log in under Manage Accounts, or add one.") + "</div>";
    $("av-list").querySelectorAll(".av-card").forEach(function (c) {
      avNear.observe(c);
      var id = +c.dataset.id;
      if (avPics[id] && avPics[id] !== "asking") avFill(c, avPics[id]);
    });
    return;
  }
  list.forEach(function (a) {                                    // the numbers and marks, in place
    var card = $("av-list").querySelector('.av-card[data-id="' + a.id + '"]'), c = card && card.querySelector(".av-meta");
    var html = avMeta(a);
    if (c && c.innerHTML !== html) c.innerHTML = html;
  });
}
function avAsk() {
  avTimer = 0;
  var ids = Array.from(avWant).slice(0, AV_BATCH);
  ids.forEach(function (id) { avWant.delete(id); });
  if (!ids.length) return;
  api("GET", "/api/overview?ids=" + ids.join(",")).then(function (d) {
    ids.forEach(function (id) {
      avPics[id] = d[id] || [];
      var c = $("av-list").querySelector('.av-card[data-id="' + id + '"]');
      if (c) avFill(c, avPics[id]);
    });
  }).catch(function () { ids.forEach(function (id) { delete avPics[id]; }); });
  if (avWant.size) avTimer = setTimeout(avAsk, 60);
}
function avFill(card, items) {
  var box = card.querySelector(".av-pics"), tiles = "";
  for (var i = 0; i < AV_PICS; i++) {
    var it = items[i];
    tiles += it ? '<span class="av-pic" title="' + esc(it.date ? it.date.slice(0, 10) : "") + '"><img alt="" referrerpolicy="no-referrer" data-lazy="' + esc(it.thumb) + '"></span>'
      : '<span class="av-pic none">' + (!i ? "Nothing looked at yet: Refresh all (F5)" : "") + "</span>";
  }
  box.innerHTML = tiles;
  box.querySelectorAll("img[data-lazy]").forEach(function (img) { avQueue.push(img); });
  avPump();
}
// Pictures Sourcerer fetches wait in a site's polite lane and the browser opens six connections to Sourcerer: AV_AT_ONCE at a time.
function avPump() {
  while (avFlight.size < AV_AT_ONCE && avQueue.length) {
    var img = avQueue.shift();
    if (!img.isConnected || img.hasAttribute("src")) continue;
    avFlight.add(img);
    img.addEventListener("load", avDone); img.addEventListener("error", avDone);
    img.src = img.dataset.lazy;
  }
}
function avDone(e) {
  e.target.removeEventListener("load", avDone); e.target.removeEventListener("error", avDone);
  if (avFlight.delete(e.target)) avPump();
}
function avOpen(id) {
  if (!artistById(id)) return;
  setView("gallery");
  browseOpen(id);
}
$("av-search").addEventListener("input", renderArtists);
$("av-sort").addEventListener("change", function () {
  S.avSort = /^(activity|name|favorites)$/.test(this.value) ? this.value : "activity";
  try { localStorage.setItem(AV_SORT, S.avSort); } catch (e) {}
  renderArtists();
});
$("av-list").addEventListener("click", function (e) {
  var c = e.target.closest(".av-card");
  if (c) avOpen(+c.dataset.id);
});
$("av-list").addEventListener("keydown", function (e) {
  var c = e.target.closest(".av-card");
  if (c && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); avOpen(+c.dataset.id); }
});
$("av-list").addEventListener("contextmenu", function (e) {
  var c = e.target.closest(".av-card"), a = c && artistById(+c.dataset.id);
  if (!a) return;
  e.preventDefault();
  openMenu(a, e.clientX, e.clientY);
});

function start() {
  showView(S.view);
  load().then(function () {
    poll();
    checkUpdate(false);        // once per start: a dot on the settings button when there is one
  });
}
api("GET", "/api/lock").then(function (d) {
  S.lock = d;
  if (d.locked) showLock(start); else start();
}).catch(function () { start(); });
