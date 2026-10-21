import http.client
import json
import sys
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from remote_keys import State, create_handler


class DummyKeyboard:
    def __init__(self):
        self.operations = []

    def text(self, text):
        self.operations.append(('text', text))

    def backspace(self, count):
        self.operations.append(('backspace', count))

    def key(self, key):
        self.operations.append(('key', key))


class TestProtocol(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keyboard = DummyKeyboard()
        cls.state = State(cls.keyboard)
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), create_handler(cls.state))
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def query(self, method, path, data=None, cookie=None, origin=None, remote_header=True, user_agent=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        headers = {'Host': '127.0.0.1:' + str(self.server.server_port)}
        if data is not None:
            headers['Content-Type'] = 'application/json'
            if origin is None:
                origin = 'http://127.0.0.1:' + str(self.server.server_port)
            headers['Origin'] = origin
            if remote_header:
                headers['X-Remote-Keyboard'] = '1'
        if user_agent:
            headers['User-Agent'] = user_agent
        if cookie:
            headers['Cookie'] = cookie
        conn.request(method, path, body=json.dumps(data) if data is not None else None, headers=headers)
        resp = conn.getresponse()
        result = (resp.status, json.loads(resp.read()), resp.getheader('Set-Cookie'))
        conn.close()
        return result

    def authenticate(self):
        code, _, cookie = self.query('POST', '/api/pair', {'code': self.state.pin})
        self.assertEqual(code, 200)
        session = cookie.split(';')[0]
        code, _, _ = self.query('POST', '/api/control', {'enabled':True}, cookie=session)
        self.assertEqual(code, 200)
        return session

    def test_pairing_and_status(self):
        code, body, _ = self.query('GET', '/api/status')
        self.assertEqual(code, 200)
        self.assertFalse(body['paired'])
        session = self.authenticate()
        code, body, _ = self.query('GET', '/api/status', cookie=session)
        self.assertTrue(body['paired'])
        self.assertTrue(body['enabled'])

    def test_pairing_records_only_a_generic_device_label(self):
        code, _, cookie = self.query('POST','/api/pair',{'code':self.state.pin},
                                     user_agent='Test iPhone browser')
        self.assertEqual(code,200)
        self.assertEqual(self.state.panel_status()['peer'],'iPhone')
        session=cookie.split(';')[0]
        code, body, _=self.query('GET','/api/status',cookie=session)
        self.assertEqual(code,200)
        self.assertTrue(body['paired'])
        self.assertTrue(self.state.panel_status()['connected'])

    def test_duplicate_id_exactly_once(self):
        session = self.authenticate()
        self.keyboard.operations.clear()
        pkt = {'id':'sample-test-1001', 'action':'edit','erase':1,'text':'今日🌸'}
        self.assertEqual(self.query('POST','/api/input',pkt,session)[0], 200)
        self.assertEqual(self.query('POST','/api/input',pkt,session)[1]['duplicate'], True)
        self.assertEqual(self.keyboard.operations, [('backspace',1),('text','今日🌸')])

    def test_pause_rejects_typing(self):
        session = self.authenticate()
        self.query('POST', '/api/control', {'enabled':False}, session)
        code, _, _ = self.query('POST', '/api/input',
            {'id':'sample-test-1002','action':'edit','erase':0,'text':'a'}, session)
        self.assertEqual(code,409)

    def test_cross_origin_rejected(self):
        session = self.authenticate()
        code, _, _ = self.query('POST','/api/control',{'enabled':True}, session,
                               origin='https://example.org')
        self.assertEqual(code,403)
        code, _, _ = self.query('POST','/api/control',{'enabled':True}, session,
                               remote_header=False)
        self.assertEqual(code,403)

    def test_invalid_actions_not_injected(self):
        session = self.authenticate()
        self.keyboard.operations.clear()
        code, _, _ = self.query('POST', '/api/input',
            {'id':'sample-test-1003','action':'key','key':'Win+R'}, session)
        self.assertEqual(code,400)
        self.assertEqual(self.keyboard.operations, [])


if __name__ == '__main__':
    unittest.main()
