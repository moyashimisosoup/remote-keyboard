"""Remote Keyboard: local-only Windows keyboard receiver (standard library only).

To expose to an iPhone, run tailscale serve 8787 separately.
Never expose this process using Tailscale Funnel or router port forwarding.
"""
from __future__ import annotations

import ctypes
import hashlib
import hmac
import http.cookies
import json
import os
import re
import secrets
import sys
import threading
import time
from collections import OrderedDict
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

HOST = '127.0.0.1'
PORT = 8787
HERE = Path(__file__).resolve().parent
MAX_JSON_BYTES = 8192
ARM_TIMEOUT = 35
PIN_LIFETIME = 30 * 60
SESSION_LIFETIME = 12 * 3600


class WindowsKeyboard:
    """Inject UTF-16 text and a small allowlist of virtual keys into the foreground app."""

    VK_KEYS = {'Enter': 0x0D, 'Backspace': 0x08, 'Tab': 0x09, 'Escape': 0x1B}
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004
    INPUT_KEYBOARD = 1

    def __init__(self):
        if os.name != 'nt':
            raise RuntimeError('Windows only: this app controls a Windows keyboard.')

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG),
                        ('mouseData', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
                        ('time', wintypes.DWORD), ('dwExtraInfo', wintypes.WPARAM)]

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD),
                        ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD),
                        ('dwExtraInfo', wintypes.WPARAM)]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [('uMsg', wintypes.DWORD), ('wParamL', wintypes.WORD),
                        ('wParamH', wintypes.WORD)]

        class U(ctypes.Union):
            _fields_ = [('mi', MOUSEINPUT), ('ki', KEYBDINPUT), ('hi', HARDWAREINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [('type', wintypes.DWORD), ('data', U)]

        self.INPUT = INPUT
        self.KEYBDINPUT = KEYBDINPUT
        self.user32 = ctypes.WinDLL('user32', use_last_error=True)
        self.user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        self.user32.SendInput.restype = wintypes.UINT

    def _event(self, vk=0, scan=0, flags=0):
        inp = self.INPUT()
        inp.type = self.INPUT_KEYBOARD
        inp.data.ki = self.KEYBDINPUT(vk, scan, flags, 0, 0)
        return inp

    def _send(self, events):
        for offset in range(0, len(events), 100):
            batch = events[offset:offset + 100]
            arr = (self.INPUT * len(batch))(*batch)
            sent = self.user32.SendInput(len(batch), arr, ctypes.sizeof(self.INPUT))
            if sent != len(batch):
                raise RuntimeError('Windows rejected one or more input events; input might be partial.')

    def key(self, key):
        if key not in self.VK_KEYS:
            raise ValueError('Unsupported key')
        vk = self.VK_KEYS[key]
        self._send([self._event(vk=vk), self._event(vk=vk, flags=self.KEYEVENTF_KEYUP)])

    def text(self, value):
        fragments = value.split('\n')
        for index, fragment in enumerate(fragments):
            if fragment:
                raw = fragment.encode('utf-16-le')
                units = [int.from_bytes(raw[i:i+2], 'little')
                         for i in range(0, len(raw), 2)]
                events = []
                for scan in units:
                    events.append(self._event(scan=scan, flags=self.KEYEVENTF_UNICODE))
                    events.append(self._event(scan=scan, flags=self.KEYEVENTF_UNICODE | self.KEYEVENTF_KEYUP))
                self._send(events)
            if index != len(fragments) - 1:
                self.key('Enter')

    def backspace(self, count):
        for _ in range(count):
            self.key('Backspace')


class State:
    def __init__(self, keyboard):
        self.keyboard = keyboard
        self.lock = threading.RLock()
        self.pin = f'{secrets.randbelow(1_000_000):06d}'
        self.pin_born = time.monotonic()
        self.failed = 0
        self.locked_until = 0.0
        self.session = None
        self.session_until = 0.0
        self.armed_until = 0.0
        self.seen = OrderedDict()

    def authenticated(self, token):
        return bool(token and self.session and
                    time.monotonic() < self.session_until and
                    hmac.compare_digest(token, self.session))

    def armed(self, token):
        return self.authenticated(token) and time.monotonic() < self.armed_until

    def pair(self, supplied):
        now = time.monotonic()
        if now < self.locked_until:
            return None, 'Too many attempts. Try again later.'
        if now - self.pin_born > PIN_LIFETIME:
            return None, 'Pairing code expired. Restart the receiver.'
        if not isinstance(supplied, str) or not hmac.compare_digest(supplied, self.pin):
            self.failed += 1
            if self.failed >= 6:
                self.failed = 0
                self.locked_until = now + 300
            return None, 'Incorrect pairing code.'
        self.failed = 0
        self.session = secrets.token_urlsafe(32)
        self.session_until = now + SESSION_LIFETIME
        self.armed_until = 0.0
        self.seen.clear()
        return self.session, None

    def set_armed(self, token, enabled):
        if not self.authenticated(token):
            return False
        self.armed_until = time.monotonic() + ARM_TIMEOUT if enabled else 0.0
        return True

    def heartbeat(self, token):
        if self.armed(token):
            self.armed_until = time.monotonic() + ARM_TIMEOUT

    def apply(self, token, payload):
        """Return (HTTP code, result). Lock must be held externally."""
        if not self.authenticated(token):
            return 401, {'error': 'Please pair again.'}
        if not self.armed(token):
            return 409, {'error': 'Input is paused. Tap Start first.'}
        event_id = payload.get('id')
        if not isinstance(event_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{8,80}', event_id):
            return 400, {'error': 'Invalid event ID.'}
        if event_id in self.seen:
            return 200, {'ok': True, 'duplicate': True}
        action = payload.get('action')
        if action == 'edit':
            erase, value = payload.get('erase'), payload.get('text')
            if (type(erase) is not int or erase < 0 or erase > 1000
                    or not isinstance(value, str) or len(value) > 1000
                    or '\x00' in value or '\r' in value):
                return 400, {'error': 'Invalid edit operation.'}
            try:
                if erase:
                    self.keyboard.backspace(erase)
                if value:
                    self.keyboard.text(value)
            except Exception:
                self.armed_until = 0.0
                return 500, {'error': 'Keyboard injection failed. Operation may be partial; input paused.'}
        elif action == 'key':
            key = payload.get('key')
            if key not in WindowsKeyboard.VK_KEYS:
                return 400, {'error': 'Unsupported key.'}
            try:
                self.keyboard.key(key)
            except Exception:
                self.armed_until = 0.0
                return 500, {'error': 'Keyboard injection failed. Input paused.'}
        else:
            return 400, {'error': 'Unknown action.'}
        self.seen[event_id] = True
        if len(self.seen) > 300:
            self.seen.popitem(last=False)
        return 200, {'ok': True}


def create_handler(state):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'RemoteKeyboard/0.1'
        sys_version = ''

        def log_message(self, fmt, *args):
            pass

        def reply(self, code, body, cookie=None):
            data = json.dumps(body, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self._common_headers()
            self.send_header('Content-Length', str(len(data)))
            if cookie:
                self.send_header('Set-Cookie', cookie)
            self.end_headers()
            self.wfile.write(data)

        def _common_headers(self):
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")

        def _token(self):
            cookies = http.cookies.SimpleCookie()
            try:
                cookies.load(self.headers.get('Cookie', ''))
                return cookies['rk_session'].value if 'rk_session' in cookies else None
            except http.cookies.CookieError:
                return None

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == '/api/status':
                token = self._token()
                with state.lock:
                    paired = state.authenticated(token)
                    if paired:
                        state.heartbeat(token)
                    enabled = state.armed(token) if paired else False
                return self.reply(200, {'paired': paired, 'enabled': enabled})
            files = {'/': ('index.html', 'text/html; charset=utf-8'),
                     '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                     '/cat.svg': ('cat.svg', 'image/svg+xml'),
                     '/style.css': ('style.css', 'text/css; charset=utf-8')}
            if path not in files:
                return self.reply(404, {'error': 'Not found.'})
            filename, content_type = files[path]
            data = (HERE / filename).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self._common_headers()
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            path = urlsplit(self.path).path
            if path not in ('/api/pair', '/api/control', '/api/input'):
                return self.reply(404, {'error': 'Not found.'})
            # Drain bounded request bodies before sending early rejections.
            # Windows can reset a socket closed with unread incoming data.
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length < 1 or length > MAX_JSON_BYTES:
                    return self.reply(413, {'error': 'Invalid payload size.'})
                raw = self.rfile.read(length)
            except ValueError:
                return self.reply(400, {'error': 'Invalid payload size.'})
            origin = self.headers.get('Origin', '')
            host = self.headers.get('Host', '')
            if (not origin or not host or urlsplit(origin).netloc.lower() != host.lower()
                    or urlsplit(origin).scheme not in ('http', 'https')
                    or self.headers.get('X-Remote-Keyboard') != '1'):
                return self.reply(403, {'error': 'Same-origin request required.'})
            if not self.headers.get('Content-Type', '').startswith('application/json'):
                return self.reply(415, {'error': 'JSON required.'})
            try:
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise ValueError('Not a JSON object.')
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
                return self.reply(400, {'error': 'Invalid JSON.'})

            if path == '/api/pair':
                with state.lock:
                    token, error = state.pair(payload.get('code'))
                if error:
                    return self.reply(403, {'error': error})
                cookie = f'rk_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_LIFETIME}'
                if urlsplit(origin).scheme == 'https':
                    cookie += '; Secure'
                return self.reply(200, {'ok': True}, cookie=cookie)
            session = self._token()
            with state.lock:
                if not state.authenticated(session):
                    return self.reply(401, {'error': 'Please pair again.'})
                if path == '/api/control':
                    enabled = payload.get('enabled')
                    if type(enabled) is not bool:
                        return self.reply(400, {'error': 'Invalid control state.'})
                    state.set_armed(session, enabled)
                    return self.reply(200, {'ok': True, 'enabled': state.armed(session)})
                status, result = state.apply(session, payload)
                return self.reply(status, result)

    return Handler


def main():
    if os.name != 'nt':
        print('This receiver runs only on Windows. On other OSes, run unit tests instead.')
        return 1
    keyboard = WindowsKeyboard()
    state = State(keyboard)
    server = ThreadingHTTPServer((HOST, PORT), create_handler(state))
    server.daemon_threads = True
    print('Remote Keyboard v0.1 (local-only receiver)')
    print(f'PC preview: http://{HOST}:{PORT}')
    print(f'Pairing PIN (valid for 30 minutes): {state.pin}')
    print('To connect iPhone, use Tailscale Serve and its HTTPS URL.')
    print('Input is PAUSED until enabled in the browser.')
    print('Close the window or press Ctrl+C to stop the receiver.')
    print('Do NOT use Tailscale Funnel or router port forwarding.')
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
