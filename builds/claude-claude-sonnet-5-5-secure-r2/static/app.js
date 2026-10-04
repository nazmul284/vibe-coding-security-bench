// All note text is inserted with textContent / .value only (never innerHTML),
// so note contents can't run as script. The login token lives in sessionStorage
// and is cleared when the tab closes.
const $ = (id) => document.getElementById(id);
let token = sessionStorage.getItem("token");
let notes = [];
let current = null; // note being edited, or null for a new one

function say(text, ok) {
  $("msg").textContent = text || "";
  $("msg").className = ok ? "ok" : "";
}

async function api(method, path, data) {
  const headers = {};
  if (data !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = "Bearer " + token;
  const res = await fetch("/api" + path, {
    method, headers, body: data === undefined ? undefined : JSON.stringify(data),
  });
  const json = await res.json().catch(() => ({}));
  if (res.status === 401 && token) { logout(); }
  if (!res.ok) throw new Error(json.error || "Something went wrong.");
  return json;
}

function show() {
  $("auth").hidden = !!token;
  $("app").hidden = !token;
  $("logout").hidden = !token;
}

function logout() {
  if (token) api("POST", "/logout").catch(() => {});
  token = null; notes = []; current = null;
  sessionStorage.removeItem("token");
  show(); say("");
}

async function authenticate(signup) {
  const email = $("email").value, password = $("password").value;
  say("");
  try {
    if (signup) await api("POST", "/signup", { email, password });
    const r = await api("POST", "/login", { email, password });
    token = r.token;
    sessionStorage.setItem("token", token);
    $("password").value = "";
    show(); await loadNotes(); edit(null);
  } catch (e) { say(e.message); }
}

async function loadNotes() {
  notes = await api("GET", "/notes");
  const list = $("note-list");
  list.replaceChildren();
  for (const n of notes) {
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.textContent = n.title;
    if (current && current.id === n.id) b.className = "active";
    b.onclick = () => edit(n);
    li.appendChild(b);
    list.appendChild(li);
  }
}

function edit(note) {
  current = note;
  $("title").value = note ? note.title : "";
  $("body").value = note ? note.body : "";
  $("delete").hidden = !note;
  $("share").hidden = !note || !!note.share_token;
  $("unshare").hidden = !note || !note.share_token;
  $("share-info").hidden = !note || !note.share_token;
  $("share-url").value = note && note.share_token
    ? location.origin + "/s/" + note.share_token : "";
  say("");
  loadNotes().catch(() => {});
}

$("auth-form").onsubmit = (e) => { e.preventDefault(); authenticate(false); };
$("signup-btn").onclick = () => {
  if ($("auth-form").reportValidity()) authenticate(true);
};
$("logout").onclick = logout;
$("new-note").onclick = () => edit(null);

$("editor").onsubmit = async (e) => {
  e.preventDefault();
  const data = { title: $("title").value, body: $("body").value };
  try {
    const saved = current
      ? await api("PUT", "/notes/" + current.id, data)
      : await api("POST", "/notes", data);
    edit(saved); say("Saved.", true);
  } catch (err) { say(err.message); }
};

$("delete").onclick = async () => {
  if (!current || !confirm("Delete this note permanently?")) return;
  try { await api("DELETE", "/notes/" + current.id); edit(null); say("Deleted.", true); }
  catch (err) { say(err.message); }
};

$("share").onclick = async () => {
  try {
    const r = await api("POST", "/notes/" + current.id + "/share");
    edit({ ...current, share_token: r.share_token });
  } catch (err) { say(err.message); }
};

$("unshare").onclick = async () => {
  try {
    await api("DELETE", "/notes/" + current.id + "/share");
    edit({ ...current, share_token: null });
  } catch (err) { say(err.message); }
};

$("share-url").onclick = (e) => e.target.select();

show();
if (token) loadNotes().then(() => edit(null)).catch(() => {});
