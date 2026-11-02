"""Modal cancel/selection behavior without any backend or hardware."""
import tempfile
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import unittest
from scripts.sugar_theme import install
from scripts.sugar_dialogs import messagebox, filedialog


class DialogTests(unittest.TestCase):
    def setUp(self):
        try:self.root=tk.Tk()
        except tk.TclError as exc:self.skipTest(str(exc))
        install(self.root,True)
        self.root.geometry('1024x600');self.root.update()
        self.addCleanup(self.root.destroy)

    def windows(self):return [w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel)]

    def descendants(self,parent):
        for child in parent.winfo_children():
            yield child
            yield from self.descendants(child)

    def click(self,text):
        win=self.windows()[-1]
        for w in self.descendants(win):
            if isinstance(w,ttk.Button) and w.cget('text')==text:w.invoke();return
        self.fail('Missing dialog action: '+text)

    def test_window_close_never_confirms(self):
        self.root.after(100,lambda:self.windows()[-1].tk.call(self.windows()[-1].protocol('WM_DELETE_WINDOW')))
        self.assertIs(messagebox.askyesno('确认','是否继续？',parent=self.root),False)

    def test_explicit_confirmation_and_cancel(self):
        self.root.after(100,lambda:self.click('确认'))
        self.assertIs(messagebox.askokcancel('确认','是否继续？',parent=self.root),True)
        self.root.after(100,lambda:self.click('取消'))
        self.assertIs(messagebox.askokcancel('确认','是否继续？',parent=self.root),False)

    def test_file_selection_and_save_suffix(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'input.png';target.write_bytes(b'fixture')
            self.root.after(100,lambda:self.click('选择'))
            self.assertEqual(Path(filedialog.askopenfilename(parent=self.root,initialdir=directory,
                initialfile='input.png',filetypes=[('图片','*.png')])),target)
            self.root.after(100,lambda:self.click('保存'))
            self.assertEqual(Path(filedialog.asksaveasfilename(parent=self.root,initialdir=directory,
                initialfile='output',defaultextension='.svg')),Path(directory)/'output.svg')
            self.assertFalse((Path(directory)/'output.svg').exists())

    def test_cancel_file_selection(self):
        self.root.after(100,lambda:self.click('取消'))
        self.assertEqual(filedialog.askopenfilename(parent=self.root),'')


if __name__=='__main__':unittest.main()
