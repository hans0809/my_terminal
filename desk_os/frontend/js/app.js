/**
 * Desk OS — 应用入口
 * Phase 1: 视图切换 + 隐藏入口 + 上电仪式
 */

(function () {
  const CURSOR_CROSS = "url('/assets/cursor-cross.png?v=2') 16 16, crosshair";
  const CURSOR_BLOCK = "url('/assets/cursor-block.png?v=2') 16 16, text";
  const BOOT_GAP = 92;

  document.documentElement.style.cursor = CURSOR_CROSS;
  document.body.style.cursor = CURSOR_CROSS;

  const viewDashboard = document.getElementById('view-dashboard');
  const viewDesk = document.getElementById('view-desk');
  const hiddenEntry = document.getElementById('hidden-entry');
  const crtMonitor = document.getElementById('crt-monitor');
  const powerBtn = document.getElementById('power-btn');
  const einkFlash = document.getElementById('eink-flash');
  let flashTimer = 0;
  const bootTimers = [];

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
    if (hiddenEntry) nodes.push(hiddenEntry);
    return nodes.filter((el) => !el.classList.contains('is-hidden'));
  }

  function startBoot() {
    cancelBoot(true);
    if (!crtMonitor || !crtMonitor.classList.contains('is-on')) return;
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

  hiddenEntry.addEventListener('mouseenter', () => {
    document.body.style.cursor = CURSOR_BLOCK;
  });
  hiddenEntry.addEventListener('mouseleave', () => {
    document.body.style.cursor = CURSOR_CROSS;
  });

  function showView(name) {
    viewDashboard.classList.toggle('active', name === 'dashboard');
    viewDesk.classList.toggle('active', name === 'desk');
  }

  hiddenEntry.addEventListener('click', (e) => {
    e.stopPropagation();
    if (!crtMonitor.classList.contains('is-on')) return;
    if (crtMonitor.classList.contains('is-booting')) return;
    showView('desk');
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      showView('dashboard');
    }

    if (e.key === 'F11') {
      e.preventDefault();
      if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.toggle_fullscreen();
      }
    }
  });

  window.DeskOS = { showView, flashEink, startBoot, cancelBoot };

  setTimeout(() => {
    if (crtMonitor && crtMonitor.classList.contains('is-on')) startBoot();
  }, 0);
})();
