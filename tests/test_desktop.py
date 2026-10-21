import http.client
import json
import unittest
from desktop_app import Receiver
from test_receiver import DummyKeyboard

class TestDesktopReceiver(unittest.TestCase):
    def setUp(self):
        self.receiver=Receiver(DummyKeyboard,port=0)
    def tearDown(self):
        self.receiver.stop()
    def test_start_paused_stop_invalidates_and_restart_requires_pairing(self):
        self.assertFalse(self.receiver.running)
        self.receiver.start()
        state=self.receiver.state
        port=self.receiver.server.server_port
        self.assertEqual(self.receiver.server.server_address[0],'127.0.0.1')
        self.assertFalse(state.armed(None))
        token,error=state.pair(state.pin)
        self.assertIsNone(error)
        state.set_armed(token,True)
        old_worker=self.receiver.worker
        self.receiver.stop()
        self.assertFalse(self.receiver.running)
        self.assertFalse(old_worker.is_alive())
        self.assertFalse(state.authenticated(token))
        self.assertIsNone(state.pair(state.pin)[0])
        with self.assertRaises(OSError):
            conn=http.client.HTTPConnection('127.0.0.1',port,timeout=1)
            try: conn.request('GET','/api/status')
            finally: conn.close()
        self.receiver.port=port
        self.receiver.start()
        self.assertFalse(self.receiver.state.authenticated(token))
        self.assertFalse(self.receiver.state.armed(None))
    def test_repeated_start_and_stop_are_idempotent(self):
        self.receiver.start()
        state=self.receiver.state
        self.receiver.start()
        self.assertIs(self.receiver.state,state)
        self.receiver.stop()
        self.receiver.stop()
    def test_old_session_cannot_inject_after_stop(self):
        self.receiver.start()
        state=self.receiver.state
        token,_=state.pair(state.pin)
        state.set_armed(token,True)
        self.receiver.stop()
        status,_=state.apply(token,{'id':'after-stop-test','action':'edit','erase':0,'text':'blocked'})
        self.assertEqual(status,401)
        self.assertEqual(state.keyboard.operations,[])

if __name__=='__main__': unittest.main()
