"""Regression for unnecessary ARM32 software repaints on idle polling."""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class PanelRenderTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node required')
    def test_unchanged_polling_and_speed_do_not_mutate_dom(self):
        script=r'''
const vm=require('vm'),fs=require('fs'),assert=require('assert');
let writes=0;const elements={};
function classes(){const set=new Set();   // counts a write only when a class really changes
 return {toggle(n,f){const on=f===undefined?!set.has(n):!!f;if(on!==set.has(n)){writes++;on?set.add(n):set.delete(n);}return on;},
  add(n){this.toggle(n,true);},remove(n){this.toggle(n,false);},contains(n){return set.has(n);}};}
function elem(){return new Proxy({textContent:'',className:'',style:{},children:[],classList:classes(),
 getAttribute(k){return this[k];},setAttribute(k,v){this[k]=v;},removeAttribute(k){delete this[k];}},
 {set(o,k,v){writes++;o[k]=v;return true;}});}
const document={getElementById(id){return elements[id]||(elements[id]=elem());},addEventListener(){}};
document.getElementById('phone-status').children=[elem(),elem()];
const state={workflow:{phase:'idle'},control_token:'test',clients:[]},requests=[];
const ctx={document,window:{PanelRequest:{json:async()=>state}},EventSource:function(){this.addEventListener=function(){};},
 setInterval(){},setTimeout(){},clearTimeout(){},location:{search:''},URLSearchParams,QR:{svg:()=>''},
 fetch:async(url,options)=>{requests.push([url,options]);return {ok:true,json:async()=>url.includes('status')?{robot_type:'TCB705',simulation:true}:
 url.includes('/speed')?{speed_pct:25,live_applied:true}:{execution:{web_program:{draw_speed_pct:20}}}};}};
vm.createContext(ctx);
let code=fs.readFileSync('user_gui/static/desktop.js','utf8');
code=code.replace(/\}\)\(\);\s*$/,'window.probe={render,network,workflow,showSpeed,saveSpeed};})();');
vm.runInContext(code,ctx);
(async()=>{
 await new Promise(r=>setImmediate(r));
 const p=ctx.window.probe;p.network(true);p.showSpeed();p.render();
 writes=0;for(let i=0;i<10;i++){p.network(true);p.workflow({phase:'idle'});p.showSpeed();p.render();}
 assert.strictEqual(writes,0,'identical polling must not invalidate layout');
 p.network(false);assert(writes>0);assert(elements['open-calligraphy'].disabled);
 p.network(true);assert(!elements['open-calligraphy'].disabled);
 p.workflow({phase:'planning',job_id:'one',can_cancel:true});assert(elements['open-calligraphy'].disabled);
 p.workflow({phase:'completed',job_id:'one'});assert(!elements['open-calligraphy'].disabled);
 // Calligraphy shares the visible speed controls, including while it runs.
 for(const phase of ['planning','ready','drawing','stopping']){
   p.workflow({phase,input_mode:'calligraphy',job_id:'one',can_cancel:true});p.showSpeed();
   assert.strictEqual(elements['speed-value'].textContent,'20%');
   assert(!elements['speed-up'].disabled);assert(!elements['speed-down'].disabled);
   assert.strictEqual(elements['speed-box'].title,'书法与归位均使用此速度');
 }
 writes=0;for(let i=0;i<10;i++){p.showSpeed();p.render();}assert.strictEqual(writes,0);
 elements['speed-up'].onclick();assert.strictEqual(elements['speed-value'].textContent,'25%');
 await p.saveSpeed();
 const saved=requests.filter(r=>r[0]==='/api/tcb/speed').pop();
 assert.strictEqual(JSON.parse(saved[1].body).speed_pct,25);
 assert.strictEqual(elements['action-error'].textContent,'速度已改为 25%，已应用到当前任务');
 p.workflow({phase:'drawing',input_mode:'lineart',job_id:'one',can_cancel:true});
 await p.saveSpeed();assert.strictEqual(elements['action-error'].textContent,'速度已改为 25%，已应用到当前任务');
 // Homing remains a busy task; normal stop exposes a second stop for the return.
 for(const stage of ['HOME','RETURN_HOME','HOME_AFTER_STOP']){
   p.workflow({phase:'drawing',input_mode:'calligraphy',motion_stage:stage,job_id:'one',can_cancel:true});
   assert(elements['workflow-title'].textContent.includes('归位'));
   assert(elements['open-settings'].disabled);assert(elements['open-calligraphy'].disabled);
   assert(!elements['cancel-job'].hidden);assert(!elements['cancel-job'].disabled);
 }
 p.workflow({phase:'stopping',input_mode:'calligraphy',motion_stage:'HOME_AFTER_STOP',job_id:'one'});
 assert.strictEqual(elements['cancel-job'].textContent,'再次停止');
 assert(!elements['cancel-job'].hidden);assert(!elements['cancel-job'].disabled);
 assert(elements['workflow-title'].textContent.includes('停止书写'));
 assert(elements['open-settings'].disabled);assert(elements['choose-lineart'].disabled);
 assert(elements['open-calligraphy'].disabled);assert(elements['start-drawing'].hidden);
 assert(elements['reset-job'].hidden);assert(elements['workflow-progress'].hidden);
 p.workflow({phase:'cancelled',input_mode:'calligraphy',job_id:'one'});
 assert(!elements['open-calligraphy'].disabled);assert(!elements['reset-job'].hidden);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result=subprocess.run([shutil.which('node'),'-e',script],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    @unittest.skipUnless(shutil.which('node'),'Node required')
    def test_brush_profile_shows_shared_speed_without_saving_an_override(self):
        script=r'''
const vm=require('vm'),fs=require('fs'),assert=require('assert');
const elements={},listeners={},requests=[];
const drawing={setTransform(){},beginPath(){},moveTo(){},lineTo(){},stroke(){},drawImage(){}};
function elem(tag='div'){return {tagName:tag.toUpperCase(),textContent:'',value:'',children:[],dataset:{},
 appendChild(child){this.children.push(child);},setAttribute(){},focus(){},getContext(){return drawing;}};}
const document={getElementById(id){return elements[id]||(elements[id]=elem());},createElement:elem,
 addEventListener(kind,callback){listeners[kind]=callback;}};
const data={simulation:false,speed_pct:20,profile:{verified:true,max_press_mm:4},items:[
 {id:'heng',name:'横',group:'basic',category:'基本',stroke_count:1,strokes:[[[0,0,.1,.5],[50,0,.2,.6]]]}]};
const window={PanelRequest:{json:async(url,opts)=>{requests.push([url,opts]);return data;}}};
const ctx={document,window};vm.createContext(ctx);
vm.runInContext(fs.readFileSync('user_gui/static/calligraphy.js','utf8'),ctx);listeners.DOMContentLoaded();
(async()=>{
 await window.BrushModules.open({token:()=>'test',submit(){throw Error('must not write');}});
 assert.strictEqual(elements['brush-speed'].textContent,'20%（主界面设置）');
 elements['brush-depth'].value='4';elements['brush-verified'].checked=true;
 await elements['brush-save'].onclick();
 const save=requests.find(r=>r[0]==='/api/tcb/brush-profile');
 assert.deepStrictEqual(JSON.parse(save[1].body),{max_press_mm:4,verified:true});
 assert.strictEqual(elements['brush-write'].textContent,'书写所选');
 const html=fs.readFileSync('user_gui/static/desktop.html','utf8');
 assert(/<output id="brush-speed">/.test(html));
 assert(!/<input[^>]+id="brush-speed"/.test(html));
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result=subprocess.run([shutil.which('node'),'-e',script],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

if __name__=='__main__':unittest.main()
