'use strict';
(() => {
  const $=id=>document.getElementById(id); let token='',planId='',busy=false,machine=null;
  async function get(path){const r=await fetch(path,{cache:'no-store'});const d=await r.json();if(!r.ok)throw Error(d.error||r.statusText);return d;}
  async function post(path,data){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Screen-Token':token},body:JSON.stringify(data||{})});const d=await r.json();if(!r.ok)throw Error(d.error||r.statusText);return d;}
  function show(value){$('result').textContent=typeof value==='string'?value:JSON.stringify(value,null,2);}
  async function action(fn){if(busy)return;busy=true;document.querySelectorAll('button:not(#stop)').forEach(b=>b.disabled=true);try{await fn();}catch(e){show(e.message);}finally{busy=false;document.querySelectorAll('button').forEach(b=>b.disabled=false);}}
  async function wait(id){for(let i=0;i<1800;i++){const s=await get('/api/tcb/jobs');const j=s.jobs.find(x=>x.id===id);if(j){show(j);if(j.status==='FAILED')throw Error(j.detail);if(j.status==='DONE'&&s.active!==id)return j;}await new Promise(r=>setTimeout(r,350));}throw Error('任务仍未结束，请检查日志');}
  $('back').onclick=()=>action(async()=>{await post('/api/settings/close',{});location.href='/';});
  function number(id){const raw=$(id).value.trim();if(!raw||!Number.isFinite(Number(raw)))throw Error('请输入有效数值：'+$(id).closest('label').textContent);return Number(raw);}
  function range(){try{const x=[number('ax'),number('bx')].sort((a,b)=>a-b),y=[number('ay'),number('by')].sort((a,b)=>a-b);$('range').textContent=`当前绘画范围　X ${x[0].toFixed(3)} ～ ${x[1].toFixed(3)}　Y ${y[0].toFixed(3)} ～ ${y[1].toFixed(3)}　跨度 X ${(x[1]-x[0]).toFixed(3)} × Y ${(y[1]-y[0]).toFixed(3)} mm`;}catch(e){$('range').textContent='请填写 A、B 两点坐标';}}
  // 机械臂速度（2026-10-20）：execution.web_program 的画线/空中速度，0～100（0 不允许保存：机械臂不会动）
  function renderSpeed(c){const wp=c.execution&&c.execution.web_program;$('speed-section').hidden=!wp;if(!wp)return;
    const d=Number(wp.draw_speed_pct),a=Number(wp.air_speed_pct);$('arm-speed').value=d;$('arm-speed-range').value=d;
    $('speed-now').textContent='当前保存的速度：画线 '+d+'%，空中 '+a+'%';}
  function speedValue(){const raw=$('arm-speed').value.trim(),v=Number(raw);
    if(!raw||!Number.isFinite(v)||v<0||v>100)throw Error('速度请输入 0～100 之间的数');
    if(v===0)throw Error('速度为 0 时机械臂不会运动，至少设为 1');return Math.round(v*10)/10;}
  function render(c){machine=c;renderSpeed(c);$('config').value=JSON.stringify(c,null,2);const a=c.armvision;$('calibration').hidden=!a;if(!a){$('plan-help').textContent='当前是独立的 100 × 100 mm 离线算法示例，不使用 ArmVision 实际标定。';return;}
    const values={ax:a.a_mm[0],ay:a.a_mm[1],bx:a.b_mm[0],by:a.b_mm[1],z:a.z_table_mm,u:a.pose_uvw_deg[0],v:a.pose_uvw_deg[1],w:a.pose_uvw_deg[2],robot:a.robot_id,lift:a.lift_mm,'final-lift':a.final_lift_mm,speed:a.draw_speed_percent,tool:a.tool,coord:a.coord,extool:a.extool,'remote-ip':c.controller.remote_ip,'web-port':c.controller.web_port||8010,'local-ip':c.controller.local_ip||'','sdk-port':c.controller.port||8001,swap:String(a.swap_xy)};
    Object.entries(values).forEach(([k,v])=>$(k).value=v);range();renderCouplet(c);renderBrush(c);$('calibration-status').textContent='已加载 ArmVision A/B + 落笔 Z/UVW 标定；导入参数不等于完成本地七轴模型核对。';}
  async function refresh(){render(await get('/api/tcb/config'));renderStore().catch(()=>{});}
  // 名帖指令库（2026-10-27）：每幅名帖按列预先算好的运动指令，标定改变后需要重新计算。
  async function renderStore(){const s=await get('/api/tcb/masterpiece_store');$('mp-store-section').hidden=!s.works||!s.works.length||s.simulation;
    const box=$('mp-store');box.textContent='';
    (s.works||[]).forEach(w=>{const row=document.createElement('div');row.className='mp-store-row'+(w.ready?' ready':'');
      const t=document.createElement('b');t.textContent=w.author+'《'+w.title+'》';const v=document.createElement('span');
      const n=w.columns.filter(c=>c.ready).length;v.textContent=w.ready?'已就绪':(n?'已就绪 '+n+'/'+w.columns.length+' 列':'需要计算');
      row.appendChild(t);row.appendChild(v);box.appendChild(row);});}
  $('mp-precompute').onclick=()=>action(async()=>{const job=await post('/api/tcb/masterpiece_all',{mode:'real'});await wait(job.id);await renderStore();});
  // 毛笔标定（2026-10-26）：写毛笔字用单独的落笔高度；素描绘画仍用上面的纸面标定。当前工具决定能执行哪一类任务。
  function renderBrush(c){$('brush-section').hidden=false;const b=c.calligraphy||{},tool=c.mounted_tool||'pen';
    $('tool-pen').classList.toggle('ink',tool==='pen');$('tool-brush').classList.toggle('ink',tool==='brush');$('tool-hardpen').classList.toggle('ink',tool==='hardpen');
    $('bz').value=b.contact_z_mm==null?'':b.contact_z_mm;$('bh').value=b.hair_length_mm==null?'':b.hair_length_mm;$('bd').value=b.max_diameter_mm==null?'':b.max_diameter_mm;$('bp').value=b.max_press_mm==null?'':b.max_press_mm;$('bv').checked=false;
    $('brush-status').textContent='当前工具：'+({brush:'毛笔',hardpen:'硬笔'}[tool]||'画笔')+'；毛笔标定'+(b.verified?'已确认':'未确认')+(b.contact_z_mm==null?'，尚未读取毛笔落笔点':'');renderHardpen(c);}
  // 硬笔（2026-10-27）：第三种工具，单独的落笔高度和下压量；试写一行字（1 / 1.5 / 2 cm）。
  let hardpenPlan='',hardpenRevision='';
  function renderHardpen(c){$('hardpen-section').hidden=false;const h=c.hardpen||{};
    $('hz').value=h.contact_z_mm==null?'':h.contact_z_mm;if(h.press_mm!=null)$('hp').value=h.press_mm;$('hv').checked=false;$('hsafe').checked=false;
    $('hardpen-status').textContent='硬笔标定'+(h.verified?'已确认':'未确认')+(h.contact_z_mm==null?'，尚未读取硬笔落笔点':'')+(['pen','hardpen'].indexOf(c.mounted_tool||'pen')>=0?'；当前装的是画笔（硬笔通用）':'；试写前请换上画笔，并把当前工具切换为画笔');}
  $('read-hz').onclick=()=>action(async()=>{const job=await post('/api/tcb/read_pen_pose',{coordinate_source:'armvision',robot_id:number('robot'),connection:{remote_ip:$('remote-ip').value.trim(),web_port:number('web-port')}});const j=await wait(job.id),r=j.result,p=r&&r.world_mm_deg;if(r.source!=='armvision_web_world_feedback'||!Array.isArray(p)||p.length!==6||!p.every(Number.isFinite))throw Error('未返回完整控制器世界坐标');
    $('hz').value=p[2].toFixed(3);$('hardpen-status').textContent='已读取硬笔落笔 Z，勾选确认后点击“保存硬笔标定”。';});
  $('save-hardpen').onclick=()=>action(async()=>{if(!$('hv').checked)throw Error('请先确认：笔尖刚好接触纸面时读取了落笔点');
    show(await post('/api/tcb/hardpen-profile',{verified:true,contact_z_mm:number('hz'),press_mm:number('hp')}));hardpenPlan='';await refresh();$('hardpen-status').textContent='硬笔标定已保存，旧的硬笔规划已失效。';});
  $('tool-hardpen').onclick=()=>action(async()=>{show(await post('/api/tcb/tool',{tool:'hardpen'}));await refresh();});
  $('hardpen-plan').onclick=()=>action(async()=>{const cat=await get('/api/tcb/hardpen');if(cat.error)throw Error(cat.error);
    const src=await post('/api/tcb/calligraphy',{schema:'hardpen-text-v1',text:$('ht').value,font_size_mm:Number($('hs').value),revision:cat.revision});await wait(src.id);
    const j=await post('/api/tcb/plan',{image_job:src.id,mode:cat.simulation?'demo':'real'});await wait(j.id);hardpenPlan=j.id;hardpenRevision=cat.revision;
    $('hardpen-preview').src='/api/tcb/plans/'+hardpenPlan+'/preview.svg';$('hardpen-preview').hidden=false;$('hardpen-status').textContent='试写轨迹已规划，勾选安全确认后可以实机试写。';});
  $('hardpen-write').onclick=()=>action(async()=>{if(!hardpenPlan)throw Error('请先点“规划试写”');if(!$('hsafe').checked)throw Error('请先确认急停旁有人、机械臂周围无人');
    const cat=await get('/api/tcb/hardpen');if(cat.revision!==hardpenRevision)throw Error('标定已改变，请重新规划试写');
    const j=await post('/api/tcb/execute',{plan_job:hardpenPlan,mode:cat.simulation?'demo':'real',confirm_physical:true,speed_pct:Number($('hsp').value)});await wait(j.id);
    $('hsafe').checked=false;$('hardpen-status').textContent='试写完成，已归位。';});
  $('read-bz').onclick=()=>action(async()=>{const job=await post('/api/tcb/read_pen_pose',{coordinate_source:'armvision',robot_id:number('robot'),connection:{remote_ip:$('remote-ip').value.trim(),web_port:number('web-port')}});const j=await wait(job.id),r=j.result,p=r&&r.world_mm_deg;if(r.source!=='armvision_web_world_feedback'||!Array.isArray(p)||p.length!==6||!p.every(Number.isFinite))throw Error('未返回完整控制器世界坐标');
    $('bz').value=p[2].toFixed(3);$('brush-status').textContent='已读取毛笔落笔 Z，勾选确认后点击“保存毛笔标定”。';});
  $('save-brush').onclick=()=>action(async()=>{if(!$('bv').checked)throw Error('请先确认：笔尖刚好接触纸面时读取了落笔点，并核对了下压上限');
    const r=await post('/api/tcb/brush-profile',{verified:true,contact_z_mm:number('bz'),hair_length_mm:number('bh'),max_diameter_mm:number('bd'),max_press_mm:number('bp')});
    show(r);await refresh();$('brush-status').textContent='毛笔标定已保存，旧的毛笔规划已失效。';});
  $('tool-pen').onclick=()=>action(async()=>{show(await post('/api/tcb/tool',{tool:'pen'}));await refresh();});
  $('tool-brush').onclick=()=>action(async()=>{show(await post('/api/tcb/tool',{tool:'brush'}));await refresh();});
  // 春联台面（2026-10-25）：单独的 A/B 两点，落笔 Z 与笔轴姿态沿用上面的纸面标定；保存时离线检查四角可达。
  function renderCouplet(c){$('couplet-section').hidden=false;const t=c.couplet_table,p=c.couplet_paper;
    if(t){$('cax').value=t.a_mm[0];$('cay').value=t.a_mm[1];$('cbx').value=t.b_mm[0];$('cby').value=t.b_mm[1];}
    coupletRange();$('couplet-status').textContent=p?'已标定 '+p.width_mm.toFixed(0)+' × '+p.height_mm.toFixed(0)+' mm（七言需 590 × 212 mm）':'尚未标定';}
  function coupletRange(){try{const x=[number('cax'),number('cbx')].sort((a,b)=>a-b),y=[number('cay'),number('cby')].sort((a,b)=>a-b);$('couplet-range').textContent=`X ${x[0].toFixed(1)} ～ ${x[1].toFixed(1)}　Y ${y[0].toFixed(1)} ～ ${y[1].toFixed(1)}　跨度 ${(x[1]-x[0]).toFixed(1)} × ${(y[1]-y[0]).toFixed(1)} mm`;}catch(e){$('couplet-range').textContent='';}}
  ['cax','cay','cbx','cby'].forEach(id=>$(id).addEventListener('input',coupletRange));
  async function readCouplet(slot){const job=await post('/api/tcb/read_pen_pose',{coordinate_source:'armvision',robot_id:number('robot'),connection:{remote_ip:$('remote-ip').value.trim(),web_port:number('web-port')}});const j=await wait(job.id),r=j.result,p=r&&r.world_mm_deg;if(r.source!=='armvision_web_world_feedback'||!Array.isArray(p)||p.length!==6||!p.every(Number.isFinite))throw Error('未返回完整控制器世界坐标，春联台面保持不变');
    $('c'+slot+'x').value=p[0].toFixed(3);$('c'+slot+'y').value=p[1].toFixed(3);coupletRange();$('couplet-status').textContent=slot.toUpperCase()+' 点已读取，点击“保存春联台面”保存。';}
  $('read-ca').onclick=()=>action(()=>readCouplet('a'));$('read-cb').onclick=()=>action(()=>readCouplet('b'));
  $('save-couplet').onclick=()=>action(async()=>{const c=JSON.parse(JSON.stringify(machine));c.couplet_table={a_mm:[number('cax'),number('cay')],b_mm:[number('cbx'),number('cby')]};
    const r=await post('/api/tcb/config',c);invalidate();await refresh();show(r);$('couplet-status').textContent='春联台面已保存，四个角点离线检查可达。';});
  function form(){const c=JSON.parse(JSON.stringify(machine)),a=c.armvision;if(!a)throw Error('当前配置是独立算法示例');Object.assign(a,{a_mm:[number('ax'),number('ay')],b_mm:[number('bx'),number('by')],z_table_mm:number('z'),pose_uvw_deg:[number('u'),number('v'),number('w')],robot_id:number('robot'),lift_mm:number('lift'),final_lift_mm:number('final-lift'),draw_speed_percent:number('speed'),swap_xy:$('swap').value==='true',tool:number('tool'),coord:number('coord'),extool:number('extool')});c.controller.remote_ip=$('remote-ip').value.trim();c.controller.web_port=number('web-port');c.controller.local_ip=$('local-ip').value.trim();c.controller.port=number('sdk-port');return c;}
  function invalidate(){planId='';$('preview').hidden=true;}
  async function saveCalibration(){const result=await post('/api/tcb/config',form());invalidate();await refresh();$('calibration-status').textContent='标定参数已保存，旧规划已失效。';show(result);}
  $('refresh').onclick=()=>action(refresh);
  $('save').onclick=()=>action(async()=>{show(await post('/api/tcb/config',JSON.parse($('config').value)));invalidate();await refresh();});
  $('save-calibration').onclick=()=>action(saveCalibration);
  $('arm-speed-range').addEventListener('input',()=>{$('arm-speed').value=$('arm-speed-range').value;$('speed-status').textContent='';});
  $('arm-speed').addEventListener('input',()=>{const v=Number($('arm-speed').value);if(Number.isFinite(v))$('arm-speed-range').value=Math.max(0,Math.min(100,v));$('speed-status').textContent='';});
  $('save-speed').onclick=()=>action(async()=>{const v=speedValue(),c=JSON.parse(JSON.stringify(machine));
    if(!c.execution||!c.execution.web_program)throw Error('当前配置没有实机执行设置');
    const r=await post('/api/tcb/speed',{speed_pct:v});show(r);await refresh();
    $('speed-status').textContent='速度已保存为 '+v+'%'+(r.live_applied?'，正在绘制的这一幅已立即改速。':'，下一次绘画生效。');});
  ['ax','ay','bx','by'].forEach(id=>$(id).addEventListener('input',range));
  async function capture(slot){const job=await post('/api/tcb/read_pen_pose',{coordinate_source:'armvision',robot_id:number('robot'),connection:{remote_ip:$('remote-ip').value.trim(),web_port:number('web-port')}});const j=await wait(job.id),r=j.result,p=r&&r.world_mm_deg;if(r.source!=='armvision_web_world_feedback'||!Array.isArray(p)||p.length!==6||!p.every(Number.isFinite))throw Error('未返回完整控制器世界坐标，原标定保持不变');
    if(slot==='landing'){['z','u','v','w'].forEach((id,i)=>$(id).value=p[i+2].toFixed(3));await saveCalibration();}
    else{$(slot+'x').value=p[0].toFixed(3);$(slot+'y').value=p[1].toFixed(3);range();$('calibration-status').textContent=slot.toUpperCase()+' 点已读取，点击“保存标定参数”保存。';}}
  $('read-a').onclick=()=>action(()=>capture('a'));$('read-b').onclick=()=>action(()=>capture('b'));$('read-landing').onclick=()=>action(()=>capture('landing'));
  $('snapshot').onclick=()=>action(async()=>{await saveCalibration();const j=await post('/api/tcb/read_pen_pose',{coordinate_source:'sdk_commission'});await wait(j.id);});
  $('read').onclick=()=>action(async()=>{const j=await post('/api/tcb/read_pen_pose',{});await wait(j.id);});
  $('stop').onclick=async()=>{try{show(await post('/api/tcb/stop',{}));}catch(e){show(e.message);}};
  $('plan').onclick=()=>action(async()=>{const p=await post('/api/tcb/preset',{name:$('shape').value,width_mm:100,height_mm:100});await wait(p.id);const j=await post('/api/tcb/plan',{image_job:p.id,mode:'real'});await wait(j.id);planId=j.id;$('preview').src='/api/tcb/plans/'+planId+'/preview.svg';$('preview').hidden=false;});
  $('execute').onclick=()=>action(async()=>{if(!planId)throw Error('请先规划');const j=await post('/api/tcb/execute',{plan_job:planId,mode:'real',confirmed:true});await wait(j.id);});
  (async()=>{try{const state=await get('/api/state');token=state.control_token||'';const caps=await get('/api/tcb/status');$('mode').textContent=caps.simulation?'离线模式 · 不驱动机械臂':'只读联调 · 真实透传未开放';$('execute').textContent=caps.simulation?'模拟执行':'检查执行条件';await refresh();show(caps.sugar_calibration_detail);}catch(e){show(e.message);}})();
})();
