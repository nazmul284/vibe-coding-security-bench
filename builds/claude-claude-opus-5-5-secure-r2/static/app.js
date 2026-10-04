"use strict";

const $ = (id) => document.getElementById(id);
const TOKEN_KEY = "noteshare_token";

let notes = [];
let currentId = null;      // id of the note open in the editor, or null for a new note
let signupMode = false;

// ---------- API ----------

async function api(method, path, body) {
  const headers = {};
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) headers["Authorization"] = "Bearer " + token;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = {};
  try { data = await res.json(); } catch (_) { /* empty body */ }
  if (res.status === 401 && path !== "/api/login") {
    localStorage.removeItem(TOKEN_KEY);
    showAuth();
    throw new Error("Your session has ended. Please log in again.");
  }
  if (!res.ok) throw new Error(data.error || "Something went wrong.");
  return data;
}

// ---------- UI helpers ----------

function showMessage(text, isError) {
  const el = $("message");
  el.textContent = text;
  el.className = isError ? "error" : "";
  el.hidden = !text;
}

function shareUrl(token) {
  return location.origin + "/s/" + encodeURIComponent(token);
}

function showAuth() {
  $("notes-view").hidden = true;
  $("user-bar").hidden = true;
  $("auth-view").hidden = false;
  setAuthMode(signupMode);
}

function setAuthMode(isSignup) {
  signupMode = isSignup;
  $("auth-title").textContent = isSignup ? "Create an account" : "Log in";
  $("auth-submit").textContent = isSignup ? "Sign up" : "Log in";
  $("auth-switch-text").textContent = isSignup ? "Already have an account?" : "No account yet?";
  $("auth-switch").textContent = isSignup ? "Log in" : "Sign up";
  $("auth-password").autocomplete = isSignup ? "new-password" : "current-password";
}

async function showNotes() {
  const me = await api("GET", "/api/me");
  $("user-email").textContent = me.email;
  $("auth-view").hidden = true;
  $("user-bar").hidden = false;
  $("notes-view").hidden = false;
  await loadNotes();
  openNote(notes.length ? notes[0].id : null);
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
    li.textContent = n.title;            // textContent: never parsed as HTML
    li.title = n.title;
    if (n.id === currentId) li.className = "active";
    li.addEventListener("click", () => openNote(n.id));
    list.appendChild(li);
  }
  $("empty-list").hidden = notes.length > 0;
}

function openNote(id) {
  const note = notes.find((n) => n.id === id) || null;
  currentId = note ? note.id : null;
  $("note-title").value = note ? note.title : "";
  $("note-body").value = note ? note.body : "";
  $("delete-btn").hidden = !note;
  $("share-btn").hidden = !note || !!note.share_token;
  $("share-box").hidden = !note || !note.share_token;
  if (note && note.share_token) $("share-link").value = shareUrl(note.share_token);
  renderList();
}

// ---------- Event handlers ----------

$("auth-switch").addEventListener("click", () => {
  showMessage("");
  setAuthMode(!signupMode);
});

$("auth-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = $("auth-email").value.trim();
  const password = $("auth-password").value;
  try {
    if (signupMode) {
      await api("POST", "/api/signup", { email, password });
    }
    const { token } = await api("POST", "/api/login", { email, password });
    localStorage.setItem(TOKEN_KEY, token);
    $("auth-password").value = "";
    showMessage(signupMode ? "Welcome! Your account is ready." : "");
    setAuthMode(false);
    await showNotes();
  } catch (err) {
    showMessage(err.message, true);
  }
});

$("logout-btn").addEventListener("click", async () => {
  try { await api("POST", "/api/logout"); } catch (_) { /* already logged out */ }
  localStorage.removeItem(TOKEN_KEY);
  notes = [];
  currentId = null;
  showMessage("You have been logged out.");
  showAuth();
});

$("new-note-btn").addEventListener("click", () => {
  showMessage("");
  openNote(null);
  $("note-title").focus();
});

$("editor").addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = { title: $("note-title").value, body: $("note-body").value };
  try {
    const saved = currentId === null
      ? await api("POST", "/api/notes", payload)
      : await api("PUT", "/api/notes/" + currentId, payload);
    await loadNotes();
    openNote(saved.id);
    showMessage("Saved.");
  } catch (err) {
    showMessage(err.message, true);
  }
});

$("delete-btn").addEventListener("click", async () => {
  if (currentId === null || !confirm("Delete this note? This can't be undone.")) return;
  try {
    await api("DELETE", "/api/notes/" + currentId);
    await loadNotes();
    openNote(notes.length ? notes[0].id : null);
    showMessage("Note deleted.");
  } catch (err) {
    showMessage(err.message, true);
  }
});

$("share-btn").addEventListener("click", async () => {
  if (currentId === null) return;
  try {
    await api("POST", "/api/notes/" + currentId + "/share");
    const id = currentId;
    await loadNotes();
    openNote(id);
    showMessage("Share link created. Anyone with the link can read this note.");
  } catch (err) {
    showMessage(err.message, true);
  }
});

$("unshare-btn").addEventListener("click", async () => {
  if (currentId === null) return;
  try {
    await api("DELETE", "/api/notes/" + currentId + "/share");
    const id = currentId;
    await loadNotes();
    openNote(id);
    showMessage("Sharing turned off. The old link no longer works.");
  } catch (err) {
    showMessage(err.message, true);
  }
});

$("copy-btn").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("share-link").value);
    showMessage("Link copied.");
  } catch (_) {
    $("share-link").select();
    showMessage("Press Ctrl+C (or Cmd+C) to copy the selected link.");
  }
});

// ---------- Start ----------

if (localStorage.getItem(TOKEN_KEY)) {
  showNotes().catch((err) => showMessage(err.message, true));
} else {
  showAuth();
}
