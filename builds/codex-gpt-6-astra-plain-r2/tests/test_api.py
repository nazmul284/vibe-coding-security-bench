import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


class NoteShareTest(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.TemporaryDirectory()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        self.start()

    def start(self):
        self.process = subprocess.Popen([sys.executable, str(ROOT / 'server.py')],
            env={**os.environ, 'PORT': str(self.port), 'NOTESHARE_DATA_DIR': self.data.name},
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for _ in range(100):
            try:
                with urlopen(f'http://127.0.0.1:{self.port}/', timeout=1) as response:
                    self.assertEqual(response.status, 200)
                return
            except OSError:
                time.sleep(.05)
        self.fail('Server did not start')

    def stop(self):
        self.process.terminate()
        self.process.communicate(timeout=5)

    def tearDown(self):
        self.stop()
        self.data.cleanup()

    def call(self, path, method='GET', data=None, token=None, status=200):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        request = Request(f'http://127.0.0.1:{self.port}{path}',
            data=None if data is None else json.dumps(data).encode(), headers=headers, method=method)
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            self.assertEqual(response.status, status, response.read().decode() if response.status != status else '')
            raw = response.read()
            return json.loads(raw) if raw else None

    def account(self, email):
        data = {'email': email, 'password': 'a good password'}
        self.call('/api/signup', 'POST', data, status=201)
        return self.call('/api/login', 'POST', data)['token']

    def test_privacy_sharing_and_persistence(self):
        alice = self.account('alice@example.com')
        bob = self.account('bob@example.com')
        self.call('/api/notes', status=401)
        self.call('/api/notes', token='invalid', status=401)
        note = self.call('/api/notes', 'POST', {'title': 'Private', 'body': '<script>alert(1)</script>\nHello'}, alice, 201)
        self.assertIsNone(note['share_token'])
        path = f"/api/notes/{note['id']}"
        self.assertEqual(self.call('/api/notes', token=bob), [])
        for method, suffix, body in [('GET','',''), ('PUT','',{'title':'stolen','body':''}), ('DELETE','',''), ('POST','/share',''), ('DELETE','/share','')]:
            self.call(path + suffix, method, body or None, bob, 404)
        self.call(path, status=401)
        updated = self.call(path, 'PUT', {'title': 'Updated', 'body': 'The new body'}, alice)
        self.assertEqual(updated['title'], 'Updated')
        share = self.call(path + '/share', 'POST', token=alice)['share_token']
        public = self.call('/api/shared/' + share)
        self.assertEqual(public['body'], 'The new body')
        self.assertNotIn('share_token', public)
        self.assertNotIn('user_id', public)
        self.stop()
        self.start()
        self.assertEqual(self.call(path, token=alice)['title'], 'Updated')
        self.assertEqual(self.call('/api/shared/' + share)['title'], 'Updated')
        self.call(path + '/share', 'DELETE', token=alice)
        self.call('/api/shared/' + share, status=404)
        new_share = self.call(path + '/share', 'POST', token=alice)['share_token']
        self.assertNotEqual(share, new_share)
        self.call(path, 'DELETE', token=alice, status=204)
        self.call('/api/shared/' + new_share, status=404)
        self.call(path, token=alice, status=404)
        self.call('/api/logout', 'POST', token=alice, status=204)
        self.call('/api/notes', token=alice, status=401)

    def test_validation_and_authentication(self):
        token = self.account('hello@example.com')
        self.call('/api/signup', 'POST', {'email':'HELLO@example.com', 'password':'different password'}, status=409)
        self.call('/api/login', 'POST', {'email':'hello@example.com', 'password':'wrong password'}, status=401)
        self.call('/api/signup', 'POST', {'email':'not an email', 'password':'long enough'}, status=400)
        self.call('/api/signup', 'POST', {'email':'new@example.com', 'password':'short'}, status=400)
        for data in [{'title':'', 'body':''}, {'title':'x'}, {'title':'x','body':123}, []]:
            self.call('/api/notes', 'POST', data, token, 400)
        self.call('/api/notes', 'POST', {'title':"quote ' test", 'body':'Unicode ✓'}, token, 201)
        self.assertEqual(len(self.call('/api/notes', token=token)), 1)
        self.call('/api/shared/missing', status=404)
        self.call('/data/noteshare.sqlite3', status=404)


if __name__ == '__main__':
    unittest.main()
