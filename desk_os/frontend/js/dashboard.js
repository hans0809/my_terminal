/**
 * Desk OS — 像素终端主页
 */

(function () {
  const POLL_INTERVAL = 1500;
  let barLen = 16;
  let lastData = null;

  const els = {
    date: document.getElementById('date'),
    timeText: document.getElementById('time-text'),
    weather: document.getElementById('weather'),
    cpuBar: document.getElementById('cpu-bar'),
    cpuVal: document.getElementById('cpu-val'),
    gpuBar: document.getElementById('gpu-bar'),
    gpuVal: document.getElementById('gpu-val'),
    ramBar: document.getElementById('ram-bar'),
    ramVal: document.getElementById('ram-val'),
    vramRow: document.getElementById('vram-row'),
    vramBar: document.getElementById('vram-bar'),
    vramVal: document.getElementById('vram-val'),
    curBar: document.getElementById('cur-bar'),
    curVal: document.getElementById('cur-val'),
    othBar: document.getElementById('oth-bar'),
    othVal: document.getElementById('oth-val'),
    netDown: document.getElementById('net-down'),
    netUp: document.getElementById('net-up'),
    diskSummary: document.getElementById('disk-summary'),
    pingHost: document.getElementById('ping-host'),
    ping: document.getElementById('ping'),
    tmpRow: document.getElementById('tmp-row'),
    tmpSummary: document.getElementById('tmp-summary'),
    keySummary: document.getElementById('key-summary'),
    rstRow: document.getElementById('rst-row'),
    rstVal: document.getElementById('rst-val'),
    curRow: document.getElementById('cur-row'),
    othRow: document.getElementById('oth-row'),
    uptime: document.getElementById('uptime'),
    worldRise: document.getElementById('world-rise'),
    worldSet: document.getElementById('world-set'),
    cityHomeName: document.getElementById('city-home-name'),
    cityHomeTime: document.getElementById('city-home-time'),
    cityHomeSky: document.getElementById('city-home-sky'),
    cityLonName: document.getElementById('city-lon-name'),
    cityLonTime: document.getElementById('city-lon-time'),
    cityLonSky: document.getElementById('city-lon-sky'),
    cityNycName: document.getElementById('city-nyc-name'),
    cityNycTime: document.getElementById('city-nyc-time'),
    cityNycSky: document.getElementById('city-nyc-sky'),
    moonMark: document.getElementById('moon-mark'),
    moonName: document.getElementById('moon-name'),
    moonPct: document.getElementById('moon-pct'),
  };

  const MOON_NAMES = [
    'NEW MOON',
    'WAXING CRESCENT',
    'FIRST QUARTER',
    'WAXING GIBBOUS',
    'FULL MOON',
    'WANING GIBBOUS',
    'LAST QUARTER',
    'WANING CRESCENT',
  ];

  const CITIES = {
    home: { name: 'BEIJING', zone: 'Asia/Shanghai', sky: '' },
    lon: { name: 'LONDON', zone: 'Europe/London', sky: '' },
    nyc: { name: 'NEW YORK', zone: 'America/New_York', sky: '' },
  };

  let sky = {
    sunrise: '',
    sunset: '',
  };
  let moonKey = '';
  let extraSkiesLoaded = false;

  const QUOTA_WARN = 80;
  let quotaSeen = false;
  let quotaFlashed = false;

  function measureBarChar(barEl) {
    const canvas = measureBarChar.canvas || (measureBarChar.canvas = document.createElement('canvas'));
    const ctx = canvas.getContext('2d');
    if (!ctx || !barEl) return 8;
    const cs = getComputedStyle(barEl);
    ctx.font = cs.font;
    const w = ctx.measureText('█').width;
    return w > 1 ? w : 8;
  }

  function calcBarLen() {
    const barEl = document.querySelector('.terminal__metrics .term-row:not(.is-hidden) .term-row__bar');
    if (!barEl) return 16;
    const portrait = window.matchMedia(
      '(orientation: portrait) and (min-width: 1000px) and (min-height: 1400px)'
    ).matches;
    if (portrait) {
      const wide = barEl.getBoundingClientRect().width;
      const ch = measureBarChar(barEl);
      if (wide >= 24) return Math.max(16, Math.min(42, Math.floor(wide / ch)));
    }
    const barW = barEl.getBoundingClientRect().width;
    const charW = measureBarChar(barEl);
    if (barW < 24) return 12;
    return Math.max(8, Math.min(48, Math.floor(barW / charW)));
  }

  function pixelBar(ratio) {
    const clamped = Math.max(0, Math.min(1, ratio || 0));
    const filled = Math.round(clamped * barLen);
    const full = '█'.repeat(filled);
    const empty = '·'.repeat(barLen - filled);
    if (!empty) return `<span class="bar-full">${full}</span>`;
    if (!full) return `<span class="bar-empty">${empty}</span>`;
    return `<span class="bar-full">${full}</span><span class="bar-empty">${empty}</span>`;
  }

  function formatUptime(label) {
    if (!label) return '--';
    return label
      .replace(/(\d+)d/gi, (_, n) => `${String(n).padStart(2, '0')}D `)
      .replace(/(\d+)h/gi, (_, n) => `${String(n).padStart(2, '0')}H`)
      .replace(/(\d+)m/gi, (_, n) => `${String(n).padStart(2, '0')}M`)
      .trim();
  }

  function diskPercent(used, total) {
    if (!total) return 0;
    return (used / total) * 100;
  }

  /** 固定宽度：999.9 / 999.9G，避免小数变化导致换行 */
  function formatGbPair(usedGb, totalGb) {
    const used = Number(usedGb).toFixed(1);
    const total = Number(totalGb).toFixed(1);
    return `${used} / ${total}G`;
  }

  function renderDiskSummary(disks) {
    if (!disks || disks.length === 0) {
      els.diskSummary.textContent = '--';
      return;
    }
    els.diskSummary.textContent = disks
      .map((d) => {
        const pct = Math.round(diskPercent(d.used_gb, d.total_gb));
        return `${d.drive}: ${pct}%`;
      })
      .join('   ');
  }

  function formatKeys(n) {
    const v = Math.max(0, Number(n) || 0);
    if (v >= 100000) return `${Math.round(v / 1000)}k`;
    return String(Math.round(v));
  }

  function formatRate(n) {
    const v = Math.max(0, Number(n) || 0);
    if (v < 0.05) return '0/m';
    if (v >= 10) return `${Math.round(v)}/m`;
    return `${v.toFixed(1)}/m`;
  }

  function publishSystem(data) {
    window.DeskOS = window.DeskOS || {};
    window.DeskOS.system = data;
    if (window.PixelDog && typeof window.PixelDog.onSystem === 'function') {
      window.PixelDog.onSystem(data);
    }
  }

  function setWarn(row, on) {
    if (row) row.classList.toggle('is-warn', !!on);
  }

  function checkQuotaFlash(cursor) {
    if (!cursor || !cursor.available) return;
    const hot =
      (Number(cursor.auto_used_pct) || 0) >= QUOTA_WARN ||
      (Number(cursor.api_used_pct) || 0) >= QUOTA_WARN;
    if (!quotaSeen) {
      quotaSeen = true;
      quotaFlashed = hot;
      return;
    }
    if (hot && !quotaFlashed) {
      quotaFlashed = true;
      if (window.DeskOS && typeof window.DeskOS.flashEink === 'function') {
        window.DeskOS.flashEink();
      }
    }
    if (!hot) quotaFlashed = false;
  }

  function updateUI(data) {
    barLen = calcBarLen();
    lastData = data;
    publishSystem(data);

    els.cpuBar.innerHTML = pixelBar(data.cpu / 100);
    els.cpuVal.textContent = `${data.cpu}%`;

    if (data.gpu && data.gpu.available) {
      els.gpuBar.innerHTML = pixelBar(data.gpu.usage / 100);
      els.gpuVal.textContent = `${data.gpu.usage}%`;

      const vramPct = data.gpu.mem_total_gb
        ? data.gpu.mem_used_gb / data.gpu.mem_total_gb
        : 0;
      els.vramRow.classList.remove('is-hidden');
      els.vramBar.innerHTML = pixelBar(vramPct);
      els.vramVal.textContent = formatGbPair(data.gpu.mem_used_gb, data.gpu.mem_total_gb);
    } else {
      els.gpuBar.innerHTML = pixelBar(0);
      els.gpuVal.textContent = 'N/A';
      els.vramRow.classList.add('is-hidden');
    }

    const ram = data.ram;
    els.ramBar.innerHTML = pixelBar(ram.percent / 100);
    els.ramVal.textContent = formatGbPair(ram.used_gb, ram.total_gb);

    if (data.cursor && data.cursor.available) {
      const curPct = Number(data.cursor.auto_used_pct) || 0;
      const othPct = Number(data.cursor.api_used_pct) || 0;
      els.curBar.innerHTML = pixelBar(curPct / 100);
      els.curVal.textContent = `${curPct}%`;
      els.othBar.innerHTML = pixelBar(othPct / 100);
      els.othVal.textContent = `${othPct}%`;
      setWarn(els.curRow, curPct >= QUOTA_WARN);
      setWarn(els.othRow, othPct >= QUOTA_WARN);
      if (els.rstRow && els.rstVal) {
        const rst = data.cursor.reset_label || '';
        els.rstRow.classList.toggle('is-hidden', !rst);
        els.rstVal.textContent = rst || '--';
      }
      checkQuotaFlash(data.cursor);
    } else if (data.cursor && data.cursor.pending) {
      els.curBar.innerHTML = pixelBar(0);
      els.curVal.textContent = '--%';
      els.othBar.innerHTML = pixelBar(0);
      els.othVal.textContent = '--%';
      setWarn(els.curRow, false);
      setWarn(els.othRow, false);
      if (els.rstRow) els.rstRow.classList.add('is-hidden');
    } else {
      els.curBar.innerHTML = pixelBar(0);
      els.curVal.textContent = 'N/A';
      els.othBar.innerHTML = pixelBar(0);
      els.othVal.textContent = 'N/A';
      setWarn(els.curRow, false);
      setWarn(els.othRow, false);
      if (els.rstRow) els.rstRow.classList.add('is-hidden');
    }

    const gpuTemp =
      data.gpu && data.gpu.available && typeof data.gpu.temp_c === 'number'
        ? data.gpu.temp_c
        : null;
    const cpuTemp = typeof data.cpu_temp_c === 'number' ? data.cpu_temp_c : null;
    if (els.tmpRow && els.tmpSummary) {
      if (cpuTemp != null && gpuTemp != null) {
        els.tmpRow.classList.remove('is-hidden');
        els.tmpSummary.textContent = `${cpuTemp}° / ${gpuTemp}°`;
      } else if (gpuTemp != null) {
        els.tmpRow.classList.remove('is-hidden');
        els.tmpSummary.textContent = `${gpuTemp}°`;
      } else if (cpuTemp != null) {
        els.tmpRow.classList.remove('is-hidden');
        els.tmpSummary.textContent = `${cpuTemp}°`;
      } else {
        els.tmpRow.classList.add('is-hidden');
        els.tmpSummary.textContent = '--';
      }
    }

    if (els.keySummary) {
      const keys = data.keys || {};
      els.keySummary.textContent =
        `${formatKeys(keys.today)}   ${formatRate(keys.per_min)}`;
    }

    if (data.network) {
      els.netDown.textContent = data.network.download;
      els.netUp.textContent = data.network.upload;
    }

    renderDiskSummary(data.disks);

    if (data.ping) {
      els.pingHost.textContent = data.ping.host || '--';
      els.ping.textContent = data.ping.available ? data.ping.label : 'N/A';
    }

    if (data.uptime) {
      els.uptime.textContent = formatUptime(data.uptime.label);
    }

    if (data.weather && data.weather.available) {
      els.weather.textContent = data.weather.label;
      applyWeather(data.weather);
    } else {
      els.weather.textContent = '';
      sky.sunrise = '';
      sky.sunset = '';
    }
    renderWorld(new Date());
  }

  async function fetchSystem() {
    try {
      const res = await fetch('/api/system');
      if (!res.ok) throw new Error('API error');
      updateUI(await res.json());
    } catch {
      return;
    }
  }

  function skyWordFrom(w) {
    const d = String((w && w.description) || '').toLowerCase();
    if (d === 'clear' || d === 'mainly clear') return w && w.is_day === false ? 'clear' : 'sun';
    if (d === 'partly cloudy') return 'cloud';
    if (d === 'overcast') return 'overcast';
    if (d === 'fog') return 'fog';
    if (d === 'drizzle') return 'drizzle';
    if (d === 'rain') return 'rain';
    if (d === 'snow') return 'snow';
    if (d === 'showers') return 'showers';
    if (d === 'thunderstorm') return 'storm';
    return '';
  }

  function skyText(word) {
    const key = String(word || '').toLowerCase();
    return key ? key.toUpperCase() : '——';
  }

  function zoneTime(now, zone) {
    try {
      const parts = new Intl.DateTimeFormat('en-GB', {
        timeZone: zone,
        hour: '2-digit',
        minute: '2-digit',
        hourCycle: 'h23',
      }).formatToParts(now);
      const pick = (type) => (parts.find((p) => p.type === type) || {}).value || '--';
      return `${pick('hour')}:${pick('minute')}`;
    } catch {
      return '--:--';
    }
  }

  function skyWordFromCode(code, isDay) {
    const n = Number(code);
    if (n === 0 || n === 1) return isDay ? 'sun' : 'clear';
    if (n === 2) return 'cloud';
    if (n === 3) return 'overcast';
    if (n === 45 || n === 48) return 'fog';
    if (n === 51 || n === 53 || n === 55) return 'drizzle';
    if (n === 61 || n === 63 || n === 65) return 'rain';
    if (n === 71 || n === 73 || n === 75) return 'snow';
    if (n === 80 || n === 81 || n === 82) return 'showers';
    if (n === 95 || n === 96 || n === 99) return 'storm';
    return '';
  }

  function applyWeather(w) {
    sky.sunrise = String(w.sunrise || '');
    sky.sunset = String(w.sunset || '');
    CITIES.home.name = String(w.place || CITIES.home.name).trim() || 'BEIJING';
    CITIES.home.zone = String(w.timezone || CITIES.home.zone);
    CITIES.home.sky = String(w.sky || skyWordFrom(w)).trim();
    if (Array.isArray(w.places) && w.places.length) {
      w.places.forEach((p) => {
        const city = CITIES[p.key];
        if (!city) return;
        if (p.name) city.name = String(p.name);
        if (p.timezone) city.zone = String(p.timezone);
        city.sky = String(p.sky || '');
      });
      return;
    }
    loadExtraSkies();
  }

  function loadExtraSkies() {
    if (extraSkiesLoaded) return;
    extraSkiesLoaded = true;
    const specs = [
      ['lon', 51.5072, -0.1276],
      ['nyc', 40.7128, -74.006],
    ];
    specs.forEach(([key, lat, lon]) => {
      const url =
        'https://api.open-meteo.com/v1/forecast' +
        `?latitude=${lat}&longitude=${lon}` +
        '&current=weather_code,is_day&timezone=auto';
      fetch(url)
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => {
          const current = data && data.current;
          if (!current || !CITIES[key]) return;
          CITIES[key].sky = skyWordFromCode(current.weather_code, !!current.is_day);
          renderWorld(new Date());
        })
        .catch(() => {});
    });
  }

  function renderWorld(now) {
    const slots = [
      ['home', els.cityHomeName, els.cityHomeTime, els.cityHomeSky],
      ['lon', els.cityLonName, els.cityLonTime, els.cityLonSky],
      ['nyc', els.cityNycName, els.cityNycTime, els.cityNycSky],
    ];
    slots.forEach(([key, nameEl, timeEl, skyEl]) => {
      const city = CITIES[key];
      if (nameEl) nameEl.textContent = city.name;
      if (timeEl) timeEl.textContent = zoneTime(now, city.zone);
      if (skyEl) skyEl.textContent = skyText(city.sky);
    });
    if (els.worldRise) els.worldRise.textContent = sky.sunrise ? `↑ ${sky.sunrise}` : '';
    if (els.worldSet) els.worldSet.textContent = sky.sunset ? `↓ ${sky.sunset}` : '';
  }

  /** 月相按当地日期中午计算，一天只变一次。phase 0 新月，0.5 满月。 */
  function moonCycle(date) {
    let y = date.getFullYear();
    let m = date.getMonth() + 1;
    const day = date.getDate() + (date.getHours() + date.getMinutes() / 60) / 24;
    if (m <= 2) {
      y -= 1;
      m += 12;
    }
    const a = Math.floor(y / 100);
    const b = 2 - a + Math.floor(a / 4);
    const jd = Math.floor(365.25 * (y + 4716)) + Math.floor(30.6001 * (m + 1)) + day + b - 1524.5;
    const phase = (((jd - 2451550.1) / 29.530588853) % 1 + 1) % 1;
    const lit = (1 - Math.cos(phase * Math.PI * 2)) / 2;
    return { phase, lit };
  }

  function moonShadowPath(phase) {
    const cx = 50;
    const cy = 50;
    const r = 46;
    const k = Math.cos(phase * Math.PI * 2);
    const steps = 40;
    const pts = [];
    for (let i = 0; i <= steps; i += 1) {
      const y = -r + (2 * r * i) / steps;
      const limb = Math.sqrt(Math.max(0, r * r - y * y));
      const x = phase <= 0.5 ? -limb : -k * limb;
      pts.push([cx + x, cy + y]);
    }
    for (let i = steps; i >= 0; i -= 1) {
      const y = -r + (2 * r * i) / steps;
      const limb = Math.sqrt(Math.max(0, r * r - y * y));
      const x = phase <= 0.5 ? k * limb : limb;
      pts.push([cx + x, cy + y]);
    }
    return `M ${pts.map((p) => `${p[0].toFixed(2)} ${p[1].toFixed(2)}`).join(' L ')} Z`;
  }

  function renderMoon(now) {
    const key = `${now.getFullYear()}-${now.getMonth()}-${now.getDate()}`;
    if (key === moonKey) return;
    moonKey = key;
    const noon = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 12, 0, 0);
    const { phase, lit } = moonCycle(noon);
    const name = MOON_NAMES[Math.floor(((phase + 0.0625) % 1) * 8)] || '——';
    if (els.moonName) els.moonName.textContent = name;
    if (els.moonPct) els.moonPct.textContent = `${Math.round(lit * 100)}%`;
    if (els.moonMark) {
      const disk = phase < 0.02 || phase > 0.98;
      const full = phase > 0.48 && phase < 0.52;
      const shade = disk || full ? '' : `<path d="${moonShadowPath(phase)}" fill="currentColor"/>`;
      const fill = disk ? 'currentColor' : 'none';
      els.moonMark.innerHTML =
        `<svg viewBox="0 0 100 100" aria-hidden="true">` +
        `<circle cx="50" cy="50" r="46" fill="${fill}" stroke="currentColor" stroke-width="2.5"/>` +
        shade +
        `</svg>`;
    }
  }

  function tickLocalClock() {
    const now = new Date();
    const days = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];
    const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
                    'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];

    els.date.textContent =
      `${days[now.getDay()]} / ${months[now.getMonth()]} ${String(now.getDate()).padStart(2, '0')}`;

    els.timeText.textContent =
      `${String(now.getHours()).padStart(2, '0')}:` +
      `${String(now.getMinutes()).padStart(2, '0')}`;

    renderWorld(now);
    renderMoon(now);
  }

  tickLocalClock();
  setInterval(tickLocalClock, 1000);

  window.addEventListener('resize', () => {
    if (lastData) updateUI(lastData);
  });

  fetchSystem();
  setInterval(fetchSystem, POLL_INTERVAL);
})();
