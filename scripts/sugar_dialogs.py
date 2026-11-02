"""Themed, keyboard-accessible local dialogs; cancellation never confirms motion."""
import fnmatch
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from scripts import sugar_theme as theme


def _window(parent, title, width=660, height=340):
    parent = parent or tk._default_root
    win = tk.Toplevel(parent)
    win.title(title or '糖画坊')
    win.transient(parent.winfo_toplevel())
    sw, sh = parent.winfo_screenwidth(), parent.winfo_screenheight()
    width, height = min(width, sw-24), min(height, sh-30)
    win.geometry('%dx%d+%d+%d' % (width, height, (sw-width)//2, (sh-height)//2))
    win.minsize(min(width,480), min(height,260))
    theme.brand_header(win, title or '提示')
    return win


def _wait(win, cancel):
    previous = win.grab_current()
    win.protocol('WM_DELETE_WINDOW', cancel)
    win.bind('<Escape>', lambda e: cancel())
    try:
        win.wait_visibility()
        win.grab_set()
        win.wait_window()
    except tk.TclError:
        # Escape/close can destroy a dialog before the window manager maps it.
        if win.winfo_exists():
            raise
    if previous is not None:
        try:
            if previous.winfo_exists(): previous.grab_set()
        except tk.TclError:
            pass


class MessageDialogs:
    def _show(self, title=None, message=None, parent=None, question=False, **kwargs):
        win = _window(parent, title)
        result = [False if question else 'ok']
        body = ttk.Frame(win, padding=18); body.pack(fill='both', expand=True)
        content = tk.Text(body, wrap='word', height=5, font='TkDefaultFont', padx=10, pady=10)
        content.insert('1.0', str(message or '') + ('\n\n'+str(kwargs['detail']) if kwargs.get('detail') else ''))
        content.configure(state='disabled')
        scroll = ttk.Scrollbar(body, command=content.yview)
        content.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');content.pack(fill='both',expand=True)
        buttons = ttk.Frame(win, padding=(18,8,18,16)); buttons.pack(fill='x')
        def close(value=False):
            result[0] = value if question else 'ok'; win.destroy()
        if question:
            safe = ttk.Button(buttons,text='取消',command=close)
            safe.pack(side='right',padx=(8,0));safe.focus_set()
        affirmative = ttk.Button(buttons, text='确认' if question else '知道了', style='Primary.TButton',
                                 command=lambda:close(True))
        affirmative.pack(side='right')
        if not question: affirmative.focus_set()
        # Return/Space operate the focused button; confirmation is never the
        # implicit default for a motion-related question.
        win.bind('<Return>', lambda e: win.focus_get().invoke()
                 if isinstance(win.focus_get(), ttk.Button) else None)
        _wait(win, close)
        return result[0]

    def showinfo(self, title=None, message=None, **kwargs): return self._show(title,message,**kwargs)
    def showwarning(self, title=None, message=None, **kwargs): return self._show(title,message,**kwargs)
    def showerror(self, title=None, message=None, **kwargs): return self._show(title,message,**kwargs)
    def askokcancel(self, title=None, message=None, **kwargs): return self._show(title,message,question=True,**kwargs)
    def askyesno(self, title=None, message=None, **kwargs): return self._show(title,message,question=True,**kwargs)


messagebox = MessageDialogs()


class FileDialogs:
    def askopenfilename(self, **kwargs): return self._choose(False, **kwargs)
    def asksaveasfilename(self, **kwargs): return self._choose(True, **kwargs)

    def _choose(self, save, parent=None, title=None, initialdir=None, initialfile='',
                filetypes=(), defaultextension='', **kwargs):
        win = _window(parent, title or ('保存文件' if save else '选择文件'), 900, 550)
        result = ['']; directory = [Path(initialdir or Path.home()).expanduser()]
        if not directory[0].is_dir(): directory[0] = Path.home()
        area = ttk.Frame(win,padding=12);area.pack(fill='both',expand=True)
        nav = ttk.Frame(area);nav.pack(fill='x',pady=(0,8))
        path_var = tk.StringVar(value=str(directory[0]))
        entry = ttk.Entry(nav,textvariable=path_var);entry.pack(side='left',fill='x',expand=True)
        table = ttk.Frame(area);table.pack(fill='both',expand=True)
        tree = ttk.Treeview(table,columns=('name','type'),show='headings',selectmode='browse')
        tree.heading('name',text='文件 / 文件夹');tree.heading('type',text='类型')
        tree.column('name',width=550);tree.column('type',width=110,stretch=False)
        scrollbar = ttk.Scrollbar(table,command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set);scrollbar.pack(side='right',fill='y');tree.pack(fill='both',expand=True)
        status = tk.StringVar(value='')
        status_label=ttk.Label(area,textvariable=status,foreground=theme.MUTED)
        status_label.pack(anchor='w')
        row = ttk.Frame(area);row.pack(fill='x',pady=8)
        ttk.Label(row,text='文件名').pack(side='left')
        name = tk.StringVar(value=initialfile)
        name_entry=ttk.Entry(row,textvariable=name);name_entry.pack(side='left',fill='x',expand=True,padx=8)
        choices = list(filetypes) or [('所有文件','*')]
        filters = ttk.Combobox(row,state='readonly',values=[v[0] for v in choices],width=16)
        filters.current(0);filters.pack(side='right')
        items = {}
        def refresh(target=None):
            try:
                folder=Path(target or path_var.get()).expanduser().resolve()
                if not folder.is_dir(): raise ValueError('请选择文件夹')
                pattern=choices[max(0,filters.current())][1]
                patterns=pattern.split() if isinstance(pattern,str) else list(pattern)
                files=sorted(folder.iterdir(),key=lambda p:(not p.is_dir(),p.name.casefold()))
                selected=[p for p in files if p.is_dir() or any(x in ('*','*.*') or fnmatch.fnmatch(p.name.lower(),x.lower()) for x in patterns)]
            except (OSError, ValueError) as exc:
                status.set('无法打开：'+str(exc));return
            directory[0]=folder;path_var.set(str(folder));items.clear()
            tree.delete(*tree.get_children())
            for i,path in enumerate(selected):
                key=str(i);items[key]=path
                tree.insert('', 'end', iid=key, values=(path.name,'文件夹' if path.is_dir() else path.suffix.upper().lstrip('.')))
            status.set('%d 项 · 双击文件夹进入，选择文件后确认' % len(selected))
        def select(_event=None):
            current=tree.selection()
            if current and not items[current[0]].is_dir(): name.set(items[current[0]].name)
        def enter(_event=None):
            current=tree.selection()
            if current and items[current[0]].is_dir():refresh(items[current[0]])
            else:select()
        def accept():
            text=name.get().strip()
            if not text: status.set('请先选择或填写文件名');return
            path=Path(text).expanduser()
            if not path.is_absolute():path=directory[0]/path
            if path.is_dir():refresh(path);return
            if save and defaultextension and not path.suffix:path=path.with_suffix(defaultextension)
            if not path.parent.is_dir():status.set('目标文件夹不存在');return
            if not save and not path.is_file():status.set('文件不存在，请重新选择');return
            if save and path.exists() and not messagebox.askyesno('覆盖文件', '文件已存在，确认覆盖？\n'+str(path),parent=win):return
            result[0]=str(path);win.destroy()
        ttk.Button(nav,text='打开目录',command=refresh).pack(side='left',padx=5)
        ttk.Button(nav,text='上一级',command=lambda:refresh(directory[0].parent)).pack(side='left')
        entry.bind('<Return>',lambda e:refresh())
        filters.bind('<<ComboboxSelected>>',lambda e:refresh(directory[0]))
        tree.bind('<<TreeviewSelect>>',select);tree.bind('<Double-1>',enter)
        buttons=ttk.Frame(area);buttons.pack(fill='x')
        buttons.pack_configure(side='bottom',before=table)
        row.pack_configure(side='bottom',before=table)
        status_label.pack_configure(side='bottom',before=table)
        if getattr(parent or tk._default_root,'so101_touch',False):
            from scripts.touch_ui import TouchKeyboard
            keyboard=TouchKeyboard(win)
            ttk.Button(buttons,text='输入键盘',command=keyboard.show).pack(side='left')
        ttk.Button(buttons,text='取消',command=win.destroy).pack(side='right',padx=(8,0))
        ttk.Button(buttons,text='保存' if save else '选择',style='Primary.TButton',command=accept).pack(side='right')
        refresh(directory[0]);name_entry.focus_set()
        _wait(win,win.destroy)
        return result[0]


filedialog = FileDialogs()
