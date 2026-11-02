"use strict";
// 硬笔书法: one line in 硬笔正楷 at 1 / 1.5 / 2 cm and 70 / 85 / 100 % speed. Pieces written
// before are kept on the board with their commands, so 已保存 writes them again at once.
window.Hardpen=(function(){
  var $=function(id){return document.getElementById(id);},options=null,data=null,tab="new",selected=null,size=15,speed=70,busy=false;
  var SIZE_LABEL={10:"1 cm",15:"1.5 cm",20:"2 cm"},LAYOUT_LABEL={h:"横排",v:"竖排"};
  // 2026-10-29: 已保存 also lists pieces sent from the phone (several lines, 横排 / 竖排, pages); their
  // size and layout are part of the saved commands, so only the speed can be changed here.
  function same(a,b){return !!a&&!!b&&a.text===b.text&&a.size===b.size&&(a.layout||"")===(b.layout||"");}
  function message(s){$("hp-message").textContent=s||"";}
  function el(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;}
  function items(){
    if(tab==="saved")return (data.works||[]).map(function(w){return {text:w.text,size:w.font_size_mm,ready:w.ready,key:w.key,layout:w.layout||"",pages:w.page_count||1};});
    return (data.presets||[]).map(function(t){return {text:t};});
  }
  function segment(box,values,current,label,pick){
    box.textContent="";
    values.forEach(function(v){var b=el("button","btn",label(v));b.type="button";b.setAttribute("aria-pressed",String(v===current));
      b.onclick=function(){if(!busy){pick(v);render();}};box.appendChild(b);});
  }
  function render(){
    $("hp-tab-new").setAttribute("aria-pressed",String(tab==="new"));$("hp-tab-saved").setAttribute("aria-pressed",String(tab==="saved"));
    var list=$("hp-list");list.textContent="";var shown=items();
    if(!shown.length)list.appendChild(el("p","hp-empty",tab==="saved"?"还没有保存的作品":"字库正在准备"));
    shown.forEach(function(it){
      var b=el("button","pm-card");b.type="button";
      var on=selected&&(tab==="new"?selected.text===it.text:same(selected,it));b.setAttribute("aria-pressed",String(!!on));
      var flat=it.text.replace(/\s+/g," ");b.appendChild(el("b","",flat.length>14?flat.slice(0,14)+"…":flat));
      if(tab==="saved")b.appendChild(el("span",it.ready?"ok":"stale",SIZE_LABEL[it.size]+(it.layout?" · "+LAYOUT_LABEL[it.layout]+" · "+it.pages+" 页":"")+(it.ready?" · 已就绪":" · 需重算")));
      b.onclick=function(){if(busy)return;selected={text:it.text,size:it.size,layout:it.layout||""};if(it.size)size=it.size;render();};
      list.appendChild(b);
    });
    segment($("hp-sizes"),selected&&selected.layout?[selected.size]:data.sizes||[10,15,20],size,function(v){return SIZE_LABEL[v];},function(v){size=v;});
    segment($("hp-speeds"),data.speeds||[70,85,100],speed,function(v){return v+"%";},function(v){speed=v;});
    if(selected){var src="/api/hardpen/preview?text="+encodeURIComponent(selected.text)+"&size="+size+(selected.layout?"&layout="+selected.layout:"");
      if($("hp-preview").getAttribute("src")!==src)$("hp-preview").src=src;$("hp-preview").hidden=false;}
    else $("hp-preview").hidden=true;
    $("hp-write").disabled=busy||!selected||!$("hp-safe").checked;
  }
  async function open(opts){
    options=opts;selected=null;busy=false;tab="new";message("");$("hardpen-modal").hidden=false;$("hp-safe").checked=false;
    $("hp-list").textContent="正在读取…";$("hp-write").disabled=true;
    try{var r=await fetch("/api/hardpen",{cache:"no-store"});data=await r.json();if(!r.ok)throw Error(data.error||"读取失败");render();}
    catch(e){$("hp-list").textContent="";message(e.message||"读取失败");}
  }
  function close(){if(busy)return;$("hardpen-modal").hidden=true;}
  $("hp-close").onclick=close;
  $("hp-tab-new").onclick=function(){if(!busy&&data){tab="new";selected=null;render();}};
  $("hp-tab-saved").onclick=function(){if(!busy&&data){tab="saved";selected=null;render();}};
  $("hp-safe").onchange=function(){if(data)render();};
  $("hp-preview").onerror=function(){$("hp-preview").hidden=true;message("这句在当前字号下放不下，请换小一档字号");};
  $("hp-preview").onload=function(){message("");};
  $("hp-write").onclick=async function(){
    if(busy||!selected||!$("hp-safe").checked)return;busy=true;render();message("正在读取运动指令，随后开始书写");
    try{await options.submit(selected.text,size,speed,selected.layout||"");$("hardpen-modal").hidden=true;}
    catch(e){message(e.message||"提交失败");}
    finally{busy=false;if(!$("hardpen-modal").hidden)render();}
  };
  return {open:open};
})();
