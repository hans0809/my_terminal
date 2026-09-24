/**
 * Desk OS — 久坐起身
 * 间隔、起止时间和文案在 SIT 里改。文案里的 {时间} 会换成倒计时。
 */

(function () {
  const DEFAULTS = {
    interval: 45,
    start: '09:00',
    end: '18:00',
    phrase: '{时间}后起身',
    alert: '该起身活动一下了',
  };
  const SOON_MS = 5 * 60 * 1000;
  const STEP_MIN = 5;
  const INTERVAL_MAX = 240;
  const UNTIL_KEY = 'desk-os.sit.until';
  const CFG_KEY = 'desk-os.sit.cfg';

  const root = document.getElementById('sit-count');
  const fault = document.getElementById('sit-fault');
  const swarm = fault ? fault.querySelector('.sit-fault__swarm:not(.sit-fault__swarm--echo)') : null;
  const swarmEcho = fault ? fault.querySelector('.sit-fault__swarm--echo') : null;
  const giants = fault ? fault.querySelector('.sit-fault__giants') : null;
  const crt = document.getElementById('crt-monitor');
  const everyEl = document.getElementById('sit-every');
  const fromEl = document.getElementById('sit-from');
  const toEl = document.getElementById('sit-to');
  const phraseEl = document.getElementById('sit-phrase');
  const alertEl = document.getElementById('sit-alert');
  const preview = document.getElementById('sit-preview');
  const resetBtn = document.getElementById('sit-reset');
  if (!root || !fault || !swarm || !swarmEcho || !giants || !crt) return;

  const ROT = ['█', '▓', '#', '@', '□'];
  let cfg = loadCfg();
  let until = readUntil();
  let faulting = false;
  let builtPhrase = null;
  let swarmText = '';
  let swarmH = 0;

  function clampInt(raw, min, max, fallback) {
    const n = Math.round(Number(raw));
    if (!Number.isFinite(n)) return fallback;
    return Math.min(max, Math.max(min, n));
  }

  function clockToMin(clock) {
    const [h, m] = clock.split(':').map(Number);
    return h * 60 + m;
  }

  function tryClock(raw) {
    const s = String(raw || '').trim();
    let m = /^(\d{1,2}):(\d{2})$/.exec(s);
    if (!m && /^\d{3,4}$/.test(s)) {
      const p = s.padStart(4, '0');
      m = [null, p.slice(0, 2), p.slice(2)];
    }
    if (!m) return '';
    const h = Number(m[1]);
    const min = Number(m[2]);
    if (h > 23 || min > 59) return '';
    return `${String(h).padStart(2, '0')}:${String(min).padStart(2, '0')}`;
  }

  function normalize(raw) {
    const src = raw && typeof raw === 'object' ? raw : {};
    const start = tryClock(src.start) || DEFAULTS.start;
    const end = tryClock(src.end) || DEFAULTS.end;
    let phrase = String(src.phrase ?? DEFAULTS.phrase).slice(0, 40);
    let alert = String(src.alert ?? DEFAULTS.alert).slice(0, 40);
    if (!phrase.trim()) phrase = DEFAULTS.phrase;
    if (!alert.trim()) alert = DEFAULTS.alert;
    return {
      interval: clampInt(src.interval, 1, INTERVAL_MAX, DEFAULTS.interval),
      start,
      end,
      phrase,
      alert,
      startMin: clockToMin(start),
      endMin: clockToMin(end),
    };
  }

  function loadCfg() {
    try {
      return normalize(JSON.parse(localStorage.getItem(CFG_KEY) || '{}'));
    } catch {
      return normalize(DEFAULTS);
    }
  }

  function saveCfg() {
    try {
      localStorage.setItem(CFG_KEY, JSON.stringify({
        interval: cfg.interval,
        start: cfg.start,
        end: cfg.end,
        phrase: cfg.phrase,
        alert: cfg.alert,
      }));
    } catch {
      /* 写不进就只在这一轮里生效 */
    }
  }

  function readUntil() {
    try {
      const n = Number(localStorage.getItem(UNTIL_KEY));
      return Number.isFinite(n) && n > 0 ? n : 0;
    } catch {
      return 0;
    }
  }

  function writeUntil(t) {
    try {
      localStorage.setItem(UNTIL_KEY, String(t));
    } catch {
      /* ignore */
    }
  }

  function minutesOf(now) {
    return now.getHours() * 60 + now.getMinutes();
  }

  function inShift(now) {
    const t = minutesOf(now);
    const a = cfg.startMin;
    const b = cfg.endMin;
    if (a === b) return false;
    if (a < b) return t >= a && t < b;
    return t >= a || t < b;
  }

  function windowStart(now) {
    const a = cfg.startMin;
    const b = cfg.endMin;
    const d = new Date(now.getTime());
    d.setSeconds(0, 0);
    d.setMilliseconds(0);
    d.setHours(Math.floor(a / 60), a % 60, 0, 0);
    if (a > b && minutesOf(now) < b) d.setDate(d.getDate() - 1);
    return d.getTime();
  }

  function screenLive() {
    return crt.classList.contains('is-on') && !crt.classList.contains('is-booting');
  }

  function fmt(ms) {
    const total = Math.max(0, Math.ceil(ms / 1000));
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  function applyTemplate(template, timeText) {
    return String(template || '').split('{时间}').join(timeText);
  }

  function shownPhrase() {
    if (cfg.phrase.trim()) return cfg.phrase;
    if (phraseEl && document.activeElement === phraseEl) return cfg.phrase;
    return DEFAULTS.phrase;
  }

  function shownAlert() {
    if (cfg.alert.trim()) return cfg.alert;
    if (alertEl && document.activeElement === alertEl) return cfg.alert;
    return DEFAULTS.alert;
  }

  function renderLine(timeText) {
    const phrase = shownPhrase();
    if (builtPhrase !== phrase) {
      builtPhrase = phrase;
      const parts = phrase.split('{时间}');
      const frag = document.createDocumentFragment();
      parts.forEach((part, i) => {
        if (part) frag.append(document.createTextNode(part));
        if (i < parts.length - 1) {
          const n = document.createElement('span');
          n.className = 'terminal__sit-n';
          n.dataset.sitTime = '1';
          n.textContent = timeText;
          frag.append(n);
        }
      });
      root.replaceChildren(frag);
    } else {
      root.querySelectorAll('[data-sit-time]').forEach((n) => {
        if (n.textContent !== timeText) n.textContent = timeText;
      });
    }
    root.setAttribute('aria-label', applyTemplate(phrase, timeText) || '起身倒计时');
    if (preview) preview.textContent = applyTemplate(phrase, timeText);
  }

  function corrupt(text, salt) {
    const chars = Array.from(text);
    if (chars.length < 2) return text;
    chars[salt % chars.length] = ROT[salt % ROT.length];
    return chars.join('');
  }

  function fillSwarm(host, text, echo) {
    const screen = document.getElementById('crt-screen');
    const h = Math.max((screen && screen.clientHeight) || 0, 640);
    const rowPx = Math.max(22, Math.min(32, Math.round(h / 36)));
    const count = Math.ceil(h / rowPx) + 4;
    const frag = document.createDocumentFragment();
    for (let i = 0; i < count; i += 1) {
      const row = document.createElement('div');
      row.className = 'sit-fault__row';
      if (!echo && i % 4 === 1) row.classList.add('is-inv');
      else if (!echo && i % 7 === 4) row.classList.add('is-dim');
      const shift = (i % 2 ? 1 : -1) * (4 + (i % 5) * 2);
      row.style.setProperty('--sit-shift', `${shift}%`);
      row.style.animationDuration = `${0.22 + (i % 6) * 0.06}s`;
      row.style.animationDelay = `${-(i * 0.05)}s`;
      row.style.fontSize = `${echo ? Math.max(22, rowPx - 4) : rowPx}px`;
      const copies = [];
      for (let k = 0; k < 8; k += 1) {
        const rot = !echo && (i + k) % 9 === 5;
        copies.push(rot ? corrupt(text, i + k) : text);
      }
      row.textContent = copies.join('    ');
      frag.append(row);
    }
    host.replaceChildren(frag);
    return h;
  }

  function fillGiants(text) {
    const frag = document.createDocumentFragment();
    [2, 18, 36, 54, 72, 88].forEach((top, i) => {
      const el = document.createElement('div');
      el.className = `sit-fault__giant${i % 2 ? ' is-inv' : ''}`;
      el.style.top = `${top}%`;
      el.style.setProperty('--sit-shift', `${i % 2 ? 7 : -9}%`);
      el.style.animationDelay = `${-(i * 0.08)}s`;
      el.textContent = `${text}    ${text}    ${text}`;
      frag.append(el);
    });
    giants.replaceChildren(frag);
  }

  function renderAlert(timeText) {
    const text = applyTemplate(shownAlert(), timeText);
    fault.setAttribute('aria-label', text);
    if (!faulting) return;
    const screen = document.getElementById('crt-screen');
    const h = Math.max((screen && screen.clientHeight) || 0, 640);
    if (text === swarmText && Math.abs(h - swarmH) < 80) return;
    swarmText = text;
    swarmH = fillSwarm(swarmEcho, text, true);
    fillSwarm(swarm, text, false);
    fillGiants(text);
  }

  function hideFault() {
    fault.hidden = true;
    crt.classList.remove('is-sit-fault');
  }

  function showFault() {
    fault.hidden = false;
    crt.classList.add('is-sit-fault');
  }

  function spanMs() {
    return cfg.interval * 60 * 1000;
  }

  function arm(from) {
    until = from + spanMs();
    writeUntil(until);
    faulting = false;
  }

  function retarget() {
    if (faulting || !inShift(new Date())) return;
    arm(Date.now());
  }

  function ack() {
    if (!faulting) return;
    arm(Date.now());
    paint(new Date());
  }

  function paint(now) {
    const ms = now.getTime();
    const sample = fmt(spanMs());
    if (!inShift(now)) {
      faulting = false;
      root.hidden = true;
      root.classList.remove('is-soon', 'is-due');
      hideFault();
      renderLine(sample);
      renderAlert('00:00');
      return;
    }

    const start = windowStart(now);
    if (!until || until < start) arm(ms);

    const left = until - ms;
    root.hidden = false;
    if (left <= 0) {
      faulting = true;
      renderLine('00:00');
      renderAlert('00:00');
      root.classList.remove('is-soon');
      root.classList.add('is-due');
      if (screenLive()) showFault();
      else hideFault();
      return;
    }

    faulting = false;
    const timeText = fmt(left);
    renderLine(timeText);
    renderAlert(timeText);
    root.classList.toggle('is-soon', left <= SOON_MS);
    root.classList.remove('is-due');
    hideFault();
  }

  function fillForm() {
    if (everyEl && document.activeElement !== everyEl) everyEl.value = String(cfg.interval);
    if (fromEl && document.activeElement !== fromEl) fromEl.value = cfg.start;
    if (toEl && document.activeElement !== toEl) toEl.value = cfg.end;
    if (phraseEl && document.activeElement !== phraseEl) phraseEl.value = cfg.phrase;
    if (alertEl && document.activeElement !== alertEl) alertEl.value = cfg.alert;
  }

  function commitInterval() {
    if (!everyEl) return;
    const next = clampInt(everyEl.value, 1, INTERVAL_MAX, cfg.interval);
    const changed = next !== cfg.interval;
    cfg.interval = next;
    everyEl.value = String(next);
    saveCfg();
    if (changed) retarget();
    paint(new Date());
  }

  function commitClock(el, key) {
    if (!el) return;
    const next = tryClock(el.value) || cfg[key];
    el.value = next;
    if (next === cfg[key]) return;
    cfg[key] = next;
    cfg.startMin = clockToMin(cfg.start);
    cfg.endMin = clockToMin(cfg.end);
    saveCfg();
    paint(new Date());
  }

  function commitText(el, key, fallback) {
    if (!el) return;
    let next = el.value.slice(0, 40);
    if (!next.trim()) next = fallback;
    el.value = next;
    if (next === cfg[key]) return;
    cfg[key] = next;
    builtPhrase = null;
    saveCfg();
    paint(new Date());
  }

  if (everyEl) {
    everyEl.addEventListener('change', commitInterval);
    everyEl.addEventListener('blur', commitInterval);
    everyEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        commitInterval();
      }
    });
  }

  document.querySelectorAll('.sit-step').forEach((btn) => {
    btn.addEventListener('click', () => {
      const dir = Number(btn.dataset.dir) || 0;
      const cur = clampInt(everyEl && everyEl.value, 1, INTERVAL_MAX, cfg.interval);
      const next = clampInt(cur + dir * STEP_MIN, 1, INTERVAL_MAX, cur);
      const changed = next !== cfg.interval;
      cfg.interval = next;
      if (everyEl) everyEl.value = String(cfg.interval);
      saveCfg();
      if (changed) retarget();
      paint(new Date());
    });
  });

  if (fromEl) {
    fromEl.addEventListener('change', () => commitClock(fromEl, 'start'));
    fromEl.addEventListener('blur', () => commitClock(fromEl, 'start'));
  }
  if (toEl) {
    toEl.addEventListener('change', () => commitClock(toEl, 'end'));
    toEl.addEventListener('blur', () => commitClock(toEl, 'end'));
  }

  if (phraseEl) {
    phraseEl.addEventListener('input', () => {
      cfg.phrase = phraseEl.value.slice(0, 40);
      builtPhrase = null;
      saveCfg();
      paint(new Date());
    });
    phraseEl.addEventListener('blur', () => commitText(phraseEl, 'phrase', DEFAULTS.phrase));
  }

  if (alertEl) {
    alertEl.addEventListener('input', () => {
      cfg.alert = alertEl.value.slice(0, 40);
      saveCfg();
      paint(new Date());
    });
    alertEl.addEventListener('blur', () => commitText(alertEl, 'alert', DEFAULTS.alert));
  }

  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      cfg = normalize(DEFAULTS);
      saveCfg();
      builtPhrase = null;
      fillForm();
      if (!faulting && inShift(new Date())) arm(Date.now());
      paint(new Date());
    });
  }

  fault.addEventListener('pointerdown', (e) => {
    if (!faulting) return;
    e.preventDefault();
    e.stopPropagation();
    ack();
  });

  document.addEventListener('keydown', (e) => {
    if (!faulting || fault.hidden) return;
    e.preventDefault();
    e.stopPropagation();
    ack();
  }, true);

  if (window.DeskApps && typeof window.DeskApps.onEnter === 'function') {
    const enter = window.DeskApps.onEnter.bind(window.DeskApps);
    window.DeskApps.onEnter = (id) => {
      enter(id);
      if (id === 'sit') fillForm();
    };
  }

  fillForm();
  paint(new Date());
  setInterval(() => paint(new Date()), 1000);
  document.addEventListener('visibilitychange', () => paint(new Date()));
})();
