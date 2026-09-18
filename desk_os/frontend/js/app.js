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
    root.querySelectorAll('.term-row').forEach((el) => nodes.push(el));
    const rule = root.querySelector('.terminal__rule');
    if (rule) nodes.push(rule);
    root.querySelectorAll('.info-row').forEach((el) => nodes.push(el));
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
