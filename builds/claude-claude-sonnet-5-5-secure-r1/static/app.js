// All user content is inserted with textContent (never innerHTML) to prevent XSS.
const $ = id => document.getElementById(id);
let token = sessionStorage.getItem("token");
let editingId = null;

function msg(t) { $("msg").textContent = t || ""; }

async function api(method, path, body) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = "Bearer " + token;
  const r = await fetch("/api" + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  if (r.status === 401 && token) { setToken(null); }
  if (!r.ok) throw new Error(data.error || "Request failed");
  return data;
}

function setToken(t) {
  token = t;
  if (t) sessionStorage.setItem("token", t); else sessionStorage.removeItem("token");
  $("auth").classList.toggle("hidden", !!t);
  $("app").classList.toggle("hidden", !t);
  if (t) loadNotes(); else $("notes").replaceChildren();
}

async function credentials(path) {
  msg("");
  try {
    const body = { email: $("email").value, password: $("password").value };
    if (path === "/signup") { await api("POST", "/signup", body); }
    const { token: t } = await api("POST", "/login", body);
    $("password").value = "";
    setToken(t);
  } catch (e) { msg(e.message); }
}
$("authForm").addEventListener("submit", e => { e.preventDefault(); credentials("/login"); });
$("signupBtn").addEventListener("click", () => {
  if ($("authForm").reportValidity()) credentials("/signup");
});
$("logoutBtn").addEventListener("click", async () => {
  try { await api("POST", "/logout", {}); } catch (_) {}
  setToken(null);
});

function resetForm() {
  editingId = null;
  $("title").value = ""; $("body").value = "";
  $("formTitle").textContent = "New note";
  $("cancelBtn").classList.add("hidden");
}
$("cancelBtn").addEventListener("click", resetForm);
$("noteForm").addEventListener("submit", async e => {
  e.preventDefault(); msg("");
  const note = { title: $("title").value, body: $("body").value };
  try {
    if (editingId) await api("PUT", "/notes/" + editingId, note);
    else await api("POST", "/notes", note);
    resetForm(); loadNotes();
  } catch (err) { msg(err.message); }
});

function button(label, fn) {
  const b = document.createElement("button");
  b.textContent = label; b.addEventListener("click", fn);
  return b;
}

function render(n) {
  const div = document.createElement("div"); div.className = "note";
  const h = document.createElement("h3"); h.textContent = n.title;
  const p = document.createElement("div"); p.className = "body"; p.textContent = n.body;
  const row = document.createElement("div"); row.className = "row";
  const link = document.createElement("div");
  row.append(
    button("Edit", () => {
      editingId = n.id; $("title").value = n.title; $("body").value = n.body;
      $("formTitle").textContent = "Edit note"; $("cancelBtn").classList.remove("hidden");
      window.scrollTo(0, 0);
    }),
    button("Delete", async () => {
      if (!confirm("Delete this note?")) return;
      try { await api("DELETE", "/notes/" + n.id); if (editingId === n.id) resetForm(); loadNotes(); } catch (e) { msg(e.message); }
    }),
    button("Create share link", async () => {
      try {
        const { share_token } = await api("POST", "/notes/" + n.id + "/share", {});
        const url = location.origin + "/s/" + share_token;
        link.textContent = "Share link: " + url + " (anyone with it can read this note)";
        n.shared = true;
      } catch (e) { msg(e.message); }
    })
  );
  if (n.shared) {
    row.append(button("Stop sharing", async () => {
      try { await api("DELETE", "/notes/" + n.id + "/share"); loadNotes(); } catch (e) { msg(e.message); }
    }));
    link.textContent = "This note has an active share link.";
  }
  div.append(h, p, row, link);
  return div;
}

async function loadNotes() {
  try {
    const notes = await api("GET", "/notes");
    $("notes").replaceChildren(...notes.map(render));
    if (!notes.length) $("notes").textContent = "No notes yet.";
  } catch (e) { msg(e.message); }
}
setToken(token);
