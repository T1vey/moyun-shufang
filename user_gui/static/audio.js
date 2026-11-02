"use strict";
window.PoemAudio=(function(){
  var $=function(id){return document.getElementById(id);};
  var items=[],selected=null,group="poem",token=function(){return "";},visible=false,available=false,timer=null,lastSentence=-2;
  function text(id,s){if($(id).textContent!==s)$(id).textContent=s;}
  function hidden(id,value){if($(id).hidden!==value)$(id).hidden=value;}
  function disabled(id,value){if($(id).disabled!==value)$(id).disabled=value;}
  function message(s){text("au-message",s||"");}
  function item(){return items.filter(function(x){return x.id===selected;})[0];}
  function time(s){s=Math.floor(s||0);return Math.floor(s/60)+":"+("0"+s%60).slice(-2);}
  function render(){
    lastSentence=-2;
    var active=item();
    if(!active||active.category!==group){var first=items.filter(function(x){return x.category===group;})[0];selected=first?first.id:null;lastSentence=-2;}
    $("au-poems").setAttribute("aria-pressed",String(group==="poem"));
    $("au-works").setAttribute("aria-pressed",String(group==="masterpiece"));
    var list=$("au-list");list.textContent="";
    items.filter(function(x){return x.category===group;}).forEach(function(x){
      var b=document.createElement("button");b.type="button";b.className="au-card";b.setAttribute("aria-pressed",String(x.id===selected));
      var title=document.createElement("b"),sub=document.createElement("span");title.textContent=x.title;sub.textContent=x.author+" · "+time(x.duration_s);
      b.appendChild(title);b.appendChild(sub);b.onclick=function(){selected=x.id;lastSentence=-2;render();};list.appendChild(b);
    });
    var x=item(),text=$("au-text");text.textContent="";
    $("au-title").textContent=x?x.title:"选择一篇诗文";
    $("au-author").textContent=x?x.dynasty+" · "+x.author:"以声入境，以墨传情";
    $("au-source").textContent=x?x.source_note:"";
    if(x)x.timeline.forEach(function(seg,i){var p=document.createElement("p");p.id="au-line-"+i;p.textContent=seg.text;text.appendChild(p);});
    $("au-play").disabled=!available||!x;
  }
  async function command(action,data){
    try{
      var r=await fetch("/api/audio/"+action,{method:"POST",headers:{"Content-Type":"application/json","X-Screen-Token":token()},body:JSON.stringify(data||{})});
      var d=await r.json();if(!r.ok)throw Error(d.error||"操作失败");message(action==="play"?"正在准备朗读…":"");await poll();
    }catch(e){message(e.message||"朗读连接中断");}
  }
  async function poll(){
    try{
      var r=await fetch("/api/audio/status",{cache:"no-store"});if(!r.ok)throw Error("朗读连接中断");var s=await r.json();available=s.available;
      hidden("au-retry",available);disabled("au-retry",!!s.initializing);
      disabled("au-play",!available||!item());
      ["pm-read-wrap","mp-read-wrap"].forEach(function(id){hidden(id,!available);});
      if(!visible)return;
      if(s.initializing)message("声音正在连接…");else if(!available)message("声音暂未就绪，可先浏览诗文");else if(s.error)message(s.error);else if(s.finished)message("本篇朗读完毕");else if(s.playing)message("正在朗读 · "+(s.title||""));else if(s.paused)message("已暂停");else message("");
      text("au-pause",s.paused?"继续朗读":"暂停");$("au-pause").dataset.paused=s.paused?"1":"0";
      disabled("au-pause",!s.playing&&!s.paused);disabled("au-stop",!s.playing&&!s.paused);
      text("au-progress",time(s.position_s)+" / "+time(s.duration_s));
      var index=s.id===selected?s.sentence:null;
      if(index!==lastSentence){
        Array.prototype.forEach.call($("au-text").children,function(p,i){p.className=i===index?"current":"";});
        var el=index===null?null:$("au-line-"+index);
        if(el){var box=$("au-text");if(el.offsetTop<box.scrollTop||el.offsetTop+el.offsetHeight>box.scrollTop+box.clientHeight)box.scrollTop=el.offsetTop-box.clientHeight/3;}
        lastSentence=index;
      }
    }catch(e){if(visible)message(e.message);}
  }
  async function open(){
    visible=true;$("audio-modal").hidden=false;message("正在读取诗文…");
    try{var r=await fetch("/api/audio/list",{cache:"no-store"}),d=await r.json();if(!r.ok)throw Error(d.error||"读取失败");items=d.items||[];available=d.available;
      render();message("");poll();}
    catch(e){message(e.message);}
  }
  $("au-close").onclick=function(){visible=false;$("audio-modal").hidden=true;};
  $("au-poems").onclick=function(){group="poem";render();};$("au-works").onclick=function(){group="masterpiece";render();};
  $("au-retry").onclick=function(){command("retry");};
  $("au-play").onclick=function(){if(selected)command("play",{id:selected});};
  $("au-pause").onclick=function(){command(this.dataset.paused==="1"?"resume":"pause");};
  $("au-stop").onclick=function(){command("stop");};
  function volume(){command("volume",{volume:parseInt($("au-volume").value,10),output:$("au-output").value});}
  $("au-volume").oninput=function(){$("au-volume-label").textContent=this.value+"%";};
  $("au-volume").onchange=volume;$("au-output").onchange=volume;
  return {open:open,init:function(fn){token=fn;poll();if(!timer)timer=setInterval(poll,800);},available:function(){return available;}};
})();
