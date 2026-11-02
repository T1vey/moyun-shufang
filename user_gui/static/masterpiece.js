"use strict";
// 名帖表演: pick one famous work and it is written at once from the commands saved on the
// board (名帖指令库): 70 mm, three characters per column, columns left to right, speed 100 %.
window.Masterpieces=(function(){
  var $=function(id){return document.getElementById(id);},options=null,data=null,selected=null,busy=false;
  function message(s){$("mp-message").textContent=s||"";}
  function draw(work,canvas,cell){
    var n=work.sentence.length,cols=Math.ceil(n/3),rows=Math.min(3,n),gap=cell*0.15,gy=cell*0.1,pad=cell*0.12;
    canvas.width=Math.ceil(cols*cell+(cols-1)*gap+2*pad);canvas.height=Math.ceil(rows*cell+(rows-1)*gy+2*pad);
    var ctx=canvas.getContext("2d"),k=cell/50;
    ctx.fillStyle="#f4ead6";ctx.fillRect(0,0,canvas.width,canvas.height);
    ctx.strokeStyle="#2b1d12";ctx.lineCap="round";ctx.lineJoin="round";
    work.glyphs.forEach(function(strokes,i){
      var ox=pad+Math.floor(i/3)*(cell+gap),oy=pad+(i%3)*(cell+gy);
      strokes.forEach(function(s){for(var j=1;j<s.length;j++){var a=s[j-1],b=s[j],d=(a[2]+b[2])/2;
        ctx.lineWidth=Math.max(0.6,(0.4+4.2*d)*k);ctx.beginPath();ctx.moveTo(ox+a[0]*k,oy+a[1]*k);ctx.lineTo(ox+b[0]*k,oy+b[1]*k);ctx.stroke();}});
    });
  }
  function render(){
    var grid=$("mp-grid");grid.textContent="";
    (data.works||[]).forEach(function(w){
      var b=document.createElement("button");b.type="button";b.className="mp-tile";b.setAttribute("aria-pressed",String(selected===w.style));
      var c=document.createElement("canvas");draw(w,c,34);c.setAttribute("role","img");c.setAttribute("aria-label",w.sentence);
      var t=document.createElement("strong");t.textContent="《"+w.title+"》";
      var a=document.createElement("span");a.textContent=w.dynasty+" · "+w.author+" · "+w.script+(w.note?" · "+w.note:"");
      var s=document.createElement("em");s.textContent=w.sentence;
      b.appendChild(c);b.appendChild(t);b.appendChild(a);b.appendChild(s);
      b.onclick=function(){if(busy)return;selected=w.style;render();};
      grid.appendChild(b);
    });
    var w=(data.works||[]).filter(function(x){return x.style===selected;})[0];
    $("mp-selected").textContent=w?"已选："+w.author+"《"+w.title+"》 「"+w.sentence+"」":"请选择一幅名帖";
    $("mp-write").disabled=busy||!w||!$("mp-safe").checked;
  }
  async function open(opts){
    options=opts;selected=null;busy=false;message("");$("masterpiece-modal").hidden=false;
    $("mp-grid").textContent="正在读取名帖…";$("mp-write").disabled=true;$("mp-safe").checked=false;$("mp-read").checked=false;
    try{var r=await fetch("/api/masterpieces",{cache:"no-store"});data=await r.json();if(!r.ok)throw Error(data.error||"读取失败");
      if(!data.works.length)throw Error("板上尚未安装名帖轨迹库");render();}
    catch(e){$("mp-grid").textContent="";message(e.message||"读取失败");}
  }
  function close(){if(busy)return;$("masterpiece-modal").hidden=true;}
  $("mp-close").onclick=close;
  $("mp-safe").onchange=function(){if(data)render();};
  $("mp-write").onclick=async function(){
    if(busy||!selected||!$("mp-safe").checked)return;busy=true;render();message("正在读取运动指令，随后开始书写");
    try{await options.submit(selected,$("mp-read").checked);$("masterpiece-modal").hidden=true;}
    catch(e){message(e.message||"提交失败");}
    finally{busy=false;if(!$("masterpiece-modal").hidden)render();}
  };
  return {open:open};
})();
