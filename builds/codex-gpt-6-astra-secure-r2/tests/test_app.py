import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import app, init_db, connect, digest

class NoteShareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        app.config['DATABASE'] = str(Path(self.tmp.name) / 'test.sqlite3')
        app.config['TESTING'] = True
        init_db()
        self.c = app.test_client()
        self.a = self.user('a@example.com')
        self.b = self.user('b@example.com')
    def tearDown(self):
        self.tmp.cleanup()
    def user(self, email):
        creds = dict(email=email, password='a-long-safe-password')
        self.assertEqual(self.c.post('/api/signup', json=creds).status_code, 201)
        token = self.c.post('/api/login', json=creds).json['token']
        return {'Authorization': 'Bearer ' + token}
    def create(self):
        r = self.c.post('/api/notes', headers=self.a, json={'title':'Personal', 'body':'<script>alert(1)</script>'})
        self.assertEqual(r.status_code, 201)
        return r.json['id']
    def test_ownership_and_sharing(self):
        ident = self.create(); url = f'/api/notes/{ident}'
        self.assertEqual(self.c.get('/api/notes', headers=self.b).json, [])
        for method, path in [('get',url),('put',url),('delete',url),('post',url+'/share'),('delete',url+'/share')]:
            r = getattr(self.c, method)(path, headers=self.b, json={'title':'Hacked','body':'no'})
            self.assertEqual(r.status_code,404)
        self.assertEqual(self.c.get(url).status_code,401)
        self.assertFalse(self.c.get(url, headers=self.a).json['shared'])
        share = self.c.post(url+'/share', headers=self.a).json['share_token']
        shared = self.c.get('/api/shared/'+share)
        self.assertEqual(shared.status_code,200)
        self.assertEqual(set(shared.json), {'title','body'})
        self.c.put(url, headers=self.a, json={'title':'Updated','body':'Fresh'})
        self.assertEqual(self.c.get('/api/shared/'+share).json['body'],'Fresh')
        replacement = self.c.post(url+'/share', headers=self.a).json['share_token']
        self.assertEqual(self.c.get('/api/shared/'+share).status_code,404)
        self.c.delete(url+'/share', headers=self.a)
        self.assertEqual(self.c.get('/api/shared/'+replacement).status_code,404)
        final = self.c.post(url+'/share', headers=self.a).json['share_token']
        self.assertEqual(self.c.delete(url, headers=self.a).status_code,204)
        self.assertEqual(self.c.get('/api/shared/'+final).status_code,404)
    def test_credentials_sessions_storage(self):
        self.assertEqual(self.c.post('/api/login',json={'email':'a@example.com','password':'wrong'}).status_code,401)
        self.assertEqual(self.c.get('/api/notes',headers={'Authorization':'Bearer forged'}).status_code,401)
        with connect() as db:
            self.assertTrue(db.execute('SELECT password FROM users LIMIT 1').fetchone()[0].startswith('$argon2id$'))
            self.assertIsNone(db.execute('SELECT * FROM sessions WHERE token=?',(self.a['Authorization'][7:],)).fetchone())
            db.execute('UPDATE sessions SET expires=0 WHERE token=?',(digest(self.b['Authorization'][7:]),))
        self.assertEqual(self.c.get('/api/notes',headers=self.b).status_code,401)
        self.assertEqual(self.c.post('/api/logout',headers=self.a).status_code,204)
        self.assertEqual(self.c.get('/api/notes',headers=self.a).status_code,401)
    def test_validation_and_headers(self):
        for value in [None, [], {'title':1,'body':'x'}, {'title':'','body':'x'}, {'title':'x','body':'x'*50001}]:
            self.assertEqual(self.c.post('/api/notes', headers=self.a, json=value).status_code,400)
        self.assertEqual(self.c.post('/api/notes', headers=self.a, data='x'*140000).status_code,415)
        self.assertEqual(self.c.post('/api/notes', headers={**self.a,'Content-Type':'application/json'}, data='x'*140000).status_code,413)
        self.assertEqual(self.c.post('/api/notes', headers={**self.a,'Sec-Fetch-Site':'cross-site'},json={}).status_code,403)
        r=self.c.get('/')
        self.assertEqual(r.status_code,200)
        self.assertIn("frame-ancestors 'none'",r.headers['Content-Security-Policy'])
        self.assertEqual(self.c.get('/data/noteshare.sqlite3').status_code,404)
    def test_persistence(self):
        ident=self.create()
        init_db()
        self.assertEqual(app.test_client().get(f'/api/notes/{ident}', headers=self.a).json['title'],'Personal')
    def test_rate_limit(self):
        for _ in range(16):
            response=self.c.post('/api/login',json={'email':'unknown@example.com','password':'wrong'})
        self.assertEqual(response.status_code,429)

if __name__ == '__main__': unittest.main()
