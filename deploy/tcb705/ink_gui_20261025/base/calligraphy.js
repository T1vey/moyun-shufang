"use strict";
window.BrushModules=(function(){
  var $=function(id){return document.getElementById(id);},options=null,data=null,selected=null,group="basic",busy=false,page=0,pageSize=12;
  function message(s){$("brush-message").textContent=s||"";}
  function ready(){return data&&(data.simulation||(data.profile.verified&&data.profile.max_press_mm>0));}
  function setup(show){
    $("brush-panel").className="dialog-panel brush-panel"+(show?" brush-setup":"");
    $("brush-back").hidden=!show;
    if(show){$("brush-calibration").open=true;message("填写已确认的下压上限并保存。保存只更新参数，不会开始书写。");}
  }
  var previewCache=new WeakMap();
  function preview(item){
    var canvas=document.createElement("canvas"),cached=previewCache.get(item);
    canvas.setAttribute("role","img");canvas.setAttribute("aria-label",item.name+"笔画示意");
    if(cached){
      canvas.width=cached.width;canvas.height=cached.height;
      canvas.getContext("2d").drawImage(cached,0,0);return canvas;
    }
    var points=[];
    item.strokes.forEach(function(c){c.forEach(function(p){points.push(p);});});
    var xs=points.map(function(p){return p[0];}),ys=points.map(function(p){return p[1];});
    var x=Math.min.apply(null,xs)-5,y=Math.min.apply(null,ys)-5,w=Math.max.apply(null,xs)-x+5,h=Math.max.apply(null,ys)-y+5;
    w=Math.max(w,20);h=Math.max(h,20);
    // Rasterize once per module, retaining the exact backend curve and styles.
    // Thousands of individual SVG paths made every WebKit repaint expensive.
    var scale=384/Math.max(w,h);
    canvas.width=Math.min(384,Math.ceil(w*scale));canvas.height=Math.min(384,Math.ceil(h*scale));
    var ctx=canvas.getContext("2d");ctx.setTransform(scale,0,0,scale,-x*scale,-y*scale);
    ctx.strokeStyle="#e8a84a";ctx.lineCap="round";ctx.lineJoin="round";
    item.strokes.forEach(function(chain){
      if(chain.length<2)return;
      for(var i=1;i<chain.length;i++){
        var a=chain[i-1],b=chain[i],d=(a[2]+b[2])/2;
        // The server samples the same bounded curve used to create robot paths.
        ctx.globalAlpha=Number((0.38+0.62*d).toFixed(2));ctx.lineWidth=Number((0.4+3.4*d).toFixed(2));
        ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke();
      }
    });previewCache.set(item,canvas);return canvas;
  }
  function buttons(){
    var valid=ready();
    $("brush-plan").disabled=busy||!selected||!valid;
    $("brush-write").disabled=busy||!selected||!data;
    $("brush-save").disabled=busy||!data;
    $("brush-close").disabled=false;
    $("brush-write").textContent=data&&data.simulation?"模拟书写所选":valid?"书写所选":"设置毛笔参数";
    $("brush-selection-hint").textContent=valid?"选择模块后，点“书写所选”开始规划并执行。":"尚未保存毛笔下压参数，请点右侧按钮设置。";
    ["brush-basic","brush-radical","brush-search","brush-category","brush-size"].forEach(function(id){$(id).disabled=busy||!data;});
    Array.prototype.forEach.call($("brush-grid").children,function(b){if(b.tagName==="BUTTON")b.disabled=busy;});
    $("brush-prev").disabled=busy||page===0;
    $("brush-next").disabled=busy||!data||(page+1)*pageSize>=filtered().length;
  }
  function select(item){
    selected=item;
    if(!item){$("brush-name").textContent="暂无匹配模块";$("brush-info").textContent="换个名称或分类试试";$("brush-preview").textContent="";buttons();return;}
    $("brush-name").textContent=item.name;
    $("brush-info").textContent=item.stroke_count+" 笔 · "+item.category+" · "+(item.description||"固定笔顺 · 预设提按轨迹");
    $("brush-preview").textContent="";$("brush-preview").appendChild(preview(item));
    Array.prototype.forEach.call($("brush-grid").children,function(b){b.setAttribute("aria-pressed",String(b.dataset.id===item.id));});
    buttons();
  }
  function filtered(){
    var q=$("brush-search").value.trim().toLowerCase().replace(/[\s_'-]/g,""),category=$("brush-category").value;
    return data.items.filter(function(i){
      var text=[i.name,i.id,i.aliases||""].join(" ").toLowerCase().replace(/[\s_'-]/g,"");
      return i.group===group&&(!category||i.category===category)&&(!q||text.indexOf(q)!==-1);
    });
  }
  function categories(){
    var old=$("brush-category").value,labels=[];$("brush-category").textContent="";
    data.items.forEach(function(i){if(i.group===group&&labels.indexOf(i.category)===-1)labels.push(i.category);});
    [""].concat(labels).forEach(function(label){var o=document.createElement("option");o.value=label;o.textContent=label||"全部分类";$("brush-category").appendChild(o);});
    $("brush-category").value=labels.indexOf(old)!==-1?old:"";
  }
  function grid(){
    $("brush-grid").textContent="";
    var items=filtered();page=Math.max(0,Math.min(page,Math.ceil(items.length/pageSize)-1));
    var visible=items.slice(page*pageSize,(page+1)*pageSize);
    visible.forEach(function(item){
      var b=document.createElement("button"),name=document.createElement("span");
      b.type="button";b.className="brush-tile";b.dataset.id=item.id;b.setAttribute("aria-label",item.name);
      name.textContent=item.name;b.appendChild(preview(item));b.appendChild(name);b.onclick=function(){select(item);};
      $("brush-grid").appendChild(b);
    });
    if(!items.length){var empty=document.createElement("p");empty.className="brush-empty";empty.textContent="没有匹配的模块，请修改搜索词或分类。";$("brush-grid").appendChild(empty);}
    $("brush-count").textContent=items.length?items.length+" 项 · "+(page+1)+" / "+Math.ceil(items.length/pageSize):"0 项";
    $("brush-grid").scrollTop=0;
    select(visible.filter(function(i){return selected&&i.id===selected.id;})[0]||visible[0]||null);
    ["basic","radical"].forEach(function(k){
      $("brush-"+k).className="btn"+(group===k?" ink":"");$("brush-"+k).setAttribute("aria-pressed",String(group===k));
      $("brush-"+k).textContent=(k==="basic"?"笔画":"偏旁部首")+" · "+data.items.filter(function(i){return i.group===k;}).length;
    });
  }
  function loaded(value){
    data=value;categories();grid();
    $("brush-depth").value=data.profile.max_press_mm||"";
    $("brush-speed").textContent=typeof data.speed_pct==="number"?data.speed_pct+"%（主界面设置）":"跟随主界面速度";
    $("brush-verified").checked=data.profile.verified;
    $("brush-calibration").open=!data.profile.verified&&!data.simulation;
    message(data.simulation?"离线模拟：不会发送机械臂运动。":data.profile.verified?
      "毛笔参数已保存。书写所选会在规划成功后立即执行，可在主界面停止。":
      "首次使用请完成毛笔 TCP / 纸面标定，并填写实测下压上限；模块示意可直接浏览。");
    buttons();
  }
  async function request(url,body){
    var opts={cache:"no-store"};
    if(body){opts.method="POST";opts.headers={"Content-Type":"application/json","X-Screen-Token":options.token()};opts.body=JSON.stringify(body);}
    // Cold-start catalog builds the 88 preset previews on the ARM32 CPU.
    return window.PanelRequest.json(url,opts,body?15000:60000);
  }
  async function open(o){
    if(busy){$("calligraphy-modal").hidden=false;return;}
    options=o;busy=true;data=null;selected=null;setup(false);$("calligraphy-modal").hidden=false;
    $("brush-grid").textContent="";$("brush-preview").textContent="";$("brush-info").textContent="";$("brush-name").textContent="读取中";$("brush-count").textContent="";
    buttons();message("正在读取书法模块…");
    try{loaded(await request("/api/tcb/calligraphy"));}
    catch(e){message(e.message);}
    finally{busy=false;buttons();$("brush-close").focus();}
  }
  function close(){$("calligraphy-modal").hidden=true;$("open-calligraphy").focus();}
  document.addEventListener("DOMContentLoaded",function(){
    $("brush-close").onclick=close;
    $("brush-back").onclick=function(){setup(false);buttons();};
    ["basic","radical"].forEach(function(k){$("brush-"+k).onclick=function(){if(data&&!busy){group=k;page=0;$("brush-search").value="";categories();grid();}};});
    $("brush-search").oninput=$("brush-category").onchange=function(){if(data&&!busy){page=0;grid();}};
    $("brush-prev").onclick=function(){if(data&&!busy&&page>0){page--;grid();}};
    $("brush-next").onclick=function(){if(data&&!busy&&(page+1)*pageSize<filtered().length){page++;grid();}};
    $("brush-save").onclick=async function(){
      busy=true;buttons();
      try{loaded(await request("/api/tcb/brush-profile",{max_press_mm:Number($("brush-depth").value),
        verified:$("brush-verified").checked}));setup(false);}
      catch(e){message(e.message);}finally{busy=false;buttons();}
    };
    async function submit(auto){
      if(busy||!selected)return;
      if(!ready()){setup(true);return;}
      busy=true;buttons();message("正在提交，请勿重复点击…");
      try{await options.submit(selected.id,Number($("brush-size").value),auto);close();}
      catch(e){message(e.message);}finally{busy=false;buttons();}
    }
    $("brush-plan").onclick=function(){submit(false);};
    $("brush-write").onclick=function(){submit(true);};
    document.addEventListener("keydown",function(e){if(e.key==="Escape"&&!$("calligraphy-modal").hidden)close();});
  });
  return {open:open};
})();
