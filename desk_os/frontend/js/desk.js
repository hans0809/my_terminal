/**
 * Desk OS — 应用层调度
 * 新页面：单独一个 js，调用 DeskApps.register(id, hooks)。
 * hooks 可用 onEnter、onLeave、onHome、onEscape；后两个返回 true 表示已处理。
 */

(function () {
  document.querySelectorAll('.app-tile').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (window.DeskOS && typeof window.DeskOS.openApp === 'function') {
        window.DeskOS.openApp(btn.dataset.app);
      }
    });
  });

  const apps = {};

  function current() {
    return window.DeskOS && typeof window.DeskOS.app === 'function'
      ? window.DeskOS.app()
      : '';
  }

  function run(id, name) {
    const app = apps[id];
    const fn = app && app[name];
    if (typeof fn !== 'function') return false;
    return fn() === true;
  }

  window.DeskApps = {
    register(id, hooks) {
      if (!id || !hooks) return;
      apps[id] = hooks;
    },
    onEnter(id) {
      const app = apps[id];
      if (app && typeof app.onEnter === 'function') app.onEnter();
    },
    onLeave(id) {
      const app = apps[id];
      if (app && typeof app.onLeave === 'function') app.onLeave();
    },
    onHome() {
      return run(current(), 'onHome');
    },
    onEscape() {
      return run(current(), 'onEscape');
    },
  };
})();
