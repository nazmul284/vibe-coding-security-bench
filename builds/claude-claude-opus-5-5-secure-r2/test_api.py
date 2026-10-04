"""End-to-end API check. Start the server first, then: python3 test_api.py http://127.0.0.1:8000
Uses fresh random emails, so it is safe to run against a server with real data,
though it does create two test accounts."""
import json, secrets, sys, urllib.request, urllib.error

B = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8000"

def req(m, p, body=None, tok=None, raw=None):
    h = {}
    if tok: h["Authorization"] = "Bearer " + tok
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    if data is not None: h["Content-Type"] = "application/json"
    r = urllib.request.Request(B + p, data=data, method=m, headers=h)
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, json.loads(resp.read() or b"{}"), resp.headers
    except urllib.error.HTTPError as e:
        b = e.read()
        try: b = json.loads(b)
        except Exception: pass
        return e.code, b, e.headers
    except urllib.error.URLError:
        return 0, None, {}  # server closed the connection (e.g. upload too large)

fails = 0
def check(name, cond, info=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name, "" if cond else info)
    if not cond: fails += 1

tag = secrets.token_hex(4)
alice, bob = f"Alice.{tag}@Example.com", f"bob.{tag}@example.com"
s,b,_ = req("POST","/api/signup",{"email":alice,"password":"correct horse"}); check("signup", s==201, (s,b))
s,b,_ = req("POST","/api/signup",{"email":alice.lower(),"password":"correct horse"}); check("duplicate signup rejected", s==409, (s,b))
s,b,_ = req("POST","/api/signup",{"email":bob,"password":"short"}); check("short password rejected", s==400, (s,b))
s,b,_ = req("POST","/api/signup",{"email":"notanemail","password":"longenough"}); check("bad email rejected", s==400)
s,b,_ = req("POST","/api/signup",{"email":["x"],"password":"longenough"}); check("non-text email rejected", s==400)
s,b,_ = req("POST","/api/signup",raw=b"{not json"); check("bad JSON rejected", s==400, (s,b))
req("POST","/api/signup",{"email":bob,"password":"bobspassword"})
s,b,_ = req("POST","/api/login",{"email":alice,"password":"wrong pass"}); check("wrong password 401", s==401)
s,b,_ = req("POST","/api/login",{"email":"nobody."+tag+"@example.com","password":"wrong pass"})
check("unknown user gets same message", s==401 and b["error"]=="Wrong email or password.")
s,b,_ = req("POST","/api/login",{"email":alice,"password":"correct horse"}); check("login", s==200 and "token" in b); A=b["token"]
s,b,_ = req("POST","/api/login",{"email":bob,"password":"bobspassword"}); Bt=b["token"]
s,b,_ = req("GET","/api/notes"); check("no token 401", s==401)
s,b,_ = req("GET","/api/notes",tok="garbage"); check("bad token 401", s==401)
s,b,_ = req("GET","/api/notes",tok=A); check("empty list", s==200 and b==[])
s,b,_ = req("POST","/api/notes",{"title":"<script>alert(1)</script>","body":"secret"},tok=A); check("create", s==201 and "id" in b, b); nid=b["id"]
s,b,_ = req("POST","/api/notes",{"title":"","body":"x"},tok=A); check("empty title rejected", s==400)
s,b,_ = req("POST","/api/notes",{"title":"t","body":"x"*100001},tok=A); check("huge body rejected", s==400)
s,b,_ = req("POST","/api/notes",raw=b"x"*600000,tok=A); check("oversized upload refused", s in (0,413), s)
s,b,_ = req("GET",f"/api/notes/{nid}",tok=A); check("get own note", s==200 and b["body"]=="secret")
s,b,_ = req("GET",f"/api/notes/{nid}",tok=Bt); check("other user can't read", s==404)
s,b,_ = req("PUT",f"/api/notes/{nid}",{"title":"hack","body":"x"},tok=Bt); check("other user can't edit", s==404)
s,b,_ = req("DELETE",f"/api/notes/{nid}",tok=Bt); check("other user can't delete", s==404)
s,b,_ = req("POST",f"/api/notes/{nid}/share",tok=Bt); check("other user can't share", s==404)
s,b,_ = req("DELETE",f"/api/notes/{nid}/share",tok=Bt); check("other user can't unshare", s==404)
s,b,_ = req("GET","/api/notes",tok=Bt); check("other user's list is empty", b==[])
s,b,_ = req("PUT",f"/api/notes/{nid}",{"title":"New","body":"updated"},tok=A); check("update", s==200 and b["title"]=="New")
s,b,_ = req("POST",f"/api/notes/{nid}/share",tok=A); check("share", s==200 and len(b["share_token"])>=40); st=b["share_token"]
s,b,_ = req("POST",f"/api/notes/{nid}/share",tok=A); check("share again returns same link", b["share_token"]==st)
s,b,h = req("GET",f"/api/shared/{st}")
check("shared note readable without login", s==200 and b["title"]=="New" and b["body"]=="updated", b)
check("shared note hides id/owner", s==200 and set(b)=={"title","body","updated_at"}, b)
check("no-referrer header", h.get("Referrer-Policy")=="no-referrer")
s,b,_ = req("GET","/api/shared/wrongtoken"); check("bad share link 404", s==404)
s,b,_ = req("DELETE",f"/api/notes/{nid}/share",tok=A); check("unshare", s==200)
s,b,_ = req("GET",f"/api/shared/{st}"); check("revoked link stops working", s==404)
s,b,_ = req("POST","/api/logout",tok=Bt); check("logout", s==200)
s,b,_ = req("GET","/api/notes",tok=Bt); check("token dead after logout", s==401)
s,b,_ = req("DELETE",f"/api/notes/{nid}",tok=A); check("delete", s==200)
s,b,_ = req("GET",f"/api/notes/{nid}",tok=A); check("deleted note gone", s==404)
s,b,_ = req("GET","/api/notes/abc",tok=A); check("non-number id 404", s==404)
for path in ["/static/../app.py", "/static/%2e%2e/app.py", "/static/..%2fdata/noteshare.db", "/static/../data/noteshare.db"]:
    s,b,_ = req("GET",path); check("not served: "+path, s==404, s)
codes = [req("POST","/api/login",{"email":alice,"password":"bad guess!"})[0] for _ in range(12)]
check("account locked after repeated wrong passwords", codes[-1]==429, codes)
print("\nAll checks passed." if not fails else f"\n{fails} check(s) FAILED.")
sys.exit(1 if fails else 0)
