"""Small-screen helpers shared by the Linux console and its dialogs."""
import tkinter as tk
from tkinter import ttk


def fit_window(win, root, width=1000, height=630):
    touch = getattr(root, 'so101_touch', False)
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    if touch:
        sw, sh = root.winfo_width(), root.winfo_height()
    width, height = min(width, max(480, sw - 20)), min(height, max(300, sh - 40))
    win.geometry('%dx%d+0+0' % (width, height))
    win.minsize(min(640, width), min(360, height))
    return width, height


def wrap_rows(parent, width):
    """Reflow existing control rows without changing any command bindings."""
    for frame in parent.winfo_children():
        wrap_rows(frame, width)
        if frame.winfo_class() != 'TFrame':
            continue
        children = frame.pack_slaves()
        if not children or any(c.pack_info().get('side') not in ('left', 'right') for c in children):
            continue
        if any(c.winfo_class() in ('Canvas', 'Text', 'Treeview', 'TScrollbar', 'TFrame') for c in children):
            continue
        sizes = [min(c.winfo_reqwidth() + 12, width) for c in children]
        if sum(sizes) <= width:
            continue
        for c in children:
            c.pack_forget()
        row, column, used = 0, 0, 0
        for c, size in zip(children, sizes):
            if column and used + size > width:
                row += 1; column = 0; used = 0
            c.grid(row=row, column=used, columnspan=size, sticky='w', padx=3, pady=5)
            column += 1; used += size


def scroll_page(page, root):
    """Keep complete settings reachable at the panel's 1024 x 600 size."""
    canvas = tk.Canvas(page, highlightthickness=0)
    bar = ttk.Scrollbar(page, orient='vertical', command=canvas.yview)
    canvas.configure(yscrollcommand=bar.set)
    bar.pack(side='right', fill='y')
    if getattr(root, 'so101_touch', False):
        nav = ttk.Frame(page);nav.pack(side='right', fill='y')
        ttk.Button(nav,text='上',width=3,command=lambda:canvas.yview_scroll(-1,'pages')).pack(pady=5)
        ttk.Button(nav,text='下',width=3,command=lambda:canvas.yview_scroll(1,'pages')).pack(pady=5)
        ttk.Button(nav,text='顶',width=3,command=lambda:canvas.yview_moveto(0)).pack(pady=5)
    canvas.pack(fill='both', expand=True)
    body = ttk.Frame(canvas)
    item = canvas.create_window((0,0),window=body,anchor='nw')
    body.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width))
    def wheel(event):
        if not page.winfo_ismapped():return
        w=root.winfo_containing(event.x_root,event.y_root)
        if w is None or w.winfo_class() in ('Text','TCombobox','TSpinbox','Treeview'):return
        while w is not None:
            if w == canvas:
                canvas.yview_scroll(-3 if getattr(event,'num',None)==4 or event.delta>0 else 3,'units')
                return 'break'
            w=getattr(w,'master',None)
    for event in ('<MouseWheel>','<Button-4>','<Button-5>'):root.bind(event,wheel,add='+')
    return body


class TouchKeyboard:
    """ASCII/numeric keyboard for existing entry widgets; does not send motion."""
    def __init__(self, root):
        self.root, self.target, self.win = root, None, None
        self.upper = False
        self._focus_binding = root.bind_all('<FocusIn>', self.remember, add='+')
        root.bind('<Destroy>', self._cleanup, add='+')

    def _cleanup(self, event):
        if event.widget == self.root and self._focus_binding:
            # Tkinter 3.8 lacks Misc._unbind; remove only this callback, leaving
            # the main console keyboard's global listener intact.
            binding=self._focus_binding
            script=self.root.tk.call('bind','all','<FocusIn>')
            script='\n'.join(line for line in script.splitlines()
                             if not line.startswith('if {"['+binding+' '))
            self.root.tk.call('bind','all','<FocusIn>',script)
            owner=self.root if binding in (self.root._tclCommands or []) else self.root._root()
            owner.deletecommand(binding)
            self._focus_binding = None

    def remember(self, event):
        if not isinstance(event.widget, tk.Misc):
            return  # Tcl-owned combobox popdown windows are reported as names.
        if event.widget.winfo_class() in ('TEntry', 'TSpinbox', 'Entry', 'Text'):
            if self.win is None or event.widget.winfo_toplevel() != self.win:
                self.target = event.widget

    def show(self):
        if self.win and self.win.winfo_exists():
            self.win.lift(); return
        self.win = tk.Toplevel(self.root)
        self.win.title('输入键盘  先选择输入框')
        self.win.transient(self.root)
        self.win.geometry('900x450+0+140')
        self.win.resizable(False, False)
        for ri, chars in enumerate(('1234567890', 'qwertyuiop', 'asdfghjkl', 'zxcvbnm', '!@#$%^&*()', '-_=+[]{}\\|', ';:\'",.<>/?', '`~')):
            row = ttk.Frame(self.win); row.pack(fill='x')
            for char in chars:
                ttk.Button(row, text=char, width=4, takefocus=False,
                           command=lambda v=char: self.insert(v)).pack(side='left', expand=True, pady=2)
        row = ttk.Frame(self.win); row.pack(fill='x')
        ttk.Button(row,text='大小写',takefocus=False,command=lambda:setattr(self,'upper',not self.upper)).pack(side='left')
        for text, value in [('空格',' '),('引号','"'),('退格',None)]:
            ttk.Button(row,text=text,takefocus=False,command=lambda v=value:self.insert(v)).pack(side='left',expand=True)
        ttk.Button(row,text='关闭键盘',command=self.win.destroy,takefocus=False).pack(side='right')

    def insert(self, value):
        w = self.target
        if w is None or not w.winfo_exists():
            return
        try:
            if value is None:
                if w.winfo_class() == 'Text': w.delete('insert-1c','insert')
                else:
                    index=w.index('insert')
                    if index: w.delete(index-1,index)
            else:
                w.insert('insert',value.upper() if self.upper else value)
        except tk.TclError:
            pass


def configure_touch_console(app, notebook, log_frame):
    root=app.root
    app._touch_notebook=notebook
    notebook.hide(app.tab_hand)
    notebook.add(log_frame, text='运行日志')
    app.lbl_info.configure(wraplength=430)
    app.log.configure(height=8)
    app._draw_canvas.configure(height=380)
    app.tree.configure(height=4)
    app.txt_cfg.configure(height=5)
    root.update_idletasks()
    wrap_rows(app.tab_draw,max(500,root.winfo_width()-85))
    wrap_rows(app.tab_servo,max(500,root.winfo_width()-85))
    for page in (app.tab_draw, app.tab_servo):
        def constrain(widget):
            if widget.winfo_class()=='TLabel':
                widget.configure(wraplength=max(400,root.winfo_width()-100))
            for child in widget.winfo_children():constrain(child)
        constrain(page)

