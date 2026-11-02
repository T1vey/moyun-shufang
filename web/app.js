"use strict";
const $=id=>document.getElementById(id);
let token="", imageJob=null, planJob=null, active=null, allowMotion=false, scanBusy=false;
const observed=new Set();
let cloudBusy=false, cloudJob=null, cloudImage=null, originalURL=null;
function msg(s,err=false){$("message").textContent=s;$("message").className=err?"error":"";}
async function api(path,body){const r=await fetch(path,body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json","X-Console-Token":token},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error||r.status);return d;}
function connection(){return {mode:$("mode").value,port:$("port").value.trim(),baudrate:Number($("baud").value),confirmed:$("confirmed").checked};}
function controls(){const real=$("mode").value==="real", ready=!!token&&!active&&!scanBusy&&!cloudBusy, hardwareReady=!real||($("confirmed").checked&&!!$("port").value.trim());for(const id of ["image-file","cloud-model","subject","style","detail","width","height","segments","preset-name","config"])$(id).disabled=!ready;$("real-fields").hidden=!real;$("demo-fields").hidden=real;$("mode").disabled=!ready;$("probe").disabled=!ready||!hardwareReady;for(const id of ["image","sample","preset","save-config","export","cloud-generate"])$(id).disabled=!ready;for(const id of ["enable","jog-minus","jog-plus"])$(id).disabled=!ready||!hardwareReady||(real&&!allowMotion);$("cloud-use").disabled=!ready||!cloudImage;$("plan").disabled=!ready||!hardwareReady||!imageJob;$("execute").disabled=!ready||!hardwareReady||!planJob||(real&&!allowMotion);}
function invalidate(){planJob=null;controls();}
$("mode").onchange=()=>{$("confirmed").checked=false;$("rows").replaceChildren();$("result-badge").textContent="尚未读取";invalidate();};
for(const id of ["port","baud","confirmed"])$(id).onchange=invalidate;
$("port").oninput=()=>{planJob=null;controls();};
for(const id of ["width","height","segments","detail","style"])$(id).onchange=()=>{imageJob=null;planJob=null;controls();msg('参数已修改，请重新提取或选择预设。');};
$("refresh").onclick=async()=>{try{const d=await api('/api/ports');$("ports").replaceChildren();for(const p of d.ports){const o=document.createElement('option');o.value=p.device;o.label=p.description;$("ports").append(o);}$("port-hint").textContent=d.error||`发现 ${d.ports.length} 个串口`;}catch(e){msg(e.message,true);}};
$("probe").onclick=async()=>{try{scanBusy=true;controls();$("rows").replaceChildren();const entries=$("ids").value.split(',').map(x=>x.trim());if(entries.some(x=>!/^\d+$/.test(x)))throw Error('ID 用英文逗号分隔');const d=await api('/api/probe',{...connection(),ids:entries.map(Number),scenario:$("scenario").value});for(const row of d.rows){const tr=document.createElement('tr');for(const t of [row.id,row.ping_ok?'OK':'失败',row.raw_word===null?'—':'0x'+row.raw_word.toString(16),row.position_count??'—',row.error?.code||'OK']){const td=document.createElement('td');td.textContent=t;tr.append(td);}$("rows").append(tr);}$("result-badge").textContent=d.status;$("result-note").textContent=`${d.simulated?'模拟':'实物'} · ${new Date(d.time_utc).toLocaleString()} · 单次反馈`;msg(d.error||d.status,d.status==='FAIL');}catch(e){msg(e.message,true);}finally{scanBusy=false;controls();}};
async function action(kind,extra={}){try{const d=await api('/api/'+kind,{...connection(),...extra});active=d.id;controls();msg('任务已开始：'+kind);}catch(e){msg(e.message,true);}}
$("enable").onclick=()=>{invalidate();action('enable');};
$("jog-minus").onclick=()=>{invalidate();action('jog',{id:Number($("joint").value),delta:-10});};
$("jog-plus").onclick=()=>{invalidate();action('jog',{id:Number($("joint").value),delta:10});};
async function upload(sample=false, generated=null){try{const file=generated?await(await fetch(generated)).blob():sample?await(await fetch('/sample.png')).blob():$("image-file").files[0];if(!file)throw Error('先选择图片');if(file.size>8000000)throw Error('图片需小于 8 MB');const r=await fetch('/api/image',{method:'POST',headers:{'X-Console-Token':token,'X-Image-Style':(sample||generated)?'lineart':$("style").value,'X-Width-MM':$("width").value,'X-Height-MM':$("height").value,'X-Max-Segments':$("segments").value,'X-Trace-Detail':$("detail").value},body:file});const d=await r.json();if(!r.ok)throw Error(d.error);imageJob=null;planJob=null;active=d.id;controls();msg('ArmVision 正在提取笔画…');}catch(e){msg(e.message,true);}}
$("image-file").onchange=()=>{cloudImage=null;imageJob=null;planJob=null;$("cloud-preview").hidden=true;const file=$("image-file").files[0];if(originalURL)URL.revokeObjectURL(originalURL);if(file){originalURL=URL.createObjectURL(file);$("original-preview").src=originalURL;$("original-preview").hidden=false;}controls();};
$("preset").onclick=()=>{imageJob=null;planJob=null;action('preset',{name:$("preset-name").value,width_mm:Number($("width").value),height_mm:Number($("height").value)});};
$("cloud-use").onclick=()=>upload(false,cloudImage);
$("cloud-generate").onclick=async()=>{try{const file=$("image-file").files[0];if(!file)throw Error('先选择照片');if(file.size>8000000)throw Error('图片需小于 8 MB');cloudBusy=true;cloudImage=null;imageJob=null;planJob=null;controls();const r=await fetch('/api/cloud',{method:'POST',headers:{'X-Console-Token':token,'X-Subject':$("subject").value,'X-Cloud-Profile':$("cloud-model").value},body:file});const d=await r.json();if(!r.ok)throw Error(d.error);cloudJob=d.id;$("cloud-status").textContent=d.detail;pollCloud();}catch(e){cloudBusy=false;controls();msg(e.message,true);}};
async function pollCloud(){try{const d=await api('/api/cloud');const j=d.jobs.find(x=>x.id===cloudJob);if(!j)throw Error('找不到云端任务');$("cloud-status").textContent=j.detail;if(j.status==='RUNNING'){setTimeout(pollCloud,1200);return;}cloudBusy=false;if(j.status==='DONE'){cloudImage=j.image;$("cloud-preview").src=j.image;$("cloud-preview").hidden=false;}else msg(j.detail,true);controls();}catch(e){cloudBusy=false;controls();msg(e.message,true);}}
$("image").onclick=()=>upload();$("sample").onclick=()=>upload(true);
$("plan").onclick=()=>{planJob=null;action('plan',{image_job:imageJob});};
$("execute").onclick=()=>action('execute',{plan_job:planJob});
$("stop").onclick=async()=>{try{await api('/api/stop',{});msg('已请求停止；等待反馈。');}catch(e){msg(e.message,true);}};
$("save-config").onclick=async()=>{try{await api('/api/config',JSON.parse($("config").value));invalidate();$("config-status").textContent=' 已保存';}catch(e){msg(e.message,true);}};
$("export").onclick=async()=>{try{const r=await fetch('/api/export',{method:'POST',headers:{'Content-Type':'application/json','X-Console-Token':token},body:'{}'});if(!r.ok)throw Error((await r.json()).error);const u=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=u;a.download='so101_session.zip';a.click();setTimeout(()=>URL.revokeObjectURL(u),2000);msg('诊断包已下载；原始文件也保存在服务端 logs。');}catch(e){msg(e.message,true);}};
function showJob(j){
  if(j.preview)$("preview").src=`/job/${j.id}/${j.preview}`;
  $("metrics").replaceChildren();
  const r=j.result||{}, texts=[];
  const seconds=value=>Number.isFinite(value)?value.toFixed(3)+' s':'—';
  if(['image','preset','strokes'].includes(j.kind)){
    texts.push(`${r.strokes} 条笔画`,`${r.segments} 个线段`,`${r.width_mm} × ${r.height_mm} mm`);
  }else if(j.kind==='plan'){
    texts.push(r.status,`${r.metrics?.completed_targets} 个目标`,
      '规划耗时 '+seconds(r.metrics?.timing?.build_total_s),
      'IK 耗时 '+seconds(r.metrics?.timing?.ik_s),
      '预计运动时长 '+seconds(r.metrics?.duration_s));
  }else{
    texts.push(j.detail);
    if(r.execution_finished){
      texts.push(r.feedback_fresh?'最终反馈有效':'最终反馈缺失',
        '反馈失败 '+(r.timing?.feedback_failures??0)+' 次',
        '目标写入失败 '+(r.timing?.write_failures??0)+' 次');
      if(r.tracking)texts.push('笔尖最大误差 '+(Number.isFinite(r.tracking.max_tip_error_m)?
        (r.tracking.max_tip_error_m*1000).toFixed(2)+' mm':'—'));
    }
  }
  for(const t of texts){const e=document.createElement('span');e.textContent=t;$("metrics").append(e);}
  $("downloads").replaceChildren();
  const files=['preset','strokes'].includes(j.kind)?['paths.json']:
    j.kind==='image'?['input.png','lineart.png','paths.dxf','paths.json']:
    j.kind==='plan'?['drawing.json','plan.json','timing.json']:['result.json'];
  for(const f of files){const a=document.createElement('a');a.href=`/job/${j.id}/${f}`;a.textContent=f;a.target='_blank';a.rel='noopener';$("downloads").append(a);}
}
async function poll(){try{if(!token)return;await api('/api/heartbeat',{});const d=await api('/api/jobs');active=d.active;for(const j of d.jobs){if(j.status==='RUNNING'||observed.has(j.id))continue;observed.add(j.id);if(j.status==='DONE'){if(['image','preset'].includes(j.kind))imageJob=j.id;if(j.kind==='plan')planJob=j.id;if(j.kind==='execute')planJob=null;showJob(j);}msg(j.detail,j.status==='FAILED'||j.quality_warning===true);}const last=d.jobs.at(-1);$("job-status").textContent=last?`${last.kind} · ${last.status} · ${last.detail}`:'等待任务';controls();}catch(e){msg('连接中断：'+e.message,true);}finally{setTimeout(poll,750);}}
(async()=>{try{const d=await api('/api/status');token=d.token;allowMotion=d.motion_supported;$("real-option").disabled=!d.allow_real;$("access").textContent=allowMotion?'实物调试已开放':'模拟模式已就绪';$("session").textContent=d.session_id;$("version").textContent=`SO-101 ${d.version} · Python ${d.python} · IK ${d.ik_backend}`;$("config").value=JSON.stringify(await api('/api/config'),null,2);const c=await api('/api/cloud');for(const p of c.profiles){const o=document.createElement('option');o.value=p.id;o.textContent=p.model;$("cloud-model").append(o);}$("cloud-model").options[0].textContent=c.default_model?'启动配置 · '+c.default_model:'启动配置';$("cloud-model").value='';$("cloud-status").textContent=c.configured?'上传照片，选择模型后点击 AI 生成线稿':'用 launch_pc.ps1 启动电脑端';controls();poll();}catch(e){msg(e.message,true);}})();
