"""Run end-to-end API checks in a temporary folder: python3 -m unittest -v."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class NoteShareTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(__file__).resolve().parent
        for name in ('app.py', 'start.sh'):
            shutil.copy(root / name, self.temp.name)
        shutil.copytree(root / 'static', Path(self.temp.name) / 'static')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        self.base = f'http://127.0.0.1:{self.port}'
        self.start()

    def start(self):
        self.process = subprocess.Popen(['sh', './start.sh'], cwd=self.temp.name,
            env={**os.environ, 'PORT': str(self.port)}, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for _ in range(100):
            try:
                with urlopen(self.base, timeout=1) as response:
                    if response.status == 200:
                        return
            except OSError:
                time.sleep(.05)
        raise RuntimeError('Server failed to start')

    def stop(self):
        self.process.terminate()
        self.process.communicate(timeout=5)

    def tearDown(self):
        self.stop()
        self.temp.cleanup()

    def api(self, method, path, data=None, token=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        req = Request(self.base + path, data=None if data is None else json.dumps(data).encode(), headers=headers, method=method)
        try:
            response = urlopen(req)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None

    def account(self, email):
        credentials = {'email': email, 'password': 'a sufficiently long password'}
        self.assertEqual(self.api('POST', '/api/signup', credentials)[0], 201)
        status, login = self.api('POST', '/api/login', credentials)
        self.assertEqual(status, 200)
        return login['token']

    def test_full_flow_isolation_sharing_and_persistence(self):
        alice = self.account('alice@example.com')
        bob = self.account('bob@example.com')
        self.assertEqual(self.api('GET', '/api/notes')[0], 401)
        self.assertEqual(self.api('GET', '/api/notes', token='fake')[0], 401)
        status, note = self.api('POST', '/api/notes', {'title': 'A private idea', 'body': '<script>alert(1)</script>\nHello 🌱'}, alice)
        self.assertEqual(status, 201)
        self.assertFalse(note['shared'])
        path = '/api/notes/' + note['id']
        self.assertEqual(self.api('GET', '/api/notes', token=bob), (200, []))
        for method, suffix, data in [('GET', '', None), ('PUT', '', {'title':'stolen','body':'oops'}), ('DELETE', '', None), ('POST','/share',None), ('DELETE','/share',None)]:
            self.assertEqual(self.api(method, path + suffix, data, bob)[0], 404)
        self.assertEqual(self.api('GET', path, token=alice)[1]['body'], note['body'])
        status, updated = self.api('PUT', path, {'title': 'Updated idea', 'body': 'Saved body'}, alice)
        self.assertEqual(status, 200)
        share = self.api('POST', path + '/share', token=alice)[1]['share_token']
        public = '/api/shared/' + share
        status, shared = self.api('GET', public)
        self.assertEqual(status, 200)
        self.assertEqual(shared['title'], updated['title'])
        self.assertNotIn('user_id', shared)
        self.assertNotIn('share_hash', shared)
        with urlopen(self.base + '/shared/' + share) as response:
            self.assertEqual(response.status, 200)
        self.stop()
        self.start()
        self.assertEqual(self.api('GET', path, token=alice)[1]['title'], 'Updated idea')
        self.assertEqual(self.api('GET', public)[0], 200)
        self.api('PUT', path, {'title':'Latest', 'body':'Live edit'}, alice)
        self.assertEqual(self.api('GET', public)[1]['body'], 'Live edit')
        newer = self.api('POST', path + '/share', token=alice)[1]['share_token']
        self.assertNotEqual(share, newer)
        self.assertEqual(self.api('GET', public)[0], 404)
        public = '/api/shared/' + newer
        self.assertEqual(self.api('DELETE', path + '/share', token=alice)[0], 204)
        self.assertEqual(self.api('GET', public)[0], 404)
        final_share = self.api('POST', path + '/share', token=alice)[1]['share_token']
        self.assertEqual(self.api('DELETE', path, token=alice)[0], 204)
        self.assertEqual(self.api('GET', '/api/shared/' + final_share)[0], 404)
        self.assertEqual(self.api('GET', path, token=alice)[0], 404)
        self.assertEqual(self.api('POST', '/api/logout', token=alice)[0], 204)
        self.assertEqual(self.api('GET', '/api/notes', token=alice)[0], 401)

    def test_validation(self):
        alice = self.account('alice@example.com')
        self.assertEqual(self.api('POST', '/api/signup', {'email':'ALICE@example.com','password':'password123'})[0], 409)
        self.assertEqual(self.api('POST', '/api/login', {'email':'alice@example.com','password':'wrong-password'})[0], 401)
        self.assertEqual(self.api('POST', '/api/signup', {'email':'invalid','password':'password123'})[0], 400)
        for data in ({'title':'','body':'text'}, {'title':'hello','body':{}}, {'title':'a' * 201,'body':''}, [], {'title':'test'}):
            self.assertEqual(self.api('POST', '/api/notes', data, alice)[0], 400)
        self.assertEqual(self.api('GET', '/api/shared/not-a-valid-link')[0], 404)
        self.assertEqual(self.api('POST', '/api/notes', {'title':'Empty body is fine', 'body':''}, alice)[0], 201)


if __name__ == '__main__':
    unittest.main()
