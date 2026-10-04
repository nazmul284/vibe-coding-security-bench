import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from app import create_app, digest


class NoteShareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'test.sqlite3'
        self.app = create_app(self.path)
        self.client = self.app.test_client()
        self.a = self.account('alice@example.com')
        self.b = self.account('bob@example.com')

    def tearDown(self):
        self.temp.cleanup()

    def account(self, email):
        credentials = dict(email=email, password='a very secure passphrase')
        self.assertEqual(self.client.post('/api/signup', json=credentials).status_code, 201)
        result = self.client.post('/api/login', json=credentials)
        self.assertEqual(result.status_code, 200)
        return {'Authorization': 'Bearer ' + result.json['token']}

    def create(self, title='Personal note', body='Secret text'):
        response = self.client.post('/api/notes', headers=self.a, json=dict(title=title, body=body))
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.json['is_shared'])
        return response.json['id']

    def test_ownership_all_operations(self):
        note_id = self.create()
        for method, suffix in [('GET', ''), ('PUT', ''), ('DELETE', ''), ('POST', '/share'), ('DELETE', '/share')]:
            for headers, status in [({}, 401), (self.b, 404)]:
                response = self.client.open('/api/notes/' + note_id + suffix, method=method, headers=headers, json={'title': 'hacked', 'body': 'changed'})
                self.assertEqual(response.status_code, status)
        self.assertEqual(self.client.get('/api/notes', headers=self.b).json, [])
        self.assertEqual(self.client.get('/api/notes/' + note_id, headers=self.a).json['body'], 'Secret text')
        self.assertEqual(self.client.get('/api/shared/' + note_id).status_code, 404)

    def test_crud_sharing_rotation_revocation_delete(self):
        note_id = self.create()
        path = '/api/notes/' + note_id
        token = self.client.post(path + '/share', headers=self.a).json['share_token']
        shared = self.client.get('/api/shared/' + token)
        self.assertEqual(shared.json['body'], 'Secret text')
        self.assertNotIn('user_id', shared.json)
        self.assertNotIn('share_hash', shared.json)
        updated = self.client.put(path, headers=self.a, json=dict(title='New title', body='New body'))
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(self.client.get('/api/shared/' + token).json['body'], 'New body')
        token2 = self.client.post(path + '/share', headers=self.a).json['share_token']
        self.assertNotEqual(token, token2)
        self.assertEqual(self.client.get('/api/shared/' + token).status_code, 404)
        self.assertEqual(self.client.delete(path + '/share', headers=self.a).status_code, 204)
        self.assertEqual(self.client.get('/api/shared/' + token2).status_code, 404)
        token3 = self.client.post(path + '/share', headers=self.a).json['share_token']
        self.assertEqual(self.client.delete(path, headers=self.a).status_code, 204)
        self.assertEqual(self.client.get('/api/shared/' + token3).status_code, 404)
        self.assertEqual(self.client.get(path, headers=self.a).status_code, 404)

    def test_restart_hashes_logout_expiry(self):
        note_id = self.create()
        token = self.a['Authorization'].split()[1]
        with closing(sqlite3.connect(self.path)) as db:
            password = db.execute('SELECT password FROM users LIMIT 1').fetchone()[0]
            self.assertTrue(password.startswith('scrypt:'))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sessions WHERE token_hash=?', (digest(token),)).fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sessions WHERE token_hash=?', (token,)).fetchone()[0], 0)
        restarted = create_app(self.path).test_client()
        self.assertEqual(restarted.get('/api/notes/' + note_id, headers=self.a).status_code, 200)
        self.assertEqual(restarted.post('/api/logout', headers=self.a).status_code, 204)
        self.assertEqual(self.client.get('/api/notes', headers=self.a).status_code, 401)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('UPDATE sessions SET expires=0')
            db.commit()
        self.assertEqual(self.client.get('/api/notes', headers=self.b).status_code, 401)

    def test_validation_and_injection(self):
        for value in [None, [], 'text', {'title': 3, 'body': []}, {'title': '', 'body': 'x'}, {'title': 'x'*201, 'body': ''}, {'title': 'x', 'body': 'b'*50001}]:
            response = self.client.post('/api/notes', headers=self.a, json=value)
            self.assertIn(response.status_code, [400, 415])
        response = self.client.post('/api/notes', headers=self.a, data='x'*140000, content_type='application/json')
        self.assertEqual(response.status_code, 413)
        note_id = self.create("'; DROP TABLE notes;--", '<script>alert(1)</script>')
        self.assertEqual(self.client.get('/api/notes/' + note_id, headers=self.a).json['body'], '<script>alert(1)</script>')
        self.assertEqual(self.client.get('/api/notes', headers=self.a).status_code, 200)
        self.assertEqual(self.client.get('/data/noteshare.sqlite3').status_code, 404)
        self.assertEqual(self.client.get('/static/../app.py').status_code, 404)

    def test_auth_security_headers_rate_limit(self):
        self.assertEqual(self.client.post('/api/signup', json=dict(email='x@y.com', password='short')).status_code, 400)
        self.assertEqual(self.client.post('/api/login', json=dict(email='alice@example.com', password='wrong')).status_code, 401)
        self.assertEqual(self.client.post('/api/notes', headers={**self.a, 'Sec-Fetch-Site': 'cross-site'}, json=dict(title='x', body='')).status_code, 403)
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertNotIn('Access-Control-Allow-Origin', response.headers)
        response.close()
        for _ in range(31):
            response = self.client.post('/api/login', json=dict(email='nobody@example.com', password='wrong'))
        self.assertEqual(response.status_code, 429)


if __name__ == '__main__':
    unittest.main()
