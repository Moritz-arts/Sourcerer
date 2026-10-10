// Sourcerer's window: artist cards, their sources, and the sync status line.
// Plain DOM code, no framework, no build step -- the same as TrackImage.

var S = { artists: [], sync: {}, library: "", window: false, editing: null };

function $(id) { return document.getElementById(id); }

function esc(text) {
  return String(text == null ? "" : text).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
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

function when(iso) {
  // SQLite's datetime('now') is UTC without a zone mark; say so, then show local time.
  if (!iso) return "never";
  var d = new Date(iso.replace(" ", "T") + (/[zZ+]/.test(iso.slice(10)) ? "" : "Z"));
  return isNaN(d) ? iso : d.toLocaleString();
}

// ---- rendering -------------------------------------------------------------

function render() {
  $("empty").classList.toggle("hidden", S.artists.length > 0);
  $("cards").innerHTML = S.artists.map(cardHtml).join("");
  renderSync();
}

function cardHtml(a) {
  var running = !!S.sync.running;
  var srcs = a.sources.map(function (s) {
    var meta = s.kind === "unsupported"
      ? "not supported yet"
      : s.file_count + " files · checked " + when(s.last_checked);
    return '<li class="src"><div class="line">' +
      '<span class="tag ' + esc(s.kind) + '">' + esc(s.label) + "</span>" +
      '<a href="' + esc(s.url) + '" target="_blank" title="' + esc(s.url) + '">' + esc(s.url) + "</a></div>" +
      '<div class="meta">' + esc(meta) + "</div>" +
      (s.last_error ? '<div class="err">' + esc(s.last_error) + "</div>" : "") + "</li>";
  }).join("");
  return '<div class="card" data-id="' + a.id + '">' +
    '<div class="card-head"><h3>' + esc(a.name) + '</h3><span class="count">' + a.file_count + " files</span></div>" +
    (a.notes ? '<p class="notes">' + esc(a.notes) + "</p>" : "") +
    '<ul class="sources">' + (srcs || '<li class="muted">No sources yet.</li>') + "</ul>" +
    '<div class="card-actions">' +
    '<button data-act="sync"' + (running ? " disabled" : "") + ">Sync</button>" +
    '<button data-act="folder">Folder</button>' +
    '<span class="grow"></span><button data-act="edit">Edit</button></div></div>';
}

function renderSync() {
  var s = S.sync || {};
  $("spinner").classList.toggle("hidden", !s.running);
  $("btn-sync-all").disabled = !!s.running || !S.artists.length;
  var text = s.message || "Idle";
  if (s.running) text += "  —  " + s.new + " new, " + s.duplicates + " duplicates, " + s.errors + " errors";
  $("status-text").textContent = text;
  if ($("dlg-log").open) $("log").textContent = (s.log || []).join("\n");
}

// ---- loading and polling ---------------------------------------------------

function load() {
  return api("GET", "/api/state").then(function (d) {
    S.artists = d.artists; S.sync = d.sync; S.library = d.library; S.window = d.window;
    $("version").textContent = "v" + d.version;
    $("sites").textContent = d.sites.join(", ");
    render();
  });
}

// A poll is a delay: quick while a sync runs, slow when nothing does.
var wasRunning = false;
function poll() {
  api("GET", "/api/sync").then(function (s) {
    S.sync = s;
    if (wasRunning && !s.running) load();       // counts and errors changed
    else if (s.running !== wasRunning) render();
    else renderSync();
    wasRunning = !!s.running;
  }).catch(function () {}).then(function () {
    setTimeout(poll, S.sync.running ? 1000 : 4000);
  });
}

function startSync(artistId) {
  api("POST", "/api/sync", artistId ? { artist_id: artistId } : {})
    .then(function () {
      S.sync = { running: true, new: 0, duplicates: 0, errors: 0, message: "Starting...", log: S.sync.log };
      wasRunning = true; render();
    })
    .catch(function (e) { $("status-text").textContent = e.message; });
}

// ---- artist dialog ---------------------------------------------------------

function openArtist(artist) {
  var f = $("form-artist");
  S.editing = artist ? artist.id : null;
  $("artist-title").textContent = artist ? "Edit " + artist.name : "New artist";
  f.name.value = artist ? artist.name : "";
  f.notes.value = artist ? artist.notes : "";
  f.sources.value = artist ? artist.sources.map(function (s) { return s.url; }).join("\n") : "";
  $("btn-delete").classList.toggle("hidden", !artist);
  $("artist-error").textContent = "";
  $("dlg-artist").showModal();
  f.name.focus();
}

$("form-artist").addEventListener("submit", function (e) {
  if (e.submitter && e.submitter.value === "cancel") return;
  e.preventDefault();
  var f = e.target;
  var body = {
    name: f.name.value, notes: f.notes.value,
    sources: f.sources.value.split(/\s+/).filter(Boolean)
  };
  var req = S.editing ? api("PUT", "/api/artists/" + S.editing, body) : api("POST", "/api/artists", body);
  req.then(function () { $("dlg-artist").close(); return load(); })
     .catch(function (err) { $("artist-error").textContent = err.message; });
});

$("btn-delete").addEventListener("click", function () {
  var a = S.artists.filter(function (x) { return x.id === S.editing; })[0];
  if (!a || !confirm('Delete "' + a.name + '"? The downloaded files stay in your library.')) return;
  api("DELETE", "/api/artists/" + a.id).then(function () { $("dlg-artist").close(); return load(); });
});

// ---- settings --------------------------------------------------------------

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
  if (e.submitter && e.submitter.value === "cancel") return;
  e.preventDefault();
  api("PUT", "/api/settings", { library: e.target.library.value })
    .then(function () { $("dlg-settings").close(); return load(); })
    .catch(function (err) { $("settings-error").textContent = err.message; });
});

// ---- the rest --------------------------------------------------------------

document.addEventListener("click", function (e) {
  var btn = e.target.closest("[data-act]");
  if (!btn) return;
  var card = btn.closest(".card");
  var artist = card && S.artists.filter(function (a) { return a.id === +card.dataset.id; })[0];
  var act = btn.dataset.act;
  if (act === "add") openArtist(null);
  else if (act === "edit") openArtist(artist);
  else if (act === "sync") startSync(artist.id);
  else if (act === "folder") api("POST", "/api/open-folder", { artist_id: artist.id });
});

$("btn-add").addEventListener("click", function () { openArtist(null); });
$("btn-sync-all").addEventListener("click", function () { startSync(null); });
$("btn-folder").addEventListener("click", function () { api("POST", "/api/open-folder", {}); });
$("btn-log").addEventListener("click", function () {
  $("log").textContent = (S.sync.log || []).join("\n") || "Nothing yet.";
  $("dlg-log").showModal();
});
$("btn-log-close").addEventListener("click", function () { $("dlg-log").close(); });

load().then(function () { wasRunning = !!S.sync.running; poll(); });
