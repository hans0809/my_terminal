/**
 * Desk OS — EARTH
 * 叠在 FLIGHT 世界地图上。读本地 /api/earthquakes，不直接打 USGS。
 */

(function () {
  const World = window.DeskWorldMap;
  if (!World) return;

  const POLL_MS = 5000;
  const EARTHQUAKE_MIN_MAGNITUDE = 2;
  const homeSvg = document.getElementById('flight-svg');
  const pageSvg = document.getElementById('flight-page-svg');
  const homeStage = document.getElementById('flight-stage');
  const earthTag = document.getElementById('earth-tag');
  if (!homeSvg && !pageSvg) return;

  const views = [];
  if (homeSvg) {
    views.push({
      svg: homeSvg,
      layer: World.layer(homeSvg, 'earth-layer', '.flight-tracks'),
      pool: new Map(),
    });
  }
  if (pageSvg) {
    views.push({
      svg: pageSvg,
      layer: World.layer(pageSvg, 'earth-layer', '.flight-tracks'),
      pool: new Map(),
    });
  }

  let events = [];
  let updatedAt = null;
  let stale = true;
  let offline = true;
  let selected = '';
  let busy = false;
  let chromeSec = -1;

  function pad(n) {
    return String(n).padStart(2, '0');
  }

  function whenMs(value) {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? parsed : NaN;
  }

  function relTime(ms) {
    if (!Number.isFinite(ms)) return '--';
    const age = Date.now() - ms;
    if (age < 60 * 1000) return 'NOW';
    if (age < 60 * 60 * 1000) return `${Math.max(1, Math.floor(age / 60000))} MIN AGO`;
    const d = new Date(ms);
    if (Number.isNaN(d.getTime())) return '--';
    return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function clock(ms) {
    const d = new Date(ms);
    if (Number.isNaN(d.getTime())) return '--';
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }

  function magText(mag) {
    const n = Number(mag);
    if (!Number.isFinite(n)) return '--';
    return n.toFixed(1);
  }

  function placeText(place) {
    const text = String(place || '').trim();
    return text ? text.toUpperCase() : 'UNKNOWN';
  }

  function stateWord() {
    if (offline && !events.length) return 'OFFLINE';
    if (stale) return 'STALE';
    return 'LIVE';
  }

  function visible() {
    return events.filter((row) => row.magnitude >= EARTHQUAKE_MIN_MAGNITUDE);
  }

  function markOf(mag) {
    if (mag >= 7) return { dot: 10, halo: [18, 28, 40], ripple: 48, rings: 3, cls: 'is-m7 is-strong' };
    if (mag >= 6) return { dot: 8.5, halo: [16, 26], ripple: 36, rings: 2, cls: 'is-strong' };
    if (mag >= 4) return { dot: 7, halo: [16], ripple: 28, rings: 1, cls: 'is-strong' };
    return { dot: 5.4, halo: [12], ripple: 0, rings: 0, cls: '' };
  }

  function cleanList(list) {
    const out = [];
    if (!Array.isArray(list)) return out;
    list.forEach((row) => {
      try {
        if (!row || typeof row.id !== 'string' || !row.id) return;
        const lat = Number(row.lat);
        const lon = Number(row.lon);
        const mag = Number(row.magnitude);
        if (!Number.isFinite(lat) || !Number.isFinite(lon) || !Number.isFinite(mag)) return;
        if (lon < -180 || lon > 180 || lat < -90 || lat > 90) return;
        const ms = whenMs(row.time);
        if (!Number.isFinite(ms)) return;
        out.push({
          id: row.id,
          magnitude: mag,
          place: String(row.place || '').trim(),
          time: ms,
          lat,
          lon,
          depth: row.depth == null || row.depth === '' ? null : Number(row.depth),
        });
      } catch {
        /* 单条异常不影响其余 */
      }
    });
    out.sort((a, b) => b.time - a.time);
    return out;
  }

  function apply(data) {
    const next = cleanList(data && data.events);
    const nextAt = data && data.updated_at ? data.updated_at : null;
    const nextStale = !!(data && data.stale);
    if (!next.length && nextStale && events.length) {
      stale = true;
      offline = false;
      paintChrome(true);
      return;
    }
    events = next;
    updatedAt = nextAt;
    stale = nextStale || !nextAt;
    offline = !events.length && (stale || !nextAt);
    if (selected && !events.some((row) => row.id === selected)) selected = '';
    draw();
    paintChrome(true);
  }

  function applyFail() {
    if (events.length) {
      stale = true;
      offline = false;
      paintChrome(true);
      return;
    }
    stale = true;
    offline = true;
    paintChrome(true);
  }

  function paintChrome(force) {
    const sec = Math.floor(Date.now() / 1000);
    if (!force && sec === chromeSec) return;
    chromeSec = sec;
    const word = stateWord();
    const live = word === 'LIVE';
    const shown = visible();
    const latest = shown[0];
    const latestText = latest
      ? `M${magText(latest.magnitude)}  ${placeText(latest.place)}`
      : '—';
    const countText = offline && !shown.length ? '-- EVENTS' : `${shown.length} EVENTS`;
    ['earth-latest', 'earth-page-latest'].forEach((id) => {
      const node = document.getElementById(id);
      if (node) node.textContent = latestText;
    });
    ['earth-count', 'earth-page-count'].forEach((id) => {
      const node = document.getElementById(id);
      if (node) node.textContent = countText;
    });
    ['earth-state', 'earth-page-state'].forEach((id) => {
      const node = document.getElementById(id);
      if (!node) return;
      node.textContent = word;
      node.classList.toggle('is-live', live);
    });
    views.forEach((view) => {
      if (view.layer) view.layer.classList.toggle('is-off', word === 'OFFLINE');
    });
    paintTag();
  }

  function paintTag() {
    if (!earthTag) return;
    const row = selected ? events.find((item) => item.id === selected) : null;
    if (!row) {
      earthTag.hidden = true;
      earthTag.textContent = '';
      return;
    }
    const depth = Number(row.depth);
    const depthText = Number.isFinite(depth) ? `${Math.round(depth)} km` : '--';
    earthTag.hidden = false;
    earthTag.textContent = `M ${magText(row.magnitude)}\n${placeText(row.place)}\nDEPTH ${depthText}\n${clock(row.time)}`;
    placeTag();
  }

  function placeTag() {
    if (!earthTag || earthTag.hidden || !homeStage) return;
    const home = views.find((view) => view.svg === homeSvg);
    const node = home && home.pool.get(selected);
    if (!node) return;
    const stage = homeStage.getBoundingClientRect();
    const icon = node.g.getBoundingClientRect();
    if (stage.width < 8 || icon.width < 1) return;
    const gap = 8;
    let left = icon.right - stage.left + gap;
    let top = icon.top - stage.top;
    const tagW = earthTag.offsetWidth;
    const tagH = earthTag.offsetHeight;
    if (left + tagW > stage.width - 4) left = icon.left - stage.left - gap - tagW;
    if (top + tagH > stage.height - 2) top = stage.height - tagH - 2;
    left = Math.max(2, Math.min(left, stage.width - tagW - 2));
    top = Math.max(2, top);
    earthTag.style.left = `${Math.round(left)}px`;
    earthTag.style.top = `${Math.round(top)}px`;
  }

  function hideTag() {
    if (!selected) return;
    selected = '';
    syncPick();
    paintTag();
  }

  function selectQuake(id) {
    selected = id || '';
    syncPick();
    paintTag();
  }

  function syncPick() {
    views.forEach((view) => {
      view.pool.forEach((node, id) => {
        node.g.classList.toggle('is-on', id === selected);
      });
    });
  }

  function ensureMark(view, row, latestId) {
    let node = view.pool.get(row.id);
    const spec = markOf(row.magnitude);
    if (!node) {
      const g = World.el('g');
      g.setAttribute('class', `earth-quake ${spec.cls}`.trim());
      g.dataset.id = row.id;
      const hit = World.el('circle');
      hit.setAttribute('class', 'earth-hit');
      hit.setAttribute('fill', 'transparent');
      const halos = [];
      (spec.halo || []).forEach(() => {
        const ring = World.el('circle');
        ring.setAttribute('class', 'earth-halo');
        ring.setAttribute('cx', '0');
        ring.setAttribute('cy', '0');
        g.appendChild(ring);
        halos.push(ring);
      });
      const ripples = [];
      for (let i = 0; i < spec.rings; i += 1) {
        const ring = World.el('circle');
        ring.setAttribute('class', `earth-ripple earth-ripple--${i}`);
        ring.setAttribute('cx', '0');
        ring.setAttribute('cy', '0');
        g.appendChild(ring);
        ripples.push(ring);
      }
      const dot = World.el('circle');
      dot.setAttribute('class', 'earth-dot');
      dot.setAttribute('cx', '0');
      dot.setAttribute('cy', '0');
      g.append(hit, dot);
      view.layer.appendChild(g);
      if (ripples.length) {
        const last = ripples[ripples.length - 1];
        last.addEventListener('animationend', () => {
          g.classList.add('is-played');
        });
      } else {
        g.classList.add('is-played');
      }
      node = { g, hit, dot, halos, ripples, mag: row.magnitude };
      view.pool.set(row.id, node);
    }
    const xy = World.project(row.lon, row.lat);
    node.g.setAttribute('transform', `translate(${xy[0].toFixed(1)} ${xy[1].toFixed(1)})`);
    node.g.classList.toggle('is-latest', row.id === latestId);
    node.g.classList.toggle('is-on', row.id === selected);
    node.g.classList.toggle('is-fresh', Date.now() - row.time < 3 * 60 * 1000);
    return node;
  }

  function sizeMark(view, node, mag) {
    const spec = markOf(mag);
    const unit = (px) => World.pxToUser(view.svg, px);
    const latest = node.g.classList.contains('is-latest');
    const bump = latest ? 1.16 : 1;
    node.dot.setAttribute('r', unit(spec.dot * bump).toFixed(2));
    node.hit.setAttribute('r', unit(Math.max(16, spec.dot * 2.8)).toFixed(2));
    (node.halos || []).forEach((ring, i) => {
      const size = (spec.halo && spec.halo[i]) || spec.dot * (2 + i);
      ring.setAttribute('r', unit(size * bump).toFixed(2));
    });
    node.ripples.forEach((ring, i) => {
      const grow = spec.ripple * (0.72 + i * 0.28) * bump;
      ring.setAttribute('r', unit(grow).toFixed(2));
    });
  }

  function draw() {
    const shown = visible();
    const latestId = shown.length ? shown[0].id : '';
    const live = new Set(shown.map((row) => row.id));
    views.forEach((view) => {
      if (!view.layer) return;
      shown.forEach((row) => {
        const node = ensureMark(view, row, latestId);
        sizeMark(view, node, row.magnitude);
      });
      view.pool.forEach((node, id) => {
        if (live.has(id)) return;
        node.g.remove();
        view.pool.delete(id);
        if (selected === id) selected = '';
      });
    });
    paintTag();
  }

  async function poll() {
    if (busy) return;
    const crt = document.getElementById('crt-monitor');
    if (crt && !crt.classList.contains('is-on')) return;
    if (document.visibilityState === 'hidden') return;
    busy = true;
    const ctrl = new AbortController();
    const kill = setTimeout(() => ctrl.abort(), 8000);
    try {
      const res = await fetch('/api/earthquakes', { signal: ctrl.signal });
      if (!res.ok) throw new Error(String(res.status));
      apply(await res.json());
    } catch {
      applyFail();
    } finally {
      clearTimeout(kill);
      busy = false;
    }
  }

  window.addEventListener('desk-map-layer', (event) => {
    if (!event.detail || event.detail.layer !== 'earth') hideTag();
  });

  function onStagePointer(event) {
    const hit = document.elementFromPoint(event.clientX, event.clientY);
    const quake = hit && hit.closest ? hit.closest('.earth-quake') : null;
    if (quake && (homeSvg && homeSvg.contains(quake) || pageSvg && pageSvg.contains(quake))) {
      selectQuake(quake.dataset.id || '');
      return;
    }
    if (hit && hit.closest && hit.closest('#earth-tag')) return;
    hideTag();
  }

  if (homeStage) {
    homeStage.addEventListener('pointerup', onStagePointer);
  }
  const pageStage = document.getElementById('flight-page-stage');
  if (pageStage) {
    pageStage.addEventListener('click', (event) => {
      const quake = event.target.closest && event.target.closest('.earth-quake');
      if (quake) {
        event.stopPropagation();
        selectQuake(quake.dataset.id || '');
        return;
      }
      hideTag();
    });
  }

  document.addEventListener('pointerdown', (event) => {
    const node = event.target;
    if (node.closest && (node.closest('.earth-quake') || node.closest('#earth-tag'))) return;
    hideTag();
  });

  views.forEach((view) => {
    const watch = new MutationObserver(() => {
      view.pool.forEach((node, id) => {
        const row = events.find((item) => item.id === id);
        if (row) sizeMark(view, node, row.magnitude);
      });
      placeTag();
    });
    watch.observe(view.svg, { attributes: true, attributeFilter: ['viewBox'] });
  });

  window.addEventListener('resize', () => {
    draw();
  });

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible') return;
    poll();
  });

  paintChrome(true);
  poll();
  setInterval(poll, POLL_MS);
  setInterval(() => paintChrome(false), 1000);
})();
