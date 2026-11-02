/* Production A workbench. No simulated classification, movement or sample ink. */
(function(){
'use strict';
var $=function(id){return document.getElementById(id);},state=null,token='',pointer=null,points=[],local=[],chain=Promise.resolve(),polling=false,leaving=false,grid=true,uncertain=false;
var canvas=$('ink'),ctx=canvas.getContext('2d'),toastTimer,nextIntent=false,stopIntent=false,strokeBounds=null;
var inkSize=canvas.width,inkScale=inkSize/840;
function notify(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(function(){$('toast').hidden=true;},6500);}
async function request(path,body){
  var options={cache:'no-store'},controller=new AbortController(),timer=setTimeout(function(){controller.abort();},10000);options.signal=controller.signal;
  if(body!==undefined){options.method='POST';options.headers={'Content-Type':'application/json','X-Screen-Token':token};options.body=JSON.stringify(body);}
  try{var r=await fetch(path,options),d=await r.json();if(!r.ok)throw Error(d.error||'请求失败');return d;}finally{clearTimeout(timer);}
}
function body(extra){return Object.assign({session_id:state&&state.session_id},extra||{});}
function available(){return state&&!uncertain&&!leaving&&!nextIntent&&!stopIntent&&!state.next_requested&&['READY','WRITING'].indexOf(state.phase)>=0&&local.length+(state.strokes||[]).filter(function(s){return ['DONE','FAILED','CANCELLED'].indexOf(s.status)<0;}).length<8;}
function drawStroke(p,color,width){if(!p||!p.length)return;ctx.beginPath();ctx.moveTo(p[0][0]*inkSize,p[0][1]*inkSize);for(var i=1;i<p.length;i++)ctx.lineTo(p[i][0]*inkSize,p[i][1]*inkSize);if(p.length===1)ctx.lineTo(p[0][0]*inkSize+.2*inkScale,p[0][1]*inkSize);ctx.strokeStyle=color;ctx.lineWidth=width*inkScale;ctx.lineCap='round';ctx.lineJoin='round';ctx.stroke();}
function paint(){
 ctx.clearRect(0,0,inkSize,inkSize);(state&&state.strokes||[]).forEach(function(s){drawStroke(s.points,s.status==='CANCELLED'||s.status==='FAILED'?'#b78467':s.status==='WRITING'?'#fff0c9':'#edb763',6);});
 local.forEach(function(s){drawStroke(s.points,s.failed?'#ef7966':'#ffe2a6',5);});drawStroke(points,'#fff1cf',5);
 $('emptyHint').hidden=!!((state&&state.strokes||[]).length||local.length||points.length);$('grid').hidden=!grid;
}
function apply(data){
 if(state&&data.session_id===state.session_id&&data.revision<state.revision)return;
 if(data.unchanged&&state){var sameSpeed=state.speed_pct===data.speed_pct;state=Object.assign({},state,data);if(sameSpeed)return;}else{
  var previous=state;state=data;
  if(previous&&(previous.character!==state.character||previous.session_id!==state.session_id)){local=[];points=[];pointer=null;strokeBounds=null;uncertain=false;nextIntent=false;stopIntent=false;}
  var ids=(state.strokes||[]).map(function(s){return s.id;});local=local.filter(function(s){return ids.indexOf(s.id)<0;});
  // Queue colours may wait until finger-up; never repaint all history during a drag.
  if(pointer===null)paint();
 }
 render();
}
function render(){
 if(!state)return;
 var titles={CLOSED:'尚未进入',PREPARING:'正在准备',READY:'悬停等待',WRITING:'正在跟写',DRAINING:'等待本字写完',HOMING:'正在归位',STOPPING:'正在停止',STOPPED:'已停止',FAULT:'需要处理'};
 $('statusTitle').textContent=titles[state.phase]||state.phase;$('statusSubtitle').textContent=state.message||'';
 $('sessionBadge').textContent=state.simulation?'离线模拟':'手写跟随';
 $('characterCounter').textContent='第 '+String(state.character).padStart(2,'0')+' 字 · '+(state.strokes||[]).length+' 笔';
 $('activeSize').textContent=state.size_mm;$('sizeDimension').textContent='× '+state.size_mm+' mm';
 if(document.activeElement!==$('sizeInput'))$('sizeInput').value=state.pending_size_mm;
 $('sizeNote').textContent=state.pending_size_mm!==state.size_mm?'下个字使用 '+state.pending_size_mm+' mm':'本字使用 '+state.size_mm+' mm';
 $('sizeNote').classList.toggle('pending',state.pending_size_mm!==state.size_mm);
 document.querySelectorAll('[data-size]').forEach(function(b){b.classList.toggle('selected',Number(b.dataset.size)===state.pending_size_mm);});
 if(document.activeElement!==$('speedInput'))$('speedInput').value=state.speed_pct;
 $('speedOutput').textContent=state.speed_pct+'%';
 var done=(state.strokes||[]).filter(function(s){return s.status==='DONE';}).length;
 var waiting=(state.strokes||[]).filter(function(s){return ['DONE','FAILED','CANCELLED'].indexOf(s.status)<0;}).length;
 $('queueSummary').textContent=done+' 笔完成 · '+waiting+' 笔待完成';$('queueChips').textContent='';
 (state.strokes||[]).slice(-6).forEach(function(s){var b=document.createElement('span');b.className='chip '+(s.status==='WRITING'?'writing':s.status==='READY'?'planned':s.status==='FAILED'?'failed':s.status==='CANCELLED'?'cancelled':'');b.textContent=s.number+' '+(s.match?s.match.name:'待识别');$('queueChips').appendChild(b);});
 $('nextBtn').disabled=leaving||nextIntent||['READY','WRITING','STOPPED'].indexOf(state.phase)<0||state.next_requested;
 $('nextBtn').textContent=state.next_requested?'写完后进入下一字':'下一个字';
 $('stopBtn').disabled=state.phase==='CLOSED';$('board').classList.toggle('disabled',!available());
 $('handwritingNav').textContent=state.phase==='CLOSED'?'进入手写':'手写模式';
 var last=(state.strokes||[]).slice(-1)[0];
 $('canvasNote').textContent=available()?(last&&last.match?'第 '+last.number+' 笔 · '+last.match.name+(last.match.ambiguous?' · 已匹配最近笔画':''):'写完一笔，抬手即可跟写'):(state.phase==='FAULT'?'准备未完成，请查看右侧原因':state.message);
 $('emptyHint').querySelector('b').textContent=available()?'请在此落笔':'等待准备完成';
}
async function action(name,extra){var d=await request('/api/handwriting/'+name,body(extra));apply(d);return d;}
function position(e){var r=strokeBounds||canvas.getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))];}
function addPoint(e){var p=position(e),last=points[points.length-1];if(!last||Math.hypot(p[0]-last[0],p[1]-last[1])>.001){points.push(p);return true;}return false;}
function beginStroke(e,id){
 if(pointer!==null)return;
 if(!available()){notify(state?state.message:'正在读取状态');return;}
 pointer=id;strokeBounds=canvas.getBoundingClientRect();points=[];addPoint(e);paint();
}
function moveStroke(e,id){
 if(pointer!==id)return;var last=points[points.length-1];if(!addPoint(e))return;
 if(points.length>2048){cancelStroke();notify('这一笔采样过多，未提交，请重新书写');return;}
 // Local incremental ink does not wait for HTTP, recognition, IK or old strokes.
 drawStroke([last,points[points.length-1]],'#fff1cf',5);
}
function endStroke(e,id){
 if(pointer!==id)return;addPoint(e);pointer=null;strokeBounds=null;
 if(!available()){points=[];paint();notify(state?state.message:'当前不能提交笔画');return;}
 if(points.length>2048){points=[];paint();notify('这一笔过长，未提交');return;}
 var s={id:'stroke_'+Date.now().toString(36)+'_'+Math.random().toString(36).slice(2,9),points:points.slice(),character:state.character,session_id:state.session_id};
 points=[];local.push(s);paint();render();
 // Ordered acknowledgements preserve finger order across HTTP worker threads.
 chain=chain.then(async function(){
  if(uncertain||leaving||stopIntent){s.failed=true;paint();return;}
  try{apply(await request('/api/handwriting/stroke',{session_id:s.session_id,character:s.character,stroke_id:s.id,points:s.points}));}
  catch(error){s.failed=true;uncertain=true;paint();render();notify('提交未确认：'+error.message+'。不会自动重发，请检查队列或停止。');}
 });
}
function cancelStroke(){pointer=null;strokeBounds=null;points=[];paint();}
// The deployed WebKitGTK has no PointerEvent or setPointerCapture. GT911's
// X11 bridge sends mouse events, while other touch browsers send TouchEvents.
if(typeof window.PointerEvent==='function'){
 canvas.addEventListener('pointerdown',function(e){
  if(e.isPrimary===false||e.button>0)return;e.preventDefault();beginStroke(e,e.pointerId);
  if(pointer===e.pointerId&&canvas.setPointerCapture)canvas.setPointerCapture(e.pointerId);
 });
 window.addEventListener('pointermove',function(e){if(pointer===e.pointerId){e.preventDefault();moveStroke(e,e.pointerId);}});
 window.addEventListener('pointerup',function(e){if(pointer===e.pointerId){e.preventDefault();endStroke(e,e.pointerId);}});
 window.addEventListener('pointercancel',function(e){if(pointer===e.pointerId)cancelStroke();});
 canvas.addEventListener('lostpointercapture',function(e){if(pointer===e.pointerId)cancelStroke();});
}else{
 var lastTouch=0;
 canvas.addEventListener('mousedown',function(e){if(e.button!==0||Date.now()-lastTouch<800)return;e.preventDefault();beginStroke(e,'mouse');});
 window.addEventListener('mousemove',function(e){if(pointer==='mouse'){e.preventDefault();moveStroke(e,'mouse');}});
 window.addEventListener('mouseup',function(e){if(e.button===0&&pointer==='mouse'){e.preventDefault();endStroke(e,'mouse');}});
 canvas.addEventListener('touchstart',function(e){
  lastTouch=Date.now();e.preventDefault();
  if(e.touches.length!==1){cancelStroke();return;}
  var t=e.changedTouches[0];beginStroke(t,'touch_'+t.identifier);
 },{passive:false});
 window.addEventListener('touchmove',function(e){
  if(typeof pointer!=='string'||pointer.indexOf('touch_')!==0)return;e.preventDefault();lastTouch=Date.now();
  for(var i=0;i<e.changedTouches.length;i++){var t=e.changedTouches[i];moveStroke(t,'touch_'+t.identifier);}
 },{passive:false});
 window.addEventListener('touchend',function(e){
  lastTouch=Date.now();
  for(var i=0;i<e.changedTouches.length;i++){var t=e.changedTouches[i];if(pointer==='touch_'+t.identifier){e.preventDefault();endStroke(t,pointer);}}
 },{passive:false});
 window.addEventListener('touchcancel',cancelStroke);
}
window.addEventListener('blur',cancelStroke);
window.addEventListener('resize',cancelStroke);
async function setSize(v){v=Math.round(Number(v));if(!Number.isFinite(v)||v<40||v>100){notify('字号范围为 40～100 mm');render();return;}try{await action('size',{size_mm:v});}catch(e){notify(e.message);render();}}
$('sizeInput').onchange=function(){setSize(this.value);};$('sizeMinus').onclick=function(){setSize((state?state.pending_size_mm:60)-1);};$('sizePlus').onclick=function(){setSize((state?state.pending_size_mm:60)+1);};
document.querySelectorAll('[data-size]').forEach(function(b){b.onclick=function(){setSize(b.dataset.size);};});
$('speedInput').oninput=function(){$('speedOutput').textContent=this.value+'%';};
$('speedInput').onchange=async function(){try{var d=await request('/api/tcb/speed',{speed_pct:Number(this.value)});if(state)state.speed_pct=d.speed_pct;render();}catch(e){notify(e.message);render();}};
$('exampleBtn').onclick=function(){grid=!grid;paint();};
$('nextBtn').onclick=async function(){nextIntent=true;render();try{await chain;await action('next',{character:state.character});uncertain=false;}catch(e){notify(e.message);}finally{nextIntent=false;render();}};
$('stopBtn').onclick=function(){stopIntent=true;pointer=null;points=[];action('stop').catch(function(e){notify('停止请求失败：'+e.message);});paint();};
function hideDialog(){$('overlay').hidden=true;}
function dialog(title,text){$('dialogTitle').textContent=title;$('dialogBody').textContent=text;$('dialogActions').textContent='';var b=document.createElement('button');b.className='primary';b.textContent='知道了';b.onclick=hideDialog;$('dialogActions').appendChild(b);$('overlay').hidden=false;b.focus();}
$('queuePanel').onclick=function(){var lines=(state&&state.strokes||[]).map(function(s){var labels={ACCEPTED:'待识别',PLANNING:'规划中',READY:'已规划',WRITING:'正在书写',DONE:'已完成',CANCELLED:'已取消',FAILED:'失败'};return '第 '+s.number+' 笔　'+(s.match?s.match.name:'')+'　'+labels[s.status]+(s.error?'：'+s.error:'');});dialog('笔序队列',lines.join('\n')||'尚未接收到笔画');$('dialogBody').style.whiteSpace='pre-wrap';};
$('queuePanel').onkeydown=function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();this.click();}};
async function leave(destination){
 if(leaving)return;leaving=true;cancelStroke();render();
 try{if(state&&state.phase!=='CLOSED')await action('close');
  // Navigation never releases the robot lock. The owner continues STOP and
  // blocks all other jobs until physical standstill has been confirmed.
  location.href=destination;
 }catch(e){leaving=false;notify(e.message);render();}
}
$('returnBtn').onclick=function(){leave('/');};$('settingsBtn').onclick=function(){leave('/debug');};
document.querySelectorAll('[data-mode]').forEach(function(b){b.onclick=function(){leave(b.dataset.mode==='书法模式'?'/?mode=calligraphy':'/');};});
async function enter(){
 try{apply(await request('/api/handwriting/open',{size_mm:Number($('sizeInput').value)||60}));}
 catch(e){notify(e.message);$('statusTitle').textContent='暂不能准备';$('statusSubtitle').textContent=e.message;}
}
$('handwritingNav').onclick=function(){if(!state||state.phase==='CLOSED')enter();else notify('已在手写模式');};
document.addEventListener('keydown',function(e){if(e.key==='Escape')hideDialog();});
async function tick(){
 if(polling)return;polling=true;
 try{if(state&&state.session_id&&state.phase!=='CLOSED')apply(await request('/api/handwriting/heartbeat',body({revision:state.revision})));else apply(await request('/api/handwriting/status'));}
 catch(e){$('statusTitle').textContent='连接中断';$('statusSubtitle').textContent='等待恢复；旧笔画不会自动重发';uncertain=true;}
 finally{polling=false;setTimeout(tick,500);}
}
(async function(){
 try{var d=await request('/api/state');token=d.control_token||'';apply(await request('/api/handwriting/status'));
  var intended=sessionStorage.getItem('handwriting-enter')==='1';sessionStorage.removeItem('handwriting-enter');
  if(intended&&state.phase==='CLOSED')await enter();
 }catch(e){notify(e.message);$('statusTitle').textContent='连接失败';$('statusSubtitle').textContent=e.message;}
 tick();paint();
})();
})();
