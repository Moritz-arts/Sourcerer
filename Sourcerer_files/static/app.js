// Sourcerer's window: artist cards, the card dialog, the activity bar.
// Plain DOM code, no framework, no build step -- the same as TrackImage.

var S = { artists: [], sync: {}, library: "", window: false, sep: "/", sites: [], menuFor: null };
var F = null;   // the card dialog's working copy: {id, sources, layout, dedupe, master}

function $(id) { return document.getElementById(id); }
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

// ---- small formatters ------------------------------------------------------

function utc(iso) {
  // SQLite's datetime('now') is UTC without a zone mark.
  return iso ? new Date(iso.replace(" ", "T") + (/[zZ+]/.test(iso.slice(10)) ? "" : "Z")) : null;
}
function ago(iso) {
  var d = utc(iso);
  if (!d || isNaN(d)) return "noch nie";
  var s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return "gerade eben";
  if (s < 3600) return "vor " + Math.floor(s / 60) + " Min.";
  if (s < 86400) return "vor " + Math.floor(s / 3600) + " Std.";
  var days = Math.floor(s / 86400);
  return days === 1 ? "gestern" : "vor " + days + " Tagen";
}
function bytes(n) {
  if (!n) return "";
  var units = ["B", "KB", "MB", "GB"], i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return (i ? n.toFixed(1).replace(".", ",") : n) + " " + units[i];
}
function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }

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
function avatarHtml(name) {
  var c = colours(name || "?");
  return '<div class="avatar" style="background:' + c[0] + ";color:" + c[1] + '">' + esc(initials(name || "?")) + "</div>";
}

// ---- cards -----------------------------------------------------------------

function visibleArtists() {
  var q = $("search").value.trim().toLowerCase();
  var list = S.artists.filter(function (a) { return !q || a.name.toLowerCase().indexOf(q) >= 0; });
  var by = $("sort").value;
  list.sort(function (a, b) {
    if (by === "files") return b.file_count - a.file_count;
    if (by === "activity") {
      var ta = a.last_activity || a.last_sync || "", tb = b.last_activity || b.last_sync || "";
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
  $("cards").innerHTML = list.map(cardHtml).join("");
  renderActivity();
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
  var html = '<div class="card' + (cur ? " busy" : "") + '" data-id="' + a.id + '">' +
    '<div class="card-head">' + avatarHtml(a.name) +
    '<div class="who"><p class="card-name" title="' + esc(a.name) + '">' + esc(a.name) + "</p>" +
    '<p class="card-path" title="' + esc(a.folder) + '">' + esc(a.folder) + "</p></div></div>" +
    '<div class="thumbs">' + thumbs + "</div>";

  if (cur) {
    var text, pct = 0;
    if (cur.phase === "scan") text = "Prüfe Quellen · " + cur.found + " neu gefunden";
    else {
      text = (cur.first ? "Erst-Sync: " : "") + "lade " + cur.done + " / " + cur.total;
      pct = cur.total ? Math.round(100 * cur.done / cur.total) : 100;
    }
    html += '<div class="progress-text">' + esc(text) + "</div>" +
      '<div class="bar' + (cur.phase === "scan" ? " indeterminate" : "") + '"><div style="width:' + pct + '%"></div></div>' +
      '<div class="card-foot"><span class="badges small muted">' +
      (cur.phase === "scan" ? "" : esc(cur.duplicates
        ? plural(cur.duplicates, "Duplikat", "Duplikate") + " übersprungen"
        : plural(cur.new, "neue Datei", "neue Dateien"))) +
      '</span><button class="mini" data-act="cancel">Abbrechen</button></div>';
  } else {
    var badges = "";
    var supported = a.sources.filter(function (s) { return s.supported; }).length;
    var broken = a.sources.filter(function (s) { return s.last_error; }).length;
    if (queued) badges += '<span class="badge accent">wartet</span>';
    else {
      if (a.last_new) badges += '<span class="badge accent">+' + a.last_new + " neu</span>";
      if (a.last_failed) badges += '<span class="badge warning">' + a.last_failed + " fehlgeschlagen</span>";
      if (broken) badges += '<span class="badge warning" title="' + esc(a.sources.filter(function (s) { return s.last_error; })
        .map(function (s) { return s.label + ": " + s.last_error; }).join("\n")) + '">' + plural(broken, "Quelle", "Quellen") + " mit Fehler</span>";
      if (!supported) badges += '<span class="badge plain">keine ladbare Quelle</span>';
    }
    html += '<div class="stats"><span>' + plural(a.file_count, "Datei", "Dateien") + "</span><span>" +
      esc(ago(a.last_activity || a.last_sync)) + "</span></div>" +
      '<div class="card-foot"><span class="badges">' + badges + "</span>" +
      (queued
        ? '<button class="mini" data-act="cancel">Abbrechen</button>'
        : '<button class="mini" data-act="sync" aria-label="Aktualisieren" title="Aktualisieren"' + (supported ? "" : " disabled") + ">" + icon("refresh") + "</button>" +
          '<button class="mini" data-act="folder" aria-label="Ordner öffnen" title="Ordner öffnen">' + icon("folder") + "</button>" +
          '<button class="mini" data-act="more" aria-label="Mehr" title="Mehr">' + icon("dots") + "</button>") +
      "</div>";
  }
  return html + "</div>";
}

function renderActivity() {
  var s = S.sync || {}, cur = s.current;
  var text = cur && cur.file
    ? cur.name + " · " + cur.file + (cur.size ? " · " + bytes(cur.size) : "")
    : cur ? cur.name + " · Quellen werden geprüft" : (s.message || "Bereit");
  $("activity-text").textContent = text;
  var waiting = (s.queue || []).length;
  $("queue-text").textContent = waiting ? "Warteschlange: " + plural(waiting, "Karte", "Karten") : "";
  $("btn-sync-all").disabled = !S.artists.length;
  if (!$("logpanel").classList.contains("hidden")) showLog();
}

function showLog() {
  var pre = $("log"), atEnd = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 4;
  pre.textContent = (S.sync.log || []).join("\n") || "Noch nichts passiert.";
  if (atEnd) pre.scrollTop = pre.scrollHeight;
}

// ---- loading and polling ---------------------------------------------------

function load() {
  return api("GET", "/api/state").then(function (d) {
    S.artists = d.artists; S.sync = d.sync; S.library = d.library; S.window = d.window;
    S.sep = d.sep; S.sites = d.sites;
    $("version").textContent = "v" + d.version;
    render();
  });
}

// A poll is a delay: quick while a sync runs, slow when nothing does. The
// cards are reloaded whenever the artist being synced changes, so counts,
// badges and thumbnails follow without reloading on every tick.
var lastKey = "";
function poll() {
  api("GET", "/api/sync").then(function (s) {
    var key = (s.current ? s.current.artist_id : "-") + "|" + s.running + "|" + (s.queue || []).join(",");
    S.sync = s;
    if (key !== lastKey) { lastKey = key; return load(); }
    if (s.current) render(); else renderActivity();
  }).catch(function () {}).then(function () {
    setTimeout(poll, S.sync.running ? 700 : 4000);
  });
}

function sync(artistId) {
  api("POST", "/api/sync", artistId ? { artist_id: artistId } : {}).then(function () {
    lastKey = ""; return api("GET", "/api/sync");
  }).then(function (s) { S.sync = s; render(); });
}

// ---- card actions and the "more" menu --------------------------------------

function artistById(id) { return S.artists.filter(function (a) { return a.id === id; })[0]; }

function closeMenu() { $("menu").classList.add("hidden"); S.menuFor = null; }

document.addEventListener("click", function (e) {
  if (!e.target.closest("#menu") && !e.target.closest("[data-act=more]")) closeMenu();
  var btn = e.target.closest("[data-act]");
  if (!btn) return;
  var card = btn.closest(".card");
  var a = card && artistById(+card.dataset.id);
  switch (btn.dataset.act) {
    case "add": openCard(null); break;
    case "sync": sync(a.id); break;
    case "folder": api("POST", "/api/open-folder", { artist_id: a.id }); break;
    case "cancel": api("POST", "/api/sync/cancel", { artist_id: a.id }).then(function () { lastKey = ""; }); break;
    case "more":
      var r = btn.getBoundingClientRect(), m = $("menu");
      S.menuFor = a.id;
      m.classList.remove("hidden");
      m.style.top = Math.min(r.bottom + 4, innerHeight - m.offsetHeight - 8) + "px";
      m.style.left = Math.max(8, r.right - m.offsetWidth) + "px";
      break;
  }
});

$("menu").addEventListener("click", function (e) {
  var btn = e.target.closest("[data-menu]");
  if (!btn) return;
  var a = artistById(S.menuFor);
  closeMenu();
  if (!a) return;
  if (btn.dataset.menu === "edit") openCard(a);
  else if (btn.dataset.menu === "folder") api("POST", "/api/open-folder", { artist_id: a.id });
  else if (btn.dataset.menu === "delete" &&
           confirm('Karte „' + a.name + '“ löschen? Die geladenen Dateien bleiben in der Bibliothek.')) {
    api("DELETE", "/api/artists/" + a.id).then(load);
  }
});

// ---- the card dialog -------------------------------------------------------

var DEDUPE_HINT = {
  keep_all: "Jede Quelle behält ihre eigene Kopie, auch wenn es das Bild schon von woanders gibt.",
  best: "Gibt es dasselbe Bild in mehreren Quellen, wird nur die Version mit der höchsten Auflösung gespeichert.",
  master: "Liegt ein Bild in {m} vor, wird nur diese Version gespeichert. Bilder, die es nur woanders gibt, werden einmal gespeichert, in bester Qualität."
};

function openCard(a) {
  F = {
    id: a ? a.id : null,
    sources: a ? a.sources.map(function (s) { return { url: s.url, label: s.label, supported: s.supported }; }) : [],
    layout: a ? a.layout : "together",
    dedupe: a ? a.dedupe : "best",
    master: a ? (a.sources.filter(function (s) { return s.master; })[0] || {}).url || "" : ""
  };
  var f = $("form-card");
  f.name.value = a ? a.name : "";
  $("card-title").textContent = a ? "Karte bearbeiten" : "Neue Künstlerkarte";
  $("btn-card-save").textContent = a ? "Speichern" : "Anlegen";
  $("sync-now").checked = !a;
  $("src-input").value = "";
  $("card-error").textContent = "";
  $("sites").textContent = S.sites.join(", ");
  renderForm();
  $("dlg-card").showModal();
  f.name.focus();
}

function renderForm() {
  var name = $("form-card").name.value.trim();
  $("card-avatar").outerHTML = avatarHtml(name || "?").replace('class="avatar"', 'id="card-avatar" class="avatar"');

  var master = F.dedupe === "master" ? F.master : "";
  $("src-list").innerHTML = F.sources.length ? F.sources.map(function (s, i) {
    var isMaster = master && s.url === master;
    var mark = s.supported
      ? '<button type="button" data-src="master" data-i="' + i + '" title="' + (isMaster ? "Master-Source" : "Als Master-Source wählen") + '">' +
        (isMaster ? icon("crown", "crown") : icon("point", "point")) + "</button>"
      : '<button type="button" disabled>' + icon("point", "point") + "</button>";
    return '<div class="srcrow">' + mark +
      '<span class="site">' + esc(s.label) + "</span>" +
      '<span class="url" title="' + esc(s.url) + '">' + esc(s.url.replace(/^https?:\/\/(www\.)?/, "")) + "</span>" +
      (s.supported ? '<span class="badge plain">öffentlich</span>' : '<span class="badge warning">noch nicht unterstützt</span>') +
      '<button type="button" data-src="remove" data-i="' + i + '" title="Entfernen">' + icon("x") + "</button></div>";
  }).join("") : '<div class="srcempty">Noch keine Quelle – füge unten einen Profil-Link ein.</div>';

  // Layout examples with the real name and sites.
  var n = name || "Name", sep = S.sep;
  var labels = F.sources.filter(function (s) { return s.supported; }).map(function (s) { return s.label; })
    .filter(function (l, i, all) { return all.indexOf(l) === i; });
  if (!labels.length) labels = ["Mastodon", "Bluesky"];
  $("layout-together").textContent = n + sep;
  $("layout-per-source").textContent = labels.slice(0, 2).map(function (l) { return n + sep + l + sep; }).join(" · ") + " …";
  document.querySelectorAll("[data-layout]").forEach(function (b) { b.classList.toggle("selected", b.dataset.layout === F.layout); });

  document.querySelectorAll("[data-dedupe]").forEach(function (b) { b.classList.toggle("selected", b.dataset.dedupe === F.dedupe); });
  var options = F.sources.filter(function (s) { return s.supported; });
  $("master-row").classList.toggle("hidden", F.dedupe !== "master");
  $("master-select").innerHTML = options.length
    ? options.map(function (s) {
        return '<option value="' + esc(s.url) + '"' + (s.url === F.master ? " selected" : "") + ">" +
          esc(s.label + " – " + s.url.replace(/^https?:\/\/(www\.)?/, "")) + "</option>";
      }).join("")
    : '<option value="">Erst eine ladbare Quelle hinzufügen</option>';
  if (F.dedupe === "master" && options.length && !options.some(function (s) { return s.url === F.master; })) {
    F.master = options[0].url;
  }
  var masterLabel = (options.filter(function (s) { return s.url === F.master; })[0] || {}).label || "der Master-Source";
  $("dedupe-hint").textContent = DEDUPE_HINT[F.dedupe].replace("{m}", masterLabel);
}

function addSource() {
  var input = $("src-input"), parts = input.value.split(/\s+/).filter(Boolean);
  if (!parts.length) return;
  input.value = "";
  parts.reduce(function (p, url) {
    return p.then(function () { return api("POST", "/api/detect", { url: url }); }).then(function (d) {
      if (!F.sources.some(function (s) { return s.url === d.url; })) {
        F.sources.push({ url: d.url, label: d.label, supported: d.supported });
      }
    });
  }, Promise.resolve()).then(renderForm).catch(function (e) { $("card-error").textContent = e.message; });
}

$("btn-src-add").addEventListener("click", addSource);
$("src-input").addEventListener("keydown", function (e) {
  if (e.key === "Enter") { e.preventDefault(); addSource(); }
});
$("src-input").addEventListener("paste", function () { setTimeout(addSource, 0); });
$("form-card").name.addEventListener("input", renderForm);

$("src-list").addEventListener("click", function (e) {
  var btn = e.target.closest("[data-src]");
  if (!btn) return;
  var s = F.sources[+btn.dataset.i];
  if (btn.dataset.src === "remove") F.sources.splice(+btn.dataset.i, 1);
  else { F.master = s.url; F.dedupe = "master"; }
  renderForm();
});
document.querySelectorAll("[data-layout]").forEach(function (b) {
  b.addEventListener("click", function () { F.layout = b.dataset.layout; renderForm(); });
});
document.querySelectorAll("[data-dedupe]").forEach(function (b) {
  b.addEventListener("click", function () { F.dedupe = b.dataset.dedupe; renderForm(); });
});
$("master-select").addEventListener("change", function () { F.master = this.value; renderForm(); });

$("form-card").addEventListener("submit", function (e) {
  e.preventDefault();
  if ($("src-input").value.trim()) { addSource(); return; }   // Enter in a half-typed link
  var body = {
    name: e.target.name.value, sources: F.sources.map(function (s) { return s.url; }),
    layout: F.layout, dedupe: F.dedupe, master: F.dedupe === "master" ? F.master : "",
    sync_now: $("sync-now").checked
  };
  (F.id ? api("PUT", "/api/artists/" + F.id, body) : api("POST", "/api/artists", body))
    .then(function () { $("dlg-card").close(); lastKey = ""; return load(); })
    .catch(function (err) { $("card-error").textContent = err.message; });
});

// ---- settings and the rest -------------------------------------------------

$("btn-settings").addEventListener("click", function () {
  $("form-settings").library.value = S.library;
  $("settings-error").textContent = "";
  $("btn-browse").classList.toggle("hidden", !S.window);
  $("dlg-settings").showModal();
});
$("btn-browse").addEventListener("click", function () {
  api("POST", "/api/pick-folder").then(function (d) {
    if (d.path) $("form-settings").library.value = d.path;
  }).catch(function (e) { $("settings-error").textContent = e.message; });
});
$("form-settings").addEventListener("submit", function (e) {
  e.preventDefault();
  api("PUT", "/api/settings", { library: e.target.library.value })
    .then(function () { $("dlg-settings").close(); return load(); })
    .catch(function (err) { $("settings-error").textContent = err.message; });
});

document.querySelectorAll("[data-close]").forEach(function (b) {
  b.addEventListener("click", function () { b.closest("dialog").close(); });
});
$("btn-add").addEventListener("click", function () { openCard(null); });
$("btn-sync-all").addEventListener("click", function () { sync(null); });
$("search").addEventListener("input", render);
$("sort").addEventListener("change", render);
$("btn-log").addEventListener("click", function () {
  var open = $("logpanel").classList.toggle("hidden") === false;
  $("btn-log").classList.toggle("open", open);
  if (open) { showLog(); $("log").scrollTop = $("log").scrollHeight; }
});
document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeMenu(); });

load().then(poll);
