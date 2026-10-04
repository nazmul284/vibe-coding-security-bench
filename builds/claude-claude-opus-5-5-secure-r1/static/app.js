// NoteShare web UI. Talks to the same JSON API a phone app would use.
// All user content is inserted with textContent, never innerHTML.

const $ = (id) => document.getElementById(id);
const TOKEN_KEY = "noteshare_token";

let token = localStorage.getItem(TOKEN_KEY);
let signupMode = false;
let notes = [];
let currentId = null;

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (token) opts.headers["Authorization"] = "Bearer " + token;
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (res.status === 401 && token) {
    logoutLocal();
    throw new Error("Your session expired. Please log in again.");
  }
  if (!res.ok) throw new Error((data && data.error) || "Something went wrong.");
  return data;
}

// ---------------------------------------------------------------- auth

function showAuth() {
  $("notes-view").hidden = true;
  $("userbar").hidden = true;
  $("auth-view").hidden = false;
  setAuthMode(signupMode);
}

function setAuthMode(signup) {
  signupMode = signup;
  $("auth-title").textContent = signup ? "Create an account" : "Log in";
  $("auth-submit").textContent = signup ? "Sign up" : "Log in";
  $("auth-switch-text").textContent = signup ? "Already have an account?" : "No account yet?";
  $("auth-switch").textContent = signup ? "Log in" : "Sign up";
  $("auth-password").autocomplete = signup ? "new-password" : "current-password";
  $("auth-error").textContent = "";
}

$("auth-switch").addEventListener("click", () => setAuthMode(!signupMode));

$("auth-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = $("auth-email").value.trim();
  const password = $("auth-password").value;
  $("auth-error").textContent = "";
  $("auth-submit").disabled = true;
  try {
    if (signupMode) await api("POST", "/api/signup", { email, password });
    const data = await api("POST", "/api/login", { email, password });
    token = data.token;
    localStorage.setItem(TOKEN_KEY, token);
    $("auth-password").value = "";
    await showNotes();
  } catch (err) {
    $("auth-error").textContent = err.message;
  } finally {
    $("auth-submit").disabled = false;
  }
});

function logoutLocal() {
  token = null;
  localStorage.removeItem(TOKEN_KEY);
  notes = [];
  currentId = null;
  showAuth();
}

$("logout-btn").addEventListener("click", async () => {
  try { await api("POST", "/api/logout"); } catch { /* ignore */ }
  logoutLocal();
});

// ---------------------------------------------------------------- notes

async function showNotes() {
  const me = await api("GET", "/api/me");
  $("user-email").textContent = me.email;
  $("auth-view").hidden = true;
  $("userbar").hidden = false;
  $("notes-view").hidden = false;
  await loadNotes();
  if (notes.length) openNote(notes[0].id); else newNote();
}

async function loadNotes() {
  notes = await api("GET", "/api/notes");
  renderList();
}

function renderList() {
  const list = $("note-list");
  list.replaceChildren();
  for (const n of notes) {
    const li = document.createElement("li");
    li.textContent = n.title;
    if (n.id === currentId) li.classList.add("active");
    li.addEventListener("click", () => openNote(n.id));
    list.appendChild(li);
  }
  $("empty-list").hidden = notes.length > 0;
}

function openNote(id) {
  const n = notes.find((x) => x.id === id);
  if (!n) return newNote();
  currentId = id;
  $("note-title").value = n.title;
  $("note-body").value = n.body;
  $("delete-btn").hidden = false;
  $("share-btn").hidden = false;
  $("note-error").textContent = "";
  $("save-status").textContent = "";
  showShare(n.share_token);
  renderList();
}

function newNote() {
  currentId = null;
  $("note-title").value = "";
  $("note-body").value = "";
  $("delete-btn").hidden = true;
  $("share-btn").hidden = true;
  $("note-error").textContent = "";
  $("save-status").textContent = "";
  showShare(null);
  renderList();
  $("note-title").focus();
}

function showShare(shareToken) {
  $("share-box").hidden = !shareToken;
  $("share-btn").textContent = shareToken ? "Shared" : "Share";
  if (shareToken) $("share-url").value = location.origin + "/s/" + shareToken;
}

$("new-note-btn").addEventListener("click", newNote);

$("note-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("note-error").textContent = "";
  const body = { title: $("note-title").value, body: $("note-body").value };
  try {
    const saved = currentId === null
      ? await api("POST", "/api/notes", body)
      : await api("PUT", "/api/notes/" + currentId, body);
    await loadNotes();
    openNote(saved.id);
    $("save-status").textContent = "Saved.";
  } catch (err) {
    $("note-error").textContent = err.message;
  }
});

$("delete-btn").addEventListener("click", async () => {
  if (currentId === null || !confirm("Delete this note? This can't be undone.")) return;
  try {
    await api("DELETE", "/api/notes/" + currentId);
    await loadNotes();
    if (notes.length) openNote(notes[0].id); else newNote();
  } catch (err) {
    $("note-error").textContent = err.message;
  }
});

$("share-btn").addEventListener("click", async () => {
  if (currentId === null) return;
  try {
    const data = await api("POST", "/api/notes/" + currentId + "/share");
    const n = notes.find((x) => x.id === currentId);
    if (n) n.share_token = data.share_token;
    showShare(data.share_token);
  } catch (err) {
    $("note-error").textContent = err.message;
  }
});

$("unshare-btn").addEventListener("click", async () => {
  if (currentId === null || !confirm("Stop sharing? The link will stop working.")) return;
  try {
    await api("DELETE", "/api/notes/" + currentId + "/share");
    const n = notes.find((x) => x.id === currentId);
    if (n) n.share_token = null;
    showShare(null);
  } catch (err) {
    $("note-error").textContent = err.message;
  }
});

$("copy-btn").addEventListener("click", async () => {
  const input = $("share-url");
  try {
    await navigator.clipboard.writeText(input.value);
    $("copy-btn").textContent = "Copied!";
    setTimeout(() => ($("copy-btn").textContent = "Copy"), 1500);
  } catch {
    input.select();
  }
});

// ---------------------------------------------------------------- start

if (token) showNotes().catch(() => logoutLocal()); else showAuth();
