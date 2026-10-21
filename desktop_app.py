"""Tiny Windows receiver panel. No packages, autorun or input logging."""
from __future__ import annotations
import ctypes
from ctypes import wintypes as wt
from pathlib import Path
import queue
import threading
from http.server import ThreadingHTTPServer
from remote_keys import HOST, PORT, State, WindowsKeyboard, create_handler
from pixel_cat import PIXELS, COLORS, SIZE


class Receiver:
    """The desktop controls listening; the phone separately controls typing."""
    def __init__(self, keyboard_factory=WindowsKeyboard, port=PORT):
        self.keyboard_factory = keyboard_factory
        self.port = port
        self.state = None
        self.server = None
        self.worker = None

    @property
    def running(self):
        return self.server is not None

    def start(self):
        if self.running:
            return
        state = State(self.keyboard_factory())
        server = ThreadingHTTPServer((HOST, self.port), create_handler(state))
        server.daemon_threads = True
        worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval':0.1}, daemon=True)
        try:
            worker.start()
        except Exception:
            server.server_close()
            raise
        self.state, self.server, self.worker = state, server, worker

    def stop(self):
        if not self.running:
            return
        state, server, worker = self.state, self.server, self.worker
        # Invalidate held references too: no handler may re-pair after STOP.
        with state.lock:
            state.armed_until = 0.0
            state.session = None
            state.session_until = 0.0
            state.pin_born = float('-inf')
            state.locked_until = float('inf')
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
        self.state = self.server = self.worker = None


class TrayIcon:
    """A Tk-owned notification icon; callbacks are delivered via a queue."""
    CALLBACK = 0x8000 + 24
    def __init__(self, root, commands):
        self.root, self.commands = root, commands
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.shell = ctypes.WinDLL('shell32', use_last_error=True)
        self.callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
        class GUID(ctypes.Structure):
            _fields_=[('a',wt.DWORD),('b',wt.WORD),('c',wt.WORD),('d',ctypes.c_ubyte*8)]
        class NID(ctypes.Structure):
            _fields_=[('cbSize',wt.DWORD),('hWnd',wt.HWND),('uID',wt.UINT),('uFlags',wt.UINT),
                      ('uCallbackMessage',wt.UINT),('hIcon',wt.HICON),('szTip',wt.WCHAR*128),
                      ('dwState',wt.DWORD),('dwStateMask',wt.DWORD),('szInfo',wt.WCHAR*256),
                      ('uVersion',wt.UINT),('szInfoTitle',wt.WCHAR*64),('dwInfoFlags',wt.DWORD),
                      ('guidItem',GUID),('hBalloonIcon',wt.HICON)]
        self.user.GetParent.argtypes=[wt.HWND]; self.user.GetParent.restype=wt.HWND
        self.user.SetWindowLongPtrW.argtypes=[wt.HWND,ctypes.c_int,ctypes.c_void_p]
        self.user.SetWindowLongPtrW.restype=ctypes.c_void_p
        self.user.CallWindowProcW.argtypes=[ctypes.c_void_p,wt.HWND,wt.UINT,wt.WPARAM,wt.LPARAM]
        self.user.CallWindowProcW.restype=ctypes.c_ssize_t
        self.user.LoadImageW.argtypes=[wt.HINSTANCE,wt.LPCWSTR,wt.UINT,ctypes.c_int,ctypes.c_int,wt.UINT]
        self.user.LoadImageW.restype=wt.HANDLE
        self.user.DestroyIcon.argtypes=[wt.HICON]
        self.user.RegisterWindowMessageW.argtypes=[wt.LPCWSTR]; self.user.RegisterWindowMessageW.restype=wt.UINT
        self.shell.Shell_NotifyIconW.argtypes=[wt.DWORD,ctypes.POINTER(NID)]
        self.shell.Shell_NotifyIconW.restype=wt.BOOL
        root.update_idletasks()
        self.hwnd = self.user.GetParent(root.winfo_id()) or root.winfo_id()
        self.icon = self.user.LoadImageW(None,str(Path(__file__).with_name('cat.ico')),1,0,0,0x10)
        if not self.icon:
            raise ctypes.WinError(ctypes.get_last_error())
        self.data=NID(); self.data.cbSize=ctypes.sizeof(NID); self.data.hWnd=self.hwnd
        self.data.uID=24; self.data.uFlags=1|2|4; self.data.uCallbackMessage=self.CALLBACK
        self.data.hIcon=self.icon; self.data.szTip='Remote Keyboard - STOPPED'
        self.taskbar_created=self.user.RegisterWindowMessageW('TaskbarCreated')
        self.callback=self.callback_type(self._message)
        self.previous=self.user.SetWindowLongPtrW(self.hwnd,-4,ctypes.cast(self.callback,ctypes.c_void_p))
        if not self.previous:
            self.user.DestroyIcon(self.icon)
            raise ctypes.WinError(ctypes.get_last_error())
        self.available=False
        if not self._add():
            self.close()
            raise RuntimeError('Tray icon could not be added.')

    def _add(self):
        self.available=bool(self.shell.Shell_NotifyIconW(0,ctypes.byref(self.data)))
        if self.available:
            self.data.uVersion=4
            self.shell.Shell_NotifyIconW(4,ctypes.byref(self.data))
        return self.available

    def _message(self, hwnd, msg, wp, lp):
        if msg==self.CALLBACK:
            event=lp & 0xffff
            if event in (0x400,0x401,0x202,0x203): self.commands.put('show')
            elif event in (0x7b,0x205): self.commands.put('menu')
            return 0
        if msg==self.taskbar_created:
            self.commands.put('restore_tray')
        return self.user.CallWindowProcW(self.previous,hwnd,msg,wp,lp)

    def update(self, running):
        self.data.szTip='Remote Keyboard - '+('READY' if running else 'STOPPED')
        if self.available: self.shell.Shell_NotifyIconW(1,ctypes.byref(self.data))

    def close(self):
        if self.available:
            self.shell.Shell_NotifyIconW(2,ctypes.byref(self.data)); self.available=False
        if self.previous:
            self.user.SetWindowLongPtrW(self.hwnd,-4,self.previous); self.previous=None
        if self.icon:
            self.user.DestroyIcon(self.icon); self.icon=None


DIGITS={
 '0':('111','101','101','101','111'), '1':('010','110','010','010','111'),
 '2':('111','001','111','100','111'), '3':('111','001','111','001','111'),
 '4':('101','101','111','001','001'), '5':('111','100','111','001','111'),
 '6':('111','100','111','101','111'), '7':('111','001','010','010','010'),
 '8':('111','101','111','101','111'), '9':('111','101','111','001','111'),
 '-':('000','000','111','000','000')}
class PixelPIN:
    def __init__(self, parent):
        self.canvas=tk.Canvas(parent,width=218,height=32,bg='#202a29',highlightthickness=0)
        self.canvas.pack()
        self.show('------')
    def show(self, value):
        self.canvas.delete('all')
        scale=4; spacing=23; start=(218-(6*spacing-11))//2
        for n,char in enumerate(value):
            for y,row in enumerate(DIGITS[char]):
                for x,pixel in enumerate(row):
                    if pixel=='1':
                        xx=start+n*spacing+x*scale; yy=5+y*scale
                        self.canvas.create_rectangle(xx,yy,xx+scale-1,yy+scale-1,fill='#f7d18a',outline='')


class MiniPanel:
    def __init__(self, root):
        global tk
        import tkinter as tk
        self.root=root; self.receiver=Receiver(); self.commands=queue.SimpleQueue(); self.tray=None
        root.title('Remote Keyboard'); root.geometry('246x146'); root.resizable(False,False)
        root.overrideredirect(True)
        root.configure(bg='#202a29',highlightbackground='#779486',highlightthickness=2); root.attributes('-topmost',True)
        root.protocol('WM_DELETE_WINDOW',self.hide)
        self.cat=tk.PhotoImage(width=SIZE,height=SIZE)
        for y,row in enumerate(PIXELS):
            for x,c in enumerate(row):
                if c!='.':
                    r,g,b,_=COLORS[c]; self.cat.put(f'#{r:02x}{g:02x}{b:02x}',(x,y))
        self.cat=self.cat.zoom(2); root.iconphoto(True,self.cat)
        header=tk.Frame(root,bg='#202a29'); header.pack(fill='x',padx=12,pady=(8,0))
        cat_label=tk.Label(header,image=self.cat,bg='#202a29'); cat_label.pack(side='left')
        for widget in (header,cat_label):
            widget.bind('<ButtonPress-1>',self.drag_begin); widget.bind('<B1-Motion>',self.drag_move)
        self.status=tk.Label(header,text='STOPPED',fg='#a6b8a5',bg='#202a29',font=('Consolas',11,'bold'))
        self.status.pack(side='left',padx=9)
        self.status.bind('<ButtonPress-1>',self.drag_begin); self.status.bind('<B1-Motion>',self.drag_move)
        tk.Button(header,text='×',command=self.hide,font=('Consolas',12),bg='#202a29',fg='#a6b8a5',relief='flat',borderwidth=0,padx=2,pady=0).pack(side='right')
        self.pin=PixelPIN(root)
        buttons=tk.Frame(root,bg='#202a29'); buttons.pack(fill='x',padx=12,pady=(2,0))
        self.start_button=tk.Button(buttons,text='START',command=self.start,font=('Consolas',11,'bold'),
                                    bg='#a7cc9d',fg='#20352a',relief='flat',width=10,takefocus=True)
        self.start_button.pack(side='left')
        self.stop_button=tk.Button(buttons,text='STOP',command=self.stop,font=('Consolas',11,'bold'),
                                   bg='#db9c89',fg='#422d2c',relief='flat',width=10,state='disabled')
        self.stop_button.pack(side='right')
        tk.Label(root,text='PIN / 30 min   [x] -> tray',fg='#a6b8a5',bg='#202a29',font=('Consolas',9)).pack(pady=(5,0))
        self.menu=tk.Menu(root,tearoff=0)
        for label,command in [('表示',self.show),('START',self.start),('STOP',self.stop),('終了',self.quit)]:
            self.menu.add_command(label=label,command=command)
        try: self.tray=TrayIcon(root,self.commands)
        except Exception: pass  # If unavailable, keep the window reachable in the taskbar.
        self.fix_window_style()
        root.after(150,self.poll)

    def fix_window_style(self):
        # Borderless while retaining a normal app window for accessibility/taskbar.
        self.root.update_idletasks()
        user=ctypes.WinDLL('user32',use_last_error=True)
        user.GetParent.argtypes=[wt.HWND]; user.GetParent.restype=wt.HWND
        user.GetWindowLongPtrW.argtypes=[wt.HWND,ctypes.c_int]; user.GetWindowLongPtrW.restype=ctypes.c_ssize_t
        user.SetWindowLongPtrW.argtypes=[wt.HWND,ctypes.c_int,ctypes.c_ssize_t]; user.SetWindowLongPtrW.restype=ctypes.c_ssize_t
        user.SetWindowPos.argtypes=[wt.HWND,wt.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wt.UINT]
        hwnd=user.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        extended=user.GetWindowLongPtrW(hwnd,-20)
        user.SetWindowLongPtrW(hwnd,-20,(extended & ~0x80) | 0x40000)
        user.SetWindowPos(hwnd,None,0,0,0,0,0x01|0x02|0x04|0x20|0x10)

    def drag_begin(self, event):
        self.drag_offset=(event.x_root-self.root.winfo_x(),event.y_root-self.root.winfo_y())
    def drag_move(self, event):
        x=event.x_root-self.drag_offset[0]; y=event.y_root-self.drag_offset[1]
        self.root.geometry(f'+{max(0,x)}+{max(0,y)}')

    def start(self):
        try:
            self.receiver.start()
            self.pin.show(self.receiver.state.pin)
            self.status.configure(text='READY',fg='#b7df9d')
            self.start_button.configure(state='disabled'); self.stop_button.configure(state='normal')
            if self.tray: self.tray.update(True)
        except Exception:
            from tkinter import messagebox
            messagebox.showerror('Remote Keyboard','受信を開始できません。以前の受信ウィンドウが開いている場合は閉じてからSTARTしてください。',parent=self.root)

    def stop(self):
        self.receiver.stop(); self.pin.show('------')
        self.status.configure(text='STOPPED',fg='#a6b8a5')
        self.start_button.configure(state='normal'); self.stop_button.configure(state='disabled')
        if self.tray: self.tray.update(False)

    def show(self):
        self.root.deiconify(); self.fix_window_style(); self.root.lift()

    def hide(self):
        if self.tray and self.tray.available: self.root.withdraw()
        else: self.root.iconify()

    def poll(self):
        while not self.commands.empty():
            command=self.commands.get()
            if command=='show': self.show()
            elif command=='menu':
                self.show()
                try: self.menu.tk_popup(self.root.winfo_pointerx(),self.root.winfo_pointery())
                finally: self.menu.grab_release()
            elif command=='restore_tray' and self.tray:
                if not self.tray._add(): self.show()
        if self.receiver.running:
            with self.receiver.state.lock:
                import time
                expired=time.monotonic()-self.receiver.state.pin_born > 30*60
                typing=self.receiver.state.armed_until > time.monotonic()
            self.status.configure(text='PIN EXPIRED' if expired else ('TYPING' if typing else 'READY'))
        self.root.after(150,self.poll)

    def quit(self):
        self.stop()
        if self.tray: self.tray.close()
        self.root.destroy()


def main():
    import tkinter as tk
    import os
    mutex=None
    if os.name=='nt':
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wt.BOOL,wt.LPCWSTR]
        kernel.CreateMutexW.restype=wt.HANDLE
        kernel.CloseHandle.argtypes=[wt.HANDLE]
        mutex=kernel.CreateMutexW(None,False,'Local\\RemoteKeyboardMiniPanel')
        if not mutex: raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error()==183:
            kernel.CloseHandle(mutex)
            return
    root=tk.Tk()
    app=MiniPanel(root)
    try: root.mainloop()
    finally:
        app.receiver.stop()
        if app.tray: app.tray.close()
        if mutex: kernel.CloseHandle(mutex)

if __name__=='__main__': main()
