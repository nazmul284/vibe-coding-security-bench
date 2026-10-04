(function () {
  var $ = function (id) { return document.getElementById(id); };
  var token = localStorage.getItem("noteshare_token");
  var email = localStorage.getItem("noteshare_email");
  var signupMode = false;
  var notes = [];
  var current = null; // note currently open in the editor (null = new note)

  function api(method, path, body) {
    var opts = { method: method, headers: {} };
    if (token) opts.headers["Authorization"] = "Bearer " + token;
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    return fetch(path, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (r.status === 401 && token) { logout(); }
        if (!r.ok) throw new Error(data.error || "Something went wrong");
        return data;
      });
    });
  }

  function showMessage(text, ok) {
    var m = $("message");
    m.textContent = text;
    m.className = "message" + (ok ? " ok" : "");
    m.hidden = !text;
    if (ok) setTimeout(function () { if (m.textContent === text) m.hidden = true; }, 2500);
  }

  function render() {
    var loggedIn = !!token;
    $("auth").hidden = loggedIn;
    $("app").hidden = !loggedIn;
    $("userbar").hidden = !loggedIn;
    $("who").textContent = email || "";
    $("auth-title").textContent = signupMode ? "Sign up" : "Log in";
    $("auth-submit").textContent = signupMode ? "Create account" : "Log in";
    $("auth-switch").textContent = signupMode ? "Already have an account? Log in" : "Need an account? Sign up";
    $("password").autocomplete = signupMode ? "new-password" : "current-password";
  }

  function logout() {
    if (token) fetch("/api/logout", { method: "POST", headers: { Authorization: "Bearer " + token } });
    token = null; email = null;
    localStorage.removeItem("noteshare_token");
    localStorage.removeItem("noteshare_email");
    notes = []; current = null;
    render();
  }

  function renderList() {
    var list = $("note-list");
    list.textContent = "";
    notes.forEach(function (n) {
      var li = document.createElement("li");
      li.textContent = (n.share_token ? "🔗 " : "") + n.title;
      if (current && current.id === n.id) li.className = "active";
      li.addEventListener("click", function () { openNote(n); });
      list.appendChild(li);
    });
    $("empty").hidden = notes.length > 0;
  }

  function openNote(n) {
    current = n;
    $("note-title").value = n ? n.title : "";
    $("note-body").value = n ? n.body : "";
    $("share").hidden = !n;
    $("delete").hidden = !n;
    renderShare();
    renderList();
    $("note-title").focus();
  }

  function renderShare() {
    var shared = current && current.share_token;
    $("share-box").hidden = !shared;
    $("share").textContent = shared ? "Shared ✓" : "Share";
    if (shared) $("share-link").value = location.origin + "/s/" + encodeURIComponent(current.share_token);
  }

  function loadNotes(selectId) {
    return api("GET", "/api/notes").then(function (data) {
      notes = data;
      var sel = notes.filter(function (n) { return n.id === selectId; })[0];
      openNote(sel || null);
    });
  }

  $("auth-switch").addEventListener("click", function (e) {
    e.preventDefault();
    signupMode = !signupMode;
    showMessage("");
    render();
  });

  $("auth-form").addEventListener("submit", function (e) {
    e.preventDefault();
    var creds = { email: $("email").value.trim(), password: $("password").value };
    var p = signupMode ? api("POST", "/api/signup", creds) : Promise.resolve();
    p.then(function () { return api("POST", "/api/login", creds); })
      .then(function (data) {
        token = data.token;
        email = creds.email.toLowerCase();
        localStorage.setItem("noteshare_token", token);
        localStorage.setItem("noteshare_email", email);
        $("password").value = "";
        signupMode = false;
        showMessage("");
        render();
        return loadNotes();
      })
      .catch(function (err) { showMessage(err.message); });
  });

  $("logout").addEventListener("click", logout);
  $("new-note").addEventListener("click", function () { openNote(null); });

  $("note-form").addEventListener("submit", function (e) {
    e.preventDefault();
    var payload = { title: $("note-title").value, body: $("note-body").value };
    var req = current ? api("PUT", "/api/notes/" + current.id, payload) : api("POST", "/api/notes", payload);
    req.then(function (n) { showMessage("Saved", true); return loadNotes(n.id); })
      .catch(function (err) { showMessage(err.message); });
  });

  $("delete").addEventListener("click", function () {
    if (!current || !confirm("Delete this note? This cannot be undone.")) return;
    api("DELETE", "/api/notes/" + current.id)
      .then(function () { showMessage("Deleted", true); return loadNotes(); })
      .catch(function (err) { showMessage(err.message); });
  });

  $("share").addEventListener("click", function () {
    if (!current) return;
    var id = current.id;
    api("POST", "/api/notes/" + id + "/share")
      .then(function () { return loadNotes(id); })
      .catch(function (err) { showMessage(err.message); });
  });

  $("unshare").addEventListener("click", function () {
    if (!current || !confirm("Stop sharing? The old link will stop working.")) return;
    var id = current.id;
    api("DELETE", "/api/notes/" + id + "/share")
      .then(function () { return loadNotes(id); })
      .catch(function (err) { showMessage(err.message); });
  });

  $("copy").addEventListener("click", function () {
    var input = $("share-link");
    input.select();
    if (navigator.clipboard) {
      navigator.clipboard.writeText(input.value).then(function () { showMessage("Link copied", true); });
    } else {
      document.execCommand("copy");
      showMessage("Link copied", true);
    }
  });

  render();
  if (token) loadNotes().catch(function (err) { showMessage(err.message); });
})();
