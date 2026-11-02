"use strict";
// 手机硬笔 (2026-10-29): send text (several lines), size, speed and 横排 / 竖排 to the board. The
// board plans every line once, saves it in the 硬笔作品库 and writes the piece page by page; the
// same piece is written again later straight from its saved commands.
(function(){
  var el=function(id){return document.getElementById(id);};
  var cap=null,preview=null,active=null,busy=false,page=0,pendingSubmit=null,size=10,speed=85,layout='h';
  var storageKey='tcb.hardpen.'+location.host;
  var SIZE_LABEL={10:'1 cm',15:'1.5 cm',20:'2 cm'};
  function save(key,value){try{if(value===null)localStorage.removeItem(storageKey+key);else localStorage.setItem(storageKey+key,JSON.stringify(value));}catch(e){}}
  function load(key){try{return JSON.parse(localStorage.getItem(storageKey+key)||'null');}catch(e){return null;}}
  active=load('.job');pendingSubmit=load('.pending');
  var choice=load('.choice')||{};if(choice.size)size=choice.size;if(choice.speed)speed=choice.speed;if(choice.layout)layout=choice.layout;
  function error(message){el('hp-error').hidden=!message;el('hp-error').textContent=message||'';}
  // Tabs: 照片绘画 and 毛笔写字 keep their own handlers; this one hides both of their sections.
  function show(on){
    el('hardpen-writing').hidden=!on;el('choose-hardpen-mode').setAttribute('aria-pressed',String(on));
    if(on){el('text-writing').hidden=true;el('photo-workflow').hidden=true;document.body.classList.add('text-mode');
      el('choose-text-mode').setAttribute('aria-pressed','false');el('choose-photo-mode').setAttribute('aria-pressed','false');
      if(!cap)capabilities();}
  }
  el('choose-hardpen-mode').onclick=function(){show(true);};
  el('choose-text-mode').addEventListener('click',function(){show(false);});
  el('choose-photo-mode').addEventListener('click',function(){show(false);});
  function locked(){return !!pendingSubmit||!!active&&(['planning','drawing','stopping','awaiting_paper'].indexOf(active.phase)>=0||active.motion_uncertain);}
  function segment(box,values,current,label,pick){
    box.textContent='';
    values.forEach(function(v){var b=document.createElement('button');b.type='button';b.className='btn';b.textContent=label(v);
      b.setAttribute('aria-pressed',String(v===current));b.disabled=busy||locked();
      b.onclick=function(){if(busy||locked()||v===current)return;pick(v);save('.choice',{size:size,speed:speed,layout:layout});invalidate();};
      box.appendChild(b);});
  }
  function controls(){
    var lock=locked();
    el('hp-text').disabled=busy||lock;
    segment(el('hp-sizes'),cap?cap.sizes:[10,15,20],size,function(v){return SIZE_LABEL[v]||v+' mm';},function(v){size=v;});
    segment(el('hp-layouts'),(cap?cap.layouts:[{id:'h',label:'横排'},{id:'v',label:'竖排'}]).map(function(l){return l.id;}),layout,
      function(v){return v==='h'?'横排':'竖排';},function(v){layout=v;});
    // Speed is not part of the plan: changing it keeps the preview.
    var sp=el('hp-speeds');sp.textContent='';
    (cap?cap.speeds:[70,85,100]).forEach(function(v){var b=document.createElement('button');b.type='button';b.className='btn';b.textContent=v+'%';
      b.setAttribute('aria-pressed',String(v===speed));b.disabled=busy||lock;
      b.onclick=function(){if(busy||locked())return;speed=v;save('.choice',{size:size,speed:speed,layout:layout});controls();};sp.appendChild(b);});
    var n=el('hp-text').value.replace(/[\s，。、；：？！“”‘’「」『』（）《》〈〉【】…—～·,.;:?!()\[\]<>"'`\-_~\/\\|]/g,'').length;
    el('hp-count').textContent=n+' / '+(cap?cap.max_characters:300)+' 字';
    el('hp-preview-btn').disabled=busy||lock||!cap;
    el('hp-submit').disabled=busy||(!pendingSubmit&&(!preview||lock));
    el('hp-submit').textContent=pendingSubmit?'恢复刚才的提交（不会重复书写）':cap&&cap.simulation?'提交并模拟书写':'提交，速度 '+speed+'%，开始书写';
    if(pendingSubmit)el('hp-preview-panel').hidden=false;
    el('hp-job').hidden=!active;
    if(active){
      if(lock&&active.text)el('hp-text').value=active.text;
      el('hp-job-title').textContent='硬笔 · 第 '+((active.page_index||0)+1)+' / '+(active.page_count||1)+' 页';
      el('hp-job-message').textContent=active.message||'';
      el('hp-next').hidden=active.phase!=='awaiting_paper';el('hp-next').disabled=busy;
      el('hp-stop').hidden=!active.can_cancel;el('hp-stop').disabled=busy;
      el('hp-stop').textContent=active.phase==='stopping'?'再次停止归位':active.phase==='awaiting_paper'?'结束本次书写':'停止书写';
      el('hp-new').hidden=lock;el('hp-new').disabled=busy;
    }
  }
  async function api(path,data){
    var ac=new AbortController(),timer=setTimeout(function(){ac.abort();},60000);
    try{
      var res=await fetch(path+(path.indexOf('?')<0?'?':'&')+Q,{method:data?'POST':'GET',cache:'no-store',signal:ac.signal,
        headers:data?{'Content-Type':'application/json'}:{},body:data?JSON.stringify(Object.assign({cid:CID},data)):undefined});
      var value=await res.json();if(!res.ok){var ex=new Error(value.error||value.message||'请求失败');ex.status=res.status;throw ex;}return value;
    }finally{clearTimeout(timer);}
  }
  async function capabilities(){try{
    cap=await api('/api/text/hardpen-capabilities');
    if(cap.sizes.indexOf(size)<0)size=cap.sizes[0];if(cap.speeds.indexOf(speed)<0)speed=cap.speeds[0];
    el('hp-library-info').textContent='硬笔正楷 · '+cap.count+' 常用字 · 标准笔顺'+(cap.simulation?' · 模拟':'');
    el('hp-library-summary').textContent='查看已收录的 '+cap.count+' 个汉字';el('hp-characters').textContent=cap.characters;
    controls();
  }catch(e){error(e.message);}}
  function invalidate(){preview=null;el('hp-preview-panel').hidden=true;error('');controls();}
  el('hp-text').oninput=invalidate;
  function draw(){
    if(!preview)return;
    var canvas=el('hp-canvas'),ctx=canvas.getContext('2d'),W=preview.width_mm,H=preview.height_mm,scale=600/W;
    canvas.width=600;canvas.height=Math.round(600*H/W);ctx.setTransform(1,0,0,1,0,0);ctx.fillStyle='#fffaf0';ctx.fillRect(0,0,canvas.width,canvas.height);
    ctx.setTransform(scale,0,0,scale,0,0);ctx.lineCap='round';ctx.lineJoin='round';ctx.strokeStyle='#1f1a16';ctx.lineWidth=Math.max(.5,1.4/scale);
    (preview.preview_pages[page]||[]).forEach(function(s){ctx.beginPath();ctx.moveTo(s[0][0],s[0][1]);for(var i=1;i<s.length;i++)ctx.lineTo(s[i][0],s[i][1]);ctx.stroke();});
  }
  el('hp-page').onchange=function(){page=Number(this.value);draw();};
  el('hp-preview-btn').onclick=async function(){
    if(busy||locked())return;busy=true;controls();error('');el('hp-preview-btn').textContent='正在排版…';
    try{
      preview=await api('/api/text/hardpen-preview',{text:el('hp-text').value,font_size_mm:size,layout:layout});
      page=0;el('hp-page').textContent='';
      for(var i=0;i<preview.page_count;i++){var o=document.createElement('option');o.value=i;o.textContent=(i+1)+' / '+preview.page_count;el('hp-page').appendChild(o);}
      el('hp-layout-text').textContent=SIZE_LABEL[preview.font_size_mm]+' · '+preview.layout_label+' · 每行 '+preview.per_line+' 字 · '+preview.characters+' 字 · 共 '+preview.page_count+' 页'+
        (preview.saved?' · 已保存，直接写':'');
      el('hp-preview-panel').hidden=false;draw();
    }catch(e){preview=null;error(e.message);}finally{busy=false;el('hp-preview-btn').textContent='预览排版';controls();}
  };
  el('hp-submit').onclick=async function(){
    if(busy||(!preview&&!pendingSubmit))return;busy=true;error('');
    if(!pendingSubmit){pendingSubmit={text:preview.text,font_size_mm:preview.font_size_mm,layout:preview.layout,speed_pct:speed,preview_id:preview.preview_id,
      revision:preview.revision,request_id:'hp_'+Date.now().toString(36)+'_'+Math.random().toString(36).slice(2,12),start_requested:true};save('.pending',pendingSubmit);}
    controls();
    try{active=await api('/api/text/hardpen-submit',pendingSubmit);save('.job',active);pendingSubmit=null;save('.pending',null);preview=null;el('hp-preview-panel').hidden=true;}
    catch(e){error(e.status?e.message:'连接中断，可恢复刚才的提交；若未送达会继续提交，已接收则不会重复启动。');if(e.status){pendingSubmit=null;save('.pending',null);}}
    finally{busy=false;controls();}
  };
  async function action(path,extra){
    if(busy||!active)return;busy=true;controls();error('');
    try{active=await api(path,Object.assign({job_id:active.job_id},extra||{}));save('.job',active);}
    catch(e){error(e.message);}finally{busy=false;controls();}
  }
  el('hp-stop').onclick=function(){action('/api/text/cancel');};
  el('hp-next').onclick=function(){action('/api/text/next-page',{page_index:active.page_index,paper_ready:true});};
  el('hp-new').onclick=function(){if(locked())return;active=null;save('.job',null);invalidate();};
  var polling=false;
  async function poll(){
    if(!active||polling||busy||el('hardpen-writing').hidden)return;polling=true;
    try{active=await api('/api/text/status?cid='+encodeURIComponent(CID)+'&job_id='+encodeURIComponent(active.job_id));save('.job',active);controls();}
    catch(e){error(e.message);if(e.status===400||e.status===404){active={job_id:active.job_id,phase:'error',message:'原任务已失效，服务重启不会自动重写。请核对纸面后新建任务。'};save('.job',active);controls();}}
    finally{polling=false;}
  }
  setInterval(poll,2000);controls();
  if(active||pendingSubmit){show(true);poll();}
})();
