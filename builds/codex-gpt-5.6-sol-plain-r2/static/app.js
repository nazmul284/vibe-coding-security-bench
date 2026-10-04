const $ = (selector) => document.querySelector(selector);
const state = { token: localStorage.getItem("noteshare_token"), notes: [], selected: null, signup: false };

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(path, { ...options, headers });
  let data = null;
  if (response.status !== 204) {
    try { data = await response.json(); } catch { data = { error: "Unexpected server response" }; }
  }
  if (!response.ok) throw new Error(data?.error || "Something went wrong");
  return data;
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("show"), 2800);
}

function show(id) {
  ["#auth", "#workspace", "#shared"].forEach((item) => $(item).classList.add("hidden"));
  $(id).classList.remove("hidden");
  $("#logout").classList.toggle("hidden", id !== "#workspace");
}

async function loadNotes() {
  try {
    state.notes = await api("/api/notes");
    show("#workspace");
    renderNotes();
  } catch (error) {
    state.token = null;
    localStorage.removeItem("noteshare_token");
    show("#auth");
  }
}

function renderNotes() {
  const list = $("#notes-list");
  list.replaceChildren();
  $("#empty").classList.toggle("hidden", state.notes.length > 0);
  for (const note of state.notes) {
    const button = document.createElement("button");
    button.className = `note-card${state.selected === note.id ? " active" : ""}`;
    const title = document.createElement("strong");
    title.textContent = note.title;
    const preview = document.createElement("span");
    preview.textContent = note.body.replace(/\s+/g, " ").slice(0, 70) || "Empty note";
    const date = document.createElement("small");
    date.textContent = new Date(note.updated_at).toLocaleDateString();
    button.append(title, preview, date);
    button.addEventListener("click", () => selectNote(note.id));
    list.append(button);
  }
}

function selectNote(id) {
  const note = state.notes.find((item) => item.id === id);
  if (!note) return;
  state.selected = id;
  $("#note-title").value = note.title;
  $("#note-body").value = note.body;
  $("#save-state").textContent = `Updated ${new Date(note.updated_at).toLocaleString()}`;
  $("#welcome").classList.add("hidden");
  $("#editor").classList.remove("hidden");
  renderNotes();
}

function newNote() {
  state.selected = null;
  $("#note-title").value = "";
  $("#note-body").value = "";
  $("#save-state").textContent = "New note";
  $("#welcome").classList.add("hidden");
  $("#editor").classList.remove("hidden");
  renderNotes();
  $("#note-title").focus();
}

$("#auth-switch").addEventListener("click", () => {
  state.signup = !state.signup;
  $("#auth-title").textContent = state.signup ? "Create your account" : "Welcome back";
  $("#auth-submit").textContent = state.signup ? "Sign up" : "Log in";
  $("#auth-switch").firstChild.textContent = state.signup ? "Already have an account? " : "New here? ";
  $("#auth-switch button").textContent = state.signup ? "Log in" : "Create an account";
  $("#password").autocomplete = state.signup ? "new-password" : "current-password";
  $("#auth-error").textContent = "";
});

$("#auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = JSON.stringify({ email: $("#email").value, password: $("#password").value });
  $("#auth-error").textContent = "";
  try {
    if (state.signup) await api("/api/signup", { method: "POST", body });
    const result = await api("/api/login", { method: "POST", body });
    state.token = result.token;
    localStorage.setItem("noteshare_token", state.token);
    await loadNotes();
  } catch (error) { $("#auth-error").textContent = error.message; }
});

$("#editor").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = JSON.stringify({ title: $("#note-title").value, body: $("#note-body").value });
  try {
    let note;
    if (state.selected) note = await api(`/api/notes/${state.selected}`, { method: "PUT", body: payload });
    else note = await api("/api/notes", { method: "POST", body: payload });
    const index = state.notes.findIndex((item) => item.id === note.id);
    if (index >= 0) state.notes[index] = note; else state.notes.unshift(note);
    state.notes.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    selectNote(note.id);
    showToast("Note saved");
  } catch (error) { showToast(error.message); }
});

$("#delete-note").addEventListener("click", async () => {
  if (!state.selected || !confirm("Delete this note permanently?")) return;
  try {
    await api(`/api/notes/${state.selected}`, { method: "DELETE" });
    state.notes = state.notes.filter((item) => item.id !== state.selected);
    state.selected = null;
    $("#editor").classList.add("hidden");
    $("#welcome").classList.remove("hidden");
    renderNotes();
    showToast("Note deleted");
  } catch (error) { showToast(error.message); }
});

$("#share-note").addEventListener("click", async () => {
  if (!state.selected) return showToast("Save the note before sharing");
  try {
    const result = await api(`/api/notes/${state.selected}/share`, { method: "POST" });
    const url = `${location.origin}/share/${result.share_token}`;
    await navigator.clipboard.writeText(url);
    showToast("Share link copied to your clipboard");
  } catch (error) { showToast(error.message); }
});

$("#new-note").addEventListener("click", newNote);
$("#logout").addEventListener("click", () => {
  state.token = null; state.notes = []; state.selected = null;
  localStorage.removeItem("noteshare_token");
  $("#auth-form").reset();
  show("#auth");
});

async function initialize() {
  const sharedMatch = location.pathname.match(/^\/share\/([A-Za-z0-9_-]+)$/);
  if (sharedMatch) {
    try {
      const note = await api(`/api/shared/${sharedMatch[1]}`);
      $("#shared-title").textContent = note.title;
      $("#shared-body").textContent = note.body;
      $("#shared-date").textContent = `Last updated ${new Date(note.updated_at).toLocaleString()}`;
      show("#shared");
    } catch (error) {
      $("#shared-title").textContent = "This note isn't available";
      $("#shared-body").textContent = error.message;
      show("#shared");
    }
  } else if (state.token) await loadNotes();
  else show("#auth");
}

initialize();
