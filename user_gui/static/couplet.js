"use strict";
// 春联模式: pick a built-in couplet. 2026-10-29: 70 mm like 名帖 on the 名帖 paper, one row per
// line (上联 bottom, 下联 middle, 横批 top), characters turned to face left; each line continues
// on the same row of the next sheet (sheets laid side by side), fixed 100 %.
// 2026-10-28: written at once at 100 % after the safety check; each sheet's commands are kept on the board.
window.Couplets=(function(){
  var $=function(id){return document.getElementById(id);},options=null,data=null,selected=null,count=7,busy=false;
  function message(s){$("cp-message").textContent=s||"";}
  function strip(text,cls){var d=document.createElement("span");d.className="cp-strip "+cls;d.textContent=text;return d;}
  function render(){
    var grid=$("cp-grid");grid.textContent="";
    ["7","5","4"].forEach(function(n){$("cp-tab-"+n).setAttribute("aria-pressed",String(String(count)===n));});
    (data.items||[]).filter(function(c){return c.chars===count;}).forEach(function(c){
      var b=document.createElement("button");b.type="button";b.className="cp-card";b.setAttribute("aria-pressed",String(selected===c.id));
      b.setAttribute("aria-label",c.upper+"，"+c.lower+"，横批"+c.banner);
      // As hung: banner on top (read right to left), upper line right, lower line left.
      b.appendChild(strip(c.banner.split("").reverse().join(""),"banner"));
      b.appendChild(strip(c.lower,"lower"));b.appendChild(strip(c.upper,"upper"));
      b.onclick=function(){if(busy)return;selected=c.id;render();};
      grid.appendChild(b);
    });
    var need=data.needed[String(count)],t=data.table;
    message(!t?"请先在设置中完成纸面标定":(need&&(t.width_mm<need[0]||t.height_mm<need[1]))?"已标定纸面小于 "+Math.ceil(need[0])+"×"+Math.ceil(need[1])+" mm":"7 厘米字：下行上联、中行下联、上行横批，每张写每联 3 字，换纸接着写，几张并排即成整联");
    $("cp-write").disabled=busy||!selected||!$("cp-safe").checked||!(data.items||[]).some(function(c){return c.id===selected&&c.chars===count;});
  }
  async function open(opts){
    options=opts;selected=null;busy=false;message("");$("couplet-modal").hidden=false;$("cp-safe").checked=false;
    $("cp-grid").textContent="正在读取春联…";$("cp-write").disabled=true;
    try{var r=await fetch("/api/couplets",{cache:"no-store"});data=await r.json();if(!r.ok)throw Error(data.error||"读取失败");render();}
    catch(e){$("cp-grid").textContent="";message(e.message||"读取失败");}
  }
  function close(){if(busy)return;$("couplet-modal").hidden=true;}
  $("cp-close").onclick=close;
  $("cp-safe").onchange=function(){if(data)render();};
  ["7","5","4"].forEach(function(n){$("cp-tab-"+n).onclick=function(){if(busy)return;count=Number(n);render();};});
  $("cp-write").onclick=async function(){
    if(busy||!selected||!$("cp-safe").checked)return;busy=true;render();message("正在读取运动指令，随后开始书写");
    try{await options.submit(selected);$("couplet-modal").hidden=true;}
    catch(e){message(e.message||"提交失败");}
    finally{busy=false;if(!$("couplet-modal").hidden)render();}
  };
  return {open:open};
})();
