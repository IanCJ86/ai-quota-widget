"""Real event marshalling with the production App, no account or native tray."""
import faulthandler
import json
import threading
import time
from collections import deque
import ctypes
from ctypes import wintypes
from test_monitor import UITests

faulthandler.enable()
faulthandler.dump_traceback_later(12,exit=True)
fixture=UITests();fixture.setUp();app=fixture.app
owner=threading.get_ident()
seen=[];delays=[];issued=deque()
original=app._commands.get_nowait
def receive():
    command=original()
    if command=='show':
        seen.append(threading.get_ident())
        delays.append(time.monotonic()-issued.popleft())
    return command
app._commands.get_nowait=receive
def producer():
    for i in range(50):
        issued.append(time.monotonic())
        app._commands.put('show')
        time.sleep(.012)
    app._commands.put('quit')
app.root.withdraw()
app.root.after(30,lambda:threading.Thread(target=producer,daemon=True).start())
def popup():
    # A real Win32 popup runs its nested event loop while commands keep arriving.
    api=ctypes.windll.user32
    callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    api.EnumThreadWindows.argtypes=[wintypes.DWORD,callback,wintypes.LPARAM]
    api.GetClassNameW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    api.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
    tid=threading.get_native_id()
    def cancel():
        @callback
        def visit(hwnd,_):
            text=ctypes.create_unicode_buffer(128)
            api.GetClassNameW(hwnd,text,len(text))
            if text.value=='#32768':
                api.PostMessageW(hwnd,0x100,0x1b,0)
                api.PostMessageW(hwnd,0x101,0x1b,0)
            return True
        api.EnumThreadWindows(tid,visit,0)
    app.root.after(70,cancel)
    app.menu.tk_popup(100,100)
    app.menu.grab_release()
app.root.after(160,popup)
app.root.after(5000,app._quit)
try:
    app.run()
    assert app._closed
    assert len(seen)==50
    assert seen and all(x==owner for x in seen)
    print(json.dumps(dict(commands=len(seen),max_delay=max(delays),main_thread_only=True)))
finally:
    fixture.tearDown()
    faulthandler.cancel_dump_traceback_later()
