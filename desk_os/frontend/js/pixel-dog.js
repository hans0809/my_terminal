/**
 * Desk OS — 像素小狗（电子宠物）
 * 精灵基于 Kipperfalcon「Cute Doggy 16x16」(CC-BY 4.0)，镜像 · 墨水四阶灰
 *
 * 睡 / 昏 / 醒 / 打字 / 兴奋
 * 按键积精力，太久没键或凌晨入睡
 * 鼠标靠近摇尾巴；点击屏幕丢骨头，跑去叼回来吃
 * 闲下来沿底边走两步；上电先睡后醒
 * 天气缩团 / 机器负载喘气 / 偶尔冒字
 */

(function () {
  const canvas = document.getElementById('pixel-dog-canvas');
  const boneEl = document.getElementById('pixel-bone');
  const crtMonitor = document.getElementById('crt-monitor');
  const crtScreen = document.getElementById('crt-screen');
  const dogWrap = document.querySelector('.pixel-dog');
  const sayEl = document.getElementById('pixel-dog-say');
  const eatBarEl = document.getElementById('pixel-dog-eat');
  if (!canvas) return;

  const ctx = canvas.getContext('2d');
  const W = 16;
  const H = 16;
  const SCALE = 6;

  canvas.width = W * SCALE;
  canvas.height = H * SCALE;
  ctx.imageSmoothingEnabled = false;

  const AWAKE = [
    '/assets/dog-0.png',
    '/assets/dog-1.png',
    '/assets/dog-2.png',
  ];
  const SLEEP = [
    '/assets/dog-sleep-0.png',
    '/assets/dog-sleep-1.png',
  ];

  const DROWSY_AFTER = 90 * 1000;
  const SLEEP_AFTER = 4 * 60 * 1000;
  const NIGHT_END = 7;
  const NIGHT_WAKE_MS = 8000;
  const ENERGY_PER_KEY = 3.2;
  const ENERGY_DECAY_PER_SEC = 0.14;
  const EXCITED_WINDOW = 4000;
  const EXCITED_KEYS = 10;
  const STRETCH_MS = 720;
  const HOT_TEMP = 29;
  const COLD_TEMP = 5;
  const CHIP_HOT = 68;
  const QUOTA_WARN = 80;

  const INK = [
    [28, 27, 23],
    [74, 73, 68],
    [154, 150, 140],
  ];

  const BONE_STAGES = [
    [
      '  11  11      11  11  ',
      ' 13311331    13311331 ',
      '1322222223332222222231',
      '1222222222222222222221',
      '1322222222222222222231',
      ' 12211221    12211221 ',
      '  11  11      11  11  ',
    ],
    [
      '11        11  11  ',
      '1133      13311331',
      '222333322222222231',
      '222222222222222221',
      '222222222222222231',
      '1122      12211221',
      '11        11  11  ',
    ],
    [
      '11    11  11  ',
      '1133  13311331',
      '22333222222231',
      '22222222222221',
      '22222222222231',
      '1122  12211221',
      '11    11  11  ',
    ],
    [
      '  11  11  ',
      ' 13311331 ',
      '1322222231',
      '1222222221',
      '1322222231',
      ' 12211221 ',
      '  11  11  ',
    ],
    [
      '  11  ',
      ' 1331 ',
      '132231',
      '122221',
      '132231',
      ' 1221 ',
      '  11  ',
    ],
  ];
  const BONE_TONE = {
    1: [28, 27, 23],
    2: [74, 73, 68],
    3: [154, 150, 140],
  };
  const BONE_SCALE = 3;
  const TREAT_GRID = 4;
  const TREAT_SPEED = 0.26;
  const WANDER_SPEED = 0.09;
  const EAT_MS = 3 * 60 * 1000;
  const CHEW_MS = 820;
  const EAT_BAR_LEN = 8;

  const awakeImgs = [];
  const sleepImgs = [];
  let loaded = 0;
  const totalFrames = AWAKE.length + SLEEP.length;

  function posterizeToInk(img) {
    const sheet = document.createElement('canvas');
    sheet.width = W * SCALE;
    sheet.height = H * SCALE;
    const sctx = sheet.getContext('2d');
    sctx.imageSmoothingEnabled = false;
    sctx.drawImage(img, 0, 0, sheet.width, sheet.height);
    const imageData = sctx.getImageData(0, 0, sheet.width, sheet.height);
    const d = imageData.data;
    for (let i = 0; i < d.length; i += 4) {
      if (d[i + 3] < 18) {
        d[i + 3] = 0;
        continue;
      }
      const y = d[i] * 0.2126 + d[i + 1] * 0.7152 + d[i + 2] * 0.0722;
      const c = y < 92 ? INK[0] : y < 168 ? INK[1] : INK[2];
      d[i] = c[0];
      d[i + 1] = c[1];
      d[i + 2] = c[2];
      d[i + 3] = 255;
    }
    sctx.putImageData(imageData, 0, 0);
    return sheet;
  }

  let pose = 'idle';
  let typePulse = 0;
  let wagTimer = 0;
  let lastTs = 0;
  let running = true;
  let bounceY = 0;
  let lastPulse = 0;
  let energy = 58;
  let lastKeyAt = 0;
  const bornAt = performance.now();
  let keyTimes = [];
  let petting = false;
  let stretchUntil = 0;
  let wasNight = isNight();
  let sleepTick = 0;
  let sleepTail = 0;
  let sys = (window.DeskOS && window.DeskOS.system) || null;
  let debugClimate = null;
  let debugLoad = null;
  let pantTick = 0;
  let pantOn = false;
  let nextHeatStretch = 0;
  let sayUntil = 0;
  let nextSayAt = performance.now() + 9000 + Math.random() * 8000;
  let lastSayPose = '';
  let treat = null;
  let treatBusy = false;
  let boneStage = -1;
  let eatBarFilled = -1;
  let dogX = 0;
  let faceRight = false;
  let runTick = 0;
  let eatDip = 0;
  let booting = !!(crtMonitor && crtMonitor.classList.contains('is-booting'));
  let wandering = false;
  let wanderTarget = 0;
  let nextWanderAt = performance.now() + 8000 + Math.random() * 6000;

  function loadSheet(list, bucket) {
    list.forEach((src, i) => {
      const img = new Image();
      img.onload = () => {
        bucket[i] = posterizeToInk(img);
        loaded += 1;
        if (loaded === totalFrames) render();
      };
      img.src = src;
    });
  }
  loadSheet(AWAKE, awakeImgs);
  loadSheet(SLEEP, sleepImgs);

  function snap(v, g) {
    return Math.round(v / g) * g;
  }

  function paintBone(stage) {
    if (!boneEl) return;
    const idx = Math.max(0, Math.min(BONE_STAGES.length - 1, stage | 0));
    const map = BONE_STAGES[idx];
    boneStage = idx;
    const bw = map[0].length;
    const bh = map.length;
    const src = document.createElement('canvas');
    src.width = bw;
    src.height = bh;
    const sctx = src.getContext('2d');
    const pix = sctx.createImageData(bw, bh);
    const d = pix.data;
    for (let y = 0; y < bh; y += 1) {
      const row = map[y];
      for (let x = 0; x < bw; x += 1) {
        const tone = BONE_TONE[row[x]];
        if (!tone) continue;
        const i = (y * bw + x) * 4;
        d[i] = tone[0];
        d[i + 1] = tone[1];
        d[i + 2] = tone[2];
        d[i + 3] = 255;
      }
    }
    sctx.putImageData(pix, 0, 0);
    const sc = treat && treat.phase === 'eat' ? 2 : BONE_SCALE;
    boneEl.width = bw * sc;
    boneEl.height = bh * sc;
    const bctx = boneEl.getContext('2d');
    bctx.imageSmoothingEnabled = false;
    bctx.clearRect(0, 0, boneEl.width, boneEl.height);
    bctx.drawImage(src, 0, 0, boneEl.width, boneEl.height);
    boneEl.style.width = `${boneEl.width}px`;
    boneEl.style.height = `${boneEl.height}px`;
  }
  paintBone(0);

  function boneStageFor(p) {
    if (p < 0.16) return 0;
    if (p < 0.38) return 1;
    if (p < 0.62) return 2;
    if (p < 0.84) return 3;
    return 4;
  }

  function updateEatBar(p) {
    if (!eatBarEl) return;
    const remain = Math.max(0, Math.min(1, 1 - p));
    const filled = Math.round(remain * EAT_BAR_LEN);
    if (filled === eatBarFilled) return;
    eatBarFilled = filled;
    const full = '█'.repeat(filled);
    const empty = '·'.repeat(EAT_BAR_LEN - filled);
    eatBarEl.innerHTML =
      `<span class="bar-full">${full}</span><span class="bar-empty">${empty}</span>`;
  }

  function applyDogX() {
    if (!dogWrap) return;
    dogWrap.style.transform = `translateX(${snap(dogX, TREAT_GRID)}px)`;
  }

  function placeBone() {
    if (!boneEl || !treat) return;
    boneEl.style.left = `${snap(treat.x, 2)}px`;
    boneEl.style.top = `${snap(treat.y, 2)}px`;
  }

  function boneSize() {
    return {
      w: boneEl ? boneEl.width : 66,
      h: boneEl ? boneEl.height : 21,
    };
  }

  function screenRect() {
    return crtScreen.getBoundingClientRect();
  }

  function dogRect() {
    return dogWrap.getBoundingClientRect();
  }

  function groundY(bh) {
    const sr = screenRect();
    const dr = dogRect();
    return snap(dr.bottom - sr.top - bh, TREAT_GRID);
  }

  function blurt(text, t, ms) {
    if (sayEl) sayEl.textContent = text;
    sayUntil = t + (ms || 1400);
    nextSayAt = t + 10000 + Math.random() * 8000;
    if (dogWrap) {
      dogWrap.classList.remove('pixel-dog--say');
      void dogWrap.offsetWidth;
    }
  }

  function endTreat() {
    treat = null;
    treatBusy = false;
    dogX = 0;
    faceRight = false;
    runTick = 0;
    bounceY = 0;
    eatDip = 0;
    eatBarFilled = -1;
    wandering = false;
    applyDogX();
    if (boneEl) boneEl.classList.remove('is-on');
    paintBone(0);
    if (eatBarEl) eatBarEl.innerHTML = '';
  }

  function snoutX() {
    const sr = screenRect();
    const dr = dogRect();
    const ox = faceRight ? dr.width * 0.74 : dr.width * 0.10;
    return dr.left - sr.left + ox;
  }

  function carryBone() {
    if (!treat) return;
    const { w, h } = boneSize();
    const sr = screenRect();
    const dr = dogRect();
    const mx = snoutX();
    const my = dr.top - sr.top + dr.height * 0.40;
    const bite = Math.min(10, Math.max(5, w * 0.18));
    treat.x = faceRight ? mx - bite : mx - w + bite;
    treat.y = my - h * 0.52;
    if (boneEl) boneEl.style.zIndex = '4';
    placeBone();
  }

  function pinBoneToGround() {
    if (!treat || !boneEl) return;
    const { w, h } = boneSize();
    const parent = boneEl.offsetParent || crtScreen;
    const pr = parent.getBoundingClientRect();
    const dr = dogRect();
    const g = snap(dr.bottom - pr.top - h, TREAT_GRID);
    treat.ground = g;
    if (treat.phase === 'eat') {
      const mx = dr.left - pr.left + dr.width * (1.5 / 16);
      const my = dr.top - pr.top + dr.height * (8.2 / 16);
      treat.x = snap(mx - w * 0.52, 2);
      treat.y = snap(Math.min(g, my - h * 0.28), 2);
    } else {
      treat.y = g;
      const cx = treat.anchorX != null ? treat.anchorX : treat.x + w / 2;
      treat.anchorX = cx;
      treat.x = cx - w / 2;
    }
    boneEl.style.zIndex = treat.phase === 'eat' ? '2' : '4';
    placeBone();
  }

  function wanderRange() {
    if (!crtScreen || !dogWrap) return { min: -72, max: 0 };
    const sr = screenRect();
    const dr = dogRect();
    if (!sr.width) return { min: -72, max: 0 };
    const homeLeft = dr.left - dogX;
    const room = homeLeft - sr.left - 18;
    const min = -snap(Math.max(48, Math.min(room, sr.width * 0.52)), TREAT_GRID);
    return { min, max: 0 };
  }

  function walkToward(target, dt, speed) {
    const dx = target - dogX;
    faceRight = dx > 4;
    if (dx < -4) faceRight = false;
    if (Math.abs(dx) <= 6) {
      dogX = target;
      applyDogX();
      bounceY = 0;
      faceRight = dogX < -12;
      pose = 'idle';
      return true;
    }
    const step = Math.sign(dx) * Math.min(Math.abs(dx), (speed || WANDER_SPEED) * dt);
    dogX += step;
    applyDogX();
    runTick += dt;
    if (runTick > 120) {
      runTick = 0;
      typePulse += 1;
    }
    bounceY = typePulse % 2 === 0 ? -4 : 0;
    pose = 'run';
    return false;
  }

  function pickWanderTarget() {
    const range = wanderRange();
    const span = range.max - range.min;
    if (span < 24) return 0;
    if (Math.random() < 0.28) return 0;
    const t = range.min + Math.random() * span;
    return snap(t, TREAT_GRID * 2);
  }

  function tickWander(t, dt, opts) {
    const goHome = !!(opts && opts.goHome);
    const blocked = !!(opts && opts.blocked);
    if (blocked) {
      wandering = false;
      return false;
    }
    if (goHome) {
      wandering = false;
      if (Math.abs(dogX) > 6) {
        walkToward(0, dt, WANDER_SPEED);
        return true;
      }
      dogX = 0;
      faceRight = false;
      bounceY = 0;
      applyDogX();
      return false;
    }
    if (wandering) {
      if (walkToward(wanderTarget, dt, WANDER_SPEED)) {
        wandering = false;
        nextWanderAt = t + 5000 + Math.random() * 11000;
        if (Math.random() < 0.45) {
          pose = 'wag';
          wagTimer = 0;
        }
      }
      return true;
    }
    if (t < nextWanderAt || energy < 32) return false;
    const dest = pickWanderTarget();
    if (Math.abs(dest - dogX) < 20) {
      nextWanderAt = t + 4000 + Math.random() * 6000;
      return false;
    }
    wandering = true;
    wanderTarget = dest;
    walkToward(wanderTarget, dt, WANDER_SPEED);
    return true;
  }

  function bootStart() {
    booting = true;
    wandering = false;
    if (treat) endTreat();
    dogX = 0;
    faceRight = false;
    bounceY = 0;
    applyDogX();
    pose = 'sleep';
    sleepTail = 0;
    const t = performance.now();
    applyChrome(t);
    render();
  }

  function bootEnd() {
    const t = performance.now();
    booting = false;
    wake(t);
    pose = 'idle';
    lastKeyAt = t - 1200;
    energy = Math.max(energy, 48);
    nextWanderAt = t + 3500 + Math.random() * 5000;
    applyChrome(t);
    render();
  }

  function bootCancel() {
    booting = false;
    wandering = false;
  }

  function dropTreat(clientX, clientY) {
    if (booting || treatBusy || treat) return;
    if (!isOn() || !crtScreen || !boneEl) return;
    const sr = screenRect();
    const { w, h } = boneSize();
    const ground = groundY(h);
    let x = clientX - sr.left - w / 2;
    x = Math.max(8, Math.min(sr.width - w - 8, x));
    let y = clientY - sr.top - h / 3;
    y = Math.max(10, Math.min(ground - 12, y));
    treatBusy = true;
    boneStage = -1;
    eatBarFilled = -1;
    paintBone(0);
    treat = {
      phase: 'fall',
      x: snap(x, TREAT_GRID),
      y: snap(y, TREAT_GRID),
      vy: 0.04,
      ground,
      bounced: false,
      phaseAt: performance.now(),
    };
    boneEl.classList.add('is-on');
    placeBone();
  }

  function tickTreat(t, dt) {
    if (!treat) return false;

    if (treat.phase === 'fall') {
      treat.vy += 0.0017 * dt;
      treat.y += treat.vy * dt;
      if (treat.y >= treat.ground) {
        treat.y = treat.ground;
        if (!treat.bounced && treat.vy > 0.32) {
          treat.vy = -treat.vy * 0.26;
          treat.bounced = true;
        } else {
          treat.y = treat.ground;
          treat.vy = 0;
          treat.anchorX = treat.x + boneSize().w / 2;
          if (pose === 'sleep') {
            wake(t);
            treat.phase = 'wake';
          } else {
            treat.phase = 'run';
            blurt('!', t, 900);
          }
          treat.phaseAt = t;
        }
      }
      placeBone();
      return true;
    }

    if (treat.phase === 'wake') {
      pose = 'idle';
      if (t >= stretchUntil) {
        treat.phase = 'run';
        treat.phaseAt = t;
        blurt('!', t, 900);
      }
      return true;
    }

    if (treat.phase === 'run' || treat.phase === 'back') {
      pose = 'run';
      eatDip = 0;
      runTick += dt;
      if (runTick > 90) {
        runTick = 0;
        typePulse += 1;
      }
      bounceY = typePulse % 2 === 0 ? -6 : 0;

      const goingHome = treat.phase === 'back';
      const target = goingHome
        ? 0
        : (treat.anchorX != null ? treat.anchorX : treat.x + boneSize().w * 0.5);
      const here = goingHome ? dogX : snoutX();
      const dx = target - here;
      faceRight = dx > 4;
      if (goingHome) faceRight = dogX < -4;

      if (Math.abs(dx) <= (goingHome ? 6 : 12)) {
        if (goingHome) {
          dogX = 0;
          faceRight = false;
          bounceY = 0;
          applyDogX();
          const { w } = boneSize();
          const sr = screenRect();
          const dr = dogRect();
          treat.anchorX = dr.left - sr.left + dr.width * 0.06 + w * 0.42;
          treat.phase = 'eat';
          treat.phaseAt = t;
          pose = 'eat';
          updateEatBar(0);
          paintBone(0);
          pinBoneToGround();
          blurt('nom', t, 1600);
        } else {
          treat.phase = 'grab';
          treat.phaseAt = t;
          pose = 'grab';
          bounceY = 0;
          carryBone();
          blurt(Math.random() < 0.5 ? 'woof' : '!', t, 800);
          if (!treat.noted && window.DeskLog) {
            treat.noted = true;
            window.DeskLog.note('dog-bone');
          }
        }
        return true;
      }

      const step = Math.sign(dx) * Math.min(Math.abs(dx), TREAT_SPEED * dt);
      dogX += step;
      applyDogX();
      if (goingHome) carryBone();
      return true;
    }

    if (treat.phase === 'grab') {
      pose = 'grab';
      bounceY = 0;
      typePulse = 1;
      carryBone();
      if (t - treat.phaseAt > 220) {
        treat.phase = 'back';
        treat.phaseAt = t;
      }
      return true;
    }

    if (treat.phase === 'eat') {
      pose = 'eat';
      faceRight = false;
      eatDip = 1;
      bounceY = 0;
      const elapsed = t - treat.phaseAt;
      const p = Math.max(0, Math.min(1, elapsed / EAT_MS));
      const chewPhase = (elapsed % CHEW_MS) / CHEW_MS;
      typePulse = chewPhase < 0.36 ? 1 : 0;
      lastKeyAt = t;
      updateEatBar(p);
      const stage = boneStageFor(p);
      if (stage !== boneStage) paintBone(stage);
      if (elapsed > EAT_MS) {
        energy = Math.min(100, energy + 24);
        lastKeyAt = t;
        endTreat();
        return true;
      }
      if (p > 0.97) {
        if (boneEl) boneEl.classList.remove('is-on');
      } else {
        if (boneEl) boneEl.classList.add('is-on');
        pinBoneToGround();
      }
      if (Math.floor(elapsed / CHEW_MS) > 0
        && Math.floor(elapsed / CHEW_MS) % 12 === 0
        && chewPhase < 0.36
        && t > sayUntil) {
        blurt('nom', t, 1600);
      }
      return true;
    }

    return true;
  }

  function isOn() {
    return crtMonitor && crtMonitor.classList.contains('is-on');
  }

  function isNight() {
    return new Date().getHours() < NIGHT_END;
  }

  function idleFor(t) {
    return lastKeyAt ? t - lastKeyAt : t - bornAt;
  }

  function burstCount(t) {
    const cutoff = t - EXCITED_WINDOW;
    while (keyTimes.length && keyTimes[0] < cutoff) keyTimes.shift();
    return keyTimes.length;
  }

  function isExcited(t) {
    return burstCount(t) >= EXCITED_KEYS;
  }

  function onSystem(data) {
    sys = data || null;
  }

  function climateKind() {
    if (debugClimate) return debugClimate;
    const w = sys && sys.weather;
    if (!w || !w.available) return 'fair';
    const d = String(w.description || '').toLowerCase();
    const temp = w.temp_c;
    if (/rain|drizzle|shower|thunder/.test(d)) return 'rain';
    if (/snow/.test(d)) return 'snow';
    if (typeof temp === 'number' && temp >= HOT_TEMP) return 'hot';
    if (typeof temp === 'number' && temp <= COLD_TEMP) return 'cold';
    if (/fog/.test(d)) return 'fog';
    return 'fair';
  }

  function loadLevel() {
    if (typeof debugLoad === 'number') return debugLoad;
    if (!sys) return 0;
    const cpu = Number(sys.cpu) || 0;
    const gpu = sys.gpu && sys.gpu.available ? Number(sys.gpu.usage) || 0 : 0;
    return Math.max(cpu, gpu) / 100;
  }

  function chipTemp() {
    const gpu = sys && sys.gpu;
    if (gpu && gpu.available && typeof gpu.temp_c === 'number') return gpu.temp_c;
    if (sys && typeof sys.cpu_temp_c === 'number') return sys.cpu_temp_c;
    return null;
  }

  function quotaPct() {
    const c = sys && sys.cursor;
    if (!c || !c.available) return 0;
    return Math.max(Number(c.auto_used_pct) || 0, Number(c.api_used_pct) || 0);
  }

  function quotaKind() {
    const c = sys && sys.cursor;
    if (!c || !c.available) return null;
    const cur = Number(c.auto_used_pct) || 0;
    const oth = Number(c.api_used_pct) || 0;
    if (cur < QUOTA_WARN && oth < QUOTA_WARN) return null;
    return cur >= oth ? { key: 'cur', pct: cur } : { key: 'oth', pct: oth };
  }

  function machineHot() {
    const t = chipTemp();
    if (t != null) return t >= CHIP_HOT;
    return loadLevel() >= 0.62;
  }

  function machineIdle() {
    return loadLevel() > 0 && loadLevel() < 0.12;
  }

  function shouldPant() {
    return machineHot();
  }

  function thresholds() {
    let drowsy = DROWSY_AFTER;
    let sleep = SLEEP_AFTER;
    const kind = climateKind();
    if (machineIdle()) {
      drowsy *= 0.55;
      sleep *= 0.7;
    }
    if (machineHot()) {
      drowsy *= 1.4;
      sleep *= 1.25;
    }
    if (kind === 'rain' || kind === 'cold') {
      drowsy *= 0.72;
      sleep *= 0.78;
    }
    if (kind === 'snow') drowsy *= 1.12;
    return { drowsy, sleep };
  }

  function setClass(name, on) {
    if (dogWrap) dogWrap.classList.toggle(name, !!on);
  }

  function applyChrome(t) {
    const kind = climateKind();
    const busy = pose === 'typing' || pose === 'excited' || pose === 'pant'
      || pose === 'run' || pose === 'eat' || pose === 'grab';
    setClass('pixel-dog--sleep', pose === 'sleep');
    setClass('pixel-dog--drowsy', pose === 'drowsy');
    setClass('pixel-dog--excited', pose === 'excited');
    setClass('pixel-dog--stretch', t < stretchUntil && !treat);
    setClass('pixel-dog--pant', pose === 'pant');
    setClass('pixel-dog--run', pose === 'run');
    setClass('pixel-dog--eat', false);
    setClass('pixel-dog--eating', pose === 'eat');
    setClass('pixel-dog--rain', kind === 'rain');
    setClass('pixel-dog--snow', kind === 'snow');
    setClass('pixel-dog--fog', kind === 'fog');
    setClass('pixel-dog--huddle', (kind === 'rain' || kind === 'cold') && !busy && !treat && t >= stretchUntil);
    setClass('pixel-dog--fluff', kind === 'snow' && !busy && !treat && pose !== 'sleep' && t >= stretchUntil);
    setClass('pixel-dog--hot', kind === 'hot' && !busy && !treat && pose !== 'sleep' && t >= stretchUntil);
    setClass('pixel-dog--quota', quotaPct() >= QUOTA_WARN && pose !== 'sleep');
    setClass('pixel-dog--say', t < sayUntil && pose !== 'sleep');
    if (pose !== 'typing' && pose !== 'excited') {
      setClass('pixel-dog--bounce', false);
    }
  }

  function drawEat() {
    const loaf = sleepImgs[0];
    const idle = awakeImgs[0];
    if (!loaf) return;
    const s = SCALE;
    const bw = W * s;
    const bh = H * s;
    const open = typePulse % 2 === 1;
    const settle = s;

    ctx.imageSmoothingEnabled = false;
    ctx.clearRect(0, 0, bw, bh);
    ctx.save();
    if (faceRight) {
      ctx.translate(bw, 0);
      ctx.scale(-1, 1);
    }
    ctx.drawImage(loaf, 0, 0, bw, bh, 0, settle, bw, bh);
    if (idle) {
      ctx.drawImage(
        idle,
        3 * s, 3 * s, 4 * s, 1 * s,
        3 * s, 5 * s + settle, 4 * s, 1 * s
      );
    }
    if (open) {
      ctx.drawImage(
        loaf,
        0, 7 * s, 7 * s, 1 * s,
        0, 8 * s + settle, 7 * s, 1 * s
      );
    }
    ctx.restore();
  }

  function drawImg(img) {
    if (!img) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.save();
    if (faceRight) {
      ctx.translate(canvas.width, 0);
      ctx.scale(-1, 1);
    }
    ctx.translate(0, bounceY);
    ctx.drawImage(img, 0, 0, W * SCALE, H * SCALE);
    ctx.restore();
  }

  function awakeFrame() {
    if (pose === 'eat' || pose === 'grab') {
      return awakeImgs[0];
    }
    if (pose === 'typing' || pose === 'excited' || pose === 'run') {
      return awakeImgs[typePulse % 2 === 0 ? 2 : 1];
    }
    if (pose === 'pant') return awakeImgs[pantOn ? 2 : 1];
    if (pose === 'wag' || pose === 'pet') return awakeImgs[1];
    return awakeImgs[0];
  }

  function render() {
    if (pose === 'sleep') {
      bounceY = 0;
      drawImg(sleepImgs[sleepTail]);
      return;
    }
    if (pose === 'eat' || pose === 'grab') {
      bounceY = 0;
      if (pose === 'eat') drawEat();
      else drawImg(awakeImgs[0]);
      return;
    }
    if (pose !== 'typing' && pose !== 'excited' && pose !== 'run') {
      bounceY = 0;
    }
    drawImg(awakeFrame());
  }

  function wake(t) {
    if (pose === 'sleep') stretchUntil = t + STRETCH_MS;
    wagTimer = 0;
  }

  function poke() {
    if (!isOn() || booting) return;
    const t = performance.now();
    keyTimes.push(t);
    lastKeyAt = t;
    energy = Math.min(100, energy + ENERGY_PER_KEY);
    typePulse += 1;
    const hot = isExcited(t);
    if (pose === 'sleep') wake(t);
    if (treat) {
      applyChrome(t);
      render();
      return;
    }
    pose = hot ? 'excited' : 'typing';
    const extra = machineHot() ? -3 : 0;
    bounceY = typePulse % 2 === 0 ? (hot ? -14 : -10) + extra : 0;
    if (dogWrap) {
      dogWrap.classList.remove('pixel-dog--bounce');
      void dogWrap.offsetWidth;
      dogWrap.classList.add('pixel-dog--bounce');
    }
    applyChrome(t);
    render();
  }

  function pokeTimes(n) {
    const count = Math.max(0, Math.min(Number(n) || 0, 12));
    for (let i = 0; i < count; i += 1) poke();
  }

  function onPulse(pulse) {
    const next = Number(pulse) || 0;
    if (next <= lastPulse) return;
    const delta = Math.min(next - lastPulse, 8);
    lastPulse = next;
    pokeTimes(delta);
  }

  function pickSay() {
    const kind = climateKind();
    const q = quotaKind();
    const cpu = sys ? Math.round(Number(sys.cpu) || 0) : 0;
    const temp = chipTemp();

    if (pose === 'drowsy') return '...';
    if (q && Math.random() < 0.72) return `${q.key} ${q.pct}`;
    if (temp != null && temp >= CHIP_HOT && Math.random() < 0.55) {
      return Math.random() < 0.45 ? `tmp ${temp}` : 'hff';
    }
    if (cpu >= 85 && Math.random() < 0.5) return `cpu ${cpu}`;
    if (kind === 'hot' || machineHot()) return Math.random() < 0.55 ? 'hff' : '...';
    if (kind === 'rain') return '...';
    if (pose === 'pet' || pose === 'wag' || pose === 'pant') {
      return Math.random() < 0.6 ? 'woof' : '...';
    }
    return Math.random() < 0.42 ? 'woof' : '...';
  }

  function maybeSay(t) {
    if (treat || booting || wandering) return;
    if (pose === 'sleep' || pose === 'typing' || pose === 'excited' || pose === 'run') return;
    if (t < nextSayAt) return;
    const anxious = quotaPct() >= QUOTA_WARN;
    nextSayAt = t + (anxious ? 9000 : 16000) + Math.random() * (anxious ? 10000 : 26000);
    if (sayEl) sayEl.textContent = pickSay();
    sayUntil = t + (anxious ? 2200 : 1600);
    if (dogWrap) {
      dogWrap.classList.remove('pixel-dog--say');
      void dogWrap.offsetWidth;
    }
  }

  function syncSayGlyph() {
    if (!sayEl) return;
    if (pose === 'sleep') {
      if (lastSayPose !== 'sleep') sayEl.textContent = 'z';
    }
    lastSayPose = pose;
  }

  function choosePose(t, dt) {
    if (booting) {
      pose = 'sleep';
      dogX = 0;
      faceRight = false;
      applyDogX();
      return;
    }
    if (tickTreat(t, dt)) return;

    const night = isNight();
    const idle = idleFor(t);
    const kind = climateKind();
    const lim = thresholds();
    const decay = ENERGY_DECAY_PER_SEC
      * (machineIdle() ? 1.35 : 1)
      * (machineHot() ? 0.72 : 1)
      * (kind === 'rain' || kind === 'cold' ? 1.2 : 1);

    if (night !== wasNight) {
      wasNight = night;
      if (!night) {
        energy = Math.max(energy, 52);
        if (pose === 'sleep') stretchUntil = t + STRETCH_MS;
        lastKeyAt = t - 1500;
        pose = 'idle';
        return;
      }
    }

    if (idle > 2000) {
      energy = Math.max(0, energy - decay * (dt / 1000));
    }

    if (lastKeyAt && t - lastKeyAt < 600) {
      wandering = false;
      pose = isExcited(t) ? 'excited' : 'typing';
      return;
    }

    const wantSleep = (night && idle > NIGHT_WAKE_MS && !petting)
      || (night && !lastKeyAt)
      || (!night && idle > lim.sleep && energy < 28);
    const wantDrowsy = idle > lim.drowsy || energy < 22;
    const huddle = kind === 'rain' || kind === 'cold';

    if (tickWander(t, dt, {
      goHome: wantSleep || huddle,
      blocked: petting || t < stretchUntil || (wantDrowsy && !wandering),
    })) return;

    if (wantSleep && !petting) {
      pose = 'sleep';
      return;
    }

    if (petting) {
      if (pose === 'sleep') return;
      pose = 'pet';
      return;
    }

    if (kind === 'hot' && t >= nextHeatStretch && pose !== 'sleep') {
      stretchUntil = t + STRETCH_MS;
      nextHeatStretch = t + 8000 + Math.random() * 5000;
    }

    if (t < stretchUntil) {
      pose = 'idle';
      return;
    }

    if (pose === 'sleep') return;

    if (wantDrowsy) {
      pose = 'drowsy';
      return;
    }

    if (shouldPant() && idle > 700) {
      pantTick += dt;
      if (pantTick > 300) {
        pantTick = 0;
        pantOn = !pantOn;
      }
      pose = 'pant';
      return;
    }

    wagTimer += dt;
    if (pose === 'wag') {
      if (wagTimer > 420) {
        pose = 'idle';
        wagTimer = 0;
      }
      return;
    }

    let wagEvery = energy > 70 ? 1600 : 2600;
    if (machineHot()) wagEvery *= 0.62;
    if (quotaPct() >= QUOTA_WARN) wagEvery *= 0.7;
    if (kind === 'snow') wagEvery *= 0.8;
    if (kind === 'rain' || kind === 'cold') wagEvery *= 1.35;
    if (wagTimer > wagEvery) {
      pose = 'wag';
      wagTimer = 0;
      return;
    }

    pose = 'idle';
  }

  function tickSleep(dt) {
    sleepTick += dt;
    const interval = petting ? 360 : 1800;
    if (sleepTick < interval) return;
    sleepTick = 0;
    if (petting) {
      sleepTail = sleepTail ? 0 : 1;
      return;
    }
    sleepTail = sleepTail ? 0 : (Math.random() < 0.4 ? 1 : 0);
  }

  function tick(ts) {
    if (!running || loaded < totalFrames) return;

    const dt = lastTs ? ts - lastTs : 16;
    if (dt < 8) return;
    lastTs = ts;

    if (!isOn()) {
      if (treat) endTreat();
      wandering = false;
      bounceY = 0;
      drawImg(awakeImgs[0]);
      return;
    }

    choosePose(ts, dt);
    if (pose === 'sleep') tickSleep(dt);
    maybeSay(ts);
    syncSayGlyph();
    applyChrome(ts);
    render();
  }

  function loop(ts) {
    tick(ts);
    if (running) requestAnimationFrame(loop);
  }

  setInterval(() => {
    if (running) tick(performance.now());
  }, 50);

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' || e.key === 'F11') return;
    poke();
  });

  function updatePetting(x, y) {
    if (treat || booting || !dogWrap) {
      petting = false;
      return;
    }
    const r = dogWrap.getBoundingClientRect();
    const pad = Math.max(r.width, 72) * 0.7;
    petting = (
      x >= r.left - pad &&
      x <= r.right + pad &&
      y >= r.top - pad &&
      y <= r.bottom + pad
    );
  }

  const moveRoot = crtScreen || document;
  moveRoot.addEventListener('mousemove', (e) => {
    updatePetting(e.clientX, e.clientY);
  });
  moveRoot.addEventListener('mouseleave', () => {
    petting = false;
  });
  if (crtScreen) {
    crtScreen.addEventListener('click', (e) => {
      if (document.body.dataset.layer && document.body.dataset.layer !== 'status') return;
      if (treatBusy || treat) return;
      dropTreat(e.clientX, e.clientY);
    });
  }

  if (window.chrome && window.chrome.webview) {
    window.chrome.webview.addEventListener('message', (ev) => {
      const data = typeof ev.data === 'string' ? JSON.parse(ev.data) : ev.data;
      if (data && data.pulse != null) onPulse(data.pulse);
    });
  }

  function connectPulseStream() {
    const es = new EventSource('/api/key-stream');
    es.onmessage = (ev) => onPulse(ev.data);
    es.onerror = () => {
      es.close();
      setTimeout(connectPulseStream, 1200);
    };
  }
  connectPulseStream();

  if (isNight() || booting) pose = 'sleep';
  applyDogX();

  requestAnimationFrame(loop);

  window.PixelDog = {
    poke,
    pokeTimes,
    onPulse,
    onSystem,
    dropTreat,
    bootStart,
    bootEnd,
    bootCancel,
    pause: () => { running = false; },
    resume: () => { running = true; requestAnimationFrame(loop); },
    debug: () => ({
      pose,
      energy,
      climate: climateKind(),
      load: loadLevel(),
      temp: chipTemp(),
      quota: quotaPct(),
      treat: treat ? treat.phase : '',
      busy: treatBusy,
      wander: wandering,
      x: dogX,
      booting,
      saying: sayEl ? sayEl.textContent : '',
    }),
    debugSet: (opts) => {
      if (!opts) {
        debugClimate = null;
        debugLoad = null;
        return;
      }
      if (opts.climate != null) debugClimate = opts.climate || null;
      if (opts.load != null) debugLoad = opts.load;
      nextSayAt = performance.now();
    },
  };
})();
