"use strict";

const $ = (id) => document.getElementById(id);
const state = { token: sessionStorage.getItem("noteshare_token"), notes: [], selected: null, mode: "login" };

function showToast(message) {
  $("toast").textContent = message;
  $("toast").classList.remove("hidden");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => $("toast").classList.add("hidden"), 3000);
}

async function api(path, options = {}, auth = true) {
  const headers = { ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  if (auth && state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(path, { ...options, headers });
  let data = null;
  if (response.status !== 204) data = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401 && auth) logout();
    throw new Error(data?.error || "Something went wrong");
  }
  return data;
}

function setAuthMode(mode) {
  state.mode = mode;
  const signup = mode === "signup";
  $("login-tab").classList.toggle("active", !signup);
  $("signup-tab").classList.toggle("active", signup);
  $("auth-submit").textContent = signup ? "Create account" : "Log in";
  $("password-hint").classList.toggle("hidden", !signup);
  $("password").autocomplete = signup ? "new-password" : "current-password";
}

function showApp() {
  $("auth-view").classList.add("hidden");
  $("shared-view").classList.add("hidden");
  $("notes-view").classList.remove("hidden");
  $("logout").classList.remove("hidden");
}

function logout() {
  state.token = null;
  state.notes = [];
  state.selected = null;
  sessionStorage.removeItem("noteshare_token");
  $("notes-view").classList.add("hidden");
  $("logout").classList.add("hidden");
  $("auth-view").classList.remove("hidden");
}

function renderNotes() {
  const list = $("notes-list");
  list.replaceChildren();
  if (!state.notes.length) {
    const empty = document.createElement("p");
    empty.className = "no-notes";
    empty.textContent = "No notes yet. Create your first one.";
    list.append(empty);
    return;
  }
  for (const note of state.notes) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `note-item${state.selected === note.id ? " active" : ""}`;
    const title = document.createElement("strong");
    title.textContent = note.title;
    const preview = document.createElement("span");
    preview.textContent = note.body || "Empty note";
    button.append(title, preview);
    button.addEventListener("click", () => selectNote(note.id));
    list.append(button);
  }
}

function selectNote(id) {
  const note = state.notes.find((item) => item.id === id);
  if (!note) return;
  state.selected = id;
  $("empty-state").classList.add("hidden");
  $("note-form").classList.remove("hidden");
  $("note-title").value = note.title;
  $("note-body").value = note.body;
  $("delete-note").classList.remove("hidden");
  $("share-note").classList.remove("hidden");
  $("save-status").textContent = note.shared ? "Shared link active" : "Private";
  renderNotes();
}

async function loadNotes() {
  state.notes = await api("/api/notes");
  renderNotes();
  if (state.selected && state.notes.some((n) => n.id === state.selected)) selectNote(state.selected);
}

function newNote() {
  state.selected = "new";
  $("empty-state").classList.add("hidden");
  $("note-form").classList.remove("hidden");
  $("note-title").value = "";
  $("note-body").value = "";
  $("save-status").textContent = "New private note";
  $("delete-note").classList.add("hidden");
  $("share-note").classList.add("hidden");
  renderNotes();
  $("note-title").focus();
}

$("login-tab").addEventListener("click", () => setAuthMode("login"));
$("signup-tab").addEventListener("click", () => setAuthMode("signup"));
$("logout").addEventListener("click", logout);
$("new-note").addEventListener("click", newNote);

$("auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("auth-submit");
  button.disabled = true;
  try {
    const credentials = JSON.stringify({ email: $("email").value, password: $("password").value });
    if (state.mode === "signup") {
      await api("/api/signup", { method: "POST", body: credentials }, false);
      showToast("Account created. You can log in now.");
      setAuthMode("login");
    } else {
      const result = await api("/api/login", { method: "POST", body: credentials }, false);
      state.token = result.token;
      sessionStorage.setItem("noteshare_token", result.token);
      $("password").value = "";
      showApp();
      await loadNotes();
    }
  } catch (error) { showToast(error.message); }
  finally { button.disabled = false; }
});

$("note-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = JSON.stringify({ title: $("note-title").value, body: $("note-body").value });
  try {
    if (state.selected === "new") {
      const note = await api("/api/notes", { method: "POST", body: payload });
      state.selected = note.id;
    } else {
      await api(`/api/notes/${state.selected}`, { method: "PUT", body: payload });
    }
    $("delete-note").classList.remove("hidden");
    $("share-note").classList.remove("hidden");
    await loadNotes();
    showToast("Note saved");
  } catch (error) { showToast(error.message); }
});

$("delete-note").addEventListener("click", async () => {
  if (!Number.isInteger(state.selected) || !confirm("Delete this note permanently?")) return;
  try {
    await api(`/api/notes/${state.selected}`, { method: "DELETE" });
    state.selected = null;
    $("note-form").classList.add("hidden");
    $("empty-state").classList.remove("hidden");
    await loadNotes();
    showToast("Note deleted");
  } catch (error) { showToast(error.message); }
});

$("share-note").addEventListener("click", async () => {
  if (!Number.isInteger(state.selected)) return;
  try {
    const result = await api(`/api/notes/${state.selected}/share`, { method: "POST" });
    $("share-url").value = `${location.origin}/?share=${encodeURIComponent(result.share_token)}`;
    $("share-dialog").classList.remove("hidden");
    await loadNotes();
  } catch (error) { showToast(error.message); }
});

$("copy-link").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText($("share-url").value); showToast("Link copied"); }
  catch (_) { $("share-url").select(); showToast("Select the link and copy it"); }
});
$("close-dialog").addEventListener("click", () => $("share-dialog").classList.add("hidden"));

async function boot() {
  const share = new URLSearchParams(location.search).get("share");
  if (share) {
    $("auth-view").classList.add("hidden");
    try {
      const note = await api(`/api/shared/${encodeURIComponent(share)}`, {}, false);
      $("shared-title").textContent = note.title;
      $("shared-body").textContent = note.body;
      $("shared-date").textContent = `Updated ${new Date(note.updated_at).toLocaleString()}`;
      $("shared-view").classList.remove("hidden");
    } catch (error) { $("shared-view").innerHTML = "<h1>Shared note not found</h1><p class='subtle'>This link may be invalid or replaced.</p>"; $("shared-view").classList.remove("hidden"); }
    return;
  }
  if (state.token) {
    showApp();
    try { await loadNotes(); } catch (_) { /* api() returns to login for expired tokens */ }
  }
}

boot();
