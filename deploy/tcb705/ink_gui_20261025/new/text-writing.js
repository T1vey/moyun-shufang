"use strict";
(function(){
  var el=function(id){return document.getElementById(id);};
  var preview=null,active=null,busy=false,previewPage=0,cap=null,pendingSubmit=null,style='kai';
  var storageKey='tcb.text.'+location.host;
  el('writing-license').href='/api/text/license?'+Q;
  function save(key,value){try{if(value===null)localStorage.removeItem(storageKey+key);else localStorage.setItem(storageKey+key,JSON.stringify(value));}catch(e){}}
  function load(key){try{return JSON.parse(localStorage.getItem(storageKey+key)||'null');}catch(e){return null;}}
  active=load('.job');pendingSubmit=load('.pending');style=load('.style')||'kai';
  function error(message){el('writing-error').hidden=!message;el('writing-error').textContent=message||'';}
  function mode(text){
    document.body.classList.toggle('text-mode',text);el('text-writing').hidden=!text;el('photo-workflow').hidden=text;
    el('choose-text-mode').setAttribute('aria-pressed',String(text));el('choose-photo-mode').setAttribute('aria-pressed',String(!text));
    if(text&&!cap)capabilities();
  }
  el('choose-photo-mode').onclick=function(){mode(false);};
  el('choose-text-mode').onclick=function(){mode(true);};
  function locked(){return !!pendingSubmit||!!active&&(['planning','drawing','stopping','awaiting_paper'].indexOf(active.phase)>=0||active.motion_uncertain);}
  function controls(){
    var lock=locked();el('writing-text').disabled=busy||lock;el('writing-size').disabled=busy||lock;
    Array.prototype.forEach.call(el('writing-styles').children,function(b){b.disabled=busy||lock;b.setAttribute('aria-pressed',String(b.dataset.style===style));});
    el('writing-preview').disabled=busy||lock||!cap;
    el('writing-submit').disabled=busy||(!pendingSubmit&&(!preview||lock));
    el('writing-submit').textContent=pendingSubmit?'恢复刚才的提交（不会重复书写）':cap&&cap.simulation?'提交并模拟书写':'提交并开始书写';
    if(pendingSubmit)el('writing-preview-panel').hidden=false;
    el('writing-job').hidden=!active;
    if(active){
      if(lock&&active.text){el('writing-text').value=active.text;el('writing-size').value=active.font_size_mm;el('writing-size-value').textContent=active.font_size_mm+' mm';
        if(active.style&&active.style!==style){style=active.style;library();}}
      el('writing-job-title').textContent='第 '+((active.page_index||0)+1)+' / '+(active.page_count||1)+' 页';
      el('writing-job-message').textContent=active.message||'';
      el('writing-next').hidden=active.phase!=='awaiting_paper';el('writing-next').disabled=busy;
      el('writing-stop').hidden=!active.can_cancel;el('writing-stop').disabled=busy;
      el('writing-stop').textContent=active.phase==='stopping'?'再次停止归位':active.phase==='awaiting_paper'?'结束本次书写':'停止书写';
      el('writing-new').hidden=lock;el('writing-new').disabled=busy;
    }
  }
  async function api(path,data){
    var ac=new AbortController(),timer=setTimeout(function(){ac.abort();},30000);
    try{
      var res=await fetch(path+(path.indexOf('?')<0?'?':'&')+Q,{method:data?'POST':'GET',cache:'no-store',signal:ac.signal,
        headers:data?{'Content-Type':'application/json'}:{},body:data?JSON.stringify(Object.assign({cid:CID},data)):undefined});
      var value=await res.json();if(!res.ok){var ex=new Error(value.error||value.message||'请求失败');ex.status=res.status;throw ex;}return value;
    }finally{clearTimeout(timer);}
  }
  function current(){var list=cap&&cap.styles||[];for(var i=0;i<list.length;i++)if(list[i].style===style)return list[i];return null;}
  function library(){
    var s=current();if(!cap)return;
    if(!s){style='kai';s=current()||{style:'kai',label:'楷书',count:cap.count,characters:cap.characters,notice:''};}
    el('writing-characters').textContent=s.characters;
    el('writing-library-info').textContent=s.label+' · '+s.count+' 常用字 · '+(s.style==='kai'?'正常笔顺':'按楷书笔顺书写')+' · 从左到右横排';
    el('writing-library-summary').textContent='查看'+s.label+'已收录的 '+s.count+' 个汉字';
    el('writing-style-notice').hidden=s.style==='kai';el('writing-style-notice').textContent=s.style==='kai'?'':s.label+'：'+(s.notice||'');
  }
  function styleButtons(){
    var box=el('writing-styles');box.textContent='';
    (cap.styles&&cap.styles.length?cap.styles:[{style:'kai',label:'楷书'}]).forEach(function(s){
      var b=document.createElement('button');b.type='button';b.className='btn';b.dataset.style=s.style;b.textContent=s.label;
      b.onclick=function(){if(busy||locked()||style===s.style)return;style=s.style;save('.style',style);library();invalidate();};
      box.appendChild(b);
    });
  }
  async function capabilities(){try{
    cap=await api('/api/text/capabilities');styleButtons();library();
    if(cap.simulation)el('text-writing-title').textContent='写一段心意 · 模拟';controls();
  }catch(e){error(e.message);}}
  function invalidate(){preview=null;el('writing-preview-panel').hidden=true;el('writing-size-value').textContent=el('writing-size').value+' mm';error('');controls();}
  el('writing-text').oninput=invalidate;el('writing-size').oninput=invalidate;
  function draw(){
    if(!preview)return;
    var canvas=el('writing-canvas'),ctx=canvas.getContext('2d'),W=preview.width_mm,H=preview.height_mm,scale=600/W;
    canvas.width=600;canvas.height=Math.round(600*H/W);ctx.fillStyle='#fffaf0';ctx.fillRect(0,0,canvas.width,canvas.height);
    ctx.setTransform(scale,0,0,scale,0,0);ctx.strokeStyle='rgba(179,38,30,.22)';ctx.lineWidth=.2;
    preview.pages[previewPage].forEach(function(c){ctx.strokeRect(c.x_mm,c.y_mm,preview.font_size_mm,preview.font_size_mm);});
    ctx.lineCap='round';ctx.lineJoin='round';
    preview.preview_pages[previewPage].forEach(function(stroke){for(var i=1;i<stroke.length;i++){
      var a=stroke[i-1],b=stroke[i],pressure=(a[2]+b[2])/2;ctx.strokeStyle='#1f1a16';ctx.lineWidth=.25+pressure*1.35;
      ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke();
    }});
  }
  el('writing-page').onchange=function(){previewPage=Number(this.value);draw();};
  el('writing-preview').onclick=async function(){
    if(busy||locked())return;busy=true;controls();error('');
    try{
      preview=await api('/api/text/preview',{text:el('writing-text').value,font_size_mm:Number(el('writing-size').value),style:style});
      previewPage=0;el('writing-page').textContent='';
      preview.pages.forEach(function(p,i){var option=document.createElement('option');option.value=i;option.textContent=(i+1)+' / '+preview.page_count;el('writing-page').appendChild(option);});
      el('writing-layout').textContent=(preview.style_label||'楷书')+' · '+preview.font_size_mm+' mm · 每行 '+preview.columns+' 字 · 共 '+preview.page_count+' 页';
      el('writing-preview-panel').hidden=false;draw();
    }catch(e){preview=null;error(e.message);}finally{busy=false;controls();}
  };
  el('writing-submit').onclick=async function(){
    if(busy||(!preview&&!pendingSubmit))return;busy=true;error('');
    if(!pendingSubmit){pendingSubmit={text:preview.text,font_size_mm:preview.font_size_mm,style:preview.style||'kai',preview_id:preview.preview_id,revision:preview.revision,
      request_id:'text_'+Date.now().toString(36)+'_'+Math.random().toString(36).slice(2,12),start_requested:true};save('.pending',pendingSubmit);}
    controls();
    try{active=await api('/api/text/submit',pendingSubmit);save('.job',active);pendingSubmit=null;save('.pending',null);preview=null;el('writing-preview-panel').hidden=true;}
    catch(e){error(e.status?e.message:'连接中断，可恢复刚才的提交；若未送达会继续提交，已接收则不会重复启动。');if(e.status){pendingSubmit=null;save('.pending',null);}}
    finally{busy=false;controls();}
  };
  async function action(path,extra){
    if(busy||!active)return;busy=true;controls();error('');
    try{active=await api(path,Object.assign({job_id:active.job_id},extra||{}));save('.job',active);}
    catch(e){error(e.message);}finally{busy=false;controls();}
  }
  el('writing-stop').onclick=function(){action('/api/text/cancel');};
  el('writing-next').onclick=function(){action('/api/text/next-page',{page_index:active.page_index,paper_ready:true});};
  el('writing-new').onclick=function(){if(locked())return;active=null;save('.job',null);invalidate();controls();};
  var polling=false;
  async function poll(){
    if(!active||polling||busy)return;polling=true;
    try{active=await api('/api/text/status?cid='+encodeURIComponent(CID)+'&job_id='+encodeURIComponent(active.job_id));save('.job',active);controls();}
    catch(e){error(e.message);if(e.status===400||e.status===404){active={job_id:active.job_id,phase:'error',message:'原任务已失效，服务重启不会自动重写。请核对纸面后新建任务。'};save('.job',active);controls();}}
    finally{polling=false;}
  }
  setInterval(poll,2000);controls();if(active||pendingSubmit){mode(true);poll();}
})();
