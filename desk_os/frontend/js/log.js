/**
 * Desk OS — 系统日志
 * 主页左侧滚动，右侧四个高频应用；LOG 页拉全表。
 */

(function () {
  const rowsEl = document.getElementById('log-rows');
  const streamEl = document.getElementById('sys-log-stream');
  const topEl = document.getElementById('sys-log-top');
  let timer = 0;
  let follow = true;
  let homeFollow = true;
  let painting = false;
  let paintingHome = false;

  if (rowsEl) {
    rowsEl.addEventListener('scroll', () => {
      if (painting) return;
      const gap = rowsEl.scrollHeight - rowsEl.scrollTop - rowsEl.clientHeight;
      follow = gap < 72;
    });
  }

  if (streamEl) {
    streamEl.addEventListener('scroll', () => {
      if (paintingHome) return;
      const gap = streamEl.scrollHeight - streamEl.scrollTop - streamEl.clientHeight;
      homeFollow = gap < 24;
    });
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function levelOf(row) {
    return row.level === 'warn' || row.level === 'event' ? row.level : 'info';
  }

  function phrase(row, home) {
    let text = String(row.text || '');
    if (home && levelOf(row) === 'event') text = text.replace(/ ACTIVE$/, '');
    if (text.includes('…') || text.includes('/')) {
      text = text.split(/[\s/]/)[0].replace(/…$/, '');
    }
    return text;
  }

  function lineHtml(row, cls) {
    const level = levelOf(row);
    const clock = String(row.t || '');
    const home = cls === 'log-line';
    const time = escapeHtml(home ? clock.slice(0, 5) : clock);
    const words = escapeHtml(phrase(row, home));
    return `<p class="${cls} is-${level}"><span class="${cls}__time">${time}</span><span class="${cls}__text">${words}</span></p>`;
  }

  function rankFrom(list) {
    const counts = new Map();
    list.forEach((row) => {
      let text = String(row.text || '');
      if (!text.endsWith(' ACTIVE')) return;
      text = text.replace(/ ACTIVE$/, '');
      if (text.includes('…') || text.includes('/')) {
        text = text.split(/[\s/]/)[0].replace(/…$/, '');
      }
      if (!text) return;
      counts.set(text, (counts.get(text) || 0) + 1);
    });
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
      .slice(0, 4)
      .map(([name, n]) => ({ name, n }));
  }

  function paintHome(list, apps) {
    if (!streamEl || !Array.isArray(list)) return;
    paintingHome = true;
    streamEl.innerHTML = list.map((row) => lineHtml(row, 'log-line')).join('');
    if (homeFollow) streamEl.scrollTop = streamEl.scrollHeight;
    paintingHome = false;
    if (!topEl || !Array.isArray(apps)) return;
    const ranked = apps.slice(0, 4).filter((app) => app && app.name);
    topEl.innerHTML = ranked.map((app) => {
      const name = escapeHtml(app.name);
      const count = escapeHtml(app.n);
      return `<li class="log-top__row"><span class="log-top__name">${name}</span><span class="log-top__n">${count}</span></li>`;
    }).join('');
    topEl.hidden = ranked.length === 0;
  }

  function paintApp(list) {
    if (!rowsEl || !Array.isArray(list)) return;
    painting = true;
    rowsEl.innerHTML = list.map((row) => lineHtml(row, 'log-row')).join('');
    if (follow) rowsEl.scrollTop = rowsEl.scrollHeight;
    painting = false;
  }

  async function load() {
    try {
      const res = await fetch('/api/log');
      if (!res.ok) return;
      const data = await res.json();
      const lines = Array.isArray(data.lines) ? data.lines : [];
      const apps = Array.isArray(data.apps) && data.apps.length ? data.apps : rankFrom(lines);
      paintApp(lines);
      paintHome(lines, apps);
    } catch {
      /* 主页仍靠 /api/system */
    }
  }

  function note(code) {
    fetch('/api/log', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code }),
    }).then((res) => {
      if (res.ok) load();
    }).catch(() => {});
  }

  load();
  timer = setInterval(load, 2000);

  window.DeskLog = {
    note,
    paintHome,
    onEnter() {
      load();
    },
    onLeave() {},
  };
})();
