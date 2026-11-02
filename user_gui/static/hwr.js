"use strict";
// 手写识字 (2026-10-28): write one character on the screen, tap 写完了, and the board's CPU names
// it (3755 common characters). Recognition only: the arm never moves from this window.
// Board WebKit has no PointerEvent: X11 sends mouse events, other browsers TouchEvents.
window.Hwr=(function(){
  var $=function(id){return document.getElementById(id);},canvas=null,ctx=null,strokes=[],cur=null,busy=false,lastTouch=0,result=null,picked=0;
  function message(s){$("hwr-message").textContent=s||"";}
  function clamp(v){return Math.max(0,Math.min(1,v));}
  // Ink latency (2026-10-28): a move draws only its new segment, as on the 屏上手写 page; the
  // 田字格 is a CSS background, and the whole canvas is redrawn only for undo / clear.
  function pen(){var n=canvas.width;ctx.strokeStyle="#1f1a16";ctx.fillStyle="#1f1a16";ctx.lineWidth=n*0.028;ctx.lineCap="round";ctx.lineJoin="round";return n;}
  function dot(p){var n=pen();ctx.beginPath();ctx.arc(p[0]*n,p[1]*n,ctx.lineWidth/2,0,Math.PI*2);ctx.fill();}
  function segment(a,b){var n=pen();ctx.beginPath();ctx.moveTo(a[0]*n,a[1]*n);ctx.lineTo(b[0]*n,b[1]*n);ctx.stroke();}
  function paint(){
    var n=pen();ctx.clearRect(0,0,n,n);
    strokes.forEach(function(s){
      if(s.length===1){dot(s[0]);return;}
      ctx.beginPath();ctx.moveTo(s[0][0]*n,s[0][1]*n);
      for(var i=1;i<s.length;i++)ctx.lineTo(s[i][0]*n,s[i][1]*n);
      ctx.stroke();
    });
  }
  function pos(e){var r=canvas.getBoundingClientRect();return [clamp((e.clientX-r.left)/r.width),clamp((e.clientY-r.top)/r.height)];}
  function begin(e){if(busy||cur)return;cur=[pos(e)];strokes.push(cur);dot(cur[0]);if(result){result=null;show();}}
  function move(e){
    if(!cur)return;var p=pos(e),l=cur[cur.length-1];
    if(Math.abs(p[0]-l[0])+Math.abs(p[1]-l[1])<0.004)return;
    cur.push(p);segment(l,p);
  }
  function end(e){if(!cur)return;if(e)move(e);cur=null;show();}
  function show(){
    var cands=$("hwr-cands");cands.textContent="";
    $("hwr-go").disabled=busy||!strokes.length||!!cur;
    $("hwr-undo").disabled=busy||!strokes.length;$("hwr-clear").disabled=busy||!strokes.length;
    if(!result){$("hwr-char").textContent=strokes.length?"…":"？";$("hwr-p").textContent=strokes.length?"写完后点「写完了」":"在左边田字格里写一个字";return;}
    var top=result.candidates[picked];
    $("hwr-char").textContent=top.char;
    $("hwr-p").textContent=picked?"已改为候选字":(top.p<0.5?"不太确定，请从下面选一个":"把握 "+Math.round(top.p*100)+"%");
    result.candidates.forEach(function(c,i){
      var b=document.createElement("button");b.type="button";b.className="btn";b.textContent=c.char;
      b.setAttribute("aria-pressed",String(i===picked));b.setAttribute("aria-label","候选 "+c.char);
      b.onclick=function(){picked=i;show();};cands.appendChild(b);
    });
  }
  async function recognize(){
    if(busy||!strokes.length||cur)return;busy=true;show();message("正在识别…");
    try{
      var body=JSON.stringify({strokes:strokes.map(function(s){return s.map(function(p){return [Math.round(p[0]*1e4)/1e4,Math.round(p[1]*1e4)/1e4];});})});
      var r=await fetch("/api/hwr/recognize",{method:"POST",headers:{"Content-Type":"application/json"},body:body}),d=await r.json();
      if(!r.ok)throw Error(d.error||"识别失败");
      result=d;picked=0;message("识别用时 "+Math.round(d.ms)+" ms");
    }catch(e){message(e.message||"识别失败");}
    finally{busy=false;show();}
  }
  function clear(){if(busy)return;strokes=[];cur=null;result=null;picked=0;message("");paint();show();}
  // Strokes handed over from 屏上手写: kept in 0..1, thinned to the server's 4000-point limit.
  function handed(list){
    var total=0,k;list.forEach(function(s){total+=s.length;});k=Math.max(1,Math.ceil(total/3500));
    return list.map(function(s){
      var out=[];for(var i=0;i<s.length;i+=k)out.push([clamp(+s[i][0]),clamp(+s[i][1])]);
      var last=s[s.length-1];if((s.length-1)%k)out.push([clamp(+last[0]),clamp(+last[1])]);
      return out;
    });
  }
  function open(opts){
    $("hwr-modal").hidden=false;clear();
    if(opts&&opts.strokes&&opts.strokes.length){strokes=handed(opts.strokes);paint();show();recognize();}
  }
  function close(){if(busy)return;cur=null;$("hwr-modal").hidden=true;}
  function init(){
    canvas=$("hwr-ink");ctx=canvas.getContext("2d");
    canvas.addEventListener("mousedown",function(e){if(e.button!==0||Date.now()-lastTouch<800)return;e.preventDefault();begin(e);});
    window.addEventListener("mousemove",function(e){if(cur&&Date.now()-lastTouch>=800){e.preventDefault();move(e);}});
    window.addEventListener("mouseup",function(e){if(cur&&Date.now()-lastTouch>=800)end(e);});
    canvas.addEventListener("touchstart",function(e){lastTouch=Date.now();e.preventDefault();if(e.touches.length===1)begin(e.changedTouches[0]);},{passive:false});
    canvas.addEventListener("touchmove",function(e){lastTouch=Date.now();e.preventDefault();if(cur)move(e.changedTouches[0]);},{passive:false});
    canvas.addEventListener("touchend",function(e){lastTouch=Date.now();e.preventDefault();end(e.changedTouches[0]);},{passive:false});
    canvas.addEventListener("touchcancel",function(){lastTouch=Date.now();if(cur){strokes.pop();cur=null;paint();show();}});
    $("hwr-close").onclick=close;$("hwr-clear").onclick=clear;$("hwr-go").onclick=recognize;
    $("hwr-undo").onclick=function(){if(busy||!strokes.length)return;strokes.pop();result=null;picked=0;message("");paint();show();};
    paint();show();
    // 屏上手写 → 识别 (2026-10-28): the handwriting page leaves its strokes here and opens /?hwr=1.
    if(/[?&]hwr=1/.test(location.search)){
      var list=null;
      try{list=JSON.parse(sessionStorage.getItem("hwr-strokes")||"null");sessionStorage.removeItem("hwr-strokes");}catch(e){}
      try{history.replaceState(null,"",location.pathname);}catch(e){}
      if(Array.isArray(list)&&list.length)open({strokes:list});
    }
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);else init();
  return {open:open};
})();
