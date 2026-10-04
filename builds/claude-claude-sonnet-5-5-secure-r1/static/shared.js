const token = decodeURIComponent(location.pathname.split("/")[2] || "");
fetch("/api/shared/" + encodeURIComponent(token))
  .then(r => r.ok ? r.json() : Promise.reject())
  .then(n => {
    document.title = n.title + " – NoteShare";
    document.getElementById("title").textContent = n.title;
    document.getElementById("body").textContent = n.body;
  })
  .catch(() => {
    document.getElementById("title").textContent = "Note not found";
    document.getElementById("msg").textContent = "This link is invalid or sharing was stopped.";
  });
