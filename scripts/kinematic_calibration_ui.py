"""Touch-friendly measured-contact wizard. It reads encoders, never moves axes."""
import copy
import json
import math
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from scripts.sugar_dialogs import _window, filedialog, messagebox
from scripts import sugar_theme as theme
from kinematic_calibration import capture_template, calibration_fingerprint, fit_calibration, make_candidate


def validate_draft(data):
    if (not isinstance(data, dict) or data.get('schema') != capture_template()['schema']
            or data.get('source') not in ('measured','simulation')
            or not isinstance(data.get('captures'),list) or not 27 <= len(data['captures']) <= 200):
        raise ValueError('需要27至200项规范采样及明确的实测/仿真来源')
    for row in data['captures']:
        if not isinstance(row,dict):raise ValueError('每项采样必须包含counts与xy_mm')
        counts=row.get('counts');point=row.get('xy_mm')
        if not isinstance(counts,dict) or set(counts) != {'1','2','3','4','5'}:
            raise ValueError('需要ID1至ID5的读数，未采集项填null')
        if any(v is not None and (type(v) is not int or not 0<=v<=4095) for v in counts.values()):
            raise ValueError('关节读数必须是0至4095整数或null')
        if (not isinstance(point,list) or len(point)!=2
                or any(type(v) not in (int,float) or not math.isfinite(v) for v in point)):
            raise ValueError('xy_mm必须是两个有限毫米坐标')
        if not isinstance(row.get('pose_label'),str) or row.get('split','fit') not in ('fit','validation'):
            raise ValueError('每项采样需要姿态标签与fit/validation分组')
    return data


def open_calibration(studio):
    if studio._drawing_busy():
        studio.log_msg('请在当前任务结束后打开多点标定'); return
    return CalibrationWindow(studio)


class CalibrationWindow:
    def __init__(self, studio):
        self.studio = studio
        self.win = _window(studio.root, '多点运动学标定', 920, 550)
        self.busy = False
        self.report = self.machine = None
        self.dataset = capture_template(100.)
        self.cache = Path(studio._calibration_cache)/'new_scheme_captures.json'
        if self.cache.exists():
            try:
                data = json.loads(self.cache.read_text(encoding='utf-8'))
                self.dataset = validate_draft(data)
            except (OSError, ValueError, TypeError, KeyError):
                pass
        body = ttk.Frame(self.win, padding=12); body.pack(fill='both', expand=True)
        ttk.Label(body, text='先固定 100×100 mm 九点网格并校准笔轴。每点分别竖直、前倾、后倾 10–20°，保持笔尖轻触同一点。',
                  wraplength=870).pack(anchor='w')
        ttk.Label(body, text='以下按钮仅读取当前位置；请手动摆放。拟合通过后应用，再重新采集四点纸面。',
                  foreground=theme.MUTED, wraplength=870).pack(anchor='w', pady=4)
        row = ttk.Frame(body); row.pack(fill='x', pady=6)
        self.index = tk.StringVar(value='')
        self.select = ttk.Combobox(row, textvariable=self.index, state='readonly', width=57)
        self.select.pack(side='left', padx=4)
        self.select.bind('<<ComboboxSelected>>', lambda event: self.show())
        ttk.Button(row, text='记录当前位置', command=self.capture).pack(side='left', padx=4)
        self.status = tk.StringVar(value='')
        ttk.Label(body, textvariable=self.status, wraplength=870).pack(anchor='w', pady=5)
        row = ttk.Frame(body); row.pack(fill='x', pady=5)
        ttk.Label(row, text='笔长初值 mm').pack(side='left')
        self.length = tk.StringVar(value=str(self.dataset.get('initial_pen_length_mm',95.)))
        ttk.Entry(row, textvariable=self.length, width=7).pack(side='left', padx=4)
        ttk.Button(row, text='导入采样', command=self.load).pack(side='left', padx=4)
        ttk.Button(row, text='导出采样', command=self.save_as).pack(side='left', padx=4)
        ttk.Button(row, text='重新采集', command=self.reset).pack(side='left', padx=4)
        ttk.Button(row, text='拟合与检查', command=self.fit).pack(side='left', padx=4)
        self.detail = tk.Text(body, height=8, wrap='word', bg=theme.PANEL, fg=theme.TEXT,
                              insertbackground=theme.TEXT, relief='flat', font=('Microsoft YaHei UI',11))
        self.detail.pack(fill='both', expand=True, pady=6)
        footer = ttk.Frame(body); footer.pack(fill='x')
        self.apply_button = ttk.Button(footer, text='应用标定结果', command=self.apply, state='disabled')
        self.apply_button.pack(side='left')
        ttk.Button(footer, text='关闭', command=self.close).pack(side='right')
        self.win.protocol('WM_DELETE_WINDOW', self.close)
        studio._calibration_active = True; studio._update_plan_controls()
        self.refresh()

    def refresh(self):
        labels = {'vertical':'竖直','forward':'前倾','backward':'后倾'}
        self.select['values'] = ['%02d  X=%g  Y=%g mm · %s%s' %
            (i+1,*c['xy_mm'],labels.get(c.get('pose_label'),c.get('pose_label','')),
             '  ✓' if all(type(v) is int for v in c['counts'].values()) else '')
            for i,c in enumerate(self.dataset['captures'])]
        self.select.current(min(max(self.select.current(),0),len(self.dataset['captures'])-1));self.show()

    def show(self):
        count = sum(all(type(v) is int for v in c['counts'].values()) for c in self.dataset['captures'])
        self.status.set('已记录 %d / %d 处姿态；采样来源：%s' % (count,len(self.dataset['captures']),self.dataset.get('source')))

    def persist(self):
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        temp = self.cache.with_suffix('.tmp')
        temp.write_text(json.dumps(self.dataset, ensure_ascii=False, indent=2),encoding='utf-8')
        temp.replace(self.cache)

    def run(self, action, complete):
        if self.busy: return
        self.busy = True; self.status.set('正在处理…')
        def worker():
            try:
                result = action(); error = None
            except Exception as exc:
                result = None; error = str(exc)
            def finish():
                self.busy = False
                if error: self.status.set(error)
                else: complete(result)
            self.win.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()

    def capture(self):
        if self.busy: return
        index = self.select.current()
        port = self.studio.var_port.get().strip(); source = self.studio.var_calibration_source.get()
        def read():
            machine = self.studio.client.fetch_config()
            signature = calibration_fingerprint(machine)
            if self.dataset.get('machine_fingerprint',signature) != signature:
                raise ValueError('模型或零位已改变，请重新采集全部点')
            if source == '板端':
                job = self.studio.client.read_pen_pose(port)
                done = self.studio._wait_job(job['id'],timeout=30)
                if not done or done['status'] != 'DONE':raise ValueError((done or {}).get('detail','读取超时'))
                counts = done['result']['counts']
            else:
                from pc_pen_calibration import read_pose
                counts = read_pose(source,machine)['counts']
            return machine, signature, {str(k):v for k,v in counts.items()}
        def finish(data):
            self.machine, signature, counts = data
            self.dataset['machine_fingerprint'] = signature
            self.dataset['captures'][index]['counts'] = counts
            self.report = None;self.apply_button.config(state='disabled');self.persist();self.refresh()
            self.select.current(min(index+1,len(self.dataset['captures'])-1))
        self.run(read, finish)

    def fit(self):
        if self.busy:return
        try:self.dataset['initial_pen_length_mm'] = float(self.length.get())
        except ValueError:self.status.set('请输入有限的笔长初值');return
        self.report = None;self.apply_button.config(state='disabled')
        dataset = copy.deepcopy(self.dataset)
        def compute():
            machine = self.studio.client.fetch_config()
            if dataset.get('machine_fingerprint',calibration_fingerprint(machine)) != calibration_fingerprint(machine):
                raise ValueError('采样后模型已变更，请重新采集')
            return machine,fit_calibration(machine,dataset)
        def finish(value):
            self.machine,self.report = value;self.persist()
            self.detail.delete('1.0','end')
            summary = {k:self.report.get(k) for k in ('status','applicable_to_hardware','fit','quantized_fit','validation','reasons','parameters')}
            self.detail.insert('end',json.dumps(summary,ensure_ascii=False,indent=2))
            self.status.set('拟合结果：'+self.report['status'])
            if self.report.get('applicable_to_hardware') and self.report.get('status') == 'ACCEPT':
                self.apply_button.config(state='normal')
        self.run(compute,finish)

    def apply(self):
        if self.busy or self.report is None:return
        if not messagebox.askyesno('应用多点标定','将保存零位和笔长，并清除旧四点校正。随后必须重新采集四点，旧轨迹需重新规划。',parent=self.win):return
        def write():
            current=self.studio.client.fetch_config()
            updated=make_candidate(current,self.dataset,self.report)
            self.cache.with_name('machine.before_kinematic.json').write_text(json.dumps(current,ensure_ascii=False,indent=2),encoding='utf-8')
            self.studio.client.save_config(updated)
            return updated
        def finish(updated):
            self.apply_button.config(state='disabled')
            self.studio._geometry_captures = {}
            self.studio._sync_four_point_fields(updated)
            self.studio._invalidate_geometry_plan()
            self.status.set('已保存；请关闭此窗口，重新采集并应用四点校正。')
        self.run(write,finish)

    def load(self):
        if self.busy:return
        name=filedialog.askopenfilename(parent=self.win,filetypes=[('JSON','*.json')])
        if not name:return
        try:
            data=validate_draft(json.loads(Path(name).read_text(encoding='utf-8')))
            self.dataset=data;self.report=None;self.apply_button.config(state='disabled');self.persist();self.refresh()
        except (ValueError,OSError,KeyError,TypeError) as exc:self.status.set(str(exc))

    def save_as(self):
        if self.busy:return
        name=filedialog.asksaveasfilename(parent=self.win,defaultextension='.json',initialfile='captures.json')
        if name:Path(name).write_text(json.dumps(self.dataset,ensure_ascii=False,indent=2),encoding='utf-8')

    def reset(self):
        if self.busy:return
        if not messagebox.askyesno('重新采集','清除当前采样草稿并从九点网格重新开始？',parent=self.win):return
        self.dataset=capture_template();self.report=None;self.apply_button.config(state='disabled');self.persist();self.refresh()

    def close(self):
        if self.busy:self.status.set('请等待当前读取或拟合完成');return
        self.studio._calibration_active=False;self.studio._update_plan_controls();self.win.destroy()
