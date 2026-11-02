import hashlib
import http.client
import json
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from audio_player.catalog import Catalog
from user_gui.display_server import DisplayServer, Hub


class StubAudio:
    def __init__(self):self.calls=[]
    def status(self):return dict(available=True,playing=False)
    def listing(self):return dict(available=True,items=[dict(id='poem_p01',title='静夜思')])
    def submit(self,action,data):self.calls.append((action,data));return dict(accepted=True)
    def close(self):pass


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.audio=StubAudio()
        self.hub=Hub(Path(self.temp.name)/'uploads')
        self.server=DisplayServer(('127.0.0.1',0),self.hub,interfaces=[],audio_service=self.audio)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.thread.join(2);self.server.server_close();self.temp.cleanup()
    def request(self,path,method='GET',headers=None,body=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        conn.request(method,path,json.dumps(body or {}) if method=='POST' else None,headers or {})
        res=conn.getresponse();data=res.read();code=res.status;conn.close();return code,data
    def test_audio_get_and_post_auth(self):
        self.assertEqual(self.request('/api/audio/list')[0],200)
        self.assertEqual(self.request('/api/audio/status')[0],200)
        self.assertEqual(self.request('/api/audio/play','POST',body={'id':'poem_p01'})[0],403)
        headers={'Content-Type':'application/json','X-Screen-Token':self.hub.control_token}
        self.assertEqual(self.request('/api/audio/play','POST',headers,{'id':'poem_p01'})[0],202)
        self.assertEqual(self.audio.calls,[('play',{'id':'poem_p01'})])
        headers['Origin']='http://evil.example'
        self.assertEqual(self.request('/api/audio/play','POST',headers)[0],403)
        self.assertEqual(len(self.audio.calls),1)
    def test_ui_keeps_audio_optional(self):
        code,raw=self.request('/');self.assertEqual(code,200);html=raw.decode()
        self.assertIn('id="mode-audio" class="mode" type="button"',html)
        self.assertIn('id="mp-read" type="checkbox"',html)
        for name in ('audio.js','audio.css'):
            code,body=self.request('/static/'+name);self.assertEqual(code,200)
            if name.endswith('.js'):self.assertNotIn(b'??',body)


class CatalogTests(unittest.TestCase):
    def test_tampered_wav_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);wav=p/'one.wav'
            with wave.open(str(wav),'wb') as w:w.setparams((1,2,48000,0,'NONE','not compressed'));w.writeframes(b'\0'*9600)
            item=dict(id='one',wav='one.wav',duration_s=.1,sha256=hashlib.sha256(wav.read_bytes()).hexdigest(),
                      timeline=[dict(text='一',start=.01,end=.09)])
            path=p/'manifest.json';path.write_text(json.dumps(dict(schema='tcb705-readings-v1',items=[item])),encoding='utf-8')
            cat=Catalog(path);self.assertEqual(len(cat.load('one')[1]),4800)
            wav.write_bytes(wav.read_bytes()+b'x')
            with self.assertRaisesRegex(ValueError,'校验失败'):cat.load('one')
    def test_traversal_and_invalid_timeline_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'manifest.json'
            for item in [dict(id='x',wav='../evil.wav'),dict(id='x',wav='x.wav',duration_s=1,timeline=[dict(start=.2,end=2)])]:
                p.write_text(json.dumps(dict(schema='tcb705-readings-v1',items=[item])),encoding='utf-8')
                with self.assertRaises(ValueError):Catalog(p)


class WorkflowAudioTests(unittest.TestCase):
    def test_all_masterpieces_match_recordings_and_stop_after_fake_execution(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from user_gui.workflow import Workflow
        from audio_player.catalog import Catalog
        catalog=Catalog();calls=[];executed=[]
        service=SimpleNamespace(follow=lambda action,key,owner=None:calls.append((action,key,owner)))
        pipeline=SimpleNamespace(simulation=True,busy=lambda:False,
            masterpiece_plan=lambda *args:('fake-plan',True),
            execute=lambda *args,**kwargs:executed.append(kwargs['speed_pct']))
        with tempfile.TemporaryDirectory() as folder:
            workflow=Workflow(pipeline,folder);workflow.set_audio_service(service)
            for key in catalog.items:
                if not key.startswith('masterpiece_'):continue
                jid=workflow.reserve('desktop_masterpiece','audio-'+key)
                workflow._read_along=True
                with patch('calligraphy.glyph_store.manifest',return_value={'title':'test'}):
                    workflow._run_masterpiece(jid,'mp_'+key[len('masterpiece_'):],1)
                self.assertEqual(calls[-2:],[('play',key,jid),('stop',None,jid)])
                self.assertEqual(workflow.state['phase'],'completed')
                workflow._occupied=False
        self.assertEqual(executed,[100]*7)

    def test_optional_audio_error_does_not_escape_motion_workflow(self):
        from types import SimpleNamespace
        from user_gui.workflow import Workflow
        def fail(*args,**kwargs):raise RuntimeError('audio offline')
        with tempfile.TemporaryDirectory() as folder:
            w=Workflow(SimpleNamespace(),folder);w._read_along=True
            w.set_audio_service(SimpleNamespace(follow=fail))
            w._audio('play','poem_p01');w._audio('stop')


if __name__=='__main__':unittest.main()
