"""Bounded viewport and native monitor geometry, with portable fallbacks."""
import ctypes
from ctypes import wintypes
import tkinter as tk

def work_area(root, point=None):
    try:
        api = ctypes.windll.user32
        class Info(ctypes.Structure):
            _fields_ = [('size',wintypes.DWORD),('monitor',wintypes.RECT),('work',wintypes.RECT),('flags',wintypes.DWORD)]
        if point is None:
            api.MonitorFromWindow.argtypes = [wintypes.HWND,wintypes.DWORD]
            api.MonitorFromWindow.restype = wintypes.HANDLE
            handle = api.MonitorFromWindow(int(root.wm_frame(),16),2)
        else:
            api.MonitorFromPoint.argtypes = [wintypes.POINT,wintypes.DWORD]
            api.MonitorFromPoint.restype = wintypes.HANDLE
            handle = api.MonitorFromPoint(wintypes.POINT(*point),2)
        api.GetMonitorInfoW.argtypes = [wintypes.HANDLE,ctypes.POINTER(Info)]
        info = Info(size=ctypes.sizeof(Info))
        if not api.GetMonitorInfoW(handle,ctypes.byref(info)):
            raise OSError()
        r = info.work
        return r.left,r.top,r.right,r.bottom
    except Exception:
        return 0,0,root.winfo_screenwidth(),root.winfo_screenheight()-40

def clamp_rect(x,y,w,h,area):
    left,top,right,bottom = area
    w,h = min(w,max(1,right-left-8)),min(h,max(1,bottom-top-8))
    return w,h,max(left+4,min(x,right-w-4)),max(top+4,min(y,bottom-h-4))

class Viewport:
    def __init__(self,root):
        self.root = root
        self.canvas = tk.Canvas(root,highlightthickness=0,bd=0,width=1,height=1)
        self.canvas.grid(row=0,column=0,sticky='nsew')
        self.body = tk.Frame(self.canvas)
        self._window = self.canvas.create_window(0,0,window=self.body,anchor='nw')
        self.canvas.bind('<Configure>', self._stretch_body)
        self.vertical = tk.Scrollbar(root,orient='vertical',command=self.canvas.yview)
        self.horizontal = tk.Scrollbar(root,orient='horizontal',command=self.canvas.xview)
        self.vertical._no_drag = self.horizontal._no_drag = True
        self.canvas.configure(yscrollcommand=self.vertical.set,xscrollcommand=self.horizontal.set)
        root.grid_rowconfigure(0,weight=1)
        self.body.grid_columnconfigure(0,weight=1)
        self._size = None
        self._dpi = round(float(root.tk.call('tk','scaling'))*72)
        self._fonts = []
        root.bind('<MouseWheel>',self.wheel,add='+')

    def _stretch_body(self, event=None):
        # A wide footer must not leave a narrow, disconnected card island.
        width = max(self.body.winfo_reqwidth(), self.canvas.winfo_width())
        self.canvas.itemconfigure(self._window, width=width)

    def wheel(self,event):
        if self.vertical.winfo_manager():
            self.canvas.yview_scroll(-1 if event.delta>0 else 1,'units')

    def fit(self,area):
        left,top,right,bottom=area
        w,h=self.body.winfo_reqwidth(),self.body.winfo_reqheight()
        max_w,max_h=max(60,right-left-32),max(40,bottom-top-76)
        vertical=h>max_h
        horizontal=w>max_w
        size=(w,h,min(w,max_w),min(h,max_h),vertical,horizontal)
        if size!=self._size:
            self.canvas.configure(width=size[2],height=size[3],scrollregion=(0,0,w,h))
            if vertical:
                self.vertical.grid(row=0,column=1,sticky='ns')
            else:
                self.vertical.grid_remove()
                self.canvas.yview_moveto(0)
            if horizontal:
                self.horizontal.grid(row=1,column=0,sticky='ew')
            else:
                self.horizontal.grid_remove()
                self.canvas.xview_moveto(0)
            self._size=size
        self._stretch_body()

    def update_dpi(self,app):
        try:
            api=ctypes.windll.user32.GetDpiForWindow
            api.argtypes=[wintypes.HWND]
            api.restype=wintypes.UINT
            dpi=api(int(self.root.wm_frame(),16))
            if not dpi or dpi==self._dpi:
                return False
            if self._dpi is None:
                self._dpi=dpi
                return False
            self._dpi=dpi
            self.root.tk.call('tk','scaling',dpi/72)
            from tkinter import font
            fonts = {}
            def visit(widget):
                if isinstance(widget,tk.Label):
                    spec=font.Font(root=self.root,font=widget.cget('font')).actual()
                    key=tuple(sorted(spec.items()))
                    if key not in fonts:
                        fonts[key]=font.Font(root=self.root,**spec)
                    # A new named font is essential: reapplying the same tuple
                    # reuses Tk's cached old-DPI metrics while other labels use it.
                    widget.configure(font=fonts[key])
                for child in widget.winfo_children():
                    visit(child)
            visit(self.root)
            self._fonts=list(fonts.values())
            for name, card in zip(app.section_titles, app._cards):
                header = app.section_titles[name].master
                height = font.Font(font=app.section_titles[name].cget('font')).metrics('linespace')+4
                card.winfo_children()[0].configure(height=height)
                header.place_configure(height=height)
            painter=app.theme_painter
            painter.scale=dpi/96
            painter.canvas.configure(width=236*painter.scale,height=50*painter.scale)
            painter._draw_key=None
            painter.draw()
            return True
        except Exception:
            return False
