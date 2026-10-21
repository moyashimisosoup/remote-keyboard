import http.client
import json
import unittest
from unittest.mock import patch
from desktop_app import Receiver, connection_caption
from remote_keys import State, PIN_LIFETIME, SESSION_LIFETIME, ARM_TIMEOUT, CONNECTION_FRESHNESS, peer_kind
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

class TestConnectionIndicators(unittest.TestCase):
    def setUp(self):
        self.clock=patch('remote_keys.time.monotonic', return_value=1000.0)
        self.now=self.clock.start()
        self.addCleanup(self.clock.stop)
        self.state=State(DummyKeyboard())
        self.token,_=self.state.pair(self.state.pin,'Test iPhone browser')

    def test_expired_pin_preserves_existing_session_and_can_enable_input(self):
        self.now.return_value=1000.0+PIN_LIFETIME+1
        self.state.heartbeat(self.token)
        status=self.state.panel_status()
        self.assertTrue(status['pin_expired'])
        self.assertTrue(status['paired'])
        self.assertTrue(status['connected'])
        self.assertFalse(status['receiving'])
        self.assertEqual(connection_caption(status),'iPhoneと接続中／入力停止中')
        self.assertIsNone(self.state.pair(self.state.pin)[0])
        self.assertTrue(self.state.set_armed(self.token,True))
        status=self.state.panel_status()
        self.assertTrue(status['pin_expired'])
        self.assertTrue(status['receiving'])
        self.assertEqual(connection_caption(status),'iPhoneと接続中／入力受信中')
        self.assertEqual(self.state.session_until,1000.0+SESSION_LIFETIME)
        self.assertEqual(self.state.pin_born,1000.0)

    def test_stale_contact_does_not_revoke_session_or_claim_online(self):
        self.state.set_armed(self.token,True)
        self.now.return_value=1000.0+CONNECTION_FRESHNESS+1
        status=self.state.panel_status()
        self.assertTrue(status['paired'])
        self.assertFalse(status['connected'])
        self.assertFalse(status['receiving'])
        self.assertEqual(connection_caption(status),'iPhone 認証済み／応答待ち')
        self.assertTrue(self.state.authenticated(self.token))
        self.state.heartbeat(self.token)
        self.assertTrue(self.state.panel_status()['connected'])

    def test_reading_panel_never_extends_input_authorization(self):
        self.state.set_armed(self.token,True)
        deadline=self.state.armed_until
        self.now.return_value=1000.0+5
        self.state.panel_status()
        self.assertEqual(self.state.armed_until,deadline)
        self.now.return_value=1000.0+ARM_TIMEOUT+1
        self.assertFalse(self.state.panel_status()['receiving'])
        self.assertFalse(self.state.armed(self.token))

    def test_expired_session_is_not_displayed_as_connected(self):
        self.now.return_value=1000.0+SESSION_LIFETIME+1
        status=self.state.panel_status()
        self.assertFalse(status['paired'])
        self.assertFalse(status['connected'])
        self.assertFalse(status['receiving'])
        self.assertEqual(connection_caption(status),'未接続')

    def test_only_coarse_device_kind_is_retained(self):
        self.assertEqual(peer_kind('Test iPhone browser'),'iPhone')
        self.assertEqual(peer_kind('Test Macintosh Mobile browser'),'iPad')
        self.assertEqual(peer_kind('Test Android browser'),'Android')
        self.assertEqual(peer_kind('Unrecognized custom client'),'ブラウザ')
        seen=self.state.last_seen
        self.now.return_value+=5
        self.state.heartbeat('invalid-session')
        self.assertEqual(self.state.last_seen,seen)

if __name__=='__main__': unittest.main()
