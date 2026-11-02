"""行书/草书/隶书/篆书 libraries: structure, reconstruction and owned phone jobs; no real motion."""
import copy
import tempfile
import unittest

from calligraphy import composer,glyph_store
from calligraphy.presets import validate_task
from user_gui.workflow import Workflow
from tests.test_text_calligraphy import config,FakePipeline

EXTRA=[s for s in ('xing','cao','li','zhuan') if s in glyph_store.available()]


def sample(style,n=2):
    """Characters this (deliberately incomplete) style library contains."""
    return glyph_store.manifest(style)['characters'][:n]


@unittest.skipUnless(EXTRA,'no extra style library installed')
class StyleLibraryTests(unittest.TestCase):
    def test_manifests_and_glyph_records_are_well_formed(self):
        kai=set(glyph_store.manifest()['characters'])
        for style in EXTRA:
            m=glyph_store.manifest(style)
            # Only characters whose every standard stroke traced one-to-one are kept.
            self.assertEqual(m['style'],style);self.assertGreater(m['count'],300)
            self.assertTrue(set(m['characters'])<=kai)
            for ch in m['characters'][::97]:
                g=glyph_store.glyph(ch,style);self.assertEqual(g['character'],ch);self.assertTrue(g['strokes'])
                self.assertGreaterEqual(g['stats']['pen_downs'],g['stats']['kai_strokes'])   # never merged or dropped
                for s in g['strokes']:
                    p=s['points'];self.assertGreaterEqual(len(p),2)
                    self.assertEqual(p[0][2],0);self.assertEqual(p[-1][2],0)
                    self.assertTrue(all(0<=v[0]<=50 and 0<=v[1]<=50 and 0<=v[2]<=1 and 0<v[3]<=1 for v in p))

    def test_unknown_or_missing_style_is_rejected(self):
        with self.assertRaises(ValueError):glyph_store.manifest('song')
        with self.assertRaises(ValueError):composer.task('中国',40,0,config(),'song')

    def test_task_bounds_reconstruction_and_revision(self):
        c=config();kai=composer.revision(c)
        self.assertEqual(kai,composer.revision(c,'kai'))
        revisions={kai}
        for style in EXTRA:
            chars=glyph_store.manifest(style)['characters']
            text=''.join(ch for ch in '天道酬勤永和春风中国人大一二三十' if ch in chars)[:4]
            for size in (40,70):
                p=composer.task(text,size,0,c,style)
                meta=p['calligraphy'];self.assertEqual(meta['style'],style)
                self.assertEqual(meta['revision'],composer.revision(c,style))
                for path,depth,feed in zip(p['paths'],meta['depth_mm'],meta['feed_ratio']):
                    self.assertEqual(len(path),len(depth));self.assertEqual(len(path),len(feed))
                    self.assertEqual(depth[0],0);self.assertEqual(depth[-1],0)
                    self.assertTrue(all(0<=x<=148.52 and 0<=y<=150.215 for x,y in path))
                    self.assertTrue(all(0<=d<=4 for d in depth))
                validate_task(p,c)
                bad=copy.deepcopy(p);bad['calligraphy']['style']='kai'
                with self.assertRaises(ValueError):validate_task(bad,c)
            revisions.add(composer.revision(c,style))
        self.assertEqual(len(revisions),len(EXTRA)+1)

    def test_preview_reports_style(self):
        style=EXTRA[0]
        doc=composer.preview(sample(style),40,config(),style)
        self.assertEqual(doc['style'],style);self.assertEqual(doc['style_label'],glyph_store.STYLES[style])
        self.assertEqual(doc['revision'],composer.revision(config(),style))


class StylePipeline(FakePipeline):
    def register_text(self,spec,cancelled):
        self.calls.append(('register',spec['page_index'],spec.get('style','kai')));return 'src'


@unittest.skipUnless(EXTRA,'no extra style library installed')
class StyleWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.pipeline=StylePipeline();self.w=Workflow(self.pipeline,self.tmp.name);self.style=EXTRA[0]

    def request(self,style,rid='style0001'):
        d=self.w.text_preview('phone001',sample(style),40,style)
        data={k:d[k] for k in ('text','font_size_mm','preview_id','revision')}
        data.update(start_requested=True,request_id=rid,style=style)
        return data

    def test_capabilities_list_installed_styles(self):
        caps=self.w.text_capabilities()
        self.assertEqual([s['style'] for s in caps['styles']],['kai']+EXTRA)
        self.assertEqual(caps['styles'][0]['count'],caps['count'])

    def test_style_reaches_registration(self):
        state=self.w.submit_text('phone001',self.request(self.style))
        self.w.worker.join(10)
        self.assertIn(('register',0,self.style),self.pipeline.calls)
        self.assertEqual(self.w.text_status('phone001',state['job_id'])['style'],self.style)

    def test_changed_style_after_preview_does_not_start(self):
        data=self.request(self.style)
        with self.assertRaises(ValueError):self.w.submit_text('phone001',dict(data,style='kai'))
        self.assertEqual(self.pipeline.calls,[])

    def test_unknown_style_preview_is_rejected(self):
        with self.assertRaises(ValueError):self.w.text_preview('phone001','中国',40,'song')


if __name__=='__main__':
    unittest.main()


MASTER=glyph_store.masterpieces()


def big_paper():
    c=config();c['paper'].update(width_mm=340.,height_mm=250.)
    return c


@unittest.skipUnless(MASTER,'no masterpiece library installed')
class MasterpieceTests(unittest.TestCase):
    def test_positional_records_and_fixed_sentence(self):
        for style in MASTER:
            m=glyph_store.manifest(style)
            self.assertTrue(m['positional']);self.assertEqual(len(m['characters']),m['count'])
            for i in range(m['count']):
                g=glyph_store.glyph_at(style,i);self.assertEqual(g['character'],m['characters'][i])
                for s in g['strokes']:
                    p=s['points'];self.assertEqual(p[0][2],0);self.assertEqual(p[-1][2],0)
            with self.assertRaises(ValueError):composer.task(m['characters'][:2],70,0,big_paper(),style)

    def test_vertical_three_per_column_left_to_right_and_reconstruction(self):
        c=big_paper()
        for style in MASTER:
            m=glyph_store.manifest(style);p=composer.task(m['characters'],70,0,c,style)
            meta=p['calligraphy'];self.assertEqual(meta['direction'],'ttb_columns_ltr');self.assertEqual(meta['style'],style)
            first={}
            for path,item in zip(p['paths'],meta['stroke_map']):first.setdefault(item['text_index'],path[0])
            doc=composer.layout(m['characters'],70,c['paper'],style)
            cells=doc['pages'][0]
            for a,b in zip(cells,cells[1:]):
                if a['column']==b['column']:self.assertGreater(b['y_mm'],a['y_mm'])      # down the column
                else:self.assertGreater(b['x_mm'],a['x_mm']);self.assertEqual(b['row'],0)  # next column to the right
            self.assertTrue(all(c_['row']<3 for c_ in cells))
            validate_task(p,c)

    def test_small_paper_is_refused_with_required_size(self):
        style=MASTER[0];m=glyph_store.manifest(style)
        with self.assertRaisesRegex(ValueError,'名帖表演需要至少'):composer.task(m['characters'],70,0,config(),style)

    def test_screen_workflow_writes_saved_columns_at_fixed_speed(self):
        # 2026-10-27: select -> every column's saved commands -> written column by column at 100 %.
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        pipe=StylePipeline();pipe.config['paper'].update(width_mm=340.,height_mm=250.)
        w=Workflow(pipe,tmp.name)
        with self.assertRaises(ValueError):w.submit_masterpiece(MASTER[0],'mp000000')          # safety not confirmed
        w.submit_masterpiece(MASTER[0],'mp000001',True);w.worker.join(10)
        self.assertEqual(w.state['phase'],'completed',w.state['message'])
        cols=-(-glyph_store.manifest(MASTER[0])['count']//3)
        planned=[c for c in pipe.calls if c[0]=='masterpiece_plan']
        self.assertEqual(planned,[('masterpiece_plan',MASTER[0],k) for k in range(cols)])
        self.assertEqual([c for c in pipe.calls if c[0]=='speed'],[('speed','mp%d'%k,100) for k in range(cols)])
        first_write=pipe.calls.index(('execute',))
        self.assertTrue(all(pipe.calls.index(c)<first_write for c in planned))                 # nothing moves before all are ready
        self.assertFalse([c for c in pipe.calls if c[0] in ('register','plan')])               # no planning on the board
        with self.assertRaises(ValueError):Workflow(pipe,tmp.name).submit_masterpiece('mp_nosuch','mp000002',True)
