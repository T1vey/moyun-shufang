"""Library/layout, immutable motion inputs and owned phone jobs; no real motion."""
import copy
import json
import math
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
import urllib.error

from calligraphy import composer,glyph_store
from calligraphy.text_layout import layout,normalize
from calligraphy.presets import validate_task,BRUSH,binding
from user_gui.workflow import Workflow,Cancelled
from user_gui.display_server import Hub,DisplayServer
from tests.test_calligraphy import configuration


def config():
    c=configuration();c['paper'].update(width_mm=148.52,height_mm=150.215)
    c['calligraphy']=dict(BRUSH,max_press_mm=4.,verified=True,calibration_binding=binding(c))
    return c


class LibraryTests(unittest.TestCase):
    def test_exact_repertoire_and_source_stroke_order(self):
        m=glyph_store.manifest();self.assertEqual(m['count'],3500);self.assertEqual(len(set(m['characters'])),3500)
        expected=''.join((Path(__file__).resolve().parents[1]/'data/calligraphy/sources/通用规范汉字表2013一级3500字.txt').read_text(encoding='utf-8').split())
        self.assertEqual(m['characters'],expected)
        n=0
        for ch in m['characters']:
            g=glyph_store.glyph(ch);self.assertEqual(g['character'],ch)
            for s in g['strokes']:
                n+=1;p=s['points'];raw=s['source_median']
                self.assertEqual(p[0][2],0);self.assertEqual(p[-1][2],0)
                for a,b in zip((p[0],p[-1]),(raw[0],raw[-1])):
                    self.assertAlmostEqual(a[0],b[0]/1024*50,places=5)
                    self.assertAlmostEqual(a[1],(900-b[1])/1024*50,places=5)
                self.assertTrue(all(0<=v[2]<=1 and 0<v[3]<=1 for v in p))
                self.assertTrue(all(math.isfinite(x) for v in p for x in v))
        self.assertGreater(n,30000)
        a=glyph_store.glyph('一');a['strokes'].clear();self.assertTrue(glyph_store.glyph('一')['strokes'])

    def test_all_3500_at_size_extremes_are_bounded_and_released(self):
        c=config()
        for ch in glyph_store.manifest()['characters']:
            for size in (40,70):
                p=composer.task(ch,size,0,c)
                for path,depth,feed in zip(p['paths'],p['calligraphy']['depth_mm'],p['calligraphy']['feed_ratio']):
                    self.assertEqual(len(path),len(depth));self.assertEqual(len(path),len(feed))
                    self.assertEqual(depth[0],0);self.assertEqual(depth[-1],0)
                    self.assertTrue(all(0<=x<=148.52 and 0<=y<=150.215 for x,y in path),(ch,size))
                    self.assertTrue(all(0<=d<=4 for d in depth))

    def test_reconstruction_rejects_geometry_pressure_or_version_tampering(self):
        c=config();p=composer.task('中国',40,0,c);validate_task(p,c)
        for change in (lambda d:d['paths'][0][0].__setitem__(0,0),
                       lambda d:d['calligraphy']['depth_mm'][0].__setitem__(1,4.01),
                       lambda d:d['calligraphy'].__setitem__('glyph_version','wrong'),
                       lambda d:d['calligraphy']['stroke_map'].reverse()):
            bad=copy.deepcopy(p);change(bad)
            with self.assertRaises(ValueError):validate_task(bad,c)
        changed=copy.deepcopy(c);changed['paper']['width_mm']+=1
        with self.assertRaises(ValueError):validate_task(p,changed)


class LayoutTests(unittest.TestCase):
    def test_modern_order_autowrap_and_pagination(self):
        doc=layout('一二三四五六七八九十',40,config()['paper'])
        self.assertEqual((doc['columns'],doc['rows'],doc['page_count']),(3,2,2))
        p=doc['pages'][0];self.assertEqual(''.join(c['character'] for c in p),'一二三四五六')
        self.assertEqual([(c['row'],c['column']) for c in p],[(0,0),(0,1),(0,2),(1,0),(1,1),(1,2)])
        self.assertLess(p[0]['x_mm'],p[1]['x_mm']);self.assertLess(p[0]['y_mm'],p[3]['y_mm'])
        doc=layout('中国',70,config()['paper']);self.assertEqual(doc['page_count'],2)
        self.assertEqual(layout('中国',50,config()['paper'])['columns'],2)

    def test_line_break_spaces_and_input_rejection(self):
        paper=config()['paper']
        a=layout('一二三\n四',40,paper);self.assertEqual(a['pages'][0][-1]['row'],1)
        self.assertEqual(layout('一 二',40,paper)['pages'][0][-1]['column'],2)
        for value in ('','  ','你好，世界','A','你好🙂','一'*201):
            with self.assertRaises(ValueError):normalize(value)
        for size in (39,71,float('nan'),float('inf'),True,'40'):
            with self.assertRaises(ValueError):layout('一',size,paper)
        with self.assertRaises(ValueError):layout('一',70,dict(width_mm=60,height_mm=60))


class FakePipeline:
    def __init__(self):
        self.config=config();self.calls=[];self.gate=None;self.entered=threading.Event();self.fail=False
    def busy(self):return False
    def text_config(self):return copy.deepcopy(self.config)
    def register_text(self,spec,cancelled):self.calls.append(('register',spec['page_index']));return 'src'
    def plan(self,*args,**kw):self.calls.append(('plan',));return 'plan'
    def hardpen_plan(self,text,size_mm,cancelled,progress=None):
        self.calls.append(('hardpen_plan',text,size_mm));return 'hp_plan',False
    def masterpiece_plan(self,style,column,cancelled,progress=None):
        self.calls.append(('masterpiece_plan',style,column));return 'mp%d'%column,True
    def preview(self,*args):return b'<svg xmlns="http://www.w3.org/2000/svg"/>'
    def execute(self,plan,cancelled,**kw):
        self.calls.append(('execute',));self.entered.set()
        if kw.get('speed_pct') is not None:self.calls.append(('speed',plan,kw['speed_pct']))
        if self.gate:self.gate.wait(5)
        if self.fail:raise OSError('lost response')
        if cancelled():raise Cancelled('已停止书写并归位')
        return dict(motion_stage='RETURN_HOME_DONE')
    def stop_execution(self,*args,**kw):
        self.calls.append(('stop',))
        if self.gate:self.gate.set()


class TextWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.pipeline=FakePipeline();self.w=Workflow(self.pipeline,self.tmp.name)
    def request(self,text='中国',size=70,rid='request001'):
        d=self.w.text_preview('phone001',text,size)
        data={k:d[k] for k in ('text','font_size_mm','preview_id','revision')}
        data.update(start_requested=True,request_id=rid)
        return data
    def finish(self):self.w.worker.join(10);self.assertFalse(self.w.worker.is_alive())
    def test_preview_no_motion_and_page_confirmation(self):
        data=self.request();self.assertEqual(self.pipeline.calls,[])
        state=self.w.submit_text('phone001',data);jid=state['job_id'];self.finish()
        self.assertEqual(self.w.state['phase'],'awaiting_paper')
        self.assertEqual(self.pipeline.calls.count(('execute',)),1)
        with self.assertRaises(RuntimeError):self.w.reserve('other001','other001')
        self.w.next_text_page('phone001',jid,0);self.finish()
        self.assertEqual(self.w.state['phase'],'completed');self.assertEqual(self.pipeline.calls.count(('execute',)),2)
        with self.assertRaises(ValueError):self.w.next_text_page('phone001',jid,0)
    def test_duplicate_submit_and_other_owner_cannot_replay(self):
        data=self.request('一',40);state=self.w.submit_text('phone001',data);self.finish()
        again=self.w.submit_text('phone001',data);self.assertEqual(again['job_id'],state['job_id'])
        self.assertEqual(self.pipeline.calls.count(('execute',)),1)
        for f in (lambda:self.w.text_status('phone002',state['job_id']),lambda:self.w.cancel_text('phone002',state['job_id'])):
            with self.assertRaises(ValueError):f()
        with self.assertRaises(ValueError):self.w.submit_text('phone001',dict(data,text='二'))
        w2=Workflow(self.pipeline,self.tmp.name);new=w2.text_preview('phone001','一',40)
        replay=dict(data,preview_id=new['preview_id'],revision=new['revision'])
        with self.assertRaises(ValueError):w2.submit_text('phone001',replay)
    def test_stale_preview_and_config_change_do_not_start(self):
        data=self.request();self.w.text_preview('phone001','你好',40)
        with self.assertRaises(ValueError):self.w.submit_text('phone001',data)
        data=self.request();self.pipeline.config['paper']['width_mm']+=1
        with self.assertRaises(ValueError):self.w.submit_text('phone001',data)
        self.assertEqual(self.pipeline.calls,[])
    def test_cancel_motion_preserves_home_and_never_writes_next_page(self):
        self.pipeline.gate=threading.Event();data=self.request()
        state=self.w.submit_text('phone001',data);self.assertTrue(self.pipeline.entered.wait(10))
        self.w.cancel_text('phone001',state['job_id']);self.finish()
        self.assertEqual(self.w.state['phase'],'cancelled');self.assertIn(('stop',),self.pipeline.calls)
        self.assertEqual(self.pipeline.calls.count(('execute',)),1)
    def test_uncertain_motion_blocks_other_jobs(self):
        self.pipeline.fail=True;self.w.submit_text('phone001',self.request());self.finish()
        self.assertTrue(self.w.state['motion_uncertain']);self.assertTrue(self.w.state['can_cancel'])
        with self.assertRaises(RuntimeError):self.w.reserve('phone002','other001')

    def test_cancel_between_pages_revokes_next_page(self):
        state=self.w.submit_text('phone001',self.request());self.finish()
        self.w.cancel_text('phone001',state['job_id'])
        self.assertFalse(self.w.state['can_next_page'])
        with self.assertRaises(RuntimeError):self.w.next_text_page('phone001',state['job_id'],0)


class HttpTextTests(TextWorkflowTests):
    def setUp(self):
        super().setUp();hub=Hub(Path(self.tmp.name)/'uploads',token='paired')
        self.server=DisplayServer(('127.0.0.1',0),hub,workflow=self.w,interfaces=[])
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.close)
    def close(self):self.server.shutdown();self.server.server_close();self.thread.join(2)
    def req(self,path,data=None,headers=None):
        hdr=dict(headers or {});raw=None
        if data is not None:raw=json.dumps(data).encode();hdr['Content-Type']='application/json'
        req=urllib.request.Request('http://127.0.0.1:%d'%self.server.server_port+path,data=raw,headers=hdr)
        try:
            with urllib.request.urlopen(req,timeout=10) as r:return r.status,json.loads(r.read())
        except urllib.error.HTTPError as e:return e.code,json.loads(e.read())
    def test_authority_and_full_phone_flow(self):
        self.assertEqual(self.req('/api/text/capabilities')[0],403)
        self.assertEqual(self.req('/api/text/capabilities?t=paired')[1]['count'],3500)
        code,p=self.req('/api/text/preview?t=paired',dict(cid='phone001',text='一',font_size_mm=40));self.assertEqual(code,200)
        data={k:p[k] for k in ('text','font_size_mm','preview_id','revision')}
        data.update(cid='phone001',request_id='http001',start_requested=True)
        self.assertEqual(self.req('/api/text/submit?t=paired',data,{'Origin':'http://evil.invalid'})[0],403)
        code,state=self.req('/api/text/submit?t=paired',data);self.assertEqual(code,200);self.finish()
        code,again=self.req('/api/text/submit?t=paired',data);self.assertEqual(code,200)
        self.assertEqual(state['job_id'],again['job_id']);self.assertEqual(self.pipeline.calls.count(('execute',)),1)
        self.assertEqual(self.req('/api/text/status?t=paired&cid=phone002&job_id='+state['job_id'])[0],400)

    def test_screen_next_page_keeps_complete_workflow_state(self):
        state=self.w.submit_text('phone001',self.request());self.finish()
        headers={'X-Screen-Token':self.server.hub.control_token}
        code,value=self.req('/api/workflow/text-next-page',dict(job_id=state['job_id'],page_index=0,paper_ready=True),headers)
        self.assertEqual(code,200);self.assertTrue(value['text_mode']);self.assertEqual(value['input_mode'],'calligraphy')
        self.assertIn('preview_url',value);self.finish()


if __name__=='__main__':unittest.main()
