"""Sugar Workshop's shared Tk skin, matching user_gui/static/base.css.

Presentation only: no API calls, device access, or changes to control bindings.
"""
import tkinter as tk
from tkinter import ttk, font

BG = '#120c08'
PANEL = '#1a120c'
FIELD = '#231910'
HOVER = '#2e2116'
BORDER = '#443323'
TEXT = '#f7ead6'
MUTED = '#cbb497'
DIM = '#8a735a'
GOLD = '#f3ad45'
LIGHT = '#ffe2a6'
INK = '#2a1505'
RED = '#c93a2c'
ERROR = '#ef5d4f'
OK = '#8fd694'


def install(root, touch=False):
    if getattr(root, '_sugar_theme', False):
        return
    root._sugar_theme = True
    families = set(font.families(root))
    family = next((f for f in ('Microsoft YaHei UI', 'Noto Sans CJK SC', 'WenQuanYi Micro Hei',
                               'Microsoft YaHei', 'DejaVu Sans') if f in families), 'TkDefaultFont')
    size = 11 if touch else 10
    for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont', 'TkCaptionFont'):
        font.Font(root=root, name=name, exists=True).configure(family=family, size=size)
    root.configure(background=BG)
    for key, value in {
        '*background': PANEL, '*foreground': TEXT, '*insertBackground': LIGHT,
        '*selectBackground': '#68451f', '*selectForeground': LIGHT,
        '*activeBackground': HOVER, '*activeForeground': LIGHT,
        '*highlightBackground': BORDER, '*highlightColor': GOLD,
        '*disabledForeground': DIM, '*troughColor': BG,
        '*Text.background': BG, '*Text.relief': 'flat', '*Text.borderWidth': 0,
        '*Canvas.background': PANEL, '*Listbox.background': FIELD,
        '*Entry.background': FIELD, '*Menu.background': FIELD,
        '*TCombobox*Listbox.background': FIELD, '*TCombobox*Listbox.foreground': TEXT,
        '*TCombobox*Listbox.selectBackground': '#68451f',
    }.items():
        root.option_add(key, value)
    style = ttk.Style(root)
    style.theme_use('clam')  # Native Windows themes ignore custom field colors.
    style.configure('.', background=PANEL, foreground=TEXT, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER, troughcolor=BG,
                    selectbackground='#68451f', selectforeground=LIGHT, font=(family, size))
    style.configure('TFrame', background=PANEL)
    style.configure('Header.TFrame', background=FIELD)
    style.configure('TLabel', background=PANEL, foreground=TEXT)
    style.configure('Brand.TLabel', background=FIELD, foreground=LIGHT, font=(family, 19, 'bold'))
    style.configure('Subtitle.TLabel', background=FIELD, foreground=MUTED, font=(family, 10))
    style.configure('Seal.TLabel', background=RED, foreground=TEXT, padding=(6, 2), font=(family, 12, 'bold'))
    style.configure('TLabelframe', background=PANEL, bordercolor=BORDER, borderwidth=1, relief='solid')
    style.configure('TLabelframe.Label', background=PANEL, foreground=LIGHT, font=(family, size, 'bold'))
    style.configure('TButton', padding=(10, 7 if touch else 6), background=FIELD, foreground=TEXT,
                    width=0, borderwidth=1, bordercolor=BORDER, focusthickness=1, focuscolor=GOLD)
    style.map('TButton', background=[('disabled', PANEL), ('pressed', '#68451f'), ('active', HOVER)],
              foreground=[('disabled', DIM), ('active', LIGHT)], bordercolor=[('focus', GOLD), ('active', GOLD)])
    style.configure('Primary.TButton', background=GOLD, foreground=INK, padding=(8,2), font=(family, size, 'bold'))
    style.map('Primary.TButton', background=[('disabled', HOVER), ('pressed', '#d9861f'), ('active', '#ffd27e')],
              foreground=[('disabled', DIM), ('!disabled', INK)])
    style.configure('Danger.TButton', background='#492019', foreground='#ffb0a5', bordercolor=RED)
    style.map('Danger.TButton', background=[('disabled', PANEL), ('pressed', '#76271e'), ('active', '#64271e')],
              foreground=[('disabled', DIM), ('!disabled', '#ffb0a5')])
    for name in ('TEntry', 'TSpinbox', 'TCombobox'):
        style.configure(name, fieldbackground=FIELD, background=HOVER, foreground=TEXT,
                        insertcolor=LIGHT, arrowcolor=GOLD, padding=5, bordercolor=BORDER)
        style.map(name, fieldbackground=[('disabled', PANEL), ('readonly', FIELD), ('!disabled', FIELD)],
                  foreground=[('disabled', DIM), ('!disabled', TEXT)],
                  selectbackground=[('!disabled', '#68451f')], selectforeground=[('!disabled', LIGHT)],
                  bordercolor=[('focus', GOLD)])
    for name in ('TCheckbutton', 'TRadiobutton'):
        style.configure(name, background=PANEL, foreground=TEXT, padding=(2, 3),
                        indicatorbackground=FIELD, indicatorforeground=GOLD)
        style.map(name, background=[('active', PANEL)], foreground=[('disabled', DIM), ('active', LIGHT)],
                  indicatorbackground=[('selected', GOLD), ('!selected', FIELD)])
    style.configure('TNotebook', background=PANEL, borderwidth=0)
    style.configure('TNotebook.Tab', background=FIELD, foreground=MUTED, padding=(16, 8))
    style.map('TNotebook.Tab', background=[('selected', '#68451f'), ('active', HOVER)],
              foreground=[('disabled', DIM), ('selected', LIGHT), ('active', LIGHT)])
    style.configure('Treeview', background=BG, fieldbackground=BG, foreground=TEXT,
                    borderwidth=0, rowheight=32 if touch else 28)
    style.map('Treeview', background=[('selected', '#68451f')], foreground=[('selected', LIGHT)])
    style.configure('Treeview.Heading', background=FIELD, foreground=LIGHT, padding=7, relief='flat')
    style.map('Treeview.Heading', background=[('active', HOVER)])
    for axis in ('Vertical', 'Horizontal'):
        style.configure(axis+'.TScrollbar', background='#68451f', troughcolor=BG,
                        arrowcolor=MUTED, arrowsize=24 if touch else 16, borderwidth=0)
        style.map(axis+'.TScrollbar', background=[('active', GOLD), ('pressed', GOLD)])
        style.configure(axis+'.TScale', background=GOLD, troughcolor=FIELD, bordercolor=BORDER)
        style.configure(axis+'.TProgressbar', background=GOLD, troughcolor=FIELD, borderwidth=0)
    style.configure('TSeparator', background=BORDER)
    # Image-backed nine-slice elements give the main action the same warm
    # gradient/rounded outline on Linux and Windows. No external asset dependency.
    pictures = []
    for name, top, bottom in [('normal', '#ffd27e', '#d9861f'), ('hover', '#ffe2a6', '#f3ad45'),
                               ('pressed', '#e9a340', '#b8661a'), ('disabled', HOVER, HOVER)]:
        image = tk.PhotoImage(master=root, width=32, height=32)
        a = tuple(int(top[i:i+2], 16) for i in (1, 3, 5)); b = tuple(int(bottom[i:i+2], 16) for i in (1, 3, 5))
        for y in range(32):
            color = '#%02x%02x%02x' % tuple(round(a[k]+(b[k]-a[k])*y/31) for k in range(3))
            inset = (5, 3, 2, 1, 1)[min(y, 31-y)] if min(y,31-y)<5 else 0
            image.put(color, to=(inset,y,32-inset,y+1))
        pictures.append(image)
    root._sugar_images = pictures
    style.element_create('Sugar.action', 'image', pictures[0], ('disabled',pictures[3]),
                         ('pressed',pictures[2]), ('active',pictures[1]), border=7, sticky='nsew')
    style.layout('Primary.TButton', [('Sugar.action', {'sticky':'nsew','children':[
        ('Button.padding', {'sticky':'nsew','children':[('Button.label', {'sticky':'nsew'})]})]})])


def brand_header(parent, subtitle='设置与调试'):
    row = ttk.Frame(parent, style='Header.TFrame', padding=(14, 8))
    row.pack(fill='x')
    ttk.Label(row, text='设', style='Seal.TLabel').pack(side='left', padx=(0, 10))
    ttk.Label(row, text='糖画坊', style='Brand.TLabel').pack(side='left')
    ttk.Label(row, text='  /  '+subtitle, style='Subtitle.TLabel').pack(side='left', padx=8)
    return row
