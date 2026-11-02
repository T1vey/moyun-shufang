"use strict";
(function(){
  var $=function(id){return document.getElementById(id);};
  var current=null, token="", connected=false, pending=false, previewLoaded=false, previewUrl="", pairUrl="", simulation=null, realReady=false;
  var localFile=null, localPreviewUrl="", localQueued=false, motionIntent=null, autoDrawJob=null;
  var localCid="desktop_"+Math.random().toString(36).slice(2,12);
  // 主页（六个模式）覆盖在工作区之上；有任务进行时自动回到工作区。
  var atHome=true;
  function setHome(on){if(atHome===on)return;atHome=on;var root=document.documentElement;if(root&&root.classList)root.classList.toggle("home-on",on);}
  var labels={idle:["等待上传","候"],cloud:["正在生成线稿","云"],extracting:["正在整理线条","稿"],planning:["正在准备绘画","绘"],ready:["准备完毕，可以开始工作","成"],drawing:["正在绘制这一幅","绘"],stopping:["正在停止并归位","归"],completed:["这一幅，完成了","成"],cancelled:["任务已取消","止"],error:["暂时未能完成","示"]};
  function textIfChanged(element,text){if(element.textContent!==text)element.textContent=text;}
  function network(ok){connected=ok;var cls="led "+(ok?"ok":"err");if($("connection-led").className!==cls)$("connection-led").className=cls;textIfChanged($("connection-text"),simulation===true?(ok?"离线模拟 · 不驱动机械臂":"正在重新连接"):(ok?"已连接":"正在重新连接"));render();}
  var renderedKey="";
  function render(){
    // Repeated identical polling replies must not repaint the software-rendered
    // ARM32 screen, especially behind the brush picker.
    var key=JSON.stringify([current,connected,pending,previewLoaded,simulation,realReady,
      localQueued,localPreviewUrl,!!localFile,!!token,atHome]);
    if(key===renderedKey)return;
    renderedKey=key;
    var w=current||{phase:"idle",message:"选择本地线条图，或手机扫码上传照片。"}, phase=w.phase||"idle", label=labels[phase]||labels.idle;
    $("workflow-title").textContent=label[0];$("phase-seal").textContent=label[1];
    if(simulation===true){
      $("connection-text").textContent=connected?"离线模拟 · 不驱动机械臂":"正在重新连接";
      if(phase==="ready")$("workflow-title").textContent="预览已准备好，可以模拟运行";
      if(phase==="drawing")$("workflow-title").textContent="正在验证轨迹";
      if(phase==="completed")$("workflow-title").textContent="模拟验证完成";
    }
    var timing=w.timing||{}, times=[];
    [["cloud_s","云端"],["extraction_s","提线"],["planning_s","规划"]].forEach(function(pair){if(typeof timing[pair[0]]==="number")times.push(pair[1]+" "+timing[pair[0]].toFixed(1)+"秒");});
    $("workflow-message").textContent=(phase==="idle"&&!w.job_id?"选择本地线条图，或手机扫码上传照片。":w.message||"")+(times.length?" · "+times.join(" / "):"");
    var busy=["cloud","extracting","planning","drawing","stopping"].indexOf(phase)>=0;
    var ready=phase==="ready";
    $("workflow-progress").hidden=!busy||phase==="drawing"||phase==="stopping";
    var progress=Math.max(0,Math.min(100,Number(w.progress)||0));$("progress-fill").style.width=progress+"%";$("workflow-progress").setAttribute("aria-valuenow",String(progress));
    $("cancel-job").hidden=!(w.can_cancel||phase==="stopping");$("cancel-job").disabled=pending||!connected;
    $("cancel-job").textContent=phase==="stopping"?"再次停止":(phase==="drawing"||w.motion_uncertain)?"停止绘画":ready?"更换图片":"取消处理";
    $("reset-job").hidden=["completed","cancelled","error"].indexOf(phase)<0;$("reset-job").disabled=pending||!connected;
    $("reset-job").textContent=phase==="error"?"重新选择图片":"制作下一幅";
    $("open-settings").disabled=pending||busy||!connected;
    var inputBlocked=pending||busy||ready||phase==="awaiting_paper"||!!w.motion_uncertain||!connected||!token;
    $("choose-lineart").disabled=inputBlocked;
    $("prepare-lineart").disabled=inputBlocked||!localFile;
    $("open-calligraphy").disabled=inputBlocked;$("open-handwriting").disabled=inputBlocked;$("open-masterpiece").disabled=inputBlocked;
    $("mode-masterpiece").disabled=inputBlocked;$("mode-brush").disabled=inputBlocked;$("mode-hand").disabled=inputBlocked;$("mode-couplet").disabled=inputBlocked;$("mode-poem").disabled=inputBlocked;$("mode-hardpen").disabled=inputBlocked;
    // 强制复位 (2026-10-29): only a running or stopping motion, or a lost link, disables it.
    $("arm-home").disabled=pending||!connected||!token||phase==="drawing"||phase==="stopping";
    var engaged=busy||ready||phase==="awaiting_paper"||!!w.motion_uncertain;
    if(engaged&&atHome){setHome(false);renderedKey="";}
    $("go-home").hidden=atHome;$("go-home").disabled=engaged||pending;
    var url=localQueued?"":w.preview_url||"";
    if(url!==previewUrl){previewUrl=url;previewLoaded=false;$("prediction-error").hidden=true;if(url){$("prediction").src=url;}else{$("prediction").removeAttribute("src");}}
    $("start-drawing").hidden=!ready;$("start-drawing").disabled=!connected||pending||!w.can_start||!previewLoaded;
    $("start-drawing").textContent=simulation===true?"确认并模拟运行":"确认并开始绘制";
    if(simulation!==true&&!realReady){$("start-drawing").disabled=true;$("start-drawing").textContent="请先完成机械臂配置";}
    var original=localQueued?localPreviewUrl:(w.input_mode==="lineart"?(w.source_url||localPreviewUrl):"");
    $("lineart-original").hidden=!!url||!original;
    if(original&&$("lineart-original").getAttribute("src")!==original)$("lineart-original").src=original;
    $("prediction").hidden=!url;$("empty-preview").hidden=!!url||!!original;$("preview-label").hidden=!url&&!original;
    var sourcePreview=w.preview_kind==="cloud_image"||w.preview_kind==="source_image";
    $("preview-label").textContent=url?(w.preview_kind==="cloud_image"?"云端线稿":sourcePreview?"线稿原图":"预设笔画预览"):"本地线稿原图";
    $("prediction").classList.toggle("lineart-original",sourcePreview);
    $("prediction").alt=sourcePreview?"待绘制的线稿图片":"预设书法笔画预览";
    $("preview-heading").textContent=url?"这一幅，等你确认":original?"线稿已选好，先生成预览":busy?"正在准备这幅画":"选择一张心仪的图";
    if(original&&busy)$("preview-heading").textContent="正在准备这张线稿";
    if(phase==="drawing")$("preview-heading").textContent=simulation===true?"正在模拟验证这幅轨迹":"这一幅，正在绘制";
    if(phase==="completed")$("preview-heading").textContent=simulation===true?"这幅轨迹，模拟验证已完成":"这一幅，已经完成";
    $("empty-title").textContent=busy?"好画，值得稍候":"拍一张 · 画一幅";
    $("empty-message").textContent=busy?"准备好后会在这里显示线稿":"选择本地线条图，或扫码上传照片";
    if(w.input_mode==="calligraphy"){
      var homing=phase==="drawing"&&["HOME","RETURN_HOME","HOME_AFTER_STOP"].indexOf(w.motion_stage)>=0;
      $("preview-heading").textContent=phase==="stopping"?"笔画工坊 · 停止归位":homing?"笔画工坊 · 正在归位":phase==="drawing"?"笔画工坊 · 正在书写":phase==="completed"?"本次书写已完成":"笔画工坊 · 预设轨迹";
      if(phase==="stopping")$("workflow-title").textContent="停止书写，正在归位";
      else if(homing)$("workflow-title").textContent=w.motion_stage==="HOME"?"开始书写前归位":"书写结束，正在归位";
      $("cancel-job").textContent=phase==="stopping"?"再次停止":(phase==="drawing"||w.motion_uncertain)?"停止书写":ready?"取消本次书写":"取消规划";
      $("reset-job").textContent="选择下一个模块";
    }
    $("text-next-page").hidden=!w.text_mode||phase!=="awaiting_paper";
    $("text-next-page").disabled=pending||!connected;
    if(w.text_mode){
      $("preview-heading").textContent="汉字书写 · 第 "+((w.page_index||0)+1)+" / "+w.page_count+" 页";
      $("preview-label").textContent="本页轨迹预测图";
      $("reset-job").textContent="完成本次书写";
      if(phase==="awaiting_paper"){$("workflow-title").textContent="本页完成，请换纸";$("cancel-job").textContent="结束本次书写";}
    }
    if(w.module==="home"){
      $("preview-heading").textContent="机械臂复位";$("reset-job").textContent="完成";
      $("workflow-title").textContent=phase==="drawing"?"正在复位":phase==="completed"?"复位完成":phase==="stopping"?"正在停止":$("workflow-title").textContent;
      $("cancel-job").textContent="停止复位";
    }
    if(w.module==="poem"){
      $("preview-heading").textContent="诗词 · "+(w.poem_title||"")+" · 第 "+((w.page_index||0)+1)+" / "+(w.page_count||1)+" 张";
      $("preview-label").textContent="纸面排版预览";$("reset-job").textContent="写下一首";
      $("text-next-page").textContent="已换好纸，继续";
      if(phase==="awaiting_paper")$("workflow-title").textContent="这张写好了，请换纸";
      if(phase==="completed")$("workflow-title").textContent="这首诗写完了";
    }
    if(w.module==="hardpen"&&w.text_mode){
      $("preview-heading").textContent="硬笔 · 第 "+((w.page_index||0)+1)+" / "+(w.page_count||1)+" 页";
      $("preview-label").textContent="纸面排版预览";$("reset-job").textContent="完成本次书写";
      $("text-next-page").textContent="已换好纸，继续";
      if(phase==="awaiting_paper")$("workflow-title").textContent="这页写好了，请换纸";
      if(phase==="completed")$("workflow-title").textContent="硬笔作品写完了";
    }
    if(w.module==="couplet"){
      $("preview-heading").textContent="春联 · 第 "+((w.page_index||0)+1)+" / "+(w.page_count||1)+" 张";
      $("preview-label").textContent="纸面排版预览";$("reset-job").textContent="完成本副春联";
      $("text-next-page").textContent="已换好纸，继续";
      if(phase==="awaiting_paper"){$("workflow-title").textContent="这张写好了，请换纸";}
      if(phase==="completed")$("workflow-title").textContent="春联写完了";
    }
  }
  function workflow(w){if(!w)return;current=w;render();autoDraw();}
  // "一键画画" (2026-10-18): planning done -> start drawing at once, no confirmation tap.
  function autoDraw(){
    if(!autoDrawJob||!current||current.job_id!==autoDrawJob)return;
    if(["error","cancelled","completed","idle"].indexOf(current.phase)>=0){autoDrawJob=null;return;}
    if(current.phase!=="ready"||!current.can_start||pending||(!realReady&&simulation!==true))return;
    autoDrawJob=null;action('/api/workflow/start',{job_id:current.job_id,revision:current.revision,confirmed:true});
  }
  function pairing(pair){
    if(!pair)return;var interfaces=pair.interfaces||[], chosen=null;
    for(var i=0;i<interfaces.length;i++){if(/wlan|wifi|wi-fi|wireless/i.test(interfaces[i].adapter||"")){chosen=interfaces[i];break;}}
    chosen=chosen||interfaces[0];var url=pair.public_url|| (chosen?"http://"+chosen.ip+":"+pair.port+"/upload":"");
    if(url&&pair.token)url+=(url.indexOf("?")<0?"?":"&")+"t="+encodeURIComponent(pair.token);
    if(url===pairUrl)return;pairUrl=url;
    if(url){try{$("qr").innerHTML=$("home-qr").innerHTML=QR.svg(url);$("pair-url").textContent=url.replace(/\?.*/,"");}catch(e){$("qr").textContent=$("home-qr").textContent="二维码生成失败";}}
    else{$("qr").textContent=$("home-qr").textContent="等待 Wi-Fi 连接";$("pair-url").textContent="请在设置中连接 ESP8200";}
  }
  function phones(rows){var n=(rows||[]).filter(function(c){return c.online&&!/^desktop_/.test(c.id||"");}).length,cls="led "+(n?"ok":"");
    ["phone-status","home-phones"].forEach(function(id){var box=$(id);if(!box.children||box.children.length<2)return;if(box.children[0].className!==cls)box.children[0].className=cls;textIfChanged(box.children[1],n?(id==="home-phones"?n+" 台手机已连接":"手机已连接，可以上传"):"等待手机连接");});}
  var syncing=false,openBrushOnLoad=new URLSearchParams(location.search).get('mode')==='calligraphy';
  async function sync(){
    if(syncing)return;
    syncing=true;
    try{var d=await window.PanelRequest.json('/api/state',{cache:'no-store'},8000);token=d.control_token||"";pairing(d.pair);phones(d.clients);if(d.workflow)workflow(d.workflow);network(true);if(openBrushOnLoad&&!$("open-calligraphy").disabled){openBrushOnLoad=false;$("open-calligraphy").click();}}
    catch(e){network(false);}
    finally{syncing=false;}
  }
  async function action(path,body){
    if(pending)return;pending=true;$("action-error").hidden=true;render();
    try{var d=await window.PanelRequest.json(path,{method:'POST',headers:{'Content-Type':'application/json','X-Screen-Token':token},body:JSON.stringify(body||{})});if(d.phase)workflow(d);if(path==='/api/settings/open'){location.href='/debug';}}
    catch(e){$("action-error").textContent=e.message||"连接中断，请确认屏幕状态后重试";$("action-error").hidden=false;}
    finally{pending=false;await sync();render();}
  }
  function showError(message){$("action-error").textContent=message;$("action-error").hidden=false;}
  function clearLocal(){localFile=null;localQueued=false;localPreviewUrl="";$("lineart-name").textContent="未选择文件";}
  $("choose-lineart").onclick=function(){
    window.LineartGallery.open({token:function(){return token;},select:function(item){
      var phase=current&&current.phase;
      if(pending||["cloud","extracting","planning","ready","drawing","stopping"].indexOf(phase)>=0||(current&&current.motion_uncertain)){showError("当前任务尚未结束，请先处理当前任务。");return;}
      clearLocal();$("action-error").hidden=true;localFile=item;localPreviewUrl=item.url;localQueued=true;
      $("lineart-name").textContent=item.name;$("lineart-name").title=item.filename;render();
    }});
  };
  $("prepare-lineart").onclick=async function(){
    if(pending||!connected||!localFile)return;
    pending=true;$("action-error").hidden=true;render();
    var rid="lineart_"+Date.now().toString(36)+Math.random().toString(36).slice(2,8);
    try{
      var r=await fetch('/api/lineart-library/prepare',{method:'POST',headers:{'Content-Type':'application/json','X-Screen-Token':token},body:JSON.stringify({id:localFile.id,cid:localCid,rid:rid})});
      var d=await r.json();if(!r.ok)throw Error(d.error||"线稿上传未完成");
      localQueued=false;autoDrawJob=d.job_id||(d.workflow&&d.workflow.job_id)||null;if(d.workflow)workflow(d.workflow);
    }catch(e){showError(e.message||"上传中断，请查看任务状态后再试");}
    finally{pending=false;await sync();render();autoDraw();}
  };
  $("prediction").onload=function(){previewLoaded=!!previewUrl;render();if(previewLoaded&&current&&token)fetch('/api/workflow/preview-shown',{method:'POST',headers:{'Content-Type':'application/json','X-Screen-Token':token},body:JSON.stringify({job_id:current.job_id})}).catch(function(){});};
  $("prediction").onerror=function(){previewLoaded=false;$("prediction-error").hidden=false;render();};
  $("start-drawing").onclick=function(){
    if(!current||!previewLoaded||(!realReady&&simulation!==true))return;
    // "确认并开始绘制" is the confirmation itself (2026-10-18): start right away, no second safety dialog.
    action('/api/workflow/start',{job_id:current.job_id,revision:current.revision,confirmed:true});
  };
  $("motion-safe").onchange=function(){$("motion-confirm").disabled=!this.checked;};
  $("motion-cancel").onclick=function(){motionIntent=null;$("motion-modal").hidden=true;$("start-drawing").focus();};
  $("motion-confirm").onclick=function(){if(!$("motion-safe").checked||!current||current.phase!=="ready"||!previewLoaded||!realReady||!motionIntent)return;if(motionIntent.job_id!==current.job_id||motionIntent.revision!==current.revision){$("motion-modal").hidden=true;motionIntent=null;showError("任务已更新，请重新核对预测图并确认。");return;}$("motion-modal").hidden=true;var intent=motionIntent;motionIntent=null;action('/api/workflow/start',{job_id:intent.job_id,revision:intent.revision,confirmed:true});};
  $("cancel-job").onclick=function(){if(current)action('/api/workflow/cancel',{job_id:current.job_id});};
  $("text-next-page").onclick=function(){if(current)action('/api/workflow/text-next-page',{job_id:current.job_id,page_index:current.page_index,paper_ready:true});};
  $("reset-job").onclick=function(){clearLocal();setHome(true);if(current)action('/api/workflow/reset',{job_id:current.job_id});};
  $("go-home").onclick=function(){setHome(true);render();};
  $("mode-text").onclick=$("mode-photo").onclick=function(){setHome(false);render();};
  $("mode-masterpiece").onclick=function(){$("open-masterpiece").onclick();};
  // 复位 (2026-10-26): back to the calibrated home pose at the GUI speed, after an on-screen confirmation.
  $("arm-home").onclick=function(){$("home-confirm").disabled=false;$("home-modal").hidden=false;};
  $("home-cancel").onclick=function(){$("home-modal").hidden=true;};
  $("home-confirm").onclick=function(){$("home-modal").hidden=true;
    action('/api/workflow/home',{request_id:"home_"+Date.now().toString(36),confirmed:true});};
  $("mode-poem").onclick=function(){
    window.Poems.open({submit:async function(id,readAlong){
      if(pending||!connected)throw Error("当前不能提交，请等待连接恢复");
      pending=true;render();autoDrawJob=null;clearLocal();
      try{
        var d=await window.PanelRequest.json('/api/workflow/poem',{method:'POST',headers:{'Content-Type':'application/json','X-Screen-Token':token},
          body:JSON.stringify({poem_id:id,confirmed:true,read_along:readAlong,request_id:"pm_"+Date.now().toString(36)})});
        workflow(d);
      }finally{pending=false;render();sync();}
    }});
  };
  $("mode-hardpen").onclick=function(){
    window.Hardpen.open({submit:async function(text,size,speed,layout){
      if(pending||!connected)throw Error("当前不能提交，请等待连接恢复");
      pending=true;render();autoDrawJob=null;clearLocal();
      try{   // layout: a saved phone piece (2026-10-29), written again from its saved commands
        var d=await window.PanelRequest.json(layout?'/api/workflow/hardpen-doc':'/api/workflow/hardpen',{method:'POST',headers:{'Content-Type':'application/json','X-Screen-Token':token},
          body:JSON.stringify({text:text,size_mm:size,layout:layout||undefined,speed_pct:speed,confirmed:true,request_id:"hp_"+Date.now().toString(36)})});
        workflow(d);
      }finally{pending=false;render();sync();}
    }});
  };
  $("mode-couplet").onclick=function(){
    window.Couplets.open({submit:async function(id){
      if(pending||!connected)throw Error("当前不能提交，请等待连接恢复");
      pending=true;render();autoDrawJob=null;clearLocal();
      try{
        var d=await window.PanelRequest.json('/api/workflow/couplet',{method:'POST',headers:{'Content-Type':'application/json','X-Screen-Token':token},
          body:JSON.stringify({couplet_id:id,confirmed:true,request_id:"cp_"+Date.now().toString(36)})});
        workflow(d);
      }finally{pending=false;render();sync();}
    }});
  };
  $("mode-brush").onclick=function(){$("open-calligraphy").onclick();};
  $("mode-hand").onclick=function(){$("open-handwriting").onclick();};
  $("mode-vision").onclick=function(){$("open-vision").onclick();};
  $("mode-wiki").onclick=function(){window.Encyclopedia.open();};
  $("mode-quiz").onclick=function(){window.Quiz.open();};
  $("mode-hwr").onclick=function(){window.Hwr.open();};
  $("mode-audio").onclick=function(){window.PoemAudio.open();};
  if(window.PoemAudio)window.PoemAudio.init(function(){return token;});
  $("open-settings").onclick=function(){action('/api/settings/open',{});};
  $("open-handwriting").onclick=function(){sessionStorage.setItem("handwriting-enter","1");location.href="/handwriting";};
  $("open-vision").onclick=function(){location.href="/vision";};
  $("open-calligraphy").onclick=function(){
    window.BrushModules.open({token:function(){return token;},submit:async function(module,size,auto){
      if(pending||!connected)throw Error("当前不能提交，请等待连接恢复");
      pending=true;render();autoDrawJob=null;clearLocal();
      try{
        var d=await window.PanelRequest.json('/api/workflow/calligraphy',{method:'POST',headers:{'Content-Type':'application/json','X-Screen-Token':token},
          body:JSON.stringify({module:module,size_mm:size,request_id:"brush_"+Date.now().toString(36)})});
        if(auto)autoDrawJob=d.job_id;workflow(d);
      }catch(e){autoDrawJob=null;throw e;}
      finally{pending=false;render();autoDraw();sync();}
    }});
  };
  $("open-masterpiece").onclick=function(){
    window.Masterpieces.open({submit:async function(style,readAlong){
      if(pending||!connected)throw Error("当前不能提交，请等待连接恢复");
      pending=true;render();autoDrawJob=null;clearLocal();
      try{
        var d=await window.PanelRequest.json('/api/workflow/masterpiece',{method:'POST',headers:{'Content-Type':'application/json','X-Screen-Token':token},
          body:JSON.stringify({style:style,confirmed:true,read_along:readAlong,request_id:"mp_"+Date.now().toString(36)})});
        workflow(d);
      }finally{pending=false;render();sync();}
    }});
  };
  var events=new EventSource('/api/events');
  events.addEventListener('workflow',function(e){try{workflow(JSON.parse(e.data));}catch(error){sync();}});
  events.addEventListener('clients',function(e){try{phones(JSON.parse(e.data));}catch(error){}});
  events.onopen=function(){sync();};events.onerror=function(){network(false);};
  document.addEventListener('visibilitychange',function(){if(!document.hidden)sync();});
  setInterval(sync,4000);sync();
  // 书法、归位和绘画共用主界面全局速度，SDK 改速应用到当前任务。
  var speed=null, speedTimer=null, speedSaved=null, speedKey="";
  function showSpeed(){var brushActive=current&&current.input_mode==="calligraphy"&&["planning","ready","drawing","stopping"].indexOf(current.phase)>=0;
    var key=JSON.stringify([!!brushActive,connected,speed]);if(key===speedKey)return;speedKey=key;
    $("speed-value").textContent=speed===null?"--%":speed+"%";$("speed-box").title=brushActive?"书法与归位均使用此速度":"机械臂速度";
    $("speed-down").disabled=!connected||speed===null||speed<=1;$("speed-up").disabled=!connected||speed===null||speed>=100;}
  // 名帖表演 opens at its default speed; the user can still change it with − / +.
  window.setArmSpeed=function(v){speed=Math.max(1,Math.min(100,Math.round(v)));showSpeed();clearTimeout(speedTimer);saveSpeed();};
  function stepSpeed(dir){if(speed===null)return;var step=(dir<0?speed<=10:speed<10)?1:5;speed=Math.max(1,Math.min(100,dir<0?speed-step:speed+step));showSpeed();
    clearTimeout(speedTimer);speedTimer=setTimeout(saveSpeed,450);}
  async function saveSpeed(){var v=speed;try{var r=await fetch('/api/tcb/speed',{method:'POST',headers:{'Content-Type':'application/json','X-Screen-Token':token},body:JSON.stringify({speed_pct:v})});var d=await r.json();if(!r.ok)throw Error(d.error||"速度未保存");speedSaved=d.speed_pct;
    var t=$("action-error");t.textContent=d.live_applied?"速度已改为 "+v+"%，已应用到当前任务":"速度已保存为 "+v+"%";t.hidden=false;setTimeout(function(){if(t.textContent.indexOf("速度")===0)t.hidden=true;},2500);}
    catch(e){speed=speedSaved;showSpeed();showError(e.message||"速度未保存，请重试");}}
  $("speed-down").onclick=function(){stepSpeed(-1);};$("speed-up").onclick=function(){stepSpeed(1);};
  fetch('/api/tcb/config',{cache:'no-store'}).then(r=>r.json()).then(c=>{var wp=c.execution&&c.execution.web_program;if(!wp)return;speed=speedSaved=Number(wp.draw_speed_pct);$("speed-box").hidden=false;showSpeed();}).catch(()=>{});
  setInterval(showSpeed,1000);
  fetch('/api/tcb/status',{cache:'no-store'}).then(r=>r.json()).then(c=>{if(c.robot_type==='TCB705'){simulation=!!c.simulation;realReady=!!(c.allow_real&&c.readiness&&c.readiness.physical_ready);render();}}).catch(()=>{});
})();
