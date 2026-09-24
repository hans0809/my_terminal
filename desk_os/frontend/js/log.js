/**
 * Desk OS — 系统日志
 * 主页四行由状态轮询刷；LOG 页拉全表。
 */

(function () {
  const rowsEl = document.getElementById('log-rows');
  const homeEl = document.getElementById('sys-log');
  let timer = 0;
  let follow = true;
  let painting = false;

  if (rowsEl) {
    rowsEl.addEventListener('scroll', () => {
      if (painting) return;
      const gap = rowsEl.scrollHeight - rowsEl.scrollTop - rowsEl.clientHeight;
      follow = gap < 72;
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
    const body = home
      ? `<span class="${cls}__text">${words}</span><span class="${cls}__time">${time}</span>`
      : `<span class="${cls}__time">${time}</span><span class="${cls}__text">${words}</span>`;
    return `<p class="${cls} is-${level}">${body}</p>`;
  }

  function paintHome(list) {
    if (!homeEl || !Array.isArray(list)) return;
    homeEl.innerHTML = list.slice(-4).map((row) => lineHtml(row, 'log-line')).join('');
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
      paintApp(lines);
      paintHome(lines);
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

  window.DeskLog = {
    note,
    paintHome,
    onEnter() {
      load();
      clearInterval(timer);
      timer = setInterval(load, 2000);
    },
    onLeave() {
      clearInterval(timer);
      timer = 0;
    },
  };
})();
