"use strict";
(async function () {
  const token = decodeURIComponent(location.pathname.split("/").pop() || "");
  const titleEl = document.getElementById("title");
  try {
    const res = await fetch("/api/shared/" + encodeURIComponent(token));
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Could not load note.");
    // textContent only: note content is never interpreted as HTML.
    titleEl.textContent = data.title;
    document.title = data.title + " - NoteShare";
    document.getElementById("updated").textContent =
      "Last updated " + new Date(data.updated_at * 1000).toLocaleString();
    document.getElementById("body").textContent = data.body;
  } catch (err) {
    titleEl.textContent = err.message || "Could not load note.";
  }
})();
