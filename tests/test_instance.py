import os
from pathlib import Path
import subprocess
import sys
import unittest
import unittest.mock
import uuid
from instance_guard import InstanceGuard


@unittest.skipUnless(os.name == 'nt', 'Windows named-object integration')
class TestInstanceGuard(unittest.TestCase):
    def start_owner(self, legacy=False, respond=True):
        name = r'Local\RemoteKeyboardTest-' + uuid.uuid4().hex
        source = """
import ctypes, sys, time
from instance_guard import InstanceGuard
name, legacy, respond = sys.argv[1:]
guard = InstanceGuard(name)
if legacy == 'True':
    guard.mutex = guard.kernel.CreateMutexW(None, False, name)
else:
    assert guard.acquire(lambda: False)
print('ready', flush=True)
try:
    while True:
        if respond == 'True' and guard.restart_requested():
            break
        time.sleep(0.01)
finally:
    guard.close()
"""
        child = subprocess.Popen([sys.executable, '-u', '-c', source, name, str(legacy), str(respond)],
                                 cwd=Path(__file__).resolve().parents[1], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.stop_child, child)
        self.assertEqual(child.stdout.readline().strip(), 'ready')
        return name, child

    @staticmethod
    def stop_child(child):
        if child.poll() is None:
            child.terminate()
        child.communicate(timeout=5)

    def test_cancel_preserves_owner_and_does_not_request_restart(self):
        name, child = self.start_owner()
        guard = InstanceGuard(name)
        self.addCleanup(guard.close)
        with unittest.mock.patch.object(guard.kernel, 'SetEvent') as signal:
            self.assertFalse(guard.acquire(lambda: False))
            signal.assert_not_called()
        self.assertIsNone(child.poll())

    def test_confirm_waits_for_old_exit_then_owns_fresh_instance(self):
        name, child = self.start_owner()
        guard = InstanceGuard(name)
        self.addCleanup(guard.close)
        self.assertTrue(guard.acquire(lambda: True))
        self.assertEqual(child.wait(timeout=5), 0)
        self.assertTrue(guard.owned)
        self.assertFalse(guard.restart_requested())
        guard.close()
        # All handles were released; a new launch must not ask for replacement.
        fresh = InstanceGuard(name)
        self.addCleanup(fresh.close)
        self.assertTrue(fresh.acquire(lambda: self.fail('stale instance')))

    def test_legacy_owner_is_not_forcibly_terminated(self):
        name, child = self.start_owner(legacy=True)
        guard = InstanceGuard(name)
        self.addCleanup(guard.close)
        with self.assertRaisesRegex(RuntimeError, '以前のバージョン'):
            guard.acquire(lambda: True)
        self.assertFalse(guard.owned)
        self.assertIsNone(child.poll())

    def test_shutdown_timeout_never_grants_a_second_owner(self):
        name, child = self.start_owner(respond=False)
        guard = InstanceGuard(name)
        self.addCleanup(guard.close)
        with self.assertRaisesRegex(RuntimeError, '重複起動は中止'):
            guard.acquire(lambda: True, timeout_ms=100)
        self.assertFalse(guard.owned)
        self.assertIsNone(child.poll())

if __name__ == '__main__': unittest.main()
