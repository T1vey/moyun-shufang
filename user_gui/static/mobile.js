"use strict";
const $ = id => document.getElementById(id);
const TOKEN = new URLSearchParams(location.search).get("t") || "";
const Q = TOKEN ? `t=${encodeURIComponent(TOKEN)}&` : "";
const CID = (() => {
  let id = null;
  try { id = localStorage.getItem("so101.cid"); } catch {}
  if (!id) { id = "m" + Math.random().toString(36).slice(2, 12) + Date.now().toString(36).slice(-4); try { localStorage.setItem("so101.cid", id); } catch {} }
  return id;
})();
const buzz = p => { try { navigator.vibrate && navigator.vibrate(p); } catch {} };

const S = {
  display: { width: 800, height: 480, rotation: 0, format: "rgb565" },
  img: null, turn: 0, fit: "cover", zoom: 1, ox: 0, oy: 0, scale: 1, quality: 0.8,
  online: false, expired: false, busy: false, view: "pick", rtt: null,
  subject: "portrait", custom: "", detail: "simple",
};

/* ---------------- 画什么（云端提示词，2026-10-18） ---------------- */
const SUBJECT_HINTS = {
  portrait: "保留脸型、发型和表情，只画头部和肩部，笔画很少",
  object: "只画主体外轮廓和几条结构线，去掉背景和花纹",
  landscape: "远山、水面、日月或一棵树，不含人物和建筑",
  custom: "",
};
try { S.subject = localStorage.getItem("so101.subject") || "portrait"; S.custom = localStorage.getItem("so101.custom") || ""; } catch {}
if (!(S.subject in SUBJECT_HINTS)) S.subject = "portrait";
try { S.detail = localStorage.getItem("so101.detail") === "detail" ? "detail" : "simple"; } catch {}
const DETAIL_HINTS = { simple: "简略：笔画少、画得快", detail: "细节：保留更多结构，线条更多、画得更久" };
function subjectUI() {
  document.querySelectorAll("[data-subject]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.subject === S.subject)));
  document.querySelectorAll("[data-detail]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.detail === S.detail)));
  const own = S.subject === "custom";
  $("custom-row").hidden = !own;
  $("subject-hint").textContent = own
    ? `只写画什么就行，线条要求会自动加上，保证能画出来 · ${S.custom.length}/200`
    : `${SUBJECT_HINTS[S.subject]} · ${DETAIL_HINTS[S.detail]}`;
}
document.querySelectorAll("[data-subject]").forEach(b => b.onclick = () => {
  S.subject = b.dataset.subject; buzz(6);
  try { localStorage.setItem("so101.subject", S.subject); } catch {}
  subjectUI(); if (S.subject === "custom") $("custom-prompt").focus();
});
document.querySelectorAll("[data-detail]").forEach(b => b.onclick = () => {
  S.detail = b.dataset.detail; buzz(6);
  try { localStorage.setItem("so101.detail", S.detail); } catch {}
  subjectUI();
});
$("custom-prompt").value = S.custom;
$("custom-prompt").oninput = e => {
  S.custom = e.target.value.slice(0, 200);
  try { localStorage.setItem("so101.custom", S.custom); } catch {}
  subjectUI();
};
subjectUI();

/* ---------------- 链路 ---------------- */
function link(led, text) { $("led").className = `led ${led}`; $("link-text").textContent = text; }
async function hello() {
  const t0 = performance.now();
  try {
    const r = await fetch(`/api/hello?${Q}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cid: CID, rtt: S.rtt, state: S.busy ? "uploading" : S.view === "edit" ? "editing" : "idle" }),
    });
    S.rtt = Math.round(performance.now() - t0);
    if (r.status === 403) { expire(); return; }
    const d = await r.json();
    const changed = !S.online || ["width", "height", "rotation"].some(k => d.display[k] !== S.display[k]);
    S.display = d.display; S.online = true;
    if (!S.busy) link("ok", `LINKED  ${S.display.width}×${S.display.height}  ${S.rtt}ms`);
    if (changed) { aspect(); if (S.img) { clampPan(); draw(); } }
  } catch {
    S.online = false; link("err", "OFFLINE  重试中");
  }
  update();
}
function expire() {
  S.expired = true; link("err", TOKEN ? "配对码已失效" : "无权访问");
  showErr(TOKEN ? "屏幕已更换配对码，请重新扫描板子上的二维码。" : "只接受局域网内的设备，请连接与板子相同的 Wi-Fi 后重新扫码。");
  update();
}
setInterval(() => { if (!S.expired) hello(); }, 4000);
document.addEventListener("visibilitychange", () => { if (!document.hidden && !S.expired) hello(); });

/* ---------------- 目标尺寸 ---------------- */
function target() {
  const { width: W, height: H, rotation } = S.display;
  const sideways = rotation % 180 !== 0, bw = sideways ? H : W, bh = sideways ? W : H;
  const k = Math.min(S.scale, 1024 / Math.max(bw, bh));
  return { w: Math.round(bw * k), h: Math.round(bh * k), bw, bh };
}
function aspect() {
  const t = target();
  document.documentElement.style.setProperty("--aspect", `${t.bw} / ${t.bh}`);
  $("finder-res").textContent = `${S.display.width}×${S.display.height}  ${(S.display.format || "").toUpperCase()}`;
  $("scale-1").textContent = `${t.bw}×${t.bh}`;
  $("scale-2").textContent = `${t.bw * 2}×${t.bh * 2}`;
}

/* ---------------- 合成：预览与发送同一函数，所见即所发 ---------------- */
const srcSize = () => { const w = S.img.naturalWidth, h = S.img.naturalHeight; return S.turn % 2 ? { w: h, h: w } : { w, h }; };
function clampPan() {
  if (S.fit !== "cover") { S.ox = S.oy = 0; return; }
  const s = srcSize(), t = target(), unitH = t.bh / t.bw;
  const k = Math.max(1 / s.w, unitH / s.h) * S.zoom;
  const mx = Math.max(0, (s.w * k - 1) / 2), my = Math.max(0, (s.h * k - unitH) / 2);
  S.ox = Math.min(mx, Math.max(-mx, S.ox)); S.oy = Math.min(my, Math.max(-my, S.oy));
}
function compose(canvas, w, h) {
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  const g = canvas.getContext("2d");
  g.fillStyle = "#000"; g.fillRect(0, 0, w, h);
  g.imageSmoothingEnabled = true; g.imageSmoothingQuality = "high";
  const s = srcSize();
  const k = S.fit === "cover" ? Math.max(w / s.w, h / s.h) * S.zoom : Math.min(w / s.w, h / s.h);
  const iw = S.img.naturalWidth * k, ih = S.img.naturalHeight * k;
  g.save();
  g.translate(w / 2 + S.ox * w, h / 2 + S.oy * w);
  g.rotate(S.turn * Math.PI / 2);
  g.drawImage(S.img, -iw / 2, -ih / 2, iw, ih);
  g.restore();
}
const preview = $("preview"), finder = $("finder");
function draw() {
  if (!S.img) return;
  const t = target(), dpr = Math.min(devicePixelRatio || 1, 2);
  const w = Math.min(t.w, Math.round(finder.clientWidth * dpr));
  compose(preview, Math.max(1, w), Math.max(1, Math.round(w * t.h / t.w)));
  $("finder-zoom").textContent = `${S.zoom.toFixed(1)}×`;
  $("zoom-v").textContent = `${S.zoom.toFixed(1)}×`;
  estimate();
}
let estTimer;
function estimate() {
  clearTimeout(estTimer); $("size").textContent = "…";
  estTimer = setTimeout(async () => { const b = await output(); $("size").textContent = b ? `${Math.max(1, Math.round(b.size / 1024))} KB` : "—"; }, 250);
}
function output() {
  const t = target(), c = document.createElement("canvas");
  compose(c, t.w, t.h);
  return new Promise(res => c.toBlob(res, "image/jpeg", S.quality));
}

/* ---------------- 视图 ---------------- */
function go(view) {
  S.view = view;
  $("pick").hidden = view !== "pick"; $("edit").hidden = view !== "edit"; $("done").hidden = view !== "done";
  $("bar").hidden = view !== "edit";
  finder.classList.toggle("has-image", !!S.img);
  finder.classList.toggle("sent", view === "done");
  $("finder-empty").hidden = !!S.img;
  $("finder-zoom").hidden = view !== "edit" || S.fit !== "cover";
  if (!S.img) preview.getContext("2d").clearRect(0, 0, preview.width, preview.height);
  $("lede").hidden = view !== "pick";
  $("subject").hidden = view === "done";
  $("finder-flip").hidden = true;
  if (view === "pick" && !S.img) idleSugar(); else { idleLoop++; idlePainter.stop(); }
  if (view !== "done") { outPainter.stop(); finder.classList.remove("show-photo"); }
  update(); if (!S.expired) hello();
}

/* ---------------- 糖画：待机小鱼循环 / 发送后浇出这张照片 ---------------- */
const wait = ms => new Promise(r => setTimeout(r, ms));
const idleCanvas = $("idle-sugar"), idlePainter = new Sugar.Painter(idleCanvas, { lineScale: 2, min: 3200 });
let idleLoop = 0;
async function idleSugar() {
  const run = ++idleLoop;
  while (run === idleLoop) {
    idleCanvas.classList.remove("fade");
    const ok = await idlePainter.play(Sugar.fish());
    if (!ok || run !== idleLoop || Sugar.reduce) return;
    await wait(2400); if (run !== idleLoop) return;
    idleCanvas.classList.add("fade"); await wait(700);
  }
}
const outPainter = new Sugar.Painter($("sugar-out"), { max: 9000 });
function pourSent() {
  const t = target(), k = 360 / Math.max(t.w, t.h), c = document.createElement("canvas");
  compose(c, Math.round(t.w * k), Math.round(t.h * k));
  finder.classList.remove("show-photo"); $("finder-flip").textContent = "点画面 · 看原图";
  outPainter.play(Sugar.extract(c, { side: 220 }));
}
finder.addEventListener("click", () => {
  return; // The sent photo is not a simulated drawing preview.
  const photo = finder.classList.toggle("show-photo"); buzz(5);
  $("finder-flip").textContent = photo ? "点画面 · 看糖画" : "点画面 · 看原图";
});
new ResizeObserver(() => { idlePainter.resize(); outPainter.resize(); }).observe(finder);

/* ---------------- 选图 ---------------- */
function load(file) {
  if (!file) return;
  hideErr();
  const url = URL.createObjectURL(file), img = new Image();
  img.onload = () => {
    S.rid = null; S.img = img; S.turn = 0; S.zoom = 1; S.ox = S.oy = 0; $("zoom").value = "1";
    buzz(8); go("edit"); requestAnimationFrame(draw);
  };
  img.onerror = () => { URL.revokeObjectURL(url); buzz([20, 40, 20]); showErr("这张图片无法读取。iPhone 可在 设置 › 相机 › 格式 选“兼容性最佳”，或换一张 JPG/PNG。"); };
  img.src = url;
}
$("cam").onchange = e => { load(e.target.files[0]); e.target.value = ""; };
$("gallery").onchange = e => { load(e.target.files[0]); e.target.value = ""; };

/* ---------------- 调整 ---------------- */
document.querySelectorAll("[data-fit]").forEach(b => b.onclick = () => {
  S.fit = b.dataset.fit; buzz(5);
  document.querySelectorAll("[data-fit]").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
  $("zoom-row").hidden = S.fit !== "cover"; $("finder-zoom").hidden = S.fit !== "cover";
  clampPan(); draw();
});
document.querySelectorAll("[data-scale]").forEach(b => b.onclick = () => {
  S.scale = +b.dataset.scale; buzz(5);
  document.querySelectorAll("[data-scale]").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
  draw();
});
$("zoom").oninput = e => { S.zoom = +e.target.value; finder.classList.add("dragging"); clampPan(); draw(); };
$("zoom").onchange = () => finder.classList.remove("dragging");
$("quality").oninput = e => { S.quality = +e.target.value; estimate(); };
$("rotate").onclick = () => { S.turn = (S.turn + 1) % 4; S.ox = S.oy = 0; buzz(5); clampPan(); draw(); };
$("reset").onclick = () => { S.img = null; go("pick"); };

// 拖动取景 + 双指缩放；拖动时加深三分线
const pts = new Map(); let pinch0 = 0, zoom0 = 1;
preview.addEventListener("pointerdown", e => {
  if (!S.img || S.view !== "edit") return;
  preview.setPointerCapture(e.pointerId); pts.set(e.pointerId, [e.clientX, e.clientY]);
  finder.classList.add("dragging");
  if (pts.size === 2) { const [a, b] = [...pts.values()]; pinch0 = Math.hypot(a[0] - b[0], a[1] - b[1]); zoom0 = S.zoom; }
});
preview.addEventListener("pointermove", e => {
  if (!pts.has(e.pointerId) || S.fit !== "cover") return;
  const prev = pts.get(e.pointerId); pts.set(e.pointerId, [e.clientX, e.clientY]);
  if (pts.size === 2) {
    const [a, b] = [...pts.values()];
    S.zoom = Math.min(3, Math.max(1, zoom0 * Math.hypot(a[0] - b[0], a[1] - b[1]) / pinch0));
    $("zoom").value = String(S.zoom); $("finder-zoom").textContent = `${S.zoom.toFixed(1)}×`;
  } else {
    const w = preview.getBoundingClientRect().width;
    S.ox += (e.clientX - prev[0]) / w; S.oy += (e.clientY - prev[1]) / w;
  }
  clampPan(); compose(preview, preview.width, preview.height);
});
const up = e => { if (pts.delete(e.pointerId) && !pts.size) { finder.classList.remove("dragging"); draw(); } };
preview.addEventListener("pointerup", up); preview.addEventListener("pointercancel", up);
new ResizeObserver(() => { if (S.img) draw(); }).observe(finder);

/* ---------------- 发送 ---------------- */
function update() {
  const btn = $("send");
  btn.disabled = S.busy || !S.img || !S.online || S.expired;
  if (!S.busy) $("send-text").textContent = S.expired ? (TOKEN ? "配对码已失效" : "无权访问") : !S.online ? "等待连接屏幕" : "上传并自动处理";
}
function showErr(t) { $("err").textContent = t; $("err").hidden = false; $("bar").hidden = false; }
function hideErr() { $("err").hidden = true; if (S.view !== "edit") $("bar").hidden = true; }

$("send").onclick = async () => {
  hideErr(); buzz(8);
  const own = S.custom.trim();
  if (S.subject === "custom" && !own) { showErr("选了“自己写”，请先写下想画的内容"); $("custom-prompt").focus(); return; }
  S.busy = true; update();
  const track = $("track"); track.parentElement.classList.remove("done"); track.style.width = "0%";
  $("send-text").textContent = "正在熬糖…";
  link("sync", "SENDING");
  let blob; try { blob = await output(); if (!blob) throw Error("无法生成上传图片"); } catch (e) { S.busy = false; update(); showErr(e.message); return; } const t = target();
  const xhr = new XMLHttpRequest();
  S.rid = S.rid || ("u" + Date.now().toString(36) + Math.random().toString(36).slice(2,10));
  const what = `&subject=${S.subject}&detail=${S.detail}` + (S.subject === "custom" ? `&prompt=${encodeURIComponent(own)}` : "");
  xhr.open("POST", `/api/upload?${Q}cid=${CID}&rid=${S.rid}&w=${t.w}&h=${t.h}${what}`);
  xhr.setRequestHeader("Content-Type", "image/jpeg");
  xhr.timeout = 60000;
  xhr.upload.onprogress = e => {
    if (!e.lengthComputable) return;
    const p = Math.round(e.loaded / e.total * 100);
    track.style.width = `${p}%`; $("send-text").textContent = `正在浇糖  ${p}%`; link("sync", `SENDING  ${p}%`);
  };
  const finish = (ok, msg, data) => {
    S.busy = false;
    if (ok) {
      track.parentElement.classList.add("done"); track.style.width = "100%";
      $("done-meta").textContent = `#${String(data.frame.id).padStart(4, "0")}  ${t.w}×${t.h}  ${Math.max(1, Math.round(blob.size / 1024))} KB`;
      buzz(20);
      setTimeout(() => { track.style.width = "0%"; }, 400);
      go("done"); finder.classList.add("show-photo"); watchJob(data.job_id);
    } else {
      track.style.width = "0%"; buzz([20, 40, 20]); update(); showErr(msg);
    }
    if (!S.expired) hello();
  };
  xhr.onload = () => {
    let d = {}; try { d = JSON.parse(xhr.responseText); } catch {}
    if (xhr.status === 200) finish(true, "", d);
    else { if (xhr.status === 403) expire(); finish(false, d.error || `发送失败（${xhr.status}），请重试`); }
  };
  xhr.onerror = () => finish(false, "网络中断，请先查看板子屏幕是否已收到图片，再决定是否重试。");
  xhr.ontimeout = () => finish(false, "发送超时。靠近路由器，或把画质调低后重试。");
  xhr.send(blob);
};

$("again").onclick = () => { S.img = null; go("pick"); };
$("tweak").onclick = () => { go("edit"); requestAnimationFrame(draw); };

aspect();
go("pick");

var jobTimer=null;
function watchJob(id){
  clearTimeout(jobTimer);if(!id)return;
  async function tick(){
    try{const r=await fetch('/api/upload-status?'+Q+'cid='+encodeURIComponent(CID)+'&job_id='+encodeURIComponent(id),{cache:'no-store'});const d=await r.json();if(!r.ok)throw Error(d.error||'请查看板子屏幕');
      $('job-message').textContent=d.message||'';
      $('job-phase').textContent=d.phase==='ready'?'准备完毕，请在板子确认':d.phase==='drawing'?'板子正在绘画':d.phase==='completed'?'绘画已完成':d.phase==='error'?'处理未完成，请查看板子':'图片已送达，正在自动处理';
      const locked=['cloud','extracting','planning','ready','drawing'].indexOf(d.phase)>=0;
      $('again').disabled=locked;$('tweak').disabled=locked;
      if(['completed','cancelled','error'].indexOf(d.phase)<0)jobTimer=setTimeout(tick,2500);
    }catch(e){$('job-message').textContent=e.message||'连接暂时中断，请查看板子屏幕';jobTimer=setTimeout(tick,4000);}
  }tick();
}
