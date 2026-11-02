"use strict";
// 诗词库: pick a built-in quatrain; 楷书, vertical from the right, fixed 70 mm and 100 % speed.
// Each segment is planned once and kept on the board, so writing it again starts at once.
window.Poems=(function(){
  var $=function(id){return document.getElementById(id);},options=null,data=null,selected=null,form="五言绝句",size=70,busy=false;
  function message(s){$("pm-message").textContent=s||"";}
  function current(){return (data.items||[]).filter(function(p){return p.id===selected;})[0];}
  function render(){
    $("pm-tab-5").setAttribute("aria-pressed",String(form==="五言绝句"));$("pm-tab-7").setAttribute("aria-pressed",String(form==="七言绝句"));
    var list=$("pm-list");list.textContent="";
    (data.items||[]).filter(function(p){return p.form===form;}).forEach(function(p){
      var b=document.createElement("button");b.type="button";b.className="pm-card";b.setAttribute("aria-pressed",String(selected===p.id));
      var t=document.createElement("b");t.textContent=p.title;var a=document.createElement("span");a.textContent=p.author;
      b.appendChild(t);b.appendChild(a);b.onclick=function(){if(busy)return;selected=p.id;render();};list.appendChild(b);
    });
    var p=current(),n=p&&p.sheets[String(size)];
    $("pm-sheets").textContent=p?(n?"共 "+n+" 张纸":"纸面放不下"):"";
    if(p&&n){var src="/api/poems/preview?id="+encodeURIComponent(p.id)+"&size="+size;if($("pm-preview").getAttribute("src")!==src)$("pm-preview").src=src;$("pm-preview").hidden=false;}
    else $("pm-preview").hidden=true;
    $("pm-write").disabled=busy||!p||!n||!$("pm-safe").checked;
  }
  async function open(opts){
    options=opts;selected=null;busy=false;message("");$("poem-modal").hidden=false;
    $("pm-list").textContent="正在读取诗词…";$("pm-write").disabled=true;$("pm-safe").checked=false;$("pm-read").checked=false;
    try{var r=await fetch("/api/poems",{cache:"no-store"});data=await r.json();if(!r.ok)throw Error(data.error||"读取失败");size=data.default_size||70;render();}
    catch(e){$("pm-list").textContent="";message(e.message||"读取失败");}
  }
  function close(){if(busy)return;$("poem-modal").hidden=true;}
  $("pm-close").onclick=close;
  $("pm-tab-5").onclick=function(){if(!busy){form="五言绝句";render();}};
  $("pm-tab-7").onclick=function(){if(!busy){form="七言绝句";render();}};
  $("pm-safe").onchange=function(){if(data)render();};
  $("pm-write").onclick=async function(){
    if(busy||!selected||!$("pm-safe").checked)return;busy=true;render();message("正在读取运动指令，随后开始书写");
    try{await options.submit(selected,$("pm-read").checked);$("poem-modal").hidden=true;}
    catch(e){message(e.message||"提交失败");}
    finally{busy=false;if(!$("poem-modal").hidden)render();}
  };
  return {open:open};
})();
