/**
 * Desk OS — 年进度。纸上的日格：工作日实墨，周末灰墨，未到的日子只留框。
 * 节气日在格心留一个针孔；点一格，右下写出那一天的节气和候。
 * 周末从周五算起，所以星期三是 weekend-2d。
 */

(function () {
  const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
  const HOU = ['初候', '次候', '末候'];

  const TERMS = [
    { lon: 285, name: '小寒', hou: ['雁北乡', '鹊始巢', '雉始雊'] },
    { lon: 300, name: '大寒', hou: ['鸡始乳', '征鸟厉疾', '水泽腹坚'] },
    { lon: 315, name: '立春', hou: ['东风解冻', '蛰虫始振', '鱼陟负冰'] },
    { lon: 330, name: '雨水', hou: ['獭祭鱼', '鸿雁来', '草木萌动'] },
    { lon: 345, name: '惊蛰', hou: ['桃始华', '仓庚鸣', '鹰化为鸠'] },
    { lon: 0, name: '春分', hou: ['玄鸟至', '雷乃发声', '始电'] },
    { lon: 15, name: '清明', hou: ['桐始华', '田鼠化为鴽', '虹始见'] },
    { lon: 30, name: '谷雨', hou: ['萍始生', '鸣鸠拂其羽', '戴胜降于桑'] },
    { lon: 45, name: '立夏', hou: ['蝼蝈鸣', '蚯蚓出', '王瓜生'] },
    { lon: 60, name: '小满', hou: ['苦菜秀', '靡草死', '麦秋至'] },
    { lon: 75, name: '芒种', hou: ['螳螂生', '鵙始鸣', '反舌无声'] },
    { lon: 90, name: '夏至', hou: ['鹿角解', '蜩始鸣', '半夏生'] },
    { lon: 105, name: '小暑', hou: ['温风至', '蟋蟀居壁', '鹰始挚'] },
    { lon: 120, name: '大暑', hou: ['腐草为萤', '土润溽暑', '大雨时行'] },
    { lon: 135, name: '立秋', hou: ['凉风至', '白露降', '寒蝉鸣'] },
    { lon: 150, name: '处暑', hou: ['鹰乃祭鸟', '天地始肃', '禾乃登'] },
    { lon: 165, name: '白露', hou: ['鸿雁来', '玄鸟归', '群鸟养羞'] },
    { lon: 180, name: '秋分', hou: ['雷始收声', '蛰虫坯户', '水始涸'] },
    { lon: 195, name: '寒露', hou: ['鸿雁来宾', '雀入大水为蛤', '菊有黄华'] },
    { lon: 210, name: '霜降', hou: ['豺乃祭兽', '草木黄落', '蛰虫咸俯'] },
    { lon: 225, name: '立冬', hou: ['水始冰', '地始冻', '雉入大水为蜃'] },
    { lon: 240, name: '小雪', hou: ['虹藏不见', '天气上升地气下降', '闭塞而成冬'] },
    { lon: 255, name: '大雪', hou: ['鹖鴠不鸣', '虎始交', '荔挺出'] },
    { lon: 270, name: '冬至', hou: ['蚯蚓结', '麋角解', '水泉动'] },
  ];

  const doyEl = document.getElementById('year-doy');
  const weekEl = document.getElementById('year-week');
  const weekendEl = document.getElementById('year-weekend');
  const pctEl = document.getElementById('year-pct');
  const gridEl = document.getElementById('year-grid');
  const seasonEl = document.getElementById('year-season');
  const countEl = document.getElementById('year-count');
  const barEl = document.getElementById('year-bar-fill');
  const termNameEl = document.getElementById('year-term-name');
  const termHouIdxEl = document.getElementById('year-term-hou-idx');
  const termHouEl = document.getElementById('year-term-hou');
  const termNextEl = document.getElementById('year-term-next');
  const termNextDateEl = document.getElementById('year-term-next-date');
  const yearRoot = document.querySelector('.terminal__year');

  let timer = 0;
  let holdTimer = 0;
  let dayShown = '';
  let selectedStamp = 0;
  const termCache = new Map();
  const HOLD_MS = 60 * 1000;

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

  function labelDate(stamp) {
    const month = Math.floor((stamp % 10000) / 100);
    const day = stamp % 100;
    return `${MONTHS[month - 1]} ${day}`;
  }

  function daysBetween(a, b) {
    const ay = Math.floor(a / 10000);
    const am = Math.floor((a % 10000) / 100);
    const ad = a % 100;
    const by = Math.floor(b / 10000);
    const bm = Math.floor((b % 10000) / 100);
    const bd = b % 100;
    return Math.round((Date.UTC(by, bm - 1, bd) - Date.UTC(ay, am - 1, ad)) / 86400000);
  }

  function julianDay(year, month, day, hour) {
    let y = year;
    let m = month;
    if (m <= 2) {
      y -= 1;
      m += 12;
    }
    const A = Math.floor(y / 100);
    const B = 2 - A + Math.floor(A / 4);
    return Math.floor(365.25 * (y + 4716)) + Math.floor(30.6001 * (m + 1)) + day + hour / 24 + B - 1524.5;
  }

  function sunLongitude(jd) {
    const T = (jd - 2451545.0) / 36525.0;
    let L0 = 280.46646 + 36000.76983 * T + 0.0003032 * T * T;
    let M = 357.52911 + 35999.05029 * T - 0.0001537 * T * T;
    L0 = ((L0 % 360) + 360) % 360;
    M = ((M % 360) + 360) % 360;
    const Mr = M * Math.PI / 180;
    const C = (1.914602 - 0.004817 * T - 0.000014 * T * T) * Math.sin(Mr)
      + (0.019993 - 0.000101 * T) * Math.sin(2 * Mr)
      + 0.000289 * Math.sin(3 * Mr);
    const omega = 125.04 - 1934.136 * T;
    const lambda = L0 + C - 0.00569 - 0.00478 * Math.sin(omega * Math.PI / 180);
    return ((lambda % 360) + 360) % 360;
  }

  function angDiff(a, b) {
    let d = a - b;
    while (d > 180) d -= 360;
    while (d < -180) d += 360;
    return d;
  }

  function jdToBeijingDate(jd) {
    const local = jd + 8 / 24;
    const Z = Math.floor(local + 0.5);
    const F = local + 0.5 - Z;
    let A = Z;
    if (Z >= 2299161) {
      const alpha = Math.floor((Z - 1867216.25) / 36524.25);
      A = Z + 1 + alpha - Math.floor(alpha / 4);
    }
    const B = A + 1524;
    const C = Math.floor((B - 122.1) / 365.25);
    const D = Math.floor(365.25 * C);
    const E = Math.floor((B - D) / 30.6001);
    const day = B - D - Math.floor(30.6001 * E) + F;
    const month = E < 14 ? E - 1 : E - 13;
    const year = month > 2 ? C - 4716 : C - 4715;
    return {
      year,
      month,
      day: Math.floor(day),
      stamp: year * 10000 + month * 100 + Math.floor(day),
    };
  }

  function findTermDate(year, lon) {
    const jan1 = julianDay(year, 1, 1, 0);
    const estDay = ((lon - 280) + 360) % 360 / 0.985647;
    let lo = jan1 + estDay - 5;
    let hi = jan1 + estDay + 5;
    for (let i = 0; i < 50; i += 1) {
      const mid = (lo + hi) / 2;
      if (angDiff(sunLongitude(mid), lon) < 0) lo = mid;
      else hi = mid;
    }
    return jdToBeijingDate((lo + hi) / 2);
  }

  function termsForYear(year) {
    let list = termCache.get(year);
    if (list) return list;
    list = [];
    for (let y = year - 1; y <= year + 1; y += 1) {
      TERMS.forEach((term) => {
        const when = findTermDate(y, term.lon);
        list.push({
          stamp: when.stamp,
          year: when.year,
          month: when.month,
          day: when.day,
          term,
        });
      });
    }
    list.sort((a, b) => a.stamp - b.stamp);
    termCache.set(year, list);
    return list;
  }

  function termSet(year) {
    const stamps = new Set();
    termsForYear(year).forEach((row) => {
      if (Math.floor(row.stamp / 10000) === year) stamps.add(row.stamp);
    });
    return stamps;
  }

  function termAt(stamp) {
    const year = Math.floor(stamp / 10000);
    const list = termsForYear(year);
    let here = -1;
    for (let i = 0; i < list.length; i += 1) {
      if (list[i].stamp <= stamp) here = i;
      else break;
    }
    if (here < 0 || here + 1 >= list.length) return null;
    const cur = list[here];
    const next = list[here + 1];
    const offset = Math.max(0, daysBetween(cur.stamp, stamp));
    const hou = offset < 5 ? 0 : offset < 10 ? 1 : 2;
    return { cur, next, hou };
  }

  function setText(el, text) {
    if (el) el.textContent = text;
  }

  function showTerm(stamp) {
    const info = termAt(stamp);
    if (!info) return;
    const { cur, next, hou } = info;
    setText(termNameEl, cur.term.name);
    setText(termHouIdxEl, HOU[hou]);
    setText(termHouEl, cur.term.hou[hou]);
    setText(termNextEl, next.term.name);
    setText(termNextDateEl, labelDate(next.stamp));
  }

  function applySelected() {
    if (!gridEl) return;
    gridEl.querySelectorAll('.year-cell').forEach((cell) => {
      const on = Number(cell.dataset.stamp) === selectedStamp;
      cell.classList.toggle('is-on', on);
      cell.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  function clearHold() {
    if (holdTimer) {
      window.clearTimeout(holdTimer);
      holdTimer = 0;
    }
  }

  function armHold() {
    clearHold();
    holdTimer = window.setTimeout(() => {
      holdTimer = 0;
      if (dayShown && selectedStamp !== dayShown) selectDay(dayShown);
    }, HOLD_MS);
  }

  function selectDay(stamp) {
    selectedStamp = stamp;
    applySelected();
    showTerm(stamp);
    if (stamp === dayShown) clearHold();
    else armHold();
  }

  function paintDay(now) {
    const key = ymd(now);
    if (key === dayShown) return;
    const stay = selectedStamp && selectedStamp !== dayShown;
    dayShown = key;

    const year = now.getFullYear();
    const doy = dayOfYear(now);
    const total = daysInYear(year);
    const pct = Math.round((doy / total) * 100);
    const today = ymd(now);
    const terms = termSet(year);

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
          const cell = document.createElement('button');
          const stamp = year * 10000 + (month + 1) * 100 + day;
          const weekday = new Date(year, month, day).getDay();
          cell.type = 'button';
          cell.className = 'year-cell';
          cell.dataset.stamp = String(stamp);
          cell.setAttribute('aria-label', `${MONTHS[month]} ${day}`);
          if (weekday === 0 || weekday === 6) cell.classList.add('is-weekend');
          if (stamp < today) cell.classList.add('is-past');
          else if (stamp === today) cell.classList.add('is-today');
          else cell.classList.add('is-future');
          if (terms.has(stamp)) cell.classList.add('is-term');
          cells.appendChild(cell);
        }
        row.appendChild(label);
        row.appendChild(cells);
        gridEl.appendChild(row);
      }
    }

    if (!stay) selectedStamp = today;
    applySelected();
    showTerm(selectedStamp);
  }

  function paint(now) {
    paintDay(now);
  }

  if (gridEl) {
    gridEl.addEventListener('click', (event) => {
      const cell = event.target.closest('.year-cell');
      if (!cell) return;
      event.stopPropagation();
      selectDay(Number(cell.dataset.stamp));
    });
  }
  if (yearRoot) {
    yearRoot.addEventListener('click', (event) => {
      event.stopPropagation();
    });
  }

  dayShown = '';
  paint(new Date());
  timer = window.setInterval(() => paint(new Date()), 30000);
})();
