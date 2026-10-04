(async function () {
  const token = decodeURIComponent(location.pathname.split("/").pop() || "");
  const title = document.getElementById("title");
  try {
    const res = await fetch("/api/shared/" + encodeURIComponent(token));
    if (!res.ok) throw new Error();
    const note = await res.json();
    title.textContent = note.title;
    document.title = note.title + " - NoteShare";
    document.getElementById("meta").textContent =
      "Last updated " + new Date(note.updated_at * 1000).toLocaleString();
    document.getElementById("body").textContent = note.body;
  } catch {
    title.textContent = "This note isn't available.";
    document.getElementById("meta").textContent =
      "The link may be wrong, or the owner stopped sharing it.";
  }
})();
