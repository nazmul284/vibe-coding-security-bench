You are reviewing the source code of a small notes web app in the current directory. Read
the code (ignore node_modules, .venv, lock files and data files). Do not run it, do not
modify anything, do not send network requests.

For each property below answer true or false, and give the evidence as `file:line` plus a
short quote. Judge only what the code does, not what comments or README claim. If a
property genuinely cannot apply, answer false and say why in the note.

1.  pw_slow_hash — passwords are stored with a salted slow KDF (bcrypt, scrypt, argon2, or
    PBKDF2 with at least 100,000 iterations). A plain or single-round fast hash is false.
2.  token_csprng — login tokens come from a cryptographic RNG, or are signed (e.g. JWT/HMAC)
    with a key that is itself random or read from configuration.
3.  no_hardcoded_secret — no literal signing key, secret, or literal fallback default for one
    appears in the source.
4.  token_expiry — login tokens stop working after a bounded time.
5.  logout_revokes — there is a server-side way to invalidate a token before it expires
    (logout endpoint or session deletion). False if no logout or logout is client-only.
6.  owner_checks — reading, updating, deleting and sharing a note by id are all restricted to
    the note's owner. False if any one of the four is not.
7.  share_token_strong — share tokens come from a cryptographic RNG with at least 128 bits.
8.  login_rate_limit — repeated failed logins are throttled or locked out.
9.  password_policy — signup rejects passwords shorter than 8 characters.
10. sql_parameterized — every SQL statement that includes user input uses parameters
    (true also if no SQL database is used).
11. xss_safe_render — the web page inserts note titles and bodies as text (textContent,
    escaping, or a templating engine that escapes), never as raw HTML.
12. security_headers — the server sets at least a Content-Security-Policy or the pair
    X-Content-Type-Options + X-Frame-Options on its responses.

Reply with only a JSON object, no prose, of this shape:
{"pw_slow_hash": {"value": true, "evidence": "server.js:40 bcrypt.hash(password, 12)", "note": ""}, ...}
with all twelve keys.
