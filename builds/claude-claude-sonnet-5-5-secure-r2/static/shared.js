const token = location.pathname.split("/").pop();
fetch("/api/shared/" + encodeURIComponent(token))
  .then((r) => r.ok ? r.json() : Promise.reject())
  .then((n) => {
    document.title = n.title + " - NoteShare";
    document.getElementById("title").textContent = n.title;
    document.getElementById("body").textContent = n.body;
  })
  .catch(() => {
    document.getElementById("msg").textContent =
      "This note doesn't exist or is no longer shared.";
  });
