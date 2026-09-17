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
    status: document.getElementById('system-status'),
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
  };

  const QUOTA_WARN = 80;
  let quotaSeen = false;
  let quotaFlashed = false;

  function calcBarLen() {
    const metrics = document.querySelector('.terminal__metrics');
    if (!metrics) return 16;
    const row = metrics.querySelector('.term-row');
    if (!row) return 16;
    const barEl = row.querySelector('.term-row__bar');
    if (!barEl) return 16;
    const style = getComputedStyle(row);
    const gap = parseFloat(style.columnGap) || 8;
    const cols = row.getBoundingClientRect().width;
    const labelW = row.querySelector('.term-row__label')?.getBoundingClientRect().width || 48;
    const valEl = row.querySelector('.term-row__val');
    const valW = valEl ? parseFloat(getComputedStyle(valEl).width) : 88;
    const barW = cols - labelW - valW - gap * 2;
    const charW = 7;
    return Math.max(12, Math.min(80, Math.floor(barW / charW)));
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
    } else {
      els.weather.textContent = '';
    }

    const line = els.status && els.status.parentElement;
    const focus = data.focus;
    if (focus && focus.available && focus.label) {
      els.status.textContent = focus.label;
      if (line) {
        line.classList.add('is-focus');
        line.classList.toggle('is-media', focus.kind === 'media');
      }
    } else {
      els.status.textContent = 'SYSTEM ONLINE';
      if (line) {
        line.classList.remove('is-focus', 'is-media');
      }
    }
  }

  async function fetchSystem() {
    try {
      const res = await fetch('/api/system');
      if (!res.ok) throw new Error('API error');
      updateUI(await res.json());
    } catch {
      els.status.textContent = 'SYSTEM OFFLINE';
      const line = els.status && els.status.parentElement;
      if (line) line.classList.remove('is-focus', 'is-media');
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
  }

  tickLocalClock();
  setInterval(tickLocalClock, 1000);

  window.addEventListener('resize', () => {
    if (lastData) updateUI(lastData);
  });

  fetchSystem();
  setInterval(fetchSystem, POLL_INTERVAL);
})();
