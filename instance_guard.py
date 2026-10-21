"""Windows-only, same-session graceful replacement; no network control port."""
import ctypes
from ctypes import wintypes as wt


class InstanceGuard:
    def __init__(self, name=r'Local\RemoteKeyboardMiniPanel'):
        self.name = name
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        for method, args, result in (
            ('CreateMutexW', [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR], wt.HANDLE),
            ('CreateEventW', [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR], wt.HANDLE),
            ('OpenEventW', [wt.DWORD, wt.BOOL, wt.LPCWSTR], wt.HANDLE),
            ('SetEvent', [wt.HANDLE], wt.BOOL),
            ('WaitForSingleObject', [wt.HANDLE, wt.DWORD], wt.DWORD),
            ('ReleaseMutex', [wt.HANDLE], wt.BOOL),
            ('CloseHandle', [wt.HANDLE], wt.BOOL),
        ):
            fn = getattr(self.kernel, method)
            fn.argtypes, fn.restype = args, result
        self.mutex = self.event = None
        self.owned = False

    def acquire(self, confirm, timeout_ms=8000):
        self.mutex = self.kernel.CreateMutexW(None, True, self.name)
        error = ctypes.get_last_error()
        if not self.mutex:
            raise ctypes.WinError(error)
        self.owned = error != 183
        if not self.owned:
            if not confirm():
                return False
            event = self.kernel.OpenEventW(2, False, self.name + '.Restart')
            if not event:
                raise RuntimeError('以前のバージョンが起動中です。既存のネコのトレイメニューから「終了」を選び、もう一度起動してください。')
            try:
                if not self.kernel.SetEvent(event):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                self.kernel.CloseHandle(event)
            result = self.kernel.WaitForSingleObject(self.mutex, timeout_ms)
            if result not in (0, 0x80):  # acquired, or previous owner exited unexpectedly
                raise RuntimeError('以前のアプリの終了を確認できませんでした。重複起動は中止しました。終了後にもう一度起動してください。')
            self.owned = True
        self.event = self.kernel.CreateEventW(None, True, False, self.name + '.Restart')
        if not self.event:
            raise ctypes.WinError(ctypes.get_last_error())
        return True

    def restart_requested(self):
        return bool(self.event and self.kernel.WaitForSingleObject(self.event, 0) == 0)

    def close(self):
        # Close the old event before releasing ownership so the next owner gets a fresh event.
        if self.event:
            self.kernel.CloseHandle(self.event)
            self.event = None
        if self.mutex:
            if self.owned:
                self.kernel.ReleaseMutex(self.mutex)
            self.kernel.CloseHandle(self.mutex)
            self.mutex = None
            self.owned = False
