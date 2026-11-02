"use strict";
/* 糖画渲染：照片 → 单线稿（示意）→ 铜勺逐笔浇糖动画。屏幕页与手机页共用。
   线稿只是前端示意，实际笔画以板端 stroke_paths 规划为准。 */
const Sugar = (() => {
  const calm = () => document.documentElement.classList.contains("calm");
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

  /* ---------------- 线稿提取：模糊 → Sobel → 细化 → 追踪 → 简化 ---------------- */
  function extract(src, opt = {}) {
    const side = opt.side || 200, density = opt.density || 0.13;
    const sw = src.naturalWidth || src.width, sh = src.naturalHeight || src.height;
    const k = side / Math.max(sw, sh);
    const W = Math.max(8, Math.round(sw * k)), H = Math.max(8, Math.round(sh * k));
    const c = document.createElement("canvas"); c.width = W; c.height = H;
    const g = c.getContext("2d", { willReadFrequently: true });
    g.drawImage(src, 0, 0, W, H);
    const d = g.getImageData(0, 0, W, H).data, N = W * H;
    let L = new Float32Array(N);
    for (let i = 0; i < N; i++) L[i] = 0.299 * d[i * 4] + 0.587 * d[i * 4 + 1] + 0.114 * d[i * 4 + 2];
    L = blur(blur(L, W, H), W, H);

    const mag = new Float32Array(N);
    for (let y = 1; y < H - 1; y++) for (let x = 1; x < W - 1; x++) {
      const i = y * W + x;
      const gx = L[i - W + 1] + 2 * L[i + 1] + L[i + W + 1] - L[i - W - 1] - 2 * L[i - 1] - L[i + W - 1];
      const gy = L[i + W - 1] + 2 * L[i + W] + L[i + W + 1] - L[i - W - 1] - 2 * L[i - W] - L[i - W + 1];
      mag[i] = Math.hypot(gx, gy);
    }
    const sorted = Float32Array.from(mag).sort();
    const t = Math.max(40, sorted[Math.floor(N * (1 - density))]);
    const bin = new Uint8Array(N);
    for (let y = 1; y < H - 1; y++) for (let x = 1; x < W - 1; x++) bin[y * W + x] = mag[y * W + x] > t ? 1 : 0;
    thin(bin, W, H);

    let strokes = trace(bin, W, H).filter(s => s.length >= (opt.minLen || 6));
    strokes.sort((a, b) => b.length - a.length);
    const out = []; let budget = opt.budget || 2600;
    for (const s of strokes) {
      if (out.length >= 260 || budget <= 0) break;
      const p = rdp(s, 0.75); out.push(p); budget -= p.length;
    }
    return { w: W, h: H, strokes: order(out) };
  }

  function blur(a, W, H) {
    const o = new Float32Array(a.length);
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      let s = 0, n = 0;
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
        const xx = x + dx, yy = y + dy;
        if (xx >= 0 && yy >= 0 && xx < W && yy < H) { s += a[yy * W + xx]; n++; }
      }
      o[y * W + x] = s / n;
    }
    return o;
  }

  // Zhang-Suen 细化：边缘带收成单像素中心线，对应糖画的“一笔一线”
  function thin(b, W, H) {
    const del = [];
    for (let changed = true; changed;) {
      changed = false;
      for (let pass = 0; pass < 2; pass++) {
        del.length = 0;
        for (let y = 1; y < H - 1; y++) for (let x = 1; x < W - 1; x++) {
          const i = y * W + x; if (!b[i]) continue;
          const p2 = b[i - W], p3 = b[i - W + 1], p4 = b[i + 1], p5 = b[i + W + 1],
            p6 = b[i + W], p7 = b[i + W - 1], p8 = b[i - 1], p9 = b[i - W - 1];
          const B = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9;
          if (B < 2 || B > 6) continue;
          const A = (!p2 & p3) + (!p3 & p4) + (!p4 & p5) + (!p5 & p6) + (!p6 & p7) + (!p7 & p8) + (!p8 & p9) + (!p9 & p2);
          if (A !== 1) continue;
          if (pass === 0 ? (p2 & p4 & p6) || (p4 & p6 & p8) : (p2 & p4 & p8) || (p2 & p6 & p8)) continue;
          del.push(i);
        }
        for (const i of del) b[i] = 0;
        if (del.length) changed = true;
      }
    }
  }

  const N8 = [[1, 0], [0, 1], [-1, 0], [0, -1], [1, 1], [-1, 1], [-1, -1], [1, -1]];
  function trace(b, W, H) {
    const seen = new Uint8Array(W * H), out = [];
    const next = i => {
      const x = i % W, y = (i / W) | 0;
      for (const [dx, dy] of N8) {
        const xx = x + dx, yy = y + dy;
        if (xx < 0 || yy < 0 || xx >= W || yy >= H) continue;
        const j = yy * W + xx;
        if (b[j] && !seen[j]) return j;
      }
      return -1;
    };
    const degree = i => {
      const x = i % W, y = (i / W) | 0; let n = 0;
      for (const [dx, dy] of N8) { const xx = x + dx, yy = y + dy; if (xx >= 0 && yy >= 0 && xx < W && yy < H && b[yy * W + xx]) n++; }
      return n;
    };
    const extend = s => { const pts = []; for (let j = next(s); j >= 0; j = next(j)) { seen[j] = 1; pts.push(j); } return pts; };
    const stroke = s => {
      seen[s] = 1;
      const a = extend(s), r = extend(s).reverse();
      const idx = [...r, s, ...a], pts = idx.map(i => [i % W, (i / W) | 0]);
      const p0 = pts[0], pn = pts[pts.length - 1];
      if (pts.length > 8 && Math.abs(p0[0] - pn[0]) <= 1 && Math.abs(p0[1] - pn[1]) <= 1) pts.push([p0[0], p0[1]]);
      return pts;
    };
    for (let i = 0; i < W * H; i++) if (b[i] && !seen[i] && degree(i) === 1) out.push(stroke(i));
    for (let i = 0; i < W * H; i++) if (b[i] && !seen[i]) out.push(stroke(i));
    return out;
  }

  function rdp(p, eps) {
    if (p.length < 3) return p;
    const [ax, ay] = p[0], [bx, by] = p[p.length - 1], dx = bx - ax, dy = by - ay, len = Math.hypot(dx, dy);
    let idx = 0, dmax = 0;
    for (let i = 1; i < p.length - 1; i++) {
      const dd = len ? Math.abs(dy * p[i][0] - dx * p[i][1] + bx * ay - by * ax) / len : Math.hypot(p[i][0] - ax, p[i][1] - ay);
      if (dd > dmax) { dmax = dd; idx = i; }
    }
    if (dmax <= eps) return [p[0], p[p.length - 1]];
    return rdp(p.slice(0, idx + 1), eps).slice(0, -1).concat(rdp(p.slice(idx), eps));
  }

  // 就近排序：铜勺抬起后移动最短，和师傅手法一致
  function order(strokes) {
    if (!strokes.length) return strokes;
    const left = strokes.slice(1), out = [strokes[0]];
    while (left.length) {
      const e = out[out.length - 1].at(-1);
      let best = 0, bd = Infinity, rev = false;
      left.forEach((s, i) => {
        const a = Math.hypot(s[0][0] - e[0], s[0][1] - e[1]), z = Math.hypot(s.at(-1)[0] - e[0], s.at(-1)[1] - e[1]);
        if (a < bd) { bd = a; best = i; rev = false; }
        if (z < bd) { bd = z; best = i; rev = true; }
      });
      const s = left.splice(best, 1)[0];
      out.push(rev ? s.slice().reverse() : s);
    }
    return out;
  }

  // SVG 路径 → 笔画（Logo、待机画面用）
  function fromPaths(ds, w, h, step = 0.8) {
    const ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg");
    svg.setAttribute("style", "position:absolute;width:0;height:0;visibility:hidden");
    document.body.append(svg);
    const strokes = ds.map(dd => {
      const p = document.createElementNS(ns, "path"); p.setAttribute("d", dd); svg.append(p);
      const L = p.getTotalLength(), n = Math.max(2, Math.ceil(L / step)), pts = [];
      for (let i = 0; i <= n; i++) { const q = p.getPointAtLength(L * i / n); pts.push([q.x, q.y]); }
      return pts;
    });
    svg.remove();
    return { w, h, strokes };
  }

  // 招牌小鱼（年年有余），也是 Logo 的笔画
  const FISH_D = [
    "M8 22 C12 27 14 30 17 32 C25 19 43 18 54 32 C43 46 25 45 17 32 C14 35 12 38 8 43 C11 36 11 29 8 22",
    "M33 21 C35 15 40 13 45 15",
    "M27 25 C31 29 31 35 27 39",
    "M34 23 C38 28 38 36 34 41",
    "M44 29 a2 2 0 1 0 4 0 a2 2 0 1 0 -4 0",
    "M30 44 C31 48 34 50 38 50",
    "M58 22 c0 -2 -3 -2 -3 0 c0 3 5 3 5 -1 c0 -4 -6 -5 -7 0",
  ];
  let fishCache;
  const fish = () => fishCache || (fishCache = { ...fromPaths(FISH_D, 64, 56), stickAt: .62 });

  /* ---------------- 绘制：石板、糖线、铜勺、竹签 ---------------- */
  function rng(seed) {
    return () => { seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
  }
  function slab(g, w, h) {
    const r = rng(11);
    const grad = g.createRadialGradient(w * .5, h * .4, 0, w * .5, h * .5, Math.hypot(w, h) * .62);
    grad.addColorStop(0, "#3d342c"); grad.addColorStop(.55, "#28211b"); grad.addColorStop(1, "#141009");
    g.fillStyle = grad; g.fillRect(0, 0, w, h);
    const n = Math.round(w * h / 700);
    for (let i = 0; i < n; i++) {
      g.fillStyle = r() < .5 ? `rgba(255,236,210,${r() * .05})` : `rgba(0,0,0,${r() * .2})`;
      const s = r() * 1.6 + .4; g.fillRect(r() * w, r() * h, s, s);
    }
    g.lineCap = "round";
    for (let v = 0; v < 5; v++) {
      let x = r() * w, y = -10; g.beginPath(); g.moveTo(x, y);
      for (let k = 0; k < 6; k++) {
        const nx = x + (r() - .5) * w * .35, ny = y + h / 5;
        g.quadraticCurveTo(x + (r() - .5) * w * .3, y + h / 10, nx, ny); x = nx; y = ny;
      }
      g.strokeStyle = `rgba(255,232,205,${.02 + r() * .035})`; g.lineWidth = .6 + r() * 1.6; g.stroke();
    }
  }
  function pathOf(g, p) {
    g.beginPath(); g.moveTo(p[0][0], p[0][1]);
    for (let i = 1; i < p.length - 1; i++) g.quadraticCurveTo(p[i][0], p[i][1], (p[i][0] + p[i + 1][0]) / 2, (p[i][1] + p[i + 1][1]) / 2);
    const l = p[p.length - 1]; g.lineTo(l[0], l[1]);
  }
  // 四层：落影 → 焦糖边 + 暖光 → 糖身 → 高光，做出半透明麦芽糖的质感
  function sugarStroke(g, p, w) {
    if (p.length < 2) return;
    g.save(); g.lineCap = g.lineJoin = "round";
    pathOf(g, p);
    g.shadowColor = "rgba(0,0,0,.5)"; g.shadowBlur = w * 1.2; g.shadowOffsetX = w * .35; g.shadowOffsetY = w * .6;
    g.strokeStyle = "#8a4a0c"; g.lineWidth = w * 1.15; g.stroke();
    g.shadowColor = "rgba(255,166,52,.5)"; g.shadowBlur = w * 2.4; g.shadowOffsetX = g.shadowOffsetY = 0;
    g.strokeStyle = "#dc8c26"; g.lineWidth = w; g.stroke();
    g.shadowColor = "transparent"; g.shadowBlur = 0;
    g.strokeStyle = "#f6b752"; g.lineWidth = w * .6; g.stroke();
    g.translate(-w * .16, -w * .2); pathOf(g, p);
    g.strokeStyle = "rgba(255,244,214,.82)"; g.lineWidth = Math.max(.8, w * .2); g.stroke();
    g.restore();
  }

  class Painter {
    constructor(canvas, o = {}) {
      this.c = canvas; this.g = canvas.getContext("2d");
      this.o = { lineScale: 1, stick: true, stickAt: .9, pxPerSec: 520, min: 2500, max: 11000, ...o };
      this.base = document.createElement("canvas"); this.bg = this.base.getContext("2d");
      this.token = 0; this.i = 0; this.d = null; this.sparks = []; this.stuck = false;
    }
    fit() {
      let cw, ch, dpr;
      if (this.o.fixed) { cw = this.c.width; ch = this.c.height; dpr = this.o.dpr || 1; }
      else {
        dpr = Math.min(devicePixelRatio || 1, 2);
        const r = this.c.getBoundingClientRect();
        cw = Math.max(2, Math.round(r.width * dpr)); ch = Math.max(2, Math.round(r.height * dpr));
        if (this.c.width !== cw || this.c.height !== ch) { this.c.width = cw; this.c.height = ch; }
      }
      this.base.width = cw; this.base.height = ch; this.dpr = dpr; this.cw = cw; this.ch = ch;
      const d = this.d; if (!d) return;
      const stick = this.o.stick ? .14 : 0, m = .07;
      const s = Math.min(cw * (1 - 2 * m) / d.w, ch * (1 - 2 * m - stick) / d.h);
      this.s = s; this.ox = (cw - d.w * s) / 2; this.oy = (ch * (1 - stick) - d.h * s) / 2 + ch * m * .3;
      this.w = clamp(Math.min(d.w, d.h) * s * .011 * this.o.lineScale, 1.6 * dpr, 9 * dpr);
      this.paths = d.strokes.map(st => st.map(p => [this.ox + p[0] * s, this.oy + p[1] * s]));
      this.lens = this.paths.map(p => { const L = [0]; for (let i = 1; i < p.length; i++) L.push(L[i - 1] + Math.hypot(p[i][0] - p[i - 1][0], p[i][1] - p[i - 1][1])); return L; });
      this.total = this.lens.reduce((a, L) => a + L[L.length - 1], 0);
      this.paintBase();
    }
    paintBase() {
      const g = this.bg; g.clearRect(0, 0, this.cw, this.ch);
      slab(g, this.cw, this.ch);
      for (let k = 0; k < this.i && k < this.paths.length; k++) sugarStroke(g, this.paths[k], this.w);
      if (this.stuck) this.stick(g, 1);
    }
    resize() { if (!this.d) return; this.fit(); if (!this.raf) this.g.drawImage(this.base, 0, 0); }
    stop() { this.token++; cancelAnimationFrame(this.raf); this.raf = 0; }
    show(d) { this.stop(); this.d = d; this.i = d.strokes.length; this.stuck = this.o.stick; this.fit(); this.g.drawImage(this.base, 0, 0); }
    play(d) {
      this.stop();
      const tok = this.token; this.d = d; this.i = 0; this.stuck = false; this.sparks = [];
      this.fit();
      if (calm() || !this.total) { this.show(d); return Promise.resolve(true); }
      const dur = clamp(this.total / this.dpr / this.o.pxPerSec * 1000, this.o.min, this.o.max);
      const speed = this.total / dur, pause = Math.min(110, 2400 / Math.max(1, this.paths.length));
      let dist = 0, wait = 0, last = performance.now(), from = this.paths[0][0], stickT = 0;
      return new Promise(res => {
        const step = now => {
          if (tok !== this.token) return res(false);
          const dt = Math.min(120, now - last); last = now;
          const g = this.g;
          g.clearRect(0, 0, this.cw, this.ch);
          if (this.i < this.paths.length) {
            if (wait > 0) wait -= dt; else dist += speed * dt;
            while (this.i < this.paths.length && dist >= this.lens[this.i].at(-1)) {
              sugarStroke(this.bg, this.paths[this.i], this.w);
              from = this.paths[this.i].at(-1); this.i++; dist = 0; wait = pause;
            }
            g.drawImage(this.base, 0, 0);
            if (this.i < this.paths.length) {
              if (wait > 0) {
                const to = this.paths[this.i][0], t = 1 - wait / pause;
                this.ladle(g, [from[0] + (to[0] - from[0]) * t, from[1] + (to[1] - from[1]) * t], true);
              } else {
                const { pts, at } = this.partial(this.i, dist);
                sugarStroke(g, pts, this.w); this.ladle(g, at, false); this.emit(at, dt);
              }
            } else stickT = now;
          } else {
            const t = this.o.stick ? Math.min(1, (now - stickT) / 700) : 1;
            g.drawImage(this.base, 0, 0);
            if (this.o.stick) this.stick(g, 1 - Math.pow(1 - t, 3));
            if (t >= 1 && !this.sparks.length) {
              this.stuck = this.o.stick; if (this.stuck) this.stick(this.bg, 1);
              this.raf = 0; return res(true);
            }
          }
          this.drawSparks(g, dt);
          this.raf = requestAnimationFrame(step);
        };
        this.raf = requestAnimationFrame(step);
      });
    }
    partial(i, dist) {
      const p = this.paths[i], L = this.lens[i];
      let j = 0; while (j < L.length - 2 && L[j + 1] <= dist) j++;
      const f = L[j + 1] > L[j] ? (dist - L[j]) / (L[j + 1] - L[j]) : 0;
      const at = [p[j][0] + (p[j + 1][0] - p[j][0]) * f, p[j][1] + (p[j + 1][1] - p[j][1]) * f];
      return { pts: [...p.slice(0, j + 1), at], at };
    }
    ladle(g, [x, y], lifted) {
      const u = this.dpr, w = this.w, lx = x + 7 * u, ly = y - (lifted ? 38 : 28) * u;
      g.save(); g.lineCap = "round";
      if (!lifted) {
        g.strokeStyle = "rgba(244,176,76,.9)"; g.lineWidth = Math.max(1, w * .35);
        g.beginPath(); g.moveTo(lx - 3 * u, ly + 5 * u);
        g.quadraticCurveTo(x + Math.sin(performance.now() / 90) * 1.6 * u, (y + ly) / 2, x, y); g.stroke();
        const rg = g.createRadialGradient(x, y, 0, x, y, w * 3.2);
        rg.addColorStop(0, "rgba(255,224,150,.9)"); rg.addColorStop(1, "rgba(255,160,40,0)");
        g.fillStyle = rg; g.beginPath(); g.arc(x, y, w * 3.2, 0, 7); g.fill();
      }
      g.shadowColor = "rgba(0,0,0,.45)"; g.shadowBlur = 8 * u; g.shadowOffsetY = 6 * u;
      g.strokeStyle = "#5a3418"; g.lineWidth = 3.2 * u;
      g.beginPath(); g.moveTo(lx + 6 * u, ly - 3 * u); g.lineTo(lx + 38 * u, ly - 34 * u); g.stroke();
      const cg = g.createLinearGradient(lx - 10 * u, ly - 7 * u, lx + 10 * u, ly + 7 * u);
      cg.addColorStop(0, "#f3c286"); cg.addColorStop(.5, "#b9692b"); cg.addColorStop(1, "#6a3512");
      g.fillStyle = cg; g.beginPath(); g.ellipse(lx, ly, 11 * u, 7 * u, -.5, 0, 7); g.fill();
      g.shadowColor = "transparent";
      g.fillStyle = "#f0a23a"; g.beginPath(); g.ellipse(lx - 1 * u, ly - 1 * u, 7 * u, 3.8 * u, -.5, 0, 7); g.fill();
      g.fillStyle = "rgba(255,246,220,.85)"; g.beginPath(); g.ellipse(lx - 3 * u, ly - 2.4 * u, 2.4 * u, 1 * u, -.5, 0, 7); g.fill();
      g.restore();
    }
    emit([x, y], dt) {
      if (Math.random() > dt / 45) return;
      const u = this.dpr;
      this.sparks.push({ x, y, vx: (Math.random() - .5) * .06 * u, vy: -(.02 + Math.random() * .05) * u, t: 0, max: 500 + Math.random() * 600, r: (.7 + Math.random()) * u });
    }
    drawSparks(g, dt) {
      this.sparks = this.sparks.filter(s => (s.t += dt) < s.max);
      for (const s of this.sparks) {
        s.x += s.vx * dt; s.y += s.vy * dt;
        g.fillStyle = `rgba(255,216,140,${(1 - s.t / s.max) * .9})`;
        g.beginPath(); g.arc(s.x, s.y, s.r, 0, 7); g.fill();
      }
    }
    // 竹签：最后从下方插上来
    stick(g, t) {
      const u = this.dpr, x = this.cw / 2, w = 6 * u;
      const top = this.oy + this.d.h * this.s * (this.d.stickAt || this.o.stickAt), y = this.ch + 10 * u + (top - this.ch - 10 * u) * t;
      g.save();
      g.shadowColor = "rgba(0,0,0,.45)"; g.shadowBlur = 6 * u; g.shadowOffsetX = 2 * u; g.shadowOffsetY = 3 * u;
      const sg = g.createLinearGradient(x - w / 2, 0, x + w / 2, 0);
      sg.addColorStop(0, "#c7a25c"); sg.addColorStop(.45, "#f2dfaa"); sg.addColorStop(1, "#a9853f");
      g.fillStyle = sg; g.beginPath();
      if (g.roundRect) g.roundRect(x - w / 2, y, w, this.ch - y + 20 * u, w / 2); else g.rect(x - w / 2, y, w, this.ch - y + 20 * u);
      g.fill();
      g.shadowColor = "transparent"; g.fillStyle = "rgba(110,80,30,.45)";
      for (let k = y + 40 * u; k < this.ch; k += 46 * u) g.fillRect(x - w / 2, k, w, 1.5 * u);
      g.restore();
    }
  }

  // 一次性静态渲染到离屏画布（屏幕页待机画面）
  function still(d, w, h, o = {}) {
    const c = document.createElement("canvas"); c.width = w; c.height = h;
    new Painter(c, { fixed: true, ...o }).show(d);
    return c;
  }

  return { extract, fromPaths, fish, Painter, still, get reduce() { return calm(); } };
})();
