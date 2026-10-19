// Sourcerer's window: the artists and their posts (Browse), the card dialog, settings, the activity bar.
// Plain DOM code, no framework, no build step -- the same as TrackImage.

var S = {
  artists: [], sync: {}, library: "", window: false, sep: "/", sites: [], fields: [], settings: {},
  menuFor: null, logFilter: "all", logSeen: "", update: null
};
var F = null;   // the card dialog's working copy: {id, sources, layout, dedupe, master, autoName}
var DEFAULT_GAL = 200;

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
    return "<img" + attr + ' class="' + cls + '" alt="" loading="lazy" decoding="async" src="/api/avatar/' + a.id + "?v=" +
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
  document.documentElement.classList.toggle("no-tile-logo", S.settings.tile_logo === "0");
}

// ---- artists ---------------------------------------------------------------

function artistById(id) { return S.artists.filter(function (a) { return a.id === id; })[0]; }

// When something last happened on a card: a download, else a sync, else its making.
function activityOf(a) { return a.last_activity || a.last_sync || a.created || ""; }

function renderAll() {
  $("empty").classList.toggle("hidden", S.artists.length > 0);
  $("browse").classList.toggle("blank", !S.artists.length);
  renderBrowseList(); renderBrowseHead(); renderActivity();
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

function renderActivity() {
  var s = S.sync || {}, cur = s.current, q = s.queue || [], html;
  if (cur) {
    var a = artistById(cur.artist_id) || { name: cur.name };
    var scan = cur.phase === "scan", pct = cur.total ? 100 * cur.done / cur.total : 0;
    html = '<div class="state">' + avatarHtml(a, "xs") + "<b>" + esc(cur.name) + "</b>" +
      '<span class="num">' + (cur.mode === "refresh" ? "Looking for new posts · " + cur.found + " found"
                              : scan ? "Checking sources · " + cur.found + " new"
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

var lastLoad = 0, loadTimer = 0, LOAD_GAP = 4000;
function load() {
  lastLoad = Date.now();
  return api("GET", "/api/state").then(function (d) {
    S.artists = d.artists; S.sync = d.sync; S.library = d.library; S.window = d.window;
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
    if (!G) browseOpen(S.brArtist);
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
    var key = (s.current ? s.current.artist_id : "-") + "|" + s.running + "|" + (s.queue || []).join(",") +
      "|" + (s.log || []).length + "|" + s.follows + "|" + (s.pauses || []).map(function (p) { return p.site; }).join(",");
    // A sync that ended may have saved files: a gallery kept aside would still show them as not downloaded.
    if (S.sync.finished !== s.finished) {
      Object.keys(GS).forEach(function (k) { GS[k].stale = true; });
      if (G) G.stale = true;                       // (the open one is let go of when it is left)
    }
    S.sync = s;
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
  var body = artistId ? { artist_id: artistId } : {};
  if (download) body.mode = "download";
  api("POST", "/api/sync", body).then(function () {
    lastKey = ""; return api("GET", "/api/sync");
  }).then(function (s) { S.sync = s; if (s.pauses) S.pauses = s.pauses; renderAll(); }).catch(fail);
}

function removeArtist(a) {
  if (!confirm('Delete the card "' + a.name + '"? The downloaded files stay in the library.')) return;
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
var M = { from: 0, picked: [], keep: 0, key: "", base: "", handles: [], suggested: [] };

// Two names are one when only what is no letter or digit differs: emoji, spaces, marks, width, case
// ("👹 青林檎テル" is "青林檎テル"). The base leaves out a "(handle)" at the end, which a card gets when another had its name.
function nameKey(name) { return String(name || "").normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ""); }
function baseKey(name) { return nameKey(String(name || "").replace(/\s*[(\[（【][^)\]）】]*[)\]）】]\s*$/, "")); }
// The account names in a card's links: "foo" in bsky.app/profile/foo.bsky.social, x.com/foo and mastodon.social/@foo.
// Numbers (pixiv's ids) and short ones say nothing.
function handlesOf(a) {
  var out = [];
  a.sources.forEach(function (s) {
    var last = "";
    try { last = decodeURIComponent(new URL(s.url).pathname.replace(/\/+$/, "").split("/").pop()); } catch (e) { return; }
    var h = nameKey(last.replace(/^@/, "").split("@")[0].split(".")[0]);
    if (h.length >= 3 && !/^\d+$/.test(h) && out.indexOf(h) < 0) out.push(h);
  });
  return out;
}
// How likely b is the open card's artist: 4 the same name, 3 the same but for a "(handle)" or a shared account name,
// 2 a name that is the other's account name, 1 one name inside the other. 0: nothing.
function sameness(b) {
  var kb = nameKey(b.name), hb = handlesOf(b);
  if (M.key && M.key === kb) return 4;
  if ((M.base && M.base === baseKey(b.name)) || M.handles.some(function (h) { return hb.indexOf(h) >= 0; })) return 3;
  if (hb.indexOf(M.key) >= 0 || M.handles.indexOf(kb) >= 0) return 2;
  var lo = M.key.length < kb.length ? M.key : kb, hi = lo === M.key ? kb : M.key;
  return lo.length >= 3 && lo.length * 2 >= hi.length && hi.indexOf(lo) >= 0 ? 1 : 0;
}
function openMerge(a) {
  closeMenu();
  M = { from: a.id, picked: [], keep: 0, key: nameKey(a.name), base: baseKey(a.name), handles: handlesOf(a), suggested: [] };
  M.suggested = S.artists.filter(function (b) { return b.id !== a.id; })
    .map(function (b) { return [sameness(b), b]; }).filter(function (x) { return x[0]; })
    .sort(function (x, y) { return y[0] - x[0] || x[1].name.localeCompare(y[1].name); })
    .slice(0, 10).map(function (x) { return x[1].id; });
  $("merge-title").textContent = "Merge " + a.name + " with…";
  $("merge-hint").textContent = "Tick the cards that are the same artist. They become one card: the one marked Stays keeps " +
    "every source and downloaded file, the others go away.";
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
    var on = fixed || M.picked.indexOf(a.id) >= 0;
    return '<div class="merge-row' + (on ? " on" : "") + '"><button type="button" class="br-item" data-id="' + a.id + '" aria-pressed="' + on + '">' +
      '<span class="tick">' + (on ? icon("tick") : "") + "</span>" + avatarHtml(a) +
      '<span class="br-name" title="' + esc(a.name) + '">' + esc(a.name) + "</span>" +
      '<span class="br-n">' + (a.sources.filter(function (s) { return s.supported; }).length || "") + "</span></button>" +
      (on && group ? (keeper === a.id ? '<span class="keeps">Stays</span>' : '<button type="button" class="keep" data-keep="' + a.id + '">Keep this one</button>') : "") + "</div>";
  }
  var me = artistById(M.from), others = S.artists.filter(function (a) { return a.id !== M.from && (!q || a.name.toLowerCase().indexOf(q) >= 0); });
  var sug = M.suggested.map(artistById).filter(function (a) { return a && others.indexOf(a) >= 0; });
  var rest = others.filter(function (a) { return sug.indexOf(a) < 0; }).sort(function (x, y) { return x.name.localeCompare(y.name); });
  box.innerHTML = (me ? row(me, true) : "") +
    (sug.length ? '<div class="br-group">Possibly the same artist</div>' + sug.map(function (a) { return row(a); }).join("") : "") +
    (rest.length ? (sug.length ? '<div class="br-group">All artists</div>' : "") + rest.map(function (a) { return row(a); }).join("") : "") +
    (others.length ? "" : '<p class="hint">No other artist.</p>');
  box.scrollTop = top;
  var n = M.picked.length, stay = artistById(keeper), gone = [M.from].concat(M.picked).filter(function (id) { return id !== keeper; }).map(function (id) { return (artistById(id) || {}).name; });
  $("merge-go").disabled = !n;
  $("merge-go").textContent = n ? "Merge " + plural(n + 1, "card") : "Merge";
  $("merge-sum").textContent = n ? "Stays: " + stay.name + " · goes away: " + (gone.length > 3 ? gone.slice(0, 3).join(", ") + " +" + (gone.length - 3) : gone.join(", "))
    : "Nothing ticked yet.";
}
$("merge-search").addEventListener("input", renderMerge);
$("merge-list").addEventListener("click", function (e) {
  var k = e.target.closest("[data-keep]"), b = e.target.closest("[data-id]");
  if (k) M.keep = +k.dataset.keep;
  else if (b && +b.dataset.id !== M.from) {
    var id = +b.dataset.id, i = M.picked.indexOf(id);
    if (i < 0) M.picked.push(id); else M.picked.splice(i, 1);
    if (M.keep === id) M.keep = 0;
  } else return;
  renderMerge();
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

function openFolder(a) { api("POST", "/api/open", { target: "artist", artist_id: a.id }).catch(fail); }

// ---- the artist's menu, mouse and keyboard ------------------------------------

function closeMenu() { $("menu").classList.add("hidden"); $("picmenu").classList.add("hidden"); S.menuFor = null; }
function openMenu(a, x, y) {
  var m = $("menu");
  S.menuFor = a.id;
  $("menu-auto").textContent = a.auto_download ? "Turn auto-download off" : "Turn auto-download on";
  m.classList.remove("hidden");
  m.style.top = Math.max(4, Math.min(y, innerHeight - m.offsetHeight - 8)) + "px";
  m.style.left = Math.max(4, Math.min(x, innerWidth - m.offsetWidth - 8)) + "px";
}

// The open artist's actions: from the menu, the header's buttons and the keys.
function artistAct(act, a) {
  if (!a) return;
  if (act === "edit") openCard(a);
  else if (act === "auto") setAuto(a, !a.auto_download);
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
      if (S.sync.current) api("POST", "/api/sync/cancel", { artist_id: S.sync.current.artist_id });
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
  var ids = $$("#br-list .br-item").map(function (b) { return +b.dataset.id; });
  if (!ids.length) return;
  var i = ids.indexOf(S.brArtist);
  var next = { ArrowUp: i - 1, ArrowDown: i + 1, Home: 0, End: ids.length - 1 }[key];
  S.brArtist = ids[Math.max(0, Math.min(ids.length - 1, next))];
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
    if (!dialog && t === $("br-search")) { t.value = ""; t.blur(); renderBrowseList(); }
    return;                                   // an open dialog closes itself
  }
  if (!dialog && ctrl && (k === "+" || k === "=")) { e.preventDefault(); return galSize(+$("gal-size").value + 20); }
  if (!dialog && ctrl && k === "-") { e.preventDefault(); return galSize(+$("gal-size").value - 20); }
  if (!dialog && ctrl && k === "0") { e.preventDefault(); return galSize(DEFAULT_GAL); }
  if (dialog) return;
  if ((ctrl && low === "n") || (!ctrl && !e.altKey && !typing && low === "n")) { e.preventDefault(); return openCard(null); }
  if ((ctrl && low === "f") || (k === "/" && !typing)) { e.preventDefault(); $("br-search").focus(); return $("br-search").select(); }
  if (k === "F5" || (ctrl && low === "r")) { e.preventDefault(); return sync(null); }
  if (ctrl && k === ",") { e.preventDefault(); return openSettings(); }
  if (ctrl && low === "l") { e.preventDefault(); return toggleLog(); }

  if (typing || ctrl || e.altKey || t.type === "range" || !$("gal-view").classList.contains("hidden")) return;   // (a picture open: its own keys)
  if (/^(Arrow(Up|Down)|Home|End)$/.test(k)) { e.preventDefault(); return pickArtist(k); }
  var a = artistById(S.brArtist);
  if (!a) return;
  // Enter on a button presses it; in the artist list it edits the card instead.
  if (k === "Enter" && t.tagName === "BUTTON" && !t.closest("#br-list")) return;
  var act = k === "Enter" ? "edit" : k === "Delete" ? "delete" : { a: "auto", u: "sync", d: "download", o: "folder", m: "merge" }[low];
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
var BR_FIT = "sourcerer.browse.fit", BR_SIZE = "sourcerer.browse.size";
var BR_SORT = "sourcerer.browse.sort", BR_COUNT = "sourcerer.browse.count", BR_LAST = "sourcerer.browse.last";
function brOrder(v) { return v === "activity" || v === "source" ? v : "name"; }
S.brArtist = 0; S.brFit = "square"; S.brSort = "name"; S.brCount = "sources";
try {
  S.brSort = brOrder(localStorage.getItem(BR_SORT));
  S.brCount = localStorage.getItem(BR_COUNT) === "files" ? "files" : "sources";   // (older versions also had "auto": the cloud is always shown now)
  S.brArtist = +localStorage.getItem(BR_LAST) || 0;                              // the artist that was open when Sourcerer was closed
} catch (e) {}
$("br-sort").value = S.brSort; $("br-count").value = S.brCount;
try { S.brHidden = JSON.parse(localStorage.getItem(BR_HIDDEN) || "{}"); } catch (e) { S.brHidden = {}; }
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
function siteOf(a) {
  var s = a.sources.filter(function (x) { return x.master; })[0] || a.sources.filter(function (x) { return x.supported; })[0] || a.sources[0];
  return s ? s.label : "";
}
function renderBrowseList() {
  var q = $("br-search").value.trim().toLowerCase(), bySite = S.brSort === "source", sites = {};
  var list = S.artists.filter(function (a) { return !q || a.name.toLowerCase().indexOf(q) >= 0; })
    .sort(function (x, y) {
      if (S.brSort === "activity") { var tx = activityOf(x), ty = activityOf(y); if (tx !== ty) return tx < ty ? 1 : -1; }
      if (bySite) { var sx = siteOf(x), sy = siteOf(y); if (sx !== sy) return !sx ? 1 : !sy ? -1 : sx.localeCompare(sy); }
      return x.name.localeCompare(y.name);
    });
  if (bySite) list.forEach(function (a) { var k = siteOf(a); sites[k] = (sites[k] || 0) + 1; });
  var cur = S.sync.current && S.sync.current.artist_id, queue = S.sync.queue || [];
  function count(a) {
    if (cur === a.id || queue.indexOf(a.id) >= 0) return '<i class="spin" title="' + (cur === a.id ? "Working…" : "Queued") + '"></i>';
    if (S.brCount === "files") return a.file_count || "";
    return a.sources.filter(function (s) { return s.supported; }).length || "";
  }
  var html = (q ? "" : '<button type="button" class="br-item all' + (!S.brArtist ? " selected" : "") +
    '" data-id="0">' + icon("photo") + '<span class="br-name">All artists</span></button>') +
    list.map(function (a, i) {
      var site = bySite ? siteOf(a) : "", head = bySite && (!i || siteOf(list[i - 1]) !== site) ?
        '<div class="br-group">' + (siteLogo(site) || "") + "<span>" + esc(site || "No source") + '</span><span class="num">' + sites[site] + "</span></div>" : "";
      return head + '<button type="button" class="br-item' + (S.brArtist === a.id ? " selected" : "") + '" data-id="' + a.id + '">' +
        avatarHtml(a) + '<span class="br-name" title="' + esc(a.name) + '">' + esc(a.name) + "</span>" +
        '<span class="br-n">' + count(a) + "</span>" +
        (a.auto_download ? '<span class="br-auto" title="Auto-download on">' + icon("cloud-down") + "</span>" : "") + "</button>";
    }).join("");
  if (html !== brHtml) { brHtml = html; $("br-list").innerHTML = html; }
}

var brAvatar = "";
function renderBrowseHead() {
  var a = G && G.artist, sup = !!a && a.sources.some(function (s) { return s.supported; });
  var cur = S.sync.current && a && S.sync.current.artist_id === a.id ? S.sync.current : null;
  var queued = a && (S.sync.queue || []).indexOf(a.id) >= 0;
  $("br-progress").textContent = cur ? (cur.mode === "refresh" ? "Looking for new posts…" : cur.phase === "scan" ? "Checking sources…"
    : "Downloading " + cur.done + " / " + cur.total) : queued ? "Queued" : a && a.pending ? a.pending + (a.pending >= 120 ? "+" : "") + " to download" : "";
  // The artist's picture beside the name (not for "All artists"); replaced only when it changed, or it would blink on every poll.
  var av = a ? avatarHtml(a) : "";
  if (av !== brAvatar) { brAvatar = av; $("gal-avatar").innerHTML = av; }
  ["br-download", "br-edit", "br-refresh", "br-folder", "br-auto"].forEach(function (id) { $(id).classList.toggle("hidden", !a); });
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
        downloading: {}, loading: true, newPosts: 0, polling: false };
  $("gal-title").textContent = a ? a.name : "All artists";
  $("gal-grid").innerHTML = ""; $("gal-sources").innerHTML = "";
  $("gal-body").scrollTop = 0;
  $("gal-end").textContent = "Asking the sites…";
  closeView();
  renderBrowseList(); renderBrowseHead();
  if (!id && !S.artists.length) { G.loading = false; galHead(); $("gal-end").textContent = "No cards yet: create a card first."; return; }
  var g = G;
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
  $("gal-end").textContent = g.done ? (g.items.length ? plural(g.items.length, "picture") + " – that is all" : "Nothing found.") : "";
  galWatch(); galLayout();
  $("gal-body").scrollTop = g.scroll || 0;
  if (!g.id) return;                            // still waiting for its opening: the answer shows it
  galPoll(g);
  if (!g.busy && !g.done && galEndNear()) moreGallery();
}

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
    g.busy = false; g.done = d.done; g.sources = d.sources;
    g.loading = d.loading; g.newPosts = d.new_posts;
    var start = g.items.length;
    g.items = g.items.concat(d.items);
    if (g !== G) return;                        // kept aside: shown from memory when it comes back
    $("gal-grid").insertAdjacentHTML("beforeend", d.items.map(function (it, k) { return tileHtml(it, start + k); }).join(""));
    galWatch(); galLayout();
    galSources(d.sources); galHead();
    if (g.loading) galPoll(g);
    $("gal-end").textContent = !g.done ? "" : g.items.length ? plural(g.items.length, "picture") + " – that is all" : "Nothing found.";
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
var SITE_LOGOS = { Bluesky: "bluesky", Mastodon: "mastodon", Misskey: "misskey", Pixiv: "pixiv", Patreon: "patreon", X: "x", XenForo: "xenforo", Booru: "booru" };
function siteLogo(label) {
  return SITE_LOGOS[label] ? '<svg class="ic logo" role="img" aria-label="' + esc(label) + '"><use href="#l-' + SITE_LOGOS[label] + '"/></svg>' : "";
}

function tileHtml(it, i) {
  var proxied = /^\/api\/gallery\//.test(it.thumb || "");
  var picture = it.thumb
    ? '<img loading="lazy" decoding="async" referrerpolicy="no-referrer" ' + (proxied ? "data-lazy" : "src") + '="' + esc(it.thumb) + '" alt="">'
    : '<span class="gal-noimg">' + icon(it.video ? "play" : "photo") + "</span>";
  var who = G.all ? it.artist + " · " + it.source : it.source;
  var name = G.all ? '<span class="gal-name">' + esc(it.artist) + "</span>" : "";      // "All artists": whose picture it is, beside the mark
  return '<button type="button" class="gal-tile' + (G.hidden[it.source] ? " hidden" : "") + '" data-i="' + i +
    (it.w && it.h ? '" data-ar="' + galRatio(it.w, it.h) : "") +
    '" data-src="' + esc(it.source) + '" title="' + esc(who + (it.posted ? " · " + it.posted.slice(0, 10) : "")) + '">' +
    picture + (it.video && it.thumb ? '<span class="gal-play">' + icon("play") + "</span>" : "") +
    '<span class="gal-tag">' + (siteLogo(it.source) || '<span class="gal-site">' + esc(it.source) + "</span>") + name + "</span>" +
    (it.saved ? '<span class="gal-saved" title="Downloaded">' + icon("tick") + "</span>" : "") + "</button>";
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
    var ready = !busy && !bad.length && of.every(function (s) { return s.checked || s.state === "done"; });
    var news = of.reduce(function (n, s) { return n + (s.new || 0); }, 0);
    var tip = bad.length ? label + ": " + bad[0].error : off ? "Show " + label
      : busy ? label + ": asking the site…" : "Hide " + label + (G.all ? " (" + plural(of.length, "source") + ")" : "") +
        (news ? " · " + plural(news, "new post") : "");
    // A spinner while the site is asked, green when it answered, orange when it did not.
    var state = busy ? '<i class="spin"></i>' : '<i class="dot ' + (bad.length ? "warn" : ready ? "ok" : "blank") + '"></i>';
    var mark = siteLogo(label);
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
  $("gal-source").innerHTML = siteLogo(it.source) || '<b>' + esc(it.source) + "</b>";
  $("gal-source").title = it.source;
  $("gal-who").innerHTML = avatarHtml(artistById(it.artist_id) || { name: it.artist }) + "<span>" + esc(it.artist) + "</span>";
  $("gal-info").textContent = [it.posted ? new Date(it.posted).toLocaleString() : "",
    it.w ? it.w + " × " + it.h : "", (i + 1) + " / " + G.items.length + (G.done ? "" : "+")].filter(Boolean).join(" · ");
  galDlState(it);
  $("gal-view").classList.remove("hidden");
  // Near the end of what is listed: the next page, before it is needed.
  if (i > G.items.length - 8) moreGallery();
}

// The viewer's Download button: green "Downloaded" once the picture is in the library.
function galDlState(it) {
  var b = $("gal-download"), busy = !!G.downloading[it.id];
  b.disabled = it.saved || busy;
  b.classList.toggle("done", !!it.saved);
  b.querySelector("svg use").setAttribute("href", it.saved ? "#i-tick" : "#i-download");
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
  if (!b && G && !Z.moved && outsidePicture(e)) closeView();          // the dark around the picture closes it too
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
$("gal-stage").addEventListener("dblclick", function (e) {
  if (!stageImage() || e.target.tagName !== "IMG") return;
  if (Z.s > 1) zoomReset(); else zoomAt(2.5, e.clientX, e.clientY);
});
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

function galDownload(i) {
  var g = G, it;
  if (i === undefined) i = G && G.view;               // the viewer's button and key: the picture open
  it = g && g.items[i];
  if (!it || it.saved || g.downloading[it.id]) return;
  g.downloading[it.id] = true;
  if (g.view === i) galDlState(it);
  api("POST", "/api/gallery/download", { gallery: g.id, item: it.id }).then(function (d) {
    delete g.downloading[it.id];
    g.items[i] = d.item;
    if (g === G) {                               // (left meanwhile: it shows the file saved when it comes back)
      var tile = document.querySelector('#gal-grid .gal-tile[data-i="' + i + '"]');
      if (tile) { tile.outerHTML = tileHtml(d.item, i); galWatch(); galLayout(); }
      if (g.view === i) viewItem(i);
    }
    toast(d.kept ? "Saved in " + d.item.artist + "'s folder" : "Not saved: the same picture is already in the folder");
    load();
  }).catch(function (err) {
    fail(err);
    delete g.downloading[it.id];
    if (g === G && g.view === i) galDlState(it);
  });
}
// Right-click on a picture: the grid's offers to download it, the viewer's also to copy it (as a PNG, the one
// format every program takes from the clipboard). The copy is fetched through Sourcerer -- a CDN's picture
// would taint the canvas -- like the viewer's own fallback.
var picAt = -1;
function openPicMenu(i, viewer, x, y) {
  var it = G && G.items[i], m = $("picmenu");
  if (!it) return;
  picAt = i;
  m.querySelector('[data-pic="copy"]').classList.toggle("hidden", !viewer || !!it.video);
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
  S.brCount = this.value === "files" ? "files" : "sources";
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
  var b = e.target.closest("[data-id]");
  if (b && +b.dataset.id !== S.brArtist) browseOpen(+b.dataset.id);
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
  $("set-follows").checked = st.import_follows === "1";
  $("set-tilelogo").checked = st.tile_logo !== "0";
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
$("set-tilelogo").addEventListener("change", function () { saveSetting({ tile_logo: this.checked ? "1" : "0" }); });
$("set-follows").addEventListener("change", function () { saveSetting({ import_follows: this.checked ? "1" : "0" }); });
$("set-auto").addEventListener("change", function () { saveSetting({ auto_sync: this.checked ? "1" : "0" }); });
$("set-hours").addEventListener("change", function () { saveSetting({ auto_hours: this.value }); });
$("set-parallel").addEventListener("change", function () { saveSetting({ parallel: this.value }); });
$("set-perhost").addEventListener("change", function () { saveSetting({ per_host: this.value }); });
$("set-pace").addEventListener("change", function () { saveSetting({ pace_ms: this.value }); });
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
var ACC_LOGOS = { bluesky: "bluesky", mastodon: "mastodon", pixiv: "pixiv", patreon: "patreon", x: "x", xenforo: "xenforo", booru: "booru" };
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

load().then(function () {
  poll();
  checkUpdate(false);        // once per start: a dot on the settings button when there is one
});
