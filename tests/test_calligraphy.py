"""Brush preset integration, actual native IK, and SDK arguments; no physical motion."""
import copy
import json
import re
import shutil
import subprocess
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
import numpy as np
from calligraphy.presets import BRUSH,STROKES,RADICALS,binding,profile,task,validate_task,catalog,preview_svg
from calligraphy.curves import BrushCurve
from calligraphy.presets import modules
from calligraphy.library import CATEGORY, NOTES, SECTIONS
from tcb705.config import demo_config
from tcb705.planner import plan,PHASE
from tcb705.artifact import freeze,check_frozen,save,load,load_nodes
from tcb705.web_executor import build,settings,joint_merge,prepare_joint
from tcb705.model import Model,ROOT
from tcb705.sdk_motion import SdkMotion

def configuration():
    c=demo_config()
    c['calligraphy']=dict(BRUSH,max_press_mm=.3,speed_pct=5,verified=True,calibration_binding=binding(c))
    c['execution']['web_program']=dict(enabled=True,mode='joint',ik_role='execution')
    return c

class PresetTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is needed to compare GUI and backend previews')
    def test_preview_curves_have_no_gaps_and_match_backend(self):
        script = r'''
const fs=require('fs'),vm=require('vm');
const source=fs.readFileSync('user_gui/static/calligraphy.js','utf8');
const created=[];
const createElement=tag=>{
  const ctx={paths:[],copies:[],setTransform(...t){this.transform=t;},beginPath(){this.path=[];},
    moveTo(x,y){this.path.push(x,y);},lineTo(x,y){this.path.push(x,y);},
    stroke(){this.paths.push({d:this.path.slice(),width:this.lineWidth,alpha:this.globalAlpha,
      color:this.strokeStyle,cap:this.lineCap,join:this.lineJoin});},
    drawImage(image,x,y){this.copies.push({image,x,y});}};
  const canvas={tag,children:[],attributes:{},setAttribute(k,v){this.attributes[k]=String(v);},getContext(){return ctx;}};
  created.push(canvas);return canvas;
};
const context={document:{createElement}};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('  var previewCache='),source.indexOf('  function buttons()')),context);
const items=JSON.parse(fs.readFileSync(0,'utf8'));
const rendered=items.map(item=>{
 const canvas=context.preview(item),ctx=canvas.getContext('2d'),again=context.preview(item),cached=again.getContext('2d');
 if(canvas.tag!=='canvas'||canvas.children.length)throw Error('Preview must be one bitmap, not SVG path DOM');
 if(cached.paths.length||cached.copies.length!==1||cached.copies[0].image!==canvas)throw Error('Repeated preview was not cached');
 return {paths:ctx.paths,transform:ctx.transform,width:canvas.width,height:canvas.height};
});
process.stdout.write(JSON.stringify(rendered));
'''
        items=catalog()['items']
        result=subprocess.run([shutil.which('node'),'-e',script],input=json.dumps(items),
                              capture_output=True,text=True,check=True,cwd=ROOT)
        rendered=json.loads(result.stdout)
        def coordinates(path):
            return [float(v) for v in re.findall(r'-?\d+(?:\.\d+)?(?:e[+-]?\d+)?',path)]
        for item,render in zip(items,rendered):
            paths=render['paths']
            svg=ET.fromstring(preview_svg(item['id']))
            backend=list(svg.iter('{http://www.w3.org/2000/svg}path'))
            # Browser canvas and backend SVG have the same view bounds. Scaling
            # changes only pixels, never the sampled path or pressure profile.
            x,y,w,h=map(float,svg.attrib['viewBox'].split())
            scale=384/max(w,h)
            np.testing.assert_allclose(render['transform'],[scale,0,0,scale,-x*scale,-y*scale],atol=1e-5)
            self.assertLessEqual(max(render['width'],render['height']),384)
            self.assertLessEqual(abs(render['width']-w*scale),1)
            self.assertLessEqual(abs(render['height']-h*scale),1)
            self.assertEqual(len(paths),len(backend))
            for js,py in zip(paths,backend):
                np.testing.assert_allclose(js['d'],coordinates(py.attrib['d']),atol=1e-6)
                self.assertEqual(js['width'],float(py.attrib['stroke-width']))
                self.assertEqual(js['alpha'],float(py.attrib['stroke-opacity']))
                self.assertEqual(js['color'],'#1f1a16')
                self.assertEqual(js['cap'],'round');self.assertEqual(js['join'],'round')
            offset=0
            for chain in item['strokes']:
                previous=chain[0][:2]
                for path in paths[offset:offset+len(chain)-1]:
                    coords=path['d']
                    np.testing.assert_allclose(coords[:2],previous,atol=1e-6)
                    previous=coords[-2:]
                    self.assertTrue(.4<=path['width']<=3.8)
                    self.assertTrue(.38<=path['alpha']<=1)
                np.testing.assert_allclose(previous,chain[-1][:2],atol=1e-6)
                offset+=len(chain)-1
            self.assertEqual(offset,len(paths))

    def test_all_curves_bounded_continuous_and_preserve_authored_knots(self):
        for key in list(STROKES)+list(RADICALS):
            for chain in modules(key):
                curve=BrushCurve(chain);dense=curve.sample(1.2)
                self.assertEqual(dense[0][2],0);self.assertEqual(dense[-1][2],0)
                for knot in chain:
                    self.assertTrue(any(np.allclose(p,knot,atol=1e-12) for p in dense))
                for i in range(len(chain)-1):
                    a,b=np.array(chain[i]),np.array(chain[i+1])
                    points=np.array([curve.at(i,u) for u in np.linspace(0,1,31)])
                    self.assertTrue(np.all(points>=np.minimum(a,b)-1e-10),key)
                    self.assertTrue(np.all(points<=np.maximum(a,b)+1e-10),key)
                for i in range(1,len(chain)-1):
                    eps=1e-5;v=np.array(chain[i])
                    left=(v-curve.at(i-1,1-eps))/(eps*(curve.t[i]-curve.t[i-1]))
                    right=(np.array(curve.at(i,eps))-v)/(eps*(curve.t[i+1]-curve.t[i]))
                    np.testing.assert_allclose(left,right,atol=2e-4,rtol=0,err_msg=key)
                jumps=np.abs(np.diff(dense,axis=0))
                self.assertLessEqual(np.linalg.norm(jumps[:,:2],axis=1).max()*1.2,.350001)
                self.assertLessEqual(jumps[:,2].max(),.035001)
                self.assertLessEqual(jumps[:,3].max(),.040001)

    def test_enclosures_meet_and_no_old_version_reuse(self):
        for key in ('kou','ri'):
            chains=[np.array(BrushCurve(c).sample()) for c in modules(key)]
            bottom=chains[-1];left,right=chains[:2]
            # The final horizontal must meet each side, not float inside the box.
            for side in (left,right):
                distance=np.linalg.norm(bottom[:,None,:2]-side[None,:,:2],axis=2)
                self.assertLess(distance.min(),1.0,key)
        c=configuration();p=task('heng',40,c)
        p['calligraphy']['version']='brush-modules-20261021-v3'
        with self.assertRaises(ValueError):validate_task(p,c)

    def test_library_and_correct_radical_order(self):
        self.assertEqual((len(STROKES),len(RADICALS)),(35,53))
        self.assertEqual([r['module'] for r in RADICALS['tu'][1]],['heng','shu_chuilu','heng'])
        self.assertEqual([r['module'] for r in RADICALS['nv'][1]],['pie_dian','pie','heng'])
        self.assertEqual([r['module'] for r in RADICALS['san_dian_shui'][1]],['dian','dian','ti'])
        for k in list(STROKES)+list(RADICALS):
            p=task(k,40,configuration());validate_task(p,configuration())
            for xy,depth,feed in zip(p['paths'],p['calligraphy']['depth_mm'],p['calligraphy']['feed_ratio']):
                self.assertEqual(len(xy),len(depth));self.assertEqual(len(xy),len(feed))
                self.assertEqual(depth[-1],0)
                self.assertTrue(all(0<=d<=.3 for d in depth))
                self.assertTrue(all(0<v<=1 for v in feed))

    def test_expanded_components_order_and_membership(self):
        expected={
            'ti_shou':['duan_heng','shu_gou','ti'],
            'shu_xin':['zuo_dian','dian','shu_chuilu'],
            'cao_zitou':['heng','duan_shu','shu_pie'],
            'zhi':['dian','heng_zhe_zhe_pie','ping_na'],
            'ma':['heng_zhe','shu_zhe_zhe_gou','heng'],
            'che':['duan_heng','pie_zhe','shu_chuilu','ti'],
            'tian':['shu_chuilu','heng_zhe','duan_heng','duan_shu','heng'],
            'bao_gai':['dian','zuo_dian','heng_gou'],
            'zuo_er':['heng_pie_wan_gou','shu_chuilu'],
            'you_er':['heng_pie_wan_gou','shu_xuanzhen'],
        }
        for key,order in expected.items():
            self.assertEqual([r['module'] for r in RADICALS[key][1]],order,key)
        keys=set(STROKES)|set(RADICALS)
        self.assertEqual(keys,set(CATEGORY));self.assertEqual(keys,set(NOTES))
        listed=[key for s in SECTIONS.values() for key in s.split()]
        self.assertEqual(len(listed),len(set(listed)))
        self.assertFalse(set(STROKES)&set(RADICALS))
        for key in keys:
            for chain in modules(key):
                self.assertTrue(all(0<=p[0]<=50 and 0<=p[1]<=50 for p in chain),key)
                # Authored compound turns must not accidentally become separate lifts.
                self.assertTrue(all(p[2]>0 for p in chain[1:-1]),key)
        # The two visually similar strokes exit in opposite vertical directions.
        zhe=np.array(STROKES['pie_zhe'][1]);dian=np.array(STROKES['pie_dian'][1])
        self.assertLess(zhe[-1,1],zhe[zhe[:,0].argmin(),1])
        self.assertGreater(dian[-1,1],dian[dian[:,0].argmin(),1])

    def test_structural_joins_reach_neighbouring_strokes(self):
        pairs={'tian':[(3,1),(3,4)],'zu':[(3,2)],'dan_ren':[(0,1)],
               'shuang_ren':[(1,2)],'bao_gai':[(1,2)],'mu_eye':[(4,0),(4,1)],
               'wei':[(2,0),(2,1)],'min_di':[(4,0),(4,1),(4,2),(4,3)]}
        for key,connections in pairs.items():
            chains=[np.array(BrushCurve(c).sample()) for c in modules(key)]
            for a,b in connections:
                d=np.linalg.norm(chains[a][:,None,:2]-chains[b][None,:,:2],axis=2)
                self.assertLess(d.min(),.5,(key,a,b))

    @unittest.skipUnless(shutil.which('node'), 'Node needed for browser module controls')
    def test_catalog_paging_filtering_and_empty_selection(self):
        script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const elements={};
const painted={segments:0,copies:0};
function node(tag){return {tagName:tag.toUpperCase(),children:[],attributes:{},dataset:{},value:'',disabled:false,
 setAttribute(k,v){this.attributes[k]=v;},appendChild(c){this.children.push(c);},focus(){},
 getContext(){return {setTransform(){},beginPath(){},moveTo(){},lineTo(){},stroke(){painted.segments++;},drawImage(){painted.copies++;}};},
 set textContent(s){this.text=s;this.children=[];},get textContent(){return this.text||'';}};}
const document={getElementById(id){return elements[id]||(elements[id]=node('div'));},
 createElement:node,createElementNS:(_ns,t)=>node(t),addEventListener(e,f){if(e==='DOMContentLoaded')f();}};
const data=JSON.parse(fs.readFileSync(0,'utf8'));data.profile={verified:true,max_press_mm:.3,speed_pct:5};data.simulation=true;
const context={document,window:{},setTimeout,clearTimeout,fetch:async()=>({ok:true,json:async()=>data})};vm.createContext(context);
vm.runInContext(fs.readFileSync('user_gui/static/panel-request.js','utf8'),context);
vm.runInContext(fs.readFileSync('user_gui/static/calligraphy.js','utf8'),context);
(async()=>{
 await context.window.BrushModules.open({token:()=>'',submit:async()=>{}});
 const grid=()=>elements['brush-grid'].children.filter(c=>c.tagName==='BUTTON');
 assert.strictEqual(grid().length,12);assert(elements['brush-prev'].disabled);
 assert(grid().every(b=>b.children[0].tagName==='CANVAS'&&b.children[0].children.length===0));
 assert.strictEqual(painted.segments,data.items.slice(0,12).reduce((n,i)=>n+i.strokes.reduce((m,c)=>m+c.length-1,0),0));
 const paintedBefore=painted.segments;grid()[0].onclick();
 assert.strictEqual(painted.segments,paintedBefore);assert(painted.copies>=2);
 elements['brush-next'].onclick();assert.strictEqual(grid().length,12);
 const onSecond=grid()[0].dataset.id;assert.notStrictEqual(onSecond,data.items[0].id);
 elements['brush-radical'].onclick();assert.strictEqual(grid().length,12);
 elements['brush-search'].value='提手旁';elements['brush-search'].oninput();
 assert.deepStrictEqual(grid().map(c=>c.dataset.id),['ti_shou']);
 assert.strictEqual(elements['brush-name'].textContent,'扌');
 elements['brush-search'].value='ti shou';elements['brush-search'].oninput();assert.strictEqual(grid().length,1);
 elements['brush-search'].value='notfound';elements['brush-search'].oninput();
 assert.strictEqual(grid().length,0);assert(elements['brush-write'].disabled);assert(elements['brush-plan'].disabled);
 elements['brush-search'].value='';elements['brush-category'].value='字头';elements['brush-category'].onchange();
 assert.strictEqual(grid().length,6);assert(!elements['brush-plan'].disabled);
 assert(grid().every(b=>data.items.find(i=>i.id===b.dataset.id).category==='字头'));
 elements['brush-category'].value='';elements['brush-category'].onchange();
 const found=new Set();do{grid().forEach(b=>found.add(b.dataset.id));if(elements['brush-next'].disabled)break;elements['brush-next'].onclick();}while(true);
 assert.strictEqual(found.size,53);assert(elements['brush-next'].disabled);
 // Missing real brush parameters open an actionable form, never a motion POST.
 let submitted=0;data.simulation=false;data.profile.verified=false;data.profile.max_press_mm=0;
 await context.window.BrushModules.open({token:()=>'',submit:async()=>{submitted++;}});
 assert(!elements['brush-write'].disabled);assert(elements['brush-plan'].disabled);
 assert.strictEqual(elements['brush-write'].textContent,'设置毛笔参数');
 elements['brush-write'].onclick();await new Promise(resolve=>setImmediate(resolve));
 assert(elements['brush-panel'].className.includes('brush-setup'));assert(!elements['brush-back'].hidden);
 assert.strictEqual(submitted,0);assert.strictEqual(data.profile.verified,false);
 elements['brush-back'].onclick();assert(!elements['brush-panel'].className.includes('brush-setup'));
 data.profile.verified=true;data.profile.max_press_mm=4;
 await context.window.BrushModules.open({token:()=>'',submit:async()=>{submitted++;}});
 assert.strictEqual(elements['brush-write'].textContent,'书写所选');assert(!elements['brush-write'].disabled);
 assert.strictEqual(submitted,0,'loading verified settings must not auto-submit');
 data.simulation=true;
 // A stalled submit must still allow returning to the main screen.
 let rejectSubmit;
 await context.window.BrushModules.open({token:()=>'',submit:()=>new Promise((_resolve,reject)=>{rejectSubmit=reject;})});
 elements['brush-write'].onclick();
 assert(elements['brush-write'].disabled);assert(!elements['brush-close'].disabled);
 elements['brush-close'].onclick();assert(elements['calligraphy-modal'].hidden);
 rejectSubmit(Error('request timed out'));
 await new Promise(resolve=>setImmediate(resolve));
 assert(!elements['brush-write'].disabled);
 process.stdout.write('paging, aliases, empty guard, category, all 53 reachable');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result=subprocess.run([shutil.which('node'),'-e',script],input=json.dumps(catalog()),
                              capture_output=True,text=True,cwd=ROOT)
        self.assertEqual(result.returncode,0,result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node needed for request failure regression')
    def test_panel_request_timeout_and_late_reply_never_retry(self):
        script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
let calls=0,late;
const context={window:{},setTimeout,clearTimeout,
 AbortController:typeof AbortController==='undefined'?undefined:AbortController,
 fetch:()=>{calls++;return new Promise(resolve=>{late=resolve;});}};
vm.createContext(context);vm.runInContext(fs.readFileSync('user_gui/static/panel-request.js','utf8'),context);
(async()=>{
 let succeeded=0;
 await assert.rejects(context.window.PanelRequest.json('/submit',{method:'POST'},20).then(()=>{succeeded++;}),/超时/);
 late({ok:true,json:async()=>({job_id:'late'})});
 await new Promise(r=>setTimeout(r,25));assert.strictEqual(calls,1);assert.strictEqual(succeeded,0);
 context.fetch=async()=>({ok:true,json:()=>new Promise(()=>{})});
 await assert.rejects(context.window.PanelRequest.json('/state',{},20),/超时/);
 context.fetch=async()=>({ok:false,json:async()=>({error:'expected rejection'})});
 await assert.rejects(context.window.PanelRequest.json('/submit',{method:'POST'}),/expected rejection/);
 context.fetch=async()=>({ok:true,json:async()=>({ok:123})});
 assert.strictEqual((await context.window.PanelRequest.json('/state')).ok,123);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result=subprocess.run([shutil.which('node'),'-e',script],capture_output=True,text=True,cwd=ROOT)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_size_does_not_scale_compression_and_tampering_rejected(self):
        c=configuration();a=task('heng',20,c);b=task('heng',40,c)
        self.assertAlmostEqual(max(a['calligraphy']['depth_mm'][0]),max(b['calligraphy']['depth_mm'][0]))
        a['calligraphy']['depth_mm'][0][0]=2
        with self.assertRaises(ValueError):validate_task(a,c)
        for bad in (float('nan'),0,100,True):
            with self.assertRaises(ValueError):task('heng',bad,c)

    def test_no_assumed_depth_and_calibration_invalidation(self):
        c=demo_config()
        self.assertEqual(profile(c)['max_press_mm'],0)
        with self.assertRaises(ValueError):profile(c,True)
        c=configuration();self.assertTrue(profile(c,True)['verified'])
        c['T_flange_tcp'][2][3]+=.001
        with self.assertRaises(ValueError):profile(c,True)

class PlanningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c=configuration()
        cls.p=task('heng',20,cls.c)
        cls.r=plan(cls.p,cls.c)
        cls.doc,cls.nodes=freeze(cls.r,'demo')

    def test_order_and_depth_survive_actual_ik(self):
        c=configuration();r=plan(task('tu',20,c),c)
        ids=r['node_stroke_ids'];self.assertEqual(list(dict.fromkeys(ids.tolist())),[0,1,2])
        drawing=r['interval_phase']==PHASE['DRAW']
        z=r['geometric_positions'][1:][drawing,2]
        self.assertLess(z.min(),c['paper']['origin_m'][2]-.00005)
        pos=self.r['geometric_positions'];d=np.diff(pos,axis=0)
        self.assertTrue(np.any((np.linalg.norm(d[:,:2],axis=1)<1e-10)&(abs(d[:,2])>1e-8)&(self.r['interval_phase']==1)))
        self.assertIsNone(self.r['metrics']['max_orientation_error_rad'])
        # Independent offline oracle; this work is deliberately absent from
        # the runtime planner and is not a runtime precision guarantee.
        poses=Model(self.c).fk_batch(self.r['q_rad'])
        rotation=np.asarray(self.c['tool_rotation'])
        angles=np.arccos(np.clip((np.einsum('nij,ij->n',poses[:,:3,:3],rotation)-1)/2,-1,1))
        self.assertLess(float(angles.max()),self.c['planning']['orientation_tolerance_rad'])

    def test_frozen_saved_metadata_and_integrity(self):
        check_frozen(self.doc,self.nodes,self.c)
        # Legacy profiles embedded 5% in both config and node metadata. It must
        # remain hash checked but cannot lock execution to that stale value.
        from tcb705.artifact import nodes_hash
        legacy=copy.deepcopy(self.nodes);legacy['calligraphy']['brush']['speed_pct']=5
        doc=copy.deepcopy(self.doc);doc['brush_nodes_sha256']=nodes_hash(legacy)
        changed=copy.deepcopy(self.c)
        changed['execution']['web_program']['draw_speed_pct']=40
        check_frozen(doc,legacy,changed)
        n=copy.deepcopy(self.nodes);n['interval_feed_ratio'][0]=.5
        with self.assertRaises(ValueError):check_frozen(self.doc,n,self.c)
        with tempfile.TemporaryDirectory() as d:
            save(self.r,d,'demo');doc=load(d,with_rows=False);n=load_nodes(d,doc)
            self.assertEqual(n['calligraphy'],self.nodes['calligraphy'])
            self.assertEqual(n['interval_feed_ratio'],self.nodes['interval_feed_ratio'])

    def test_joint_preparation_and_sdk_use_one_gui_speed(self):
        c=copy.deepcopy(self.c)
        c['execution']['web_program'].update(draw_speed_pct=40,air_speed_pct=40)
        check_frozen(self.doc,self.nodes,c)  # GUI speed does not stale a geometric plan.
        s=settings(c);keep=joint_merge(c,self.nodes,s)
        ready=prepare_joint(c,self.nodes)
        self.assertEqual(tuple(keep),ready.keep)
        self.assertEqual((keep[0],keep[-1]),(0,len(self.nodes['positions_m'])-1))
        mm,chunks=build(c,self.nodes,s,joint_keep=ready.keep)
        indices=[i for chunk in chunks for i in chunk['node_index']]
        self.assertEqual(indices,list(ready.keep[1:]))
        blocks=[b for chunk in chunks for b in chunk['content']['programs'][0]['codeBlock'] if b['fc']!='end']
        for i,b in zip(indices,blocks):
            code=b['code']
            self.assertEqual(code['speed'],40)
            self.assertIs(code['brush_uniform_speed'],True)
            self.assertNotIn('brush_feed_ratio',code)
            self.assertEqual(code['smooth'],0)
            self.assertEqual(code['endp'],[round(float(v),4) for v in self.nodes['sdk_degrees'][i]])
        sdk=Mock();sdk.move.side_effect=range(10,20000);sdk.finished.return_value=True
        motion=SdkMotion(sdk,Mock(),c)
        motion.set_speed(40)
        for chunk in chunks:
            motion.start(chunk['content'],lambda:False)
            while motion.pending:motion.pump()
        self.assertEqual(sdk.move.call_count,len(indices))
        self.assertTrue(all('ratio' not in c.kwargs for c in sdk.move.call_args_list))
        self.assertEqual([c.args[1] for c in sdk.move.call_args_list],[b['code']['endp'] for b in blocks])
        sdk.set_speed.assert_called_once_with(40)

class HttpTests(unittest.TestCase):
    def setUp(self):
        from app import State,Server
        from user_gui.workflow import BoardPipeline,Workflow
        from user_gui.display_server import Hub,DisplayServer
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.backend=Server(('127.0.0.1',0),State(self.tmp.name),robot='tcb705',simulation=True,
                            profile=ROOT/'robots/tcb705/profile.demo.json')
        threading.Thread(target=self.backend.serve_forever,daemon=True).start()
        self.addCleanup(self.backend.server_close);self.addCleanup(self.backend.shutdown)
        pipeline=BoardPipeline('http://127.0.0.1:%d'%self.backend.server_port,self.tmp.name)
        self.workflow=Workflow(pipeline,self.tmp.name)
        self.hub=Hub(Path(self.tmp.name)/'uploads',token='pair')
        self.display=DisplayServer(('127.0.0.1',0),self.hub,interfaces=[],workflow=self.workflow)
        threading.Thread(target=self.display.serve_forever,daemon=True).start()
        self.addCleanup(self.display.server_close);self.addCleanup(self.display.shutdown)
        self.base='http://127.0.0.1:%d'%self.display.server_port
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def req(self,path,body=None,token=True):
        hdr={'Content-Type':'application/json'}
        if token:hdr['X-Screen-Token']=self.hub.control_token
        req=urllib.request.Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers=hdr)
        with self.opener.open(req,timeout=30) as r:return json.loads(r.read())

    def test_catalog_auth_profile_and_full_prepare_execute(self):
        self.assertEqual(len(self.req('/api/tcb/calligraphy')['items']),88)
        with self.assertRaises(urllib.error.HTTPError):
            self.req('/api/workflow/calligraphy',{'module':'heng','size_mm':20},False)
        with self.assertRaises(urllib.error.HTTPError):
            self.req('/api/tcb/brush-profile',{'max_press_mm':7,'speed_pct':5,'verified':True})
        d=self.req('/api/tcb/brush-profile',{'max_press_mm':.3,'speed_pct':5,'verified':True})
        self.assertTrue(d['profile']['verified'])
        w=self.req('/api/workflow/calligraphy',{'module':'heng','size_mm':20,'request_id':'test1'})
        with self.assertRaises(urllib.error.HTTPError):
            self.req('/api/workflow/calligraphy',{'module':'dian','size_mm':20})
        self.workflow.worker.join(20)
        w=self.workflow.snapshot();self.assertEqual(w['phase'],'ready',w)
        self.assertEqual(w['input_mode'],'calligraphy')
        self.assertNotIn('image',[j['kind'] for j in self.backend.workbench.jobs.values()])
        self.assertNotIn('execute',[j['kind'] for j in self.backend.workbench.jobs.values()])
        with self.assertRaises(ValueError):self.workflow.start(w['job_id'],w['revision']-1,True)
        self.req('/api/workflow/start',{'job_id':w['job_id'],'revision':w['revision'],'confirmed':True})
        self.workflow.worker.join(20)
        w=self.workflow.snapshot();self.assertEqual(w['phase'],'completed',w)
        self.assertIn('模拟',w['message'])

if __name__=='__main__':unittest.main()
