"use strict";

const $ = (id) => document.getElementById(id);
const state = { token: localStorage.getItem("token"), notes: [], current: null, signup: false };

function showMessage(text, isError = true) {
  const el = $("message");
  el.textContent = text;
  el.className = isError ? "error" : "ok";
  el.hidden = !text;
}

async function api(method, path, body) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (state.token) headers["Authorization"] = "Bearer " + state.token;
  const res = await fetch(path, {
    method, headers, body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = null;
  try { data = await res.json(); } catch (e) { /* no body */ }
  if (res.status === 401 && state.token) {
    setToken(null);
    showView("auth");
  }
  if (!res.ok) throw new Error((data && data.error) || "Something went wrong");
  return data;
}

function setToken(token) {
  state.token = token;
  if (token) localStorage.setItem("token", token);
  else localStorage.removeItem("token");
}

function showView(name) {
  for (const v of ["auth", "notes", "shared"]) $(v + "-view").hidden = v !== name;
  $("userbar").hidden = name !== "notes";
}

// ---------- Log in / sign up ----------

function setAuthMode(signup) {
  state.signup = signup;
  $("auth-title").textContent = signup ? "Create an account" : "Log in";
  $("auth-submit").textContent = signup ? "Sign up" : "Log in";
  $("auth-switch-text").textContent = signup ? "Already have an account?" : "No account yet?";
  $("auth-switch").textContent = signup ? "Log in" : "Sign up";
  $("auth-password").autocomplete = signup ? "new-password" : "current-password";
  showMessage("");
}

$("auth-switch").addEventListener("click", () => setAuthMode(!state.signup));

$("auth-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = $("auth-email").value.trim();
  const password = $("auth-password").value;
  try {
    if (state.signup) await api("POST", "/api/signup", { email, password });
    const { token } = await api("POST", "/api/login", { email, password });
    setToken(token);
    $("auth-password").value = "";
    showMessage("");
    await openNotes();
  } catch (err) {
    showMessage(err.message);
  }
});

$("logout-btn").addEventListener("click", async () => {
  try { await api("POST", "/api/logout"); } catch (e) { /* ignore */ }
  setToken(null);
  state.notes = [];
  state.current = null;
  setAuthMode(false);
  showView("auth");
});

// ---------- Notes ----------

async function openNotes() {
  const me = await api("GET", "/api/me");
  $("user-email").textContent = me.email;
  showView("notes");
  await loadNotes();
}

async function loadNotes() {
  state.notes = await api("GET", "/api/notes");
  renderList();
}

function renderList() {
  const list = $("note-list");
  list.replaceChildren();
  for (const note of state.notes) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.className = "note-item" + (state.current && state.current.id === note.id ? " active" : "");
    btn.textContent = note.title;
    if (note.shared) {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = "shared";
      btn.append(" ", tag);
    }
    btn.addEventListener("click", () => selectNote(note));
    li.append(btn);
    list.append(li);
  }
  $("no-notes").hidden = state.notes.length > 0;
}

function selectNote(note) {
  state.current = note;
  $("editor").hidden = false;
  $("editor-empty").hidden = true;
  $("note-title").value = note ? note.title : "";
  $("note-body").value = note ? note.body : "";
  $("share-btn").hidden = !note;
  $("delete-btn").hidden = !note;
  renderShare();
  renderList();
  showMessage("");
  $("note-title").focus();
}

function renderShare() {
  const note = state.current;
  const shared = note && note.share_token;
  $("share-box").hidden = !shared;
  if (shared) $("share-link").value = location.origin + "/s/" + note.share_token;
}

function closeEditor() {
  state.current = null;
  $("editor").hidden = true;
  $("editor-empty").hidden = false;
  renderList();
}

$("new-note-btn").addEventListener("click", () => selectNote(null));

$("note-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = { title: $("note-title").value, body: $("note-body").value };
  try {
    const saved = state.current
      ? await api("PUT", "/api/notes/" + state.current.id, payload)
      : await api("POST", "/api/notes", payload);
    state.current = saved;
    await loadNotes();
    selectNote(saved);
    showMessage("Saved.", false);
  } catch (err) {
    showMessage(err.message);
  }
});

$("delete-btn").addEventListener("click", async () => {
  if (!state.current || !confirm("Delete this note? This cannot be undone.")) return;
  try {
    await api("DELETE", "/api/notes/" + state.current.id);
    closeEditor();
    await loadNotes();
    showMessage("Note deleted.", false);
  } catch (err) {
    showMessage(err.message);
  }
});

$("share-btn").addEventListener("click", async () => {
  if (!state.current) return;
  try {
    const { share_token } = await api("POST", "/api/notes/" + state.current.id + "/share");
    state.current.share_token = share_token;
    state.current.shared = true;
    await loadNotes();
    renderShare();
    showMessage("Share link ready. Send it to a friend.", false);
  } catch (err) {
    showMessage(err.message);
  }
});

$("unshare-btn").addEventListener("click", async () => {
  if (!state.current) return;
  try {
    await api("DELETE", "/api/notes/" + state.current.id + "/share");
    state.current.share_token = null;
    state.current.shared = false;
    await loadNotes();
    renderShare();
    showMessage("Sharing stopped. The old link no longer works.", false);
  } catch (err) {
    showMessage(err.message);
  }
});

$("copy-btn").addEventListener("click", async () => {
  const input = $("share-link");
  try {
    await navigator.clipboard.writeText(input.value);
    showMessage("Link copied.", false);
  } catch (e) {
    input.select();
  }
});

// ---------- Shared note page ----------

async function openShared(shareToken) {
  showView("shared");
  try {
    const note = await api("GET", "/api/shared/" + encodeURIComponent(shareToken));
    $("shared-title").textContent = note.title;
    $("shared-body").textContent = note.body;
    document.title = note.title + " - NoteShare";
  } catch (err) {
    $("shared-title").textContent = "Note not found";
    $("shared-body").textContent = "This link may have been turned off or the note was deleted.";
  }
}

// ---------- Start ----------

(async function start() {
  const m = location.pathname.match(/^\/s\/([A-Za-z0-9_-]+)$/);
  if (m) {
    const t = state.token;
    state.token = null; // shared page never sends your login
    await openShared(m[1]);
    state.token = t;
    return;
  }
  setAuthMode(false);
  if (state.token) {
    try { await openNotes(); return; } catch (e) { /* fall through to login */ }
  }
  showView("auth");
})();
