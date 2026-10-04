(function () {
  var token = decodeURIComponent(location.pathname.replace(/^\/s\//, ""));
  var titleEl = document.getElementById("title");
  var bodyEl = document.getElementById("body");
  var metaEl = document.getElementById("meta");
  fetch("/api/shared/" + encodeURIComponent(token))
    .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
    .then(function (res) {
      if (!res.ok) {
        titleEl.textContent = "Note not found";
        bodyEl.textContent = "This link is invalid or the note is no longer shared.";
        return;
      }
      titleEl.textContent = res.data.title;
      bodyEl.textContent = res.data.body;
      document.title = res.data.title + " - NoteShare";
      metaEl.textContent = "Last updated " + new Date(res.data.updated_at * 1000).toLocaleString();
    })
    .catch(function () {
      titleEl.textContent = "Could not load note";
    });
})();
