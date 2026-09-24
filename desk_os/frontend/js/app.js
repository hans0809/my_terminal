/**
 * Desk OS — 应用入口
 * 状态灯 → 桌面（图标格）→ App；Home 回到桌面
 */

(function () {
  const CURSOR_CROSS = "url('/assets/cursor-cross.png?v=2') 16 16, crosshair";
  const CURSOR_BLOCK = "url('/assets/cursor-block.png?v=2') 16 16, text";
  const BOOT_GAP = 92;

  document.documentElement.style.cursor = CURSOR_CROSS;
  document.body.style.cursor = CURSOR_CROSS;

  const deskBtn = document.getElementById('desk-btn');
  const crtMonitor = document.getElementById('crt-monitor');
  const powerBtn = document.getElementById('power-btn');
  const homeBtn = document.getElementById('home-btn');
  const einkFlash = document.getElementById('eink-flash');
  const layerStatus = document.getElementById('layer-status');
  const layerDesk = document.getElementById('layer-desk');
  const layerApp = document.getElementById('layer-app');
  let flashTimer = 0;
  const bootTimers = [];
  let layer = 'status';
  let openAppId = '';

  function flashEink() {
    if (!einkFlash) return;
    einkFlash.classList.remove('is-on');
    void einkFlash.offsetWidth;
    einkFlash.classList.add('is-on');
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => einkFlash.classList.remove('is-on'), 380);
  }

  function later(ms, fn) {
    const id = setTimeout(fn, ms);
    bootTimers.push(id);
    return id;
  }

  function cancelBoot(keep) {
    while (bootTimers.length) clearTimeout(bootTimers.pop());
    if (!crtMonitor) return;
    document.querySelectorAll('.boot-ink').forEach((el) => {
      el.classList.remove('boot-ink');
    });
    if (!keep) crtMonitor.classList.remove('is-booting');
  }

  function bootCandidates() {
    const root = document.querySelector('.terminal');
    if (!root) return [];
    const nodes = [];
    root.querySelectorAll('.terminal__head > *').forEach((el) => nodes.push(el));
    const status = root.querySelector('.terminal__status-line');
    if (status) nodes.push(status);
    root.querySelectorAll('.sky-col').forEach((el) => nodes.push(el));
    const skyRule = root.querySelector('.terminal__rule--sky');
    if (skyRule) nodes.push(skyRule);
    const flight = root.querySelector('#flight-home');
    if (flight) nodes.push(flight);
    root.querySelectorAll('.term-row').forEach((el) => nodes.push(el));
    const rule = root.querySelector('.terminal__dock .terminal__rule');
    if (rule) nodes.push(rule);
    root.querySelectorAll('.info-row').forEach((el) => nodes.push(el));
    const logRule = root.querySelector('.terminal__rule--log');
    if (logRule) nodes.push(logRule);
    const log = root.querySelector('.terminal__log');
    if (log) nodes.push(log);
    const year = root.querySelector('.terminal__year');
    if (year) nodes.push(year);
    return nodes.filter((el) => !el.classList.contains('is-hidden'));
  }

  function startBoot() {
    cancelBoot(true);
    if (!crtMonitor || !crtMonitor.classList.contains('is-on')) return;
    setLayer('status', { flash: false, boot: false });
    crtMonitor.classList.add('is-booting');
    bootCandidates().forEach((el) => el.classList.remove('boot-ink'));
    if (window.PixelDog && typeof window.PixelDog.bootStart === 'function') {
      window.PixelDog.bootStart();
    }
    flashEink();

    const queue = bootCandidates();
    queue.forEach((el, i) => {
      later(360 + i * BOOT_GAP, () => {
        if (!crtMonitor.classList.contains('is-on')) return;
        el.classList.add('boot-ink');
      });
    });

    const doneAt = 360 + queue.length * BOOT_GAP + 420;
    later(doneAt, () => {
      if (!crtMonitor.classList.contains('is-on')) return;
      crtMonitor.classList.remove('is-booting');
      bootCandidates().forEach((el) => el.classList.add('boot-ink'));
      if (window.PixelDog && typeof window.PixelDog.bootEnd === 'function') {
        window.PixelDog.bootEnd();
      }
    });
  }

  function setLayer(name, opts) {
    const options = opts || {};
    const next = name === 'app' ? 'app' : name === 'desk' ? 'desk' : 'status';
    const prev = layer;
    const prevApp = openAppId;

    if (next !== 'app') openAppId = '';
    if (options.app) openAppId = options.app;

    layer = next;
    document.body.dataset.layer = next;
    if (deskBtn) deskBtn.setAttribute('aria-pressed', String(next !== 'status'));
    if (crtMonitor) {
      crtMonitor.classList.toggle('is-spring', next !== 'status');
      crtMonitor.classList.toggle('is-app', next === 'app');
    }
    if (layerStatus) layerStatus.classList.toggle('is-on', next === 'status');
    if (layerDesk) layerDesk.classList.toggle('is-on', next === 'desk');
    if (layerApp) layerApp.classList.toggle('is-on', next === 'app');

    document.querySelectorAll('.app-page').forEach((el) => {
      el.classList.toggle('is-on', next === 'app' && el.id === `app-${openAppId}`);
    });

    if (options.flash !== false && prev !== next) flashEink();

    if (window.DeskApps) {
      if (prev === 'app' && (next !== 'app' || prevApp !== openAppId)) {
        window.DeskApps.onLeave(prevApp);
      }
      if (next === 'app' && openAppId) {
        window.DeskApps.onEnter(openAppId);
      }
    }
  }

  function goDesk() {
    if (!crtMonitor || !crtMonitor.classList.contains('is-on')) return;
    if (crtMonitor.classList.contains('is-booting')) return;
    setLayer('desk');
  }

  function goHome() {
    if (!crtMonitor || !crtMonitor.classList.contains('is-on')) return;
    if (window.DeskApps && typeof window.DeskApps.onHome === 'function') {
      if (window.DeskApps.onHome()) return;
    }
    if (layer === 'app') setLayer('desk');
  }

  function openApp(id) {
    if (!crtMonitor || !crtMonitor.classList.contains('is-on')) return;
    if (!id) return;
    setLayer('app', { app: id });
  }

  function goStatus() {
    if (layer === 'status') return;
    setLayer('status');
  }

  powerBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    const turningOn = !crtMonitor.classList.contains('is-on');
    crtMonitor.classList.toggle('is-on', turningOn);
    crtMonitor.classList.toggle('is-off', !turningOn);
    powerBtn.setAttribute('aria-pressed', String(turningOn));
    if (window.DeskLog) window.DeskLog.note(turningOn ? 'crt-on' : 'crt-off');
    if (turningOn) {
      startBoot();
    } else {
      cancelBoot();
      if (window.PixelDog && typeof window.PixelDog.bootCancel === 'function') {
        window.PixelDog.bootCancel();
      }
    }
  });

  deskBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (!crtMonitor.classList.contains('is-on')) return;
    if (crtMonitor.classList.contains('is-booting')) return;
    if (layer === 'status') goDesk();
    else goStatus();
  });

  homeBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    goHome();
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (window.DeskApps && typeof window.DeskApps.onEscape === 'function') {
        if (window.DeskApps.onEscape(e)) {
          e.preventDefault();
          return;
        }
      }
      if (layer === 'app') {
        e.preventDefault();
        goHome();
      } else if (layer === 'desk') {
        e.preventDefault();
        goStatus();
      }
    }

    if (e.key === 'F11') {
      e.preventDefault();
      if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.toggle_fullscreen();
      }
    }
  });

  const TYPE_KEY = 'desk-type';
  const TYPE_SCALES = [1, 1.2, 1.45, 1.7];
  const TYPE_NAMES = ['S', 'M', 'L', 'XL'];
  let typeState = { face: '', size: 0 };

  function readType() {
    try {
      const saved = JSON.parse(localStorage.getItem(TYPE_KEY) || '{}');
      const size = Number(saved.size);
      return {
        face: saved.face === 'mono' || saved.face === 'serif' || saved.face === 'sans' ? saved.face : '',
        size: size >= 0 && size < TYPE_SCALES.length ? size : 0,
      };
    } catch {
      return { face: '', size: 0 };
    }
  }

  function applyType() {
    if (!layerApp) return;
    if (typeState.face) layerApp.dataset.face = typeState.face;
    else delete layerApp.dataset.face;
    layerApp.style.setProperty('--type-scale', String(TYPE_SCALES[typeState.size]));
    document.querySelectorAll('.type-set__n').forEach((el) => {
      el.textContent = TYPE_NAMES[typeState.size];
    });
    document.querySelectorAll('.type-set__face').forEach((btn) => {
      const on = btn.dataset.face === typeState.face;
      btn.classList.toggle('is-on', on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    document.querySelectorAll('.type-set [data-step]').forEach((btn) => {
      const step = Number(btn.dataset.step);
      const blocked = (step < 0 && typeState.size === 0)
        || (step > 0 && typeState.size === TYPE_SCALES.length - 1);
      btn.disabled = blocked;
    });
  }

  function saveType() {
    localStorage.setItem(TYPE_KEY, JSON.stringify(typeState));
    applyType();
  }

  document.addEventListener('click', (e) => {
    const faceBtn = e.target.closest('.type-set__face');
    const stepBtn = e.target.closest('.type-set [data-step]');
    if (!faceBtn && !stepBtn) return;
    e.preventDefault();
    if (faceBtn) {
      const face = faceBtn.dataset.face;
      typeState.face = typeState.face === face ? '' : face;
    }
    if (stepBtn) {
      const next = typeState.size + Number(stepBtn.dataset.step);
      typeState.size = Math.max(0, Math.min(TYPE_SCALES.length - 1, next));
    }
    saveType();
  });

  typeState = readType();
  applyType();

  window.DeskOS = {
    flashEink,
    startBoot,
    cancelBoot,
    setLayer,
    goDesk,
    goHome,
    goStatus,
    openApp,
    layer: () => layer,
    app: () => openAppId,
  };

  setTimeout(() => {
    if (crtMonitor && crtMonitor.classList.contains('is-on')) startBoot();
  }, 0);
})();
