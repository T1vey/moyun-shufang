"use strict";
// 书法百科: read-only articles (categories -> entries -> screens, each screen with its own
// picture). Pictures are drawn from the glyph libraries' keyframes and simple drawings;
// nothing here starts a task or moves the arm.
window.Encyclopedia=(function(){
  var $=function(id){return document.getElementById(id);},doc=null,cat=null,entry=null,screen=0,cache={};
  var LABEL={kai:"楷",xing:"行",cao:"草",li:"隶",zhuan:"篆"},INK="#1f1a16",SEAL="#b3261e",PAPER="#fffaf0";
  var ORDER=["#b3261e","#1f1a16","#7a4b1e","#3f6b5c","#a8741f","#5a4a8a","#2f5f8a","#8a3a5a"];
  var ERAS=["商","周","秦","汉","魏晋","南北朝","隋唐","宋","元","明","清"];
  function el(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;}
  function canvas(w,h){var c=el("canvas");c.width=w;c.height=h;var x=c.getContext("2d");x.fillStyle=PAPER;x.fillRect(0,0,w,h);return c;}
  function glyph(ctx,g,ox,oy,cell,color){
    var k=cell/50;ctx.lineCap="round";ctx.lineJoin="round";
    g.forEach(function(s,i){ctx.strokeStyle=color?color(i):INK;for(var j=1;j<s.length;j++){var a=s[j-1],b=s[j];
      ctx.lineWidth=Math.max(1,(0.5+4.6*(a[2]+b[2])/2)*k);ctx.beginPath();ctx.moveTo(ox+a[0]*k,oy+a[1]*k);ctx.lineTo(ox+b[0]*k,oy+b[1]*k);ctx.stroke();}});
  }
  async function get(url){if(!cache[url]){var r=await fetch(url,{cache:"no-store"}),d=await r.json();if(!r.ok)throw Error(d.error||"读取失败");cache[url]=d;}return cache[url];}
  function glyphs(style,chars){return get("/api/encyclopedia/glyphs?style="+encodeURIComponent(style)+(chars?"&chars="+encodeURIComponent(chars):""));}
  function cells(list,labels,box){        // a block of characters, up to three per row
    var n=list.length,cols=n<=3?n:Math.ceil(n/2),cell=Math.min(120,Math.floor((268-16*cols)/cols)),wrap=el("div","wk-row");
    wrap.style.width=(cols*(cell+16))+"px";
    list.forEach(function(g,i){var f=el("figure","wk-cell"),c=canvas(cell,cell);glyph(c.getContext("2d"),g,0,0,cell);f.appendChild(c);
      if(labels)f.appendChild(el("figcaption","",labels[i]));wrap.appendChild(f);});
    box.appendChild(wrap);
  }
  var DRAW={
    glyph:async function(f,box){var d=await glyphs(f.style,f.chars);cells(d.glyphs,null,box);},
    styles:async function(f,box){var d=await get("/api/encyclopedia/glyphs?style=styles&chars="+encodeURIComponent(f.char));
      cells(d.figures.map(function(g){return g.glyphs[0];}),d.figures.map(function(g){return LABEL[g.style];}),box);},
    masterpiece:async function(f,box){var d=await glyphs(f.style),n=d.glyphs.length,cols=Math.ceil(n/3),gap=8,cell=Math.min(78,Math.floor((256-gap*(cols+1))/cols));
      var c=canvas(cols*cell+(cols+1)*gap,3*cell+4*gap),x=c.getContext("2d");
      d.glyphs.forEach(function(g,i){glyph(x,g,gap+Math.floor(i/3)*(cell+gap),gap+(i%3)*(cell+gap),cell);});box.appendChild(c);},
    grid:async function(f,box){var d=await glyphs(f.style||"kai",f.char),S=240,c=canvas(S,S),x=c.getContext("2d");
      x.strokeStyle=SEAL;x.lineWidth=2;x.strokeRect(1,1,S-2,S-2);x.setLineDash([6,6]);x.lineWidth=1;x.globalAlpha=.55;
      [[0,S/2,S,S/2],[S/2,0,S/2,S],[0,0,S,S],[S,0,0,S]].forEach(function(l){x.beginPath();x.moveTo(l[0],l[1]);x.lineTo(l[2],l[3]);x.stroke();});
      x.setLineDash([]);x.globalAlpha=1;glyph(x,d.glyphs[0],12,12,S-24);box.appendChild(c);},
    order:async function(f,box){var d=await glyphs("kai",f.char),S=250,c=canvas(S,S);
      glyph(c.getContext("2d"),d.glyphs[0],10,10,S-20,function(i){return ORDER[i%ORDER.length];});box.appendChild(c);},
    column:async function(f,box){                     // vertical columns from the right, with a seal
      var d=await glyphs("kai",f.chars+"印"),g=d.glyphs.slice(0,-1),seal=d.glyphs[d.glyphs.length-1],rows=Math.min(5,g.length),cols=Math.ceil(g.length/rows);
      var cell=Math.min(54,Math.floor(250/(rows+0.6))),gx=12,W=cols*cell+(cols-1)*gx+cell+40,H=rows*cell+30,c=canvas(W,H),x=c.getContext("2d");
      g.forEach(function(q,i){glyph(x,q,W-20-(Math.floor(i/rows)+1)*cell-Math.floor(i/rows)*gx,15+(i%rows)*cell,cell);});
      var s=cell*0.8,sx=12,sy=H-15-s;x.fillStyle=SEAL;x.fillRect(sx,sy,s,s);glyph(x,seal,sx+3,sy+3,s-6,function(){return PAPER;});box.appendChild(c);},
    couplet:async function(f,box){
      var d=await glyphs("kai",f.upper+f.lower+f.banner),n=f.upper.length,g=d.glyphs,cell=Math.min(30,Math.floor(210/n)),W=250,H=58+n*cell+16,c=canvas(W,H),x=c.getContext("2d");
      var bw=4*cell+24,bx=(W-bw)/2;x.fillStyle="#c8372b";x.fillRect(bx,8,bw,cell+12);x.fillRect(W-30-cell,52,cell+14,n*cell+12);x.fillRect(16,52,cell+14,n*cell+12);
      for(var i=0;i<n;i++){glyph(x,g[i],W-23-cell,58+i*cell,cell);glyph(x,g[n+i],23,58+i*cell,cell);}
      for(var j=0;j<4;j++)glyph(x,g[2*n+j],bx+12+(3-j)*cell,14,cell);   // banner reads right to left
      box.appendChild(c);},
    stroke:async function(f,box){var d=await get("/api/encyclopedia/strokes?modules="+encodeURIComponent(f.modules.join(",")));
      var n=d.strokes.length,per=Math.min(n,2),cell=Math.min(120,Math.floor((268-16*per)/per)),wrap=el("div","wk-row");wrap.style.width=(per*(cell+16))+"px";
      d.strokes.forEach(function(s){var fig=el("figure","wk-cell"),c=canvas(cell,cell),x=c.getContext("2d"),k=cell/50;x.lineCap="round";x.strokeStyle=INK;
        s.chains.forEach(function(ch){for(var j=1;j<ch.length;j++){var a=ch[j-1],b=ch[j];x.lineWidth=Math.max(1.5,(0.6+7*(a[2]+b[2])/2)*k);
          x.beginPath();x.moveTo(a[0]*k,a[1]*k);x.lineTo(b[0]*k,b[1]*k);x.stroke();}});
        fig.appendChild(c);fig.appendChild(el("figcaption","",s.name));wrap.appendChild(fig);});
      box.appendChild(wrap);},
    seals:async function(f,box){                       // 朱文 (red strokes) beside 白文 (paper strokes on red)
      var d=await glyphs("kai",f.chars),n=d.glyphs.length,w=96,h=w*n-(n-1)*14,c=canvas(2*w+40,h+20),x=c.getContext("2d");
      x.fillStyle=SEAL;x.fillRect(w+30,10,w,h);x.strokeStyle=SEAL;x.lineWidth=6;x.strokeRect(13,13,w-6,h-6);
      d.glyphs.forEach(function(g,i){glyph(x,g,18,16+i*(w-14),w-24,function(){return SEAL;});glyph(x,g,w+42,16+i*(w-14),w-24,function(){return PAPER;});});
      box.appendChild(c);},
    timeline:async function(f,box){var on=[].concat(f.era),wrap=el("div","wk-timeline");
      ERAS.forEach(function(e){wrap.appendChild(el("span",on.indexOf(e)>=0?"on":"",e));});box.appendChild(wrap);},
    tool:async function(f,box){var d=el("div","wk-tool");d.innerHTML=TOOLS[f.item]||"";box.appendChild(d);}
  };
  var TOOLS={
    brush:'<svg viewBox="0 0 120 240"><rect x="52" y="10" width="16" height="150" rx="4" fill="#7a5233"/><rect x="50" y="150" width="20" height="12" rx="2" fill="#2b2622"/><path d="M50 162C50 196 56 214 60 232C64 214 70 196 70 162Z" fill="#1f1a16"/><path d="M57 10h6v-6h-6z" fill="#b3261e"/></svg>',
    ink:'<svg viewBox="0 0 200 240"><rect x="70" y="20" width="60" height="200" rx="6" fill="#1f1a16"/><rect x="80" y="40" width="40" height="120" fill="none" stroke="#c9a24a" stroke-width="2"/><path d="M92 70h16M92 100h16M92 130h16" stroke="#c9a24a" stroke-width="3"/></svg>',
    paper:'<svg viewBox="0 0 220 240"><rect x="40" y="30" width="140" height="190" fill="#fbf6ea" stroke="#c9b48d"/><rect x="30" y="20" width="140" height="190" fill="#fffdf6" stroke="#c9b48d"/><path d="M50 50h100M50 80h100M50 110h100M50 140h100M50 170h100" stroke="#eadfc8"/></svg>',
    stone:'<svg viewBox="0 0 240 240"><rect x="30" y="40" width="180" height="170" rx="22" fill="#3b3631"/><rect x="48" y="58" width="144" height="134" rx="14" fill="#2a2622"/><ellipse cx="120" cy="88" rx="44" ry="18" fill="#141210"/><path d="M60 150c30-14 90-14 120 0" stroke="#4a443d" stroke-width="3" fill="none"/></svg>',
    seal:'<svg viewBox="0 0 240 240"><rect x="80" y="20" width="80" height="150" rx="6" fill="#c9b48d"/><path d="M80 60h80M80 100h80" stroke="#b49b70" stroke-width="2"/><rect x="74" y="168" width="92" height="22" fill="#b3261e"/><rect x="40" y="200" width="160" height="26" rx="4" fill="#fffdf6" stroke="#c9b48d"/><rect x="96" y="204" width="48" height="18" fill="#b3261e"/></svg>',
    inkpad:'<svg viewBox="0 0 240 240"><ellipse cx="120" cy="160" rx="92" ry="34" fill="#e9e2d2" stroke="#b49b70" stroke-width="2"/><ellipse cx="120" cy="150" rx="78" ry="26" fill="#b3261e"/><path d="M60 146c20-12 40 6 60-4s40 8 60-2" stroke="#8f1f17" stroke-width="3" fill="none"/><ellipse cx="120" cy="80" rx="92" ry="34" fill="#f4efe4" stroke="#b49b70" stroke-width="2"/><path d="M80 78c20-10 60-10 80 0" stroke="#6a7fa0" stroke-width="3" fill="none"/></svg>',
    four:'<svg viewBox="0 0 260 240"><rect x="20" y="40" width="120" height="160" fill="#fffdf6" stroke="#c9b48d"/><rect x="34" y="20" width="12" height="150" rx="3" fill="#7a5233"/><path d="M33 170C33 196 37 208 40 222C43 208 47 196 47 170Z" fill="#1f1a16"/><rect x="160" y="30" width="34" height="120" rx="4" fill="#1f1a16"/><rect x="150" y="160" width="96" height="66" rx="12" fill="#3b3631"/><ellipse cx="198" cy="180" rx="28" ry="9" fill="#141210"/></svg>'
  };
  async function figure(f,box,owner){
    box.textContent="";
    try{await DRAW[f.type](f,box);if(owner!==entry)box.textContent="";}catch(e){box.textContent="";}
  }
  function show(){
    var body=$("wk-body");body.textContent="";body.className="wk-body";
    $("wk-back").hidden=!cat;$("wk-title").textContent=entry?entry.title:cat?cat.title:"书法百科";$("wk-seal").textContent=cat?cat.seal:"典";
    if(!cat){
      body.classList.add("wk-home");
      doc.categories.forEach(function(c){var b=el("button","wk-cat");b.type="button";b.appendChild(el("i","",c.seal));b.appendChild(el("b","",c.title));
        b.onclick=function(){cat=c;show();};body.appendChild(b);});
    }else if(!entry){
      body.classList.add("wk-list");
      cat.entries.forEach(function(e){var b=el("button","wk-entry");b.type="button";b.appendChild(el("i","",e.seal||e.title.charAt(0)));b.appendChild(el("b","",e.title));
        b.onclick=function(){entry=e;screen=0;show();};body.appendChild(b);});
    }else{
      var s=entry.screens[screen];body.classList.add("wk-article");
      var box=el("div","wk-figure");body.appendChild(box);figure(s.figure,box,entry);
      var text=el("div","wk-text");text.appendChild(el("p","",s.text));
      var nav=el("div","wk-nav"),prev=el("button","btn","上一屏"),next=el("button","btn ink","下一屏");prev.type=next.type="button";
      prev.disabled=screen===0;next.disabled=screen===entry.screens.length-1;
      prev.onclick=function(){screen--;show();};next.onclick=function(){screen++;show();};
      nav.appendChild(prev);nav.appendChild(el("span","wk-page",(screen+1)+" / "+entry.screens.length));nav.appendChild(next);
      text.appendChild(nav);body.appendChild(text);
    }
  }
  async function open(path){              // path "category/entry" opens that article (from the quiz)
    cat=null;entry=null;screen=0;$("encyclopedia-modal").hidden=false;$("wk-body").textContent="正在读取…";
    try{if(!doc){var r=await fetch("/api/encyclopedia",{cache:"no-store"});var d=await r.json();if(!r.ok)throw Error(d.error||"读取失败");doc=d;}
      if(typeof path==="string"){var p=path.split("/");cat=doc.categories.filter(function(c){return c.id===p[0];})[0]||null;
        entry=cat&&cat.entries.filter(function(e){return e.id===p[1];})[0]||null;}
      show();}
    catch(e){$("wk-body").textContent=e.message||"读取失败";}
  }
  $("wk-close").onclick=function(){$("encyclopedia-modal").hidden=true;};
  $("wk-back").onclick=function(){if(entry)entry=null;else cat=null;show();};
  return {open:open};
})();
