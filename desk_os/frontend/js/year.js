/**
 * Desk OS — 年进度。纸上的日格：工作日实墨，周末灰墨，未到的日子只留框。
 * 周末从周五算起，所以星期三是 weekend-2d。
 */

(function () {
  const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];

  const doyEl = document.getElementById('year-doy');
  const weekEl = document.getElementById('year-week');
  const weekendEl = document.getElementById('year-weekend');
  const pctEl = document.getElementById('year-pct');
  const gridEl = document.getElementById('year-grid');
  const seasonEl = document.getElementById('year-season');
  const countEl = document.getElementById('year-count');
  const barEl = document.getElementById('year-bar-fill');

  let timer = 0;
  let dayShown = '';

  function ymd(date) {
    return date.getFullYear() * 10000 + (date.getMonth() + 1) * 100 + date.getDate();
  }

  function dayOfYear(date) {
    const start = new Date(date.getFullYear(), 0, 0);
    return Math.floor((date - start) / 86400000);
  }

  function daysInYear(year) {
    return ((year % 4 === 0 && year % 100 !== 0) || year % 400 === 0) ? 366 : 365;
  }

  function isoWeek(date) {
    const utc = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
    const day = utc.getUTCDay() || 7;
    utc.setUTCDate(utc.getUTCDate() + 4 - day);
    const yearStart = new Date(Date.UTC(utc.getUTCFullYear(), 0, 1));
    return Math.ceil((((utc - yearStart) / 86400000) + 1) / 7);
  }

  function seasonName(date) {
    const md = (date.getMonth() + 1) * 100 + date.getDate();
    if (md >= 320 && md <= 620) return 'SPRING';
    if (md >= 621 && md <= 921) return 'SUMMER';
    if (md >= 922 && md <= 1220) return 'AUTUMN';
    return 'WINTER';
  }

  function weekendLabel(date) {
    const day = date.getDay();
    if (day === 0 || day === 5 || day === 6) return 'weekend';
    return `weekend-${5 - day}d`;
  }

  function paintDay(now) {
    const key = ymd(now);
    if (key === dayShown) return;
    dayShown = key;

    const year = now.getFullYear();
    const doy = dayOfYear(now);
    const total = daysInYear(year);
    const pct = Math.round((doy / total) * 100);
    const today = ymd(now);

    if (doyEl) doyEl.textContent = `doy:${doy}`;
    if (weekEl) weekEl.textContent = `w:${isoWeek(now)}`;
    if (weekendEl) weekendEl.textContent = weekendLabel(now);
    if (pctEl) pctEl.textContent = `${pct}%`;
    if (seasonEl) seasonEl.textContent = seasonName(now);
    if (countEl) countEl.textContent = `Day ${doy} of ${total}`;
    if (barEl) barEl.style.width = `${pct}%`;
    if (gridEl) {
      gridEl.setAttribute('aria-label', `day ${doy} of ${total}`);
      gridEl.replaceChildren();
      for (let month = 0; month < 12; month += 1) {
        const row = document.createElement('div');
        row.className = 'year-row';
        const label = document.createElement('span');
        label.className = 'year-row__label';
        label.textContent = MONTHS[month];
        const cells = document.createElement('span');
        cells.className = 'year-cells';
        const count = new Date(year, month + 1, 0).getDate();
        for (let day = 1; day <= count; day += 1) {
          const cell = document.createElement('i');
          const stamp = year * 10000 + (month + 1) * 100 + day;
          const weekday = new Date(year, month, day).getDay();
          cell.className = 'year-cell';
          if (weekday === 0 || weekday === 6) cell.classList.add('is-weekend');
          if (stamp < today) cell.classList.add('is-past');
          else if (stamp === today) cell.classList.add('is-today');
          else cell.classList.add('is-future');
          cells.appendChild(cell);
        }
        row.appendChild(label);
        row.appendChild(cells);
        gridEl.appendChild(row);
      }
    }
  }

  function paint(now) {
    paintDay(now);
  }

  dayShown = '';
  paint(new Date());
  timer = window.setInterval(() => paint(new Date()), 30000);
})();
