"use strict";
// 趣味测验: ten questions per round from the encyclopedia, glyph libraries, masterpieces,
// poems and couplets. Pure screen content; it never starts a task or moves the arm.
window.Quiz=(function(){
  var $=function(id){return document.getElementById(id);},round=null,index=0,score=0,answered=false;
  var TITLES=[[9,"书法大家"],[6,"翰墨行家"],[0,"初入墨林"]];
  function el(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;}
  function draw(f){
    var n=f.glyphs.length,masterpiece=f.type==="masterpiece",cols=masterpiece?Math.ceil(n/3):1,rows=masterpiece?Math.min(3,n):1;
    var gap=10,cell=masterpiece?Math.min(80,Math.floor((260-gap*(cols+1))/cols)):220;
    var c=el("canvas");c.width=cols*cell+(cols+1)*gap;c.height=rows*cell+(rows+1)*gap;
    var x=c.getContext("2d");x.fillStyle="#fffaf0";x.fillRect(0,0,c.width,c.height);x.strokeStyle="#1f1a16";x.lineCap="round";x.lineJoin="round";
    f.glyphs.forEach(function(g,i){var ox=gap+Math.floor(i/rows)*(cell+gap),oy=gap+(i%rows)*(cell+gap),k=cell/50;
      g.forEach(function(s){for(var j=1;j<s.length;j++){var a=s[j-1],b=s[j];x.lineWidth=Math.max(1,(0.5+4.6*(a[2]+b[2])/2)*k);
        x.beginPath();x.moveTo(ox+a[0]*k,oy+a[1]*k);x.lineTo(ox+b[0]*k,oy+b[1]*k);x.stroke();}});});
    return c;
  }
  function show(){
    var body=$("qz-body");body.textContent="";answered=false;
    if(index>=round.questions.length)return finish();
    var q=round.questions[index];$("qz-progress").textContent="第 "+(index+1)+" / "+round.questions.length+" 题";
    body.className="qz-body"+(q.figure?"":" plain");
    if(q.figure){var fig=el("div","qz-figure");fig.appendChild(draw(q.figure));body.appendChild(fig);}
    var main=el("div","qz-main");main.appendChild(el("h3","qz-prompt",q.prompt));
    var opts=el("div","qz-options");
    q.options.forEach(function(o,i){var b=el("button","qz-option",o);b.type="button";b.onclick=function(){choose(i,b);};opts.appendChild(b);});
    main.appendChild(opts);
    var foot=el("div","qz-feedback");foot.id="qz-feedback";foot.hidden=true;main.appendChild(foot);
    body.appendChild(main);
  }
  function choose(i){
    if(answered)return;answered=true;var q=round.questions[index],right=i===q.answer;if(right)score++;
    document.querySelectorAll(".qz-option").forEach(function(b,k){b.disabled=true;if(k===q.answer)b.classList.add("right");else if(k===i)b.classList.add("wrong");});
    var f=$("qz-feedback");f.hidden=false;f.textContent="";
    f.appendChild(el("b",right?"ok":"no",right?"答对了":"正确答案："+q.options[q.answer]));f.appendChild(el("p","",q.explain));
    var row=el("div","qz-actions");
    if(q.entry){var wiki=el("button","btn","看百科");wiki.type="button";wiki.onclick=function(){window.Encyclopedia.open(q.entry);};row.appendChild(wiki);}
    var next=el("button","btn ink",index+1<round.questions.length?"下一题":"看成绩");next.type="button";next.onclick=function(){index++;show();};row.appendChild(next);
    f.appendChild(row);
  }
  function finish(){
    var body=$("qz-body");body.className="qz-body done";$("qz-progress").textContent="";
    var n=round.questions.length,title=TITLES.filter(function(t){return score>=t[0];})[0][1];
    var box=el("div","qz-result");box.appendChild(el("div","qz-score",score+" / "+n));box.appendChild(el("div","qz-title",title));
    var row=el("div","qz-actions"),again=el("button","btn ink","再来一轮"),back=el("button","btn","返回");again.type=back.type="button";
    again.onclick=function(){start();};back.onclick=function(){$("quiz-modal").hidden=true;};
    row.appendChild(back);row.appendChild(again);box.appendChild(row);body.appendChild(box);
  }
  async function start(){
    index=0;score=0;$("qz-body").className="qz-body";$("qz-body").textContent="正在出题…";
    try{var r=await fetch("/api/quiz/round",{cache:"no-store"}),d=await r.json();if(!r.ok)throw Error(d.error||"出题失败");round=d;show();}
    catch(e){$("qz-body").textContent=e.message||"出题失败";}
  }
  function open(){$("quiz-modal").hidden=false;start();}
  $("qz-close").onclick=function(){$("quiz-modal").hidden=true;};
  return {open:open};
})();
