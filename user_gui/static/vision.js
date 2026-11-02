/* Handwriting recognition page: USB camera preview, paper calibration, PL recognition and scoring. */
(function(){
'use strict';
var $=function(id){return document.getElementById(id);},token='',live=true,calPoints=null,showBinary=false,last=null,selected=0,status=null,busy=false,toastTimer;
var SUBS=[['shape','字形相似'],['stroke','笔画吻合'],['structure','结构布局'],['ink','笔墨均匀']];
var ctx=$('overlay').getContext('2d');

function fit(){var s=Math.min(window.innerWidth/1024,window.innerHeight/600);$('app').style.transform='scale('+s+')';}
window.addEventListener('resize',fit);fit();
function notify(m){$('toast').textContent=m;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(function(){$('toast').hidden=true;},6000);}
async function request(path,body,timeout){
  var o={cache:'no-store'},c=new AbortController(),t=setTimeout(function(){c.abort();},timeout||15000);o.signal=c.signal;
  if(body!==undefined){o.method='POST';o.headers={'Content-Type':'application/json','X-Screen-Token':token};o.body=JSON.stringify(body);}
  try{var r=await fetch(path,o),d=await r.json();if(!r.ok)throw Error(d.error||'请求失败');return d;}finally{clearTimeout(t);}
}

function drawOverlay(){
  ctx.clearRect(0,0,480,360);var k=480/640,pts=calPoints||(status&&status.corners)||[];
  if(pts.length){ctx.strokeStyle='#f3ad45';ctx.lineWidth=2;ctx.beginPath();
    pts.forEach(function(p,i){var x=p[0]*k,y=p[1]*k;if(i)ctx.lineTo(x,y);else ctx.moveTo(x,y);});
    if(pts.length===4)ctx.closePath();ctx.stroke();
    pts.forEach(function(p,i){ctx.fillStyle='#ffe2a6';ctx.beginPath();ctx.arc(p[0]*k,p[1]*k,5,0,6.3);ctx.fill();ctx.fillStyle='#120c08';ctx.font='11px sans-serif';ctx.fillText(String(i+1),p[0]*k-3,p[1]*k+4);});}
}
function applyStatus(s){
  status=s;var b=$('hwBadge');b.textContent=s.backend==='PL'?'FPGA 识别核':(s.backend==='CPU'?'CPU 后备（无识别核）':'未初始化');b.className='hw'+(s.backend==='PL'?' pl':'');
  var st=s.settings||{};$('otsuBtn').className='toggle'+(st.otsu?' on':'');$('otsuBtn').textContent=st.otsu?'自动':'手动';
  $('biasValue').textContent=st.otsu?String(st.bias):String(st.manual);$('morphBtn').className='toggle'+(st.morph?' on':'');$('morphBtn').textContent=st.morph?'去噪 开':'去噪 关';
  $('flatBtn').className='toggle'+(st.flatten?' on':'');
  document.querySelectorAll('[data-mode]').forEach(function(x){x.className='choice'+(x.dataset.mode===st.mode?' on':'');});
  document.querySelectorAll('[data-cand]').forEach(function(x){x.className='choice'+(x.dataset.cand===st.candidates?' on':'');});
  document.querySelectorAll('[data-engine]').forEach(function(x){x.className='choice'+(x.dataset.engine===(st.engine||'template')?' on':'');});
  var cats=st.categories||[];document.querySelectorAll('[data-cat]').forEach(function(x){x.className='choice'+(cats.indexOf(x.dataset.cat)>=0?' on':'');});
  drawOverlay();
}
async function configure(body){try{applyStatus(await request('/api/vision/configure',body));}catch(e){notify(e.message);}}

async function poll(){
  if(live&&!showBinary){
    try{var d=await request('/api/vision/preview',undefined,8000);$('preview').src=d.image;var c=d.camera||{};
      $('camInfo').textContent=(c.format||'')+' · '+(c.frames||0)+' 帧';}
    catch(e){$('camInfo').textContent=e.message;}
  }
  setTimeout(poll,live?700:1500);
}
$('liveBtn').onclick=function(){live=!live;this.textContent=live?'暂停画面':'恢复画面';};
$('viewBtn').onclick=function(){
  if(!last){notify('先拍照识别一次');return;}
  showBinary=!showBinary;this.textContent=showBinary?'看实时画面':'看二值图';
  if(showBinary)$('preview').src=last.binary;
};
$('calBtn').onclick=function(){
  if(calPoints){calPoints=null;$('calHint').hidden=true;this.textContent='标定纸面';drawOverlay();return;}
  calPoints=[];this.textContent='取消标定';$('calHint').hidden=false;$('calHint').textContent='依次点纸面四角：左上 → 右上 → 右下 → 左下';drawOverlay();
};
$('view').onclick=function(e){
  if(!calPoints)return;var r=$('view').getBoundingClientRect(),s=r.width/480;
  var x=(e.clientX-r.left)/s*640/480,y=(e.clientY-r.top)/s*640/480;calPoints.push([Math.round(x),Math.round(y)]);drawOverlay();
  if(calPoints.length===4){var pts=calPoints;calPoints=null;$('calHint').hidden=true;$('calBtn').textContent='标定纸面';configure({corners:pts});}
};
$('otsuBtn').onclick=function(){configure({otsu:!(status&&status.settings.otsu)});};
function step(d){var st=status&&status.settings;if(!st)return;if(st.otsu)configure({bias:Math.max(-60,Math.min(60,st.bias+d))});else configure({manual:Math.max(0,Math.min(255,st.manual+d*2))});}
$('biasMinus').onclick=function(){step(-4);};$('biasPlus').onclick=function(){step(4);};
$('morphBtn').onclick=function(){configure({morph:!(status&&status.settings.morph)});};
$('flatBtn').onclick=function(){configure({flatten:!(status&&status.settings.flatten)});};
document.querySelectorAll('[data-mode]').forEach(function(x){x.onclick=function(){configure({mode:x.dataset.mode});};});
document.querySelectorAll('[data-cand]').forEach(function(x){x.onclick=function(){configure({candidates:x.dataset.cand});};});
// 识别 (2026-10-28): FPGA 模板匹配, or the 手写识字 model on the ARM CPU (style and score still from the templates).
document.querySelectorAll('[data-engine]').forEach(function(x){x.onclick=function(){configure({engine:x.dataset.engine});};});
document.querySelectorAll('[data-cat]').forEach(function(x){x.onclick=function(){var cats=((status&&status.settings.categories)||[]).slice(),k=cats.indexOf(x.dataset.cat);if(k>=0)cats.splice(k,1);else cats.push(x.dataset.cat);if(!cats.length){notify('至少保留一种书体');return;}configure({categories:cats});};});

function showChar(i){
  selected=i;var c=last.chars[i];
  document.querySelectorAll('#chips button').forEach(function(b,j){b.className=j===i?'on':'';});
  if(!c||c.empty){$('card').hidden=true;$('emptyState').hidden=false;$('emptyState').innerHTML='框内没有找到墨迹。<br>检查标定框和阈值。';return;}
  $('emptyState').hidden=true;$('card').hidden=false;$('char').textContent=c.char;
  $('styleName').textContent=c.category?(c.category+' · '+c.style):'';
  $('top5').textContent=(c.engine==='model'?'本地模型候选 ':'候选 ')+c.top5.map(function(t){return t.char+'('+(t.p!=null?Math.round(t.p*100)+'%':t.style)+')';}).join('  ');
  $('total').textContent=c.total;$('grade').textContent=c.grade;
  $('bars').innerHTML=SUBS.map(function(s){var v=c.subs[s[0]];return '<div class="bar"><span>'+s[1]+'</span><i><b style="width:'+v+'%"></b></i><em>'+v+'</em></div>';}).join('');
  $('normImg').src=c.image;$('tplImg').src=c.template;$('comments').textContent=c.comments.join('；');
}
function showResult(d){
  last=d;var chips=$('chips');
  if(d.chars.length>1){chips.hidden=false;chips.innerHTML=d.chars.map(function(c,i){return '<button data-i="'+i+'">'+(c.empty?'空':c.char)+'</button>';}).join('');
    chips.querySelectorAll('button').forEach(function(b){b.onclick=function(){showChar(+b.dataset.i);};});}
  else chips.hidden=true;
  showChar(0);var t=d.timing_ms;
  $('timing').textContent=(d.backend==='PL'?'FPGA':'CPU')+' 处理 '+t.pl_total+' ms（预处理 '+t.preprocess+' · 校正 '+t.rectify+' · 识别 '+t.recognise+'）· ARM 校正 '+t.arm+' ms'+(d.engine==='model'&&t.model!=null?'· 本地模型 '+t.model+' ms':'')+'· 阈值 '+d.threshold+' · 总计 '+t.total+' ms'+(d.average!=null&&d.chars.length>1?' · 平均分 '+d.average:'');
  if(showBinary)$('preview').src=d.binary;
}
$('shotBtn').onclick=async function(){
  if(busy)return;busy=true;this.disabled=true;this.textContent='识别中…';
  try{showResult(await request('/api/vision/recognise',{},30000));applyStatus(await request('/api/vision/status'));}
  catch(e){notify(e.message);}
  finally{busy=false;this.disabled=false;this.textContent='拍照识别';}
};
$('returnBtn').onclick=function(){location.href='/';};

async function enter(){
  try{var d=await request('/api/state');token=d.control_token||'';}catch(e){notify('读取屏幕状态失败：'+e.message);}
  try{applyStatus(await request('/api/vision/status'));var r=await request('/api/vision/result');if(r&&r.chars)showResult(r);}catch(e){notify(e.message);}
  poll();
}
enter();
})();
