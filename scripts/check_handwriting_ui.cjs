// End-to-end against an explicitly simulated local backend. Never use a real board URL.
const {chromium}=require('C:/Users/gongj/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');
(async()=>{
 const base='http://127.0.0.1:8099',out=path.resolve('build/handwriting_20261023');
 const b=await chromium.launch({headless:true,channel:'msedge'});
 const p=await b.newPage({viewport:{width:1024,height:600}}),errors=[];
 const legacy=process.env.HANDWRITING_LEGACY_INPUT==='1';
 if(legacy)await p.addInitScript(()=>{window.PointerEvent=undefined;});
 p.on('pageerror',e=>errors.push(e.message));
 async function statusUntil(test){
  let state;const deadline=Date.now()+30000;
  do{state=await p.request.get(base+'/api/handwriting/status').then(r=>r.json());if(test(state))return state;await new Promise(r=>setTimeout(r,40));}while(Date.now()<deadline);
  throw Error('State timeout: '+JSON.stringify(state));
 }
 try{
  let initial=await p.request.get(base+'/api/handwriting/status').then(r=>r.json());
  if(initial.phase!=='CLOSED'){
   const token=(await p.request.get(base+'/api/state').then(r=>r.json())).control_token;
   await p.request.post(base+'/api/handwriting/close',{headers:{'X-Screen-Token':token},data:{session_id:initial.session_id}});
   for(let i=0;i<100;i++){initial=await p.request.get(base+'/api/handwriting/status').then(r=>r.json());if(initial.phase==='CLOSED')break;await new Promise(r=>setTimeout(r,30));}
  }
  await p.goto(base);await p.waitForFunction(()=>!document.getElementById('open-handwriting').disabled);
  assert((await p.request.get(base+'/api/tcb/status').then(r=>r.json())).simulation===true);
  await p.screenshot({path:path.join(out,'main-with-handwriting.png')});
  await p.getByRole('button',{name:'手写模式',exact:true}).click();
  await p.waitForURL('**/handwriting');await p.getByText('悬停等待',{exact:true}).waitFor();
  await p.locator('[data-size="60"]').click();
  await p.getByText('本字使用 60 mm',{exact:true}).waitFor();
  async function stroke(ps){let r=await p.locator('#ink').boundingBox();await p.mouse.move(r.x+r.width*ps[0][0],r.y+r.height*ps[0][1]);await p.mouse.down();for(let q of ps.slice(1))await p.mouse.move(r.x+r.width*q[0],r.y+r.height*q[1],{steps:12});await p.mouse.up();}
  await stroke([[.18,.35],[.80,.35]]);
  await stroke([[.50,.18],[.50,.83]]);
  let s=await statusUntil(s=>s.strokes.length===2&&s.strokes.every(x=>x.status==='DONE'));
  fs.writeFileSync(path.join(out,'ui-two-stroke-state.json'),JSON.stringify(s,null,2));
  assert.deepStrictEqual(s.strokes.map(x=>x.match.module),['heng','shu_chuilu']);
  await p.screenshot({path:path.join(out,'handwriting-ten.png')});
  await p.locator('[data-size="100"]').click();
  await p.getByText('下个字使用 100 mm',{exact:true}).waitFor();
  await p.reload();await p.getByText('悬停等待',{exact:true}).waitFor();
  s=await p.request.get(base+'/api/handwriting/status').then(r=>r.json());assert.equal(s.strokes.length,2);
  // Cancellation must not submit a third stroke.
  const box=await p.locator('#ink').boundingBox();
  await p.mouse.move(box.x+150,box.y+150);await p.mouse.down();
  if(legacy)await p.evaluate(()=>window.dispatchEvent(new Event('blur')));
  else await p.locator('#ink').dispatchEvent('pointercancel',{pointerId:1,isPrimary:true});
  await p.mouse.up();
  await p.getByRole('button',{name:'下一个字',exact:true}).click();
  s=await statusUntil(s=>s.character===2&&s.phase==='READY');assert.equal(s.strokes.length,0);assert.equal(s.size_mm,100);
  await p.getByRole('button',{name:'停止',exact:true}).click();await p.getByText('已停止',{exact:true}).waitFor();
  await p.reload();await p.getByText('已停止',{exact:true}).waitFor();
  await p.getByRole('button',{name:'返回',exact:true}).click();await p.waitForURL(base+'/');
  s=await p.request.get(base+'/api/handwriting/status').then(r=>r.json());assert.equal(s.phase,'CLOSED');
  assert.deepStrictEqual(errors,[]);
  fs.writeFileSync(path.join(out,'ui-check.json'),JSON.stringify({status:'PASS',simulation:true,checks:['main entrance','automatic simulated preparation','two pointer strokes','CPU classification and planning','ordered completion','size next character','refresh preserves ink','pointercancel','next clears after return','stop no automatic resume','return releases session','no JS errors']},null,2));
  console.log(legacy?'HANDWRITING_LEGACY_UI_PASS':'HANDWRITING_UI_PASS');
 }finally{await b.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
