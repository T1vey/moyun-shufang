"""Real Tk geometry checks, without network access or motor commands."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import tkinter as tk
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.arm_studio import ArmStudio


class TouchLayoutTests(unittest.TestCase):
    def test_console_fits_and_has_no_ssh(self):
        try: root=tk.Tk()
        except tk.TclError as e: self.skipTest('Tk display unavailable: '+str(e))
        self.addCleanup(root.destroy)
        with tempfile.TemporaryDirectory() as folder:
            args=SimpleNamespace(board_local=True,host='127.0.0.1',port=8765,tunnel=False,
                data_dir=folder,cloud_image_dir=Path(folder)/'cloud',windowed=True,
                target_drawing=True,offline=True)
            with patch.object(ArmStudio,'_heartbeat_loop'),patch.object(ArmStudio,'_auto_start'),\
                    patch('scripts.arm_studio.SSHLink',side_effect=AssertionError('Local GUI must not use SSH')):
                app=ArmStudio(root,args);root.update()
                self.assertIsNone(app.ssh)
                self.assertEqual((root.winfo_width(),root.winfo_height()),(1024,600))
                def children(widget):
                    for child in widget.winfo_children():
                        yield child
                        yield from children(child)
                for page in (app.tab_draw,app.tab_servo):
                    app._touch_notebook.select(page);root.update()
                    buttons=[w for w in children(root) if w.winfo_ismapped() and
                             w.winfo_class() in ('TButton','Button')]
                    stop=[]
                    for button in buttons:
                        if (str(button).startswith(str(app._touch_notebook)+'.') and
                                not str(button).startswith(str(page)+'.')):
                            continue  # Hidden notebook descendants can report mapped on Windows.
                        # Settings now scroll like the drawing page. Verify
                        # every action is reachable, not only the first screen.
                        ancestor=button.master
                        while ancestor is not None and ancestor.winfo_class()!='Canvas':
                            ancestor=getattr(ancestor,'master',None)
                        if ancestor is not None:
                            # Selecting a hidden notebook page can cause one
                            # final layout pass after its first scroll update.
                            for _ in range(2):
                                total=ancestor.bbox('all')[3]
                                position=ancestor.canvasy(button.winfo_rooty()-ancestor.winfo_rooty())
                                ancestor.yview_moveto(max(0,position-10)/max(1,total));root.update()
                        x=button.winfo_rootx()-root.winfo_rootx()
                        y=button.winfo_rooty()-root.winfo_rooty()
                        self.assertGreaterEqual(x,0,button.cget('text'))
                        self.assertLessEqual(x+button.winfo_width(),1024,button.cget('text'))
                        if button.cget('text')=='停止' and y<80:stop.append(button)
                        self.assertGreaterEqual(y,0,button.cget('text'))
                        self.assertLessEqual(y+button.winfo_height(),600,
                            (button.cget('text'),str(page),str(ancestor),
                             (ancestor.bbox('all'),ancestor.yview(),ancestor.winfo_height()) if ancestor else None))
                    self.assertTrue(stop,'Persistent stop must remain visible')
                app._beat_stop.set()


if __name__=='__main__':unittest.main()
