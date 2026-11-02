"""Tk drawing prediction with globally numbered segments and a scrub timeline."""
import hashlib
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from scripts.sugar_dialogs import filedialog, messagebox
from scripts import sugar_theme as theme

from drawing_prediction import export_order_csv, export_preview_svg


class DrawingPreviewWindow:
    def __init__(self, root, preview, source_path=None):
        theme.install(root, getattr(root, 'so101_touch', False))
        self.data = preview
        self.win = tk.Toplevel(root)
        self.win.title('预测绘画效果 · 每条线段顺序 — ' + preview['title'])
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        self.win.geometry('%dx%d' % (min(1100, sw-80), min(790, sh-110)))
        self.win.minsize(min(920, sw-80), min(650, sh-110))
        if getattr(root, 'so101_touch', False):
            from scripts.touch_ui import fit_window
            fit_window(self.win, root, 1000, 560)
        self._timer = None; self._rendered = 0; self._ink = {}; self._ready = False
        self._background = None
        if source_path and Path(source_path).is_file():
            try:
                if hashlib.sha256(Path(source_path).read_bytes()).hexdigest() == preview.get('source_sha256'):
                    from PIL import Image, ImageOps
                    with Image.open(source_path) as image:
                        image = ImageOps.exif_transpose(image).convert('RGB')
                        self._background = Image.blend(Image.new('RGB', image.size, theme.BG), ImageOps.invert(image), .28)
            except OSError: pass
        top = ttk.Frame(self.win, padding=8); top.pack(fill='x')
        summary = '%s · %d 笔画 / %d 落笔线段 · %.1f × %.1f mm' % (
            preview['title'], preview['strokes'], preview['segments'], preview['width_mm'], preview['height_mm'])
        if preview['mode'] in ('commands','feedback'):
            summary += (' · 编码器模型跟随最大偏差 %.3f mm' if preview['mode']=='feedback' else
                        ' · 指令目标最大偏差 %.3f mm') % preview['max_command_target_error_mm']
            if preview.get('motion_algorithm_version') == 'motion-smooth-v1':
                summary += ' · %s / 必要停点 %s' % ({'speed_priority':'速度优先','smooth_fast':'平滑加速'}.get(preview.get('motion_mode'),'平缓'),
                                                 preview.get('hard_stop_knots','?'))
        ttk.Label(top, text=summary,wraplength=1050).pack(side='left')
        if preview.get('drawing_offset_mm') is not None:
            x,y=preview['drawing_offset_mm']
            summary_position='相对纸面基准：横移 %+g mm / 纵移 %+g mm。下图显示图案内部坐标与顺序。'%(x,y)
            ttk.Label(self.win,text=summary_position,foreground=theme.LIGHT,padding=(8,0,8,4)).pack(fill='x')
        ttk.Label(self.win, text=preview['explanation'], wraplength=1050,
                  foreground=theme.MUTED, padding=(8, 0, 8, 5)).pack(fill='x')
        controls = ttk.Frame(self.win, padding=(8, 0, 8, 6)); controls.pack(fill='x')
        self.btn_play = ttk.Button(controls, text='顺序播放', command=self.play); self.btn_play.pack(side='left')
        self.btn_pause = ttk.Button(controls, text='暂停', command=self.pause); self.btn_pause.pack(side='left', padx=3)
        ttk.Button(controls, text='上一段', command=lambda: self.seek(self.position.get()-1)).pack(side='left', padx=3)
        self.btn_next = ttk.Button(controls, text='下一段', command=lambda: self.seek(self.position.get()+1))
        self.btn_next.pack(side='left', padx=3)
        ttk.Button(controls, text='从头查看', command=lambda: self.seek(0)).pack(side='left', padx=3)
        ttk.Button(controls, text='最终效果', command=lambda: self.seek(preview['segments'])).pack(side='left', padx=3)
        ttk.Label(controls, text='演示速度:').pack(side='left', padx=(8, 3))
        self.speed = tk.StringVar(value='正常')
        ttk.Combobox(controls, textvariable=self.speed, values=('慢', '正常', '快', '很快'),
                     width=6, state='readonly').pack(side='left')
        ttk.Button(controls, text='导出顺序 CSV', command=self.export_csv).pack(side='right')
        ttk.Button(controls, text='导出预测图', command=self.export_svg).pack(side='right', padx=4)
        options = ttk.Frame(self.win, padding=(8, 0, 8, 6)); options.pack(fill='x')
        self.numbers = tk.BooleanVar(value=False)
        self.reference = tk.BooleanVar(value=preview['mode'] in ('commands','feedback'))
        self.transfers = tk.BooleanVar(value=False)
        self.background = tk.BooleanVar(value=False)
        for label, variable in (('标注所有线段序号', self.numbers), ('期望路径', self.reference),
                                ('抬笔转移示意', self.transfers)):
            ttk.Checkbutton(options, text=label, variable=variable, command=self.update_layers).pack(side='left', padx=3)
        ttk.Checkbutton(options, text='原线稿底图', variable=self.background, command=self.update_layers,
                        state='normal' if self._background is not None else 'disabled').pack(side='left', padx=3)
        ttk.Label(options, text='点击列表或线段查看顺序；箭头显示当前段方向', foreground=theme.MUTED).pack(side='left', padx=8)
        body = ttk.Frame(self.win, padding=(8, 0)); body.pack(fill='both', expand=True)
        left = ttk.Frame(body); left.pack(side='left', fill='both', expand=True)
        self.canvas = tk.Canvas(left, background=theme.BG, highlightthickness=1, highlightbackground=theme.BORDER)
        self.canvas.pack(fill='both', expand=True)
        right = ttk.Frame(body, width=340); right.pack(side='right', fill='y', padx=(10, 0))
        ttk.Label(right, text='落笔线段顺序（抬笔不计入线段编号）').pack(anchor='w', pady=(0, 4))
        table = ttk.Frame(right); table.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(table, columns=('order', 'stroke', 'local', 'length'), show='headings', selectmode='browse')
        for column, label, width in (('order', '全局顺序', 78), ('stroke', '第几笔', 63),
                                     ('local', '本笔第几段', 88), ('length', '长 mm', 72)):
            self.tree.heading(column, text=label); self.tree.column(column, width=width, stretch=False)
        scrollbar = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side='left', fill='both', expand=True); scrollbar.pack(side='right', fill='y')
        for row in preview['rows']:
            self.tree.insert('', 'end', iid=str(row['order']), values=(row['order'], row['stroke'],
                             row['stroke_segment'], '%.3f' % row['length_mm']))
        self.detail = ttk.Label(right, wraplength=325, justify='left', padding=(0, 8)); self.detail.pack(fill='x')
        timeline = ttk.Frame(self.win, padding=8); timeline.pack(side='bottom',before=body,fill='x')
        self.position = tk.IntVar(value=preview['segments'])
        self.scale = ttk.Scale(timeline, from_=0, to=preview['segments'], command=self._scale_seek)
        self.scale.pack(fill='x')
        self.status = ttk.Label(timeline); self.status.pack(anchor='w')
        ttk.Label(timeline, text='金线为已绘制路径；朱红箭头为当前段；演示播放，实际时长以规划为准。',
                  foreground=theme.MUTED).pack(anchor='w')
        self.canvas.bind('<Configure>', lambda event: self._build_canvas())
        self.tree.bind('<<TreeviewSelect>>', self._tree_selected)
        self.win.protocol('WM_DELETE_WINDOW', self.close)
        self.win.bind('<Destroy>', lambda event: self.pause() if event.widget == self.win else None)
        self.win.update_idletasks()
        if getattr(root, 'so101_touch', False):
            from scripts.touch_ui import wrap_rows
            for widget in (top, options, controls):
                for child in widget.winfo_children():
                    if child.winfo_class() == 'TLabel':
                        child.configure(wraplength=940)
            wrap_rows(self.win, 950)
            self.tree.configure(height=3)
            self.detail.configure(font=('DejaVu Sans',9))
            ttk.Button(top, text='关闭', command=self.close).pack(side='right')
            self.win.update_idletasks()
        self._build_canvas()

    def point(self, p):
        y = p[1] if self.data['coordinate_system'] == 'full_canvas_xy_down' else self.data['height_mm']-p[1]
        return self._ox+p[0]*self._zoom, self._oy+y*self._zoom

    def _line(self, points, **options):
        coords = [value for point in points for value in self.point(point)]
        if len(coords)==2 and self.data['mode']=='feedback':
            x,y=coords;fill=options.get('fill',theme.GOLD)
            return self.canvas.create_oval(x-1.5,y-1.5,x+1.5,y+1.5,fill=fill,outline=fill,
                state=options.get('state','normal'),tags=options.get('tags',()))
        if len(coords) < 4: return None
        return self.canvas.create_line(*coords, **options)

    def _build_canvas(self):
        self._ready = False
        self.canvas.delete('all'); self._ink.clear(); self._rendered = 0
        width, height = self.data['width_mm'], self.data['height_mm']
        cw, ch = max(self.canvas.winfo_width(), 200), max(self.canvas.winfo_height(), 200)
        self._zoom = min((cw-50)/width, (ch-50)/height)
        self._ox = (cw-width*self._zoom)/2; self._oy = (ch-height*self._zoom)/2
        if self._background is not None:
            from PIL import ImageTk
            image = self._background.resize((max(1, round(width*self._zoom)), max(1, round(height*self._zoom))))
            self._photo = ImageTk.PhotoImage(image, master=self.win)
            self.canvas.create_image(self._ox, self._oy, anchor='nw', image=self._photo, tags='background')
        self.canvas.create_rectangle(self._ox, self._oy, cw-self._ox, ch-self._oy, outline=theme.BORDER)
        previous = None
        for row in self.data['rows']:
            order = row['order']; tag = 'segment_%d' % order
            start, end = row['start_mm'], row['end_mm']
            self._line([start, end], fill=theme.DIM, width=1, tags=('reference', tag))
            if row['stroke_segment'] == 1:
                if previous is not None:
                    self._line([previous, start], fill=theme.MUTED, width=1, dash=(4, 4), tags='transfers')
                x, y = self.point(start)
                self.canvas.create_text(x+8, y-12, text='笔%d' % row['stroke'], fill=theme.LIGHT, tags='stroke_labels')
            chain = row['predicted_points_mm'] if self.data['mode'] in ('commands','feedback') else [start, end]
            if chain:
                item = self._line(chain, fill=theme.GOLD, width=2, state='hidden', tags=('ink', tag))
                if item is not None: self._ink[order] = item
            mid = [(a+b)/2 for a, b in zip(start, end)]
            x, y = self.point(mid)
            self.canvas.create_text(x+3, y-5, text=str(order), fill=theme.LIGHT, font=('Segoe UI', 8), tags=('numbers', tag))
            self.canvas.tag_bind(tag, '<Button-1>', lambda event, n=order: self.seek(n))
            previous = end
        self._ready = True
        self.update_layers(); self._render(self.position.get())

    def update_layers(self):
        for tag, variable in (('numbers', self.numbers), ('stroke_labels', self.numbers), ('reference', self.reference),
                              ('transfers', self.transfers), ('background', self.background)):
            self.canvas.itemconfigure(tag, state='normal' if variable.get() else 'hidden')

    def _render(self, index):
        index = max(0, min(int(index), self.data['segments']))
        self.position.set(index)
        self.scale.set(index)
        if not self._ready: return
        if index >= self._rendered:
            for n in range(self._rendered+1, index+1):
                if n in self._ink: self.canvas.itemconfigure(self._ink[n], state='normal')
        else:
            for n in range(index+1, self._rendered+1):
                if n in self._ink: self.canvas.itemconfigure(self._ink[n], state='hidden')
        self._rendered = index; self.canvas.delete('active_segment')
        self.status.config(text='已绘制 %d / %d 段%s' % (index, self.data['segments'], ' · 完成' if index == self.data['segments'] else ''))
        if index:
            row = self.data['rows'][index-1]
            chain = row['predicted_points_mm'] if self.data['mode'] in ('commands','feedback') else [row['start_mm'], row['end_mm']]
            if chain and len(chain) >= 2:
                self._line(chain, fill=theme.ERROR, width=3, arrow='last', tags='active_segment')
            text = ('全局第 %d 段\n第 %d 笔内第 %d 段\n起点 (%.3f, %.3f) mm\n终点 (%.3f, %.3f) mm\n长度 %.3f mm' %
                    (index, row['stroke'], row['stroke_segment'], *row['start_mm'], *row['end_mm'], row['length_mm']))
            if 'command_first' in row:
                text += '\n舵机指令 %d → %d\n时间 %.3f → %.3f s' % (
                    row['command_first'], row['command_last'], row['time_start_s'], row['time_end_s'])
            elif self.data['mode'] in ('commands','feedback'): text += '\n此段未分配到独立采样点'
            self.detail.config(text=text)
            key = str(index)
            if self.tree.selection() != (key,): self.tree.selection_set(key)
            self.tree.see(key)
        else:
            self.tree.selection_remove(*self.tree.selection())
            self.detail.config(text='准备从第一段开始\n每笔开始前先抬笔转移，再落笔连续绘制。')

    def seek(self, index):
        self.pause(); self._render(index)

    def _scale_seek(self, value):
        index = round(float(value))
        if index != self.position.get(): self.seek(index)

    def _tree_selected(self, event=None):
        selection = self.tree.selection()
        if selection and int(selection[0]) != self.position.get(): self.seek(int(selection[0]))

    def play(self):
        self.pause()
        if self.position.get() >= self.data['segments']: self._render(0)
        self._tick()

    def _tick(self):
        self._timer = None
        n = self.position.get()+1
        if n > self.data['segments']: return
        self._render(n)
        delay = {'慢': 180, '正常': 60, '快': 20, '很快': 6}.get(self.speed.get(), 60)
        if n < self.data['segments']: self._timer = self.win.after(delay, self._tick)

    def pause(self):
        if self._timer is not None:
            try: self.win.after_cancel(self._timer)
            except tk.TclError: pass
            self._timer = None

    def export_csv(self):
        path = filedialog.asksaveasfilename(parent=self.win, title='导出线段绘制顺序',
                                           initialfile='绘画线段顺序.csv', defaultextension='.csv')
        if path:
            try: export_order_csv(self.data, path)
            except OSError as e: messagebox.showerror('导出失败', str(e), parent=self.win)

    def export_svg(self):
        path = filedialog.asksaveasfilename(parent=self.win, title='导出最终预测效果',
                                           initialfile='绘画预测效果.svg', defaultextension='.svg')
        if path:
            try: export_preview_svg(self.data, path, self.numbers.get())
            except OSError as e: messagebox.showerror('导出失败', str(e), parent=self.win)

    def close(self):
        self.pause(); self.win.destroy()
