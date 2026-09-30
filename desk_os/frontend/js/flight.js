/**
 * Desk OS — FLIGHT
 * 主页小地图 + 全屏页。位置在两次刷新之间插值，航迹最多 8 点。
 */

(function () {
  const VB_W = 3600;
  const VB_H = 1800;
  const POLL_MS = 8000;
  const TRACK_MAX = 8;
  const LIMIT_STEP = { max_draw: 100, warm_max: 100, route_draw: 10 };
  const LIMIT_FALLBACK = { max_draw: 900, warm_max: 900, route_draw: 80 };
  const TRACK_TTL = 40000;
  const NS = 'http://www.w3.org/2000/svg';
  const PLANE = 'M0 -1.35 L0.28 -0.15 L1.05 0.2 L0.28 0.02 L0.22 0.85 L0 0.48 L-0.22 0.85 L-0.28 0.02 L-1.05 0.2 L-0.28 -0.15 Z';

  const home = document.getElementById('flight-home');
  const homeSvg = document.getElementById('flight-svg');
  const pageSvg = document.getElementById('flight-page-svg');
  const pageStage = document.getElementById('flight-page-stage');
  const flightTag = document.getElementById('flight-tag');
  const homeStage = document.getElementById('flight-stage');
  const routes = new Map();
  const viewBox = { x: 0, y: 0, w: VB_W, h: VB_H };
  const ZOOM_MIN_W = VB_W / 192;
  if (!homeSvg || !pageSvg) return;

  const HOME = { lon: 116.4, lat: 39.9 };
  const views = [bindView(homeSvg, false), bindView(pageSvg, true)];
  const tracks = new Map();
  const motion = new Map();
  const latest = new Map();
  const limitEls = {
    max_draw: document.getElementById('flight-max-draw'),
    warm_max: document.getElementById('flight-warm-max'),
    route_draw: document.getElementById('flight-route-draw'),
  };
  let routeDraw = 80;
  let limitTimer = 0;
  let limitSeq = 0;
  let payload = null;
  let selected = '';
  let busy = false;
  let raf = 0;
  let chromeSec = -1;

  const planePath = new Path2D(PLANE);

  function el(name) {
    return document.createElementNS(NS, name);
  }

  function mountCraftCanvas(svg) {
    const stage = svg.parentElement;
    if (!stage) return null;
    const canvas = document.createElement('canvas');
    canvas.className = 'flight-craft-canvas';
    canvas.setAttribute('aria-hidden', 'true');
    stage.appendChild(canvas);
    return canvas;
  }

  function craftPx(svg) {
    const box = mapBox(svg);
    const zoom = VB_W / Math.max(box.w, 1);
    return Math.min(26, 4.2 * Math.pow(zoom, 0.62));
  }

  function ensureRouteLayer(svg) {
    let layer = svg.querySelector('.flight-route');
    if (layer) return layer;
    layer = el('g');
    layer.setAttribute('class', 'flight-route');
    const tracks = svg.querySelector('.flight-tracks');
    if (tracks) svg.insertBefore(layer, tracks);
    else svg.appendChild(layer);
    return layer;
  }

  function bindView(svg, page) {
    const view = {
      svg,
      page,
      grid: svg.querySelector('.flight-grid'),
      land: svg.querySelector('.flight-land'),
      borders: svg.querySelector('.flight-borders'),
      cities: svg.querySelector('.flight-cities'),
      cityNodes: [],
      tracks: svg.querySelector('.flight-tracks'),
      route: ensureRouteLayer(svg),
      craft: svg.querySelector('.flight-craft'),
      me: svg.querySelector('.flight-me'),
      meMark: null,
      pool: new Map(),
      trails: new Map(),
      canvas: mountCraftCanvas(svg),
    };
    drawGrid(view.grid);
    drawMe(view);
    return view;
  }

  function drawMe(view) {
    const g = view.me;
    if (!g || g.childNodes.length) return;
    const xy = project(HOME.lon, HOME.lat);
    const mark = el('g');
    mark.setAttribute('transform', `translate(${xy[0].toFixed(1)} ${xy[1].toFixed(1)})`);
    const ring = el('circle');
    const h = el('line');
    h.setAttribute('y1', '0');
    h.setAttribute('y2', '0');
    const v = el('line');
    v.setAttribute('x1', '0');
    v.setAttribute('x2', '0');
    mark.append(ring, h, v);
    g.appendChild(mark);
    view.meMark = { ring, h, v };
  }

  function refreshMe() {
    views.forEach((view) => {
      if (!view.meMark) return;
      const width = view.svg.getBoundingClientRect().width;
      if (width < 8) return;
      const span = Math.max(mapBox(view.svg).w, 1);
      const arm = (8 / width) * span;
      view.meMark.ring.setAttribute('r', (arm * 0.62).toFixed(2));
      view.meMark.h.setAttribute('x1', (-arm).toFixed(2));
      view.meMark.h.setAttribute('x2', arm.toFixed(2));
      view.meMark.v.setAttribute('y1', (-arm).toFixed(2));
      view.meMark.v.setAttribute('y2', arm.toFixed(2));
    });
  }

  function goNearHome() {
    const xy = project(HOME.lon, HOME.lat);
    viewBox.w = VB_W / 18;
    viewBox.h = viewBox.w * (VB_H / VB_W);
    viewBox.x = xy[0] - viewBox.w / 2;
    viewBox.y = xy[1] - viewBox.h / 2;
    clampView();
    applyView();
  }

  function drawGrid(g) {
    if (!g || g.childNodes.length) return;
    for (let lon = -150; lon <= 150; lon += 30) {
      const x = ((lon + 180) / 360) * VB_W;
      const line = el('line');
      line.setAttribute('x1', String(x));
      line.setAttribute('x2', String(x));
      line.setAttribute('y1', '0');
      line.setAttribute('y2', String(VB_H));
      g.appendChild(line);
    }
    for (let lat = -60; lat <= 60; lat += 30) {
      const y = ((90 - lat) / 180) * VB_H;
      const line = el('line');
      line.setAttribute('y1', String(y));
      line.setAttribute('y2', String(y));
      line.setAttribute('x1', '0');
      line.setAttribute('x2', String(VB_W));
      g.appendChild(line);
    }
  }

  function project(lon, lat) {
    return [
      ((lon + 180) / 360) * VB_W,
      ((90 - lat) / 180) * VB_H,
    ];
  }

  function crosses(a, b) {
    return Math.abs(b - a) > 180;
  }

  function lerp(a, b, t) {
    return a + (b - a) * t;
  }

  function lerpLon(a, b, t) {
    let delta = b - a;
    if (delta > 180) delta -= 360;
    if (delta < -180) delta += 360;
    let lon = a + delta * t;
    if (lon > 180) lon -= 360;
    if (lon < -180) lon += 360;
    return lon;
  }

  function lerpHeading(a, b, t) {
    let delta = ((b - a + 540) % 360) - 180;
    return a + delta * t;
  }

  function pose(entry, now) {
    const elapsed = now - entry.t0;
    const t = entry.dur <= 0 ? 1 : Math.min(1, elapsed / entry.dur);
    let lon = lerpLon(entry.fromLon, entry.toLon, t);
    let lat = lerp(entry.fromLat, entry.toLat, t);
    const heading = lerpHeading(entry.fromHdg, entry.toHdg, t);
    const speed = Number(entry.speed) || 0;
    if (t >= 1 && speed > 1) {
      const extra = Math.min(20 * 60, Math.max(0, (elapsed - entry.dur) / 1000));
      const dist = speed * extra;
      const rad = heading * Math.PI / 180;
      const dLat = (dist * Math.cos(rad)) / 111320;
      const cosLat = Math.cos(lat * Math.PI / 180);
      const dLon = (dist * Math.sin(rad)) / (111320 * (Math.abs(cosLat) < 0.2 ? 0.2 : cosLat));
      lat = Math.max(-85, Math.min(85, lat + dLat));
      lon += dLon;
      if (lon > 180) lon -= 360;
      if (lon < -180) lon += 360;
    }
    return { lon, lat, heading };
  }

  function currentPose(id, now) {
    const entry = motion.get(id);
    if (!entry) return null;
    return pose(entry, now);
  }

  function cleanList(list) {
    const out = [];
    if (!Array.isArray(list)) return out;
    list.forEach((row) => {
      try {
        if (!row || typeof row.icao24 !== 'string' || !row.icao24) return;
        const lat = Number(row.lat);
        const lon = Number(row.lon);
        if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
        if (row.on_ground === true) return;
        const heading = Number(row.heading);
        const originLat = Number(row.origin_lat);
        const originLon = Number(row.origin_lon);
        const destinationLat = Number(row.destination_lat);
        const destinationLon = Number(row.destination_lon);
        out.push({
          icao24: row.icao24,
          callsign: String(row.callsign || row.icao24).trim() || row.icao24.toUpperCase(),
          lat,
          lon,
          altitude: row.altitude == null || row.altitude === '' ? null : Number(row.altitude),
          velocity: Number(row.velocity) || 0,
          heading: Number.isFinite(heading) ? heading : 0,
          origin: String(row.origin || '').trim(),
          destination: String(row.destination || '').trim(),
          originLat: Number.isFinite(originLat) ? originLat : null,
          originLon: Number.isFinite(originLon) ? originLon : null,
          destinationLat: Number.isFinite(destinationLat) ? destinationLat : null,
          destinationLon: Number.isFinite(destinationLon) ? destinationLon : null,
        });
      } catch {
        /* 单架异常不影响其余 */
      }
    });
    return out;
  }

  function pushTrack(id, lon, lat, now) {
    let track = tracks.get(id);
    if (!track) {
      track = { segs: [[{ lon, lat }]], seen: now };
      tracks.set(id, track);
      return;
    }
    track.seen = now;
    const seg = track.segs[track.segs.length - 1];
    const last = seg[seg.length - 1];
    if (last && last.lon === lon && last.lat === lat) return;
    if (last && crosses(last.lon, lon)) track.segs.push([{ lon, lat }]);
    else seg.push({ lon, lat });
    let count = 0;
    track.segs.forEach((part) => {
      count += part.length;
    });
    while (count > TRACK_MAX && track.segs.length) {
      track.segs[0].shift();
      count -= 1;
      if (!track.segs[0].length) track.segs.shift();
    }
  }

  function dropStale(now, live) {
    let removed = false;
    tracks.forEach((track, id) => {
      if (live.has(id)) return;
      if (now - track.seen > TRACK_TTL) {
        tracks.delete(id);
        motion.delete(id);
        latest.delete(id);
        if (selected === id) selected = '';
        removed = true;
      }
    });
    return removed;
  }

  function ingest(list) {
    const now = performance.now();
    const wall = Date.now();
    const live = new Set();
    latest.clear();
    list.forEach((plane) => {
      live.add(plane.icao24);
      latest.set(plane.icao24, plane);
      const prev = motion.get(plane.icao24);
      let fromLon = plane.lon;
      let fromLat = plane.lat;
      let fromHdg = plane.heading;
      if (prev) {
        const at = pose(prev, now);
        fromLon = at.lon;
        fromLat = at.lat;
        fromHdg = at.heading;
      }
      motion.set(plane.icao24, {
        fromLon,
        fromLat,
        fromHdg,
        toLon: plane.lon,
        toLat: plane.lat,
        toHdg: plane.heading,
        t0: now,
        dur: POLL_MS,
        speed: Number(plane.velocity) || 0,
      });
      pushTrack(plane.icao24, plane.lon, plane.lat, wall);
    });
    dropStale(wall, live);
    views.forEach((view) => { if (viewOn(view)) drawTrails(view); });
  }

  function apply(data) {
    const nextAt = data && data.updated_at ? data.updated_at : null;
    const same = !!(payload && payload.updated_at && nextAt && nextAt === payload.updated_at);
    payload = {
      updated_at: nextAt,
      stale: !!(data && data.stale),
      offline: !!(data && data.offline),
      count: data && Number.isFinite(Number(data.count)) ? Number(data.count) : 0,
      aircraft: cleanList(data && data.aircraft),
    };
    if (!payload.aircraft.length && payload.offline) payload.count = 0;
    absorbRoutes(payload.aircraft);
    if (!same) ingest(payload.aircraft);
    paintChrome(true);
    scheduleWarm();
  }

  function applyFail() {
    if (payload && payload.aircraft.length) {
      payload.stale = true;
      payload.offline = false;
      paintChrome(true);
      return;
    }
    payload = {
      updated_at: payload && payload.updated_at,
      stale: true,
      offline: true,
      count: 0,
      aircraft: [],
    };
    paintChrome(true);
  }

  function ageLabel(iso) {
    if (!iso) return 'UPDATE --';
    const then = Date.parse(iso);
    if (!Number.isFinite(then)) return 'UPDATE --';
    const sec = Math.max(0, Math.round((Date.now() - then) / 1000));
    if (sec < 60) return `UPDATE ${sec}s`;
    return `UPDATE ${Math.floor(sec / 60)}m`;
  }

  function stateWord() {
    if (!payload) return '--';
    if (payload.offline) return 'OFFLINE';
    if (payload.stale) return 'STALE';
    return 'LIVE';
  }

  function paintChrome(force) {
    const sec = Math.floor(Date.now() / 1000);
    if (!force && sec === chromeSec) return;
    chromeSec = sec;
    const word = stateWord();
    const live = word === 'LIVE';
    const count = !payload || payload.offline ? '-- AIRCRAFT' : `${payload.count} AIRCRAFT`;
    const age = ageLabel(payload && payload.updated_at);
    ['flight-state', 'flight-state-2', 'flight-page-state'].forEach((id) => {
      const node = document.getElementById(id);
      if (!node) return;
      node.textContent = word;
      node.classList.toggle('is-live', live);
    });
    const countHome = document.getElementById('flight-count');
    const countPage = document.getElementById('flight-page-count');
    const ageHome = document.getElementById('flight-age');
    const agePage = document.getElementById('flight-page-age');
    if (countHome) countHome.textContent = count;
    if (countPage) countPage.textContent = count;
    if (ageHome) ageHome.textContent = age;
    if (agePage) agePage.textContent = age;
    if (home) home.classList.toggle('is-offline', word === 'OFFLINE');
    const page = document.getElementById('app-flight');
    if (page) page.classList.toggle('is-offline', word === 'OFFLINE');
    paintDetail();
  }

  function fmtFt(meters) {
    const value = Number(meters);
    if (!Number.isFinite(value)) return '--';
    const feet = Math.round(value * 3.2808399);
    const sign = feet < 0 ? '-' : '';
    const body = String(Math.abs(feet)).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    return `${sign}${body}`;
  }

  function paintDetail() {
    const detail = document.getElementById('flight-detail');
    const plane = selected ? latest.get(selected) : null;
    if (!plane) {
      if (flightTag) {
        flightTag.hidden = true;
        flightTag.textContent = '';
      }
      if (detail) {
        detail.textContent = '';
        detail.classList.remove('is-on');
      }
      drawRoute(null);
      return;
    }
    const route = routes.get(routeKey(plane.callsign));
    let line = '…';
    if (route && !route.pending) {
      line = route.origin && route.destination
        ? `${route.origin} → ${route.destination}`
        : 'ROUTE --';
    }
    const hdg = String(Math.round(((plane.heading % 360) + 360) % 360)).padStart(3, '0');
    const text = `${plane.callsign}\n${line}\nALT ${fmtFt(plane.altitude)} ft\nHDG ${hdg}`;
    if (flightTag) {
      flightTag.hidden = false;
      flightTag.textContent = text;
      placeTag();
    }
    if (detail) {
      detail.textContent = text;
      detail.classList.add('is-on');
    }
    drawRoute(route && !route.pending ? route : null);
  }

  function finitePair(lat, lon) {
    return Number.isFinite(lat) && Number.isFinite(lon);
  }

  function routeArcs(route) {
    if (!route || !finitePair(route.originLat, route.originLon)) return [];
    if (!finitePair(route.destinationLat, route.destinationLon)) return [];
    const steps = 64;
    const φ1 = route.originLat * Math.PI / 180;
    const λ1 = route.originLon * Math.PI / 180;
    const φ2 = route.destinationLat * Math.PI / 180;
    const λ2 = route.destinationLon * Math.PI / 180;
    const hav = Math.sin((φ2 - φ1) / 2) ** 2
      + Math.cos(φ1) * Math.cos(φ2) * Math.sin((λ2 - λ1) / 2) ** 2;
    const delta = 2 * Math.asin(Math.min(1, Math.sqrt(hav)));
    if (!Number.isFinite(delta) || delta < 1e-4) return [];
    const pts = [];
    for (let i = 0; i <= steps; i += 1) {
      const f = i / steps;
      const a = Math.sin((1 - f) * delta) / Math.sin(delta);
      const b = Math.sin(f * delta) / Math.sin(delta);
      const x = a * Math.cos(φ1) * Math.cos(λ1) + b * Math.cos(φ2) * Math.cos(λ2);
      const y = a * Math.cos(φ1) * Math.sin(λ1) + b * Math.cos(φ2) * Math.sin(λ2);
      const z = a * Math.sin(φ1) + b * Math.sin(φ2);
      pts.push({
        lon: Math.atan2(y, x) * 180 / Math.PI,
        lat: Math.atan2(z, Math.hypot(x, y)) * 180 / Math.PI,
      });
    }
    const arcs = [];
    let cur = [];
    pts.forEach((pt, index) => {
      if (index && crosses(pts[index - 1].lon, pt.lon)) {
        if (cur.length > 1) arcs.push(cur);
        cur = [pt];
      } else {
        cur.push(pt);
      }
    });
    if (cur.length > 1) arcs.push(cur);
    return arcs;
  }

  function drawRoute(route) {
    const arcs = routeArcs(route);
    views.forEach((view) => {
      if (!view.route) return;
      while (view.route.firstChild) view.route.firstChild.remove();
      arcs.forEach((arc) => {
        const path = el('path');
        path.setAttribute('d', arc.map((pt, index) => {
          const xy = project(pt.lon, pt.lat);
          return `${index ? 'L' : 'M'}${xy[0].toFixed(1)} ${xy[1].toFixed(1)}`;
        }).join(' '));
        view.route.appendChild(path);
      });
    });
  }

  function screenPoint(svg, lon, lat) {
    const rect = svg.getBoundingClientRect();
    const box = mapBox(svg);
    const xy = project(lon, lat);
    return {
      rect,
      x: ((xy[0] - box.x) / Math.max(box.w, 1)) * rect.width,
      y: ((xy[1] - box.y) / Math.max(box.h, 1)) * rect.height,
    };
  }

  function planeAtPoint(svg, clientX, clientY) {
    if (!svg) return null;
    const rect = svg.getBoundingClientRect();
    if (rect.width < 8 || rect.height < 8) return null;
    const px = clientX - rect.left;
    const py = clientY - rect.top;
    const hit = craftPx(svg) + 8;
    let best = null;
    let bestD = hit * hit;
    const now = performance.now();
    latest.forEach((plane, id) => {
      const at = currentPose(id, now);
      if (!at) return;
      const pt = screenPoint(svg, at.lon, at.lat);
      const d = (pt.x - px) * (pt.x - px) + (pt.y - py) * (pt.y - py);
      if (d < bestD) {
        bestD = d;
        best = plane;
      }
    });
    return best;
  }

  function drawCraft(view, now) {
    const canvas = view.canvas;
    const svg = view.svg;
    if (!canvas || !svg) return;
    const rect = svg.getBoundingClientRect();
    if (rect.width < 8 || rect.height < 8) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.round(rect.width * dpr));
    const h = Math.max(1, Math.round(rect.height * dpr));
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, rect.width, rect.height);
    const px = craftPx(svg);
    const color = getComputedStyle(view.craft || svg).color || '#222';
    ctx.fillStyle = color;
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    latest.forEach((_plane, id) => {
      const at = currentPose(id, now);
      if (!at) return;
      const pt = screenPoint(svg, at.lon, at.lat);
      if (pt.x < -24 || pt.y < -24 || pt.x > rect.width + 24 || pt.y > rect.height + 24) return;
      ctx.save();
      ctx.translate(pt.x, pt.y);
      ctx.rotate(at.heading * Math.PI / 180);
      const s = px / 2.2;
      ctx.scale(s, s);
      ctx.fill(planePath);
      ctx.restore();
      if (id === selected) {
        ctx.strokeRect(pt.x - px * 0.65, pt.y - px * 0.75, px * 1.3, px * 1.5);
      }
    });
  }

  function placeTag() {
    if (!flightTag || flightTag.hidden || !homeStage || !homeSvg || !selected) return;
    const at = currentPose(selected, performance.now());
    if (!at) return;
    const stage = homeStage.getBoundingClientRect();
    const pt = screenPoint(homeSvg, at.lon, at.lat);
    if (stage.width < 8 || pt.rect.width < 8) return;
    const px = craftPx(homeSvg);
    const gap = 8;
    let left = pt.rect.left - stage.left + pt.x + px * 0.5 + gap;
    let top = pt.rect.top - stage.top + pt.y - px * 0.5;
    const tagW = flightTag.offsetWidth;
    const tagH = flightTag.offsetHeight;
    if (left + tagW > stage.width - 4) left = pt.rect.left - stage.left + pt.x - px * 0.5 - gap - tagW;
    if (top + tagH > stage.height - 2) top = stage.height - tagH - 2;
    left = Math.max(2, Math.min(left, stage.width - tagW - 2));
    top = Math.max(2, top);
    flightTag.style.left = `${Math.round(left)}px`;
    flightTag.style.top = `${Math.round(top)}px`;
  }

  function resetView() {
    viewBox.x = 0;
    viewBox.y = 0;
    viewBox.w = VB_W;
    viewBox.h = VB_H;
    applyView();
  }

  function hideTag() {
    if (!selected) return;
    selected = '';
    paintDetail();
    views.forEach(syncPick);
  }

  function clearFlight() {
    hideTag();
    resetView();
  }

  const routeQueue = [];
  const routeQueued = new Set();
  let routeWorkers = 0;
  let warmTimer = 0;

  function routeKey(callsign) {
    return String(callsign || '').trim().toUpperCase();
  }

  function readRoute(data) {
    const originLat = Number(data && (data.originLat != null ? data.originLat : data.origin_lat));
    const originLon = Number(data && (data.originLon != null ? data.originLon : data.origin_lon));
    const destinationLat = Number(data && (data.destinationLat != null ? data.destinationLat : data.destination_lat));
    const destinationLon = Number(data && (data.destinationLon != null ? data.destinationLon : data.destination_lon));
    return {
      pending: false,
      origin: String((data && data.origin) || '').trim(),
      destination: String((data && data.destination) || '').trim(),
      originLat: Number.isFinite(originLat) ? originLat : null,
      originLon: Number.isFinite(originLon) ? originLon : null,
      destinationLat: Number.isFinite(destinationLat) ? destinationLat : null,
      destinationLon: Number.isFinite(destinationLon) ? destinationLon : null,
    };
  }

  function rememberRoute(callsign, data) {
    const key = routeKey(callsign || (data && data.callsign));
    if (!key) return;
    routes.set(key, readRoute(data));
  }

  function absorbRoutes(list) {
    if (!Array.isArray(list)) return;
    list.forEach((plane) => {
      if (!plane || !plane.origin || !plane.destination) return;
      rememberRoute(plane.callsign, plane);
    });
  }

  function startRoute(key) {
    const known = routes.get(key);
    if (!key || key.length < 3) return;
    if (known && !known.pending) return;
    if (known && known.pending) return;
    const plane = [...latest.values()].find((item) => routeKey(item.callsign) === key);
    const qs = new URLSearchParams({ callsign: key });
    if (plane && Number.isFinite(plane.lat)) qs.set('lat', String(plane.lat));
    if (plane && Number.isFinite(plane.lon)) qs.set('lon', String(plane.lon));
    routes.set(key, { pending: true, origin: '', destination: '' });
    routeWorkers += 1;
    fetch(`/api/flights/route?${qs.toString()}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error('route'))))
      .then((data) => {
        rememberRoute(key, data);
        paintDetail();
      })
      .catch(() => {
        routes.set(key, { pending: false, origin: '', destination: '' });
        paintDetail();
      })
      .finally(() => {
        routeWorkers -= 1;
        pumpRoutes();
      });
  }

  function pumpRoutes() {
    while (routeWorkers < 8 && routeQueue.length) {
      const key = routeQueue.shift();
      routeQueued.delete(key);
      const known = routes.get(key);
      if (known) continue;
      startRoute(key);
    }
  }

  function enqueueRoute(callsign, front) {
    const key = routeKey(callsign);
    if (!key || key.length < 3) return;
    if (routes.has(key)) return;
    if (routeQueued.has(key)) {
      if (!front) return;
      const at = routeQueue.indexOf(key);
      if (at > 0) {
        routeQueue.splice(at, 1);
        routeQueue.unshift(key);
      }
      return;
    }
    routeQueued.add(key);
    if (front) routeQueue.unshift(key);
    else routeQueue.push(key);
    pumpRoutes();
  }

  function askRoute(callsign) {
    const key = routeKey(callsign);
    if (!key) return;
    const known = routes.get(key);
    if (known && !known.pending) return;
    if (known && known.pending) return;
    const at = routeQueue.indexOf(key);
    if (at >= 0) routeQueue.splice(at, 1);
    startRoute(key);
  }

  function scheduleWarm() {
    clearTimeout(warmTimer);
    warmTimer = setTimeout(warmVisible, 200);
  }

  function warmVisible() {
    const limit = routeDraw == null ? Infinity : routeDraw;
    const padX = viewBox.w * 0.08;
    const padY = viewBox.h * 0.08;
    const x0 = viewBox.x - padX;
    const x1 = viewBox.x + viewBox.w + padX;
    const y0 = viewBox.y - padY;
    const y1 = viewBox.y + viewBox.h + padY;
    const cx = viewBox.x + viewBox.w / 2;
    const cy = viewBox.y + viewBox.h / 2;
    const hits = [];
    latest.forEach((plane) => {
      if (routeKey(plane.callsign) === String(plane.icao24 || '').toUpperCase()) return;
      const x = ((plane.lon + 180) / 360) * VB_W;
      const y = ((90 - plane.lat) / 180) * VB_H;
      if (x < x0 || x > x1 || y < y0 || y > y1) return;
      const dx = x - cx;
      const dy = y - cy;
      hits.push({ callsign: plane.callsign, d: dx * dx + dy * dy });
    });
    hits.sort((a, b) => a.d - b.d);
    const want = new Set(hits.slice(0, limit).map((item) => routeKey(item.callsign)));
    const picked = selected ? latest.get(selected) : null;
    if (picked) want.add(routeKey(picked.callsign));
    for (let i = routeQueue.length - 1; i >= 0; i -= 1) {
      if (!want.has(routeQueue[i])) routeQueue.splice(i, 1);
    }
    hits.slice(0, limit).forEach((item) => enqueueRoute(item.callsign, false));
  }

  function applyView() {
    if (!homeSvg) return;
    homeSvg.setAttribute(
      'viewBox',
      `${viewBox.x.toFixed(1)} ${viewBox.y.toFixed(1)} ${viewBox.w.toFixed(1)} ${viewBox.h.toFixed(1)}`,
    );
    refreshCities();
    refreshMe();
    scheduleWarm();
  }

  function clampView() {
    viewBox.w = Math.max(ZOOM_MIN_W, Math.min(VB_W, viewBox.w));
    viewBox.h = viewBox.w * (VB_H / VB_W);
    if (viewBox.w >= VB_W - 0.5) {
      viewBox.x = 0;
      viewBox.y = 0;
      viewBox.w = VB_W;
      viewBox.h = VB_H;
      return;
    }
    viewBox.x = Math.max(0, Math.min(VB_W - viewBox.w, viewBox.x));
    viewBox.y = Math.max(0, Math.min(VB_H - viewBox.h, viewBox.y));
  }

  function zoomAt(clientX, clientY, factor) {
    const rect = homeSvg.getBoundingClientRect();
    if (rect.width < 8 || rect.height < 8) return;
    const px = (clientX - rect.left) / rect.width;
    const py = (clientY - rect.top) / rect.height;
    const anchorX = viewBox.x + px * viewBox.w;
    const anchorY = viewBox.y + py * viewBox.h;
    viewBox.w *= factor;
    clampView();
    viewBox.x = anchorX - px * viewBox.w;
    viewBox.y = anchorY - py * viewBox.h;
    clampView();
    applyView();
  }

  function selectPlane(id) {
    selected = id || '';
    const plane = selected ? latest.get(selected) : null;
    if (plane && plane.origin && plane.destination) {
      rememberRoute(plane.callsign, plane);
    }
    if (plane) askRoute(plane.callsign);
    paintDetail();
    views.forEach(syncPick);
  }

  function syncPick(view) {
    view.pool.forEach((node, id) => {
      node.g.classList.toggle('is-on', id === selected);
    });
  }

  function trailOn(id) {
    return latest.size <= 800 || id === selected;
  }

  function drawTrails(view) {
    const live = new Set();
    tracks.forEach((track, id) => {
      if (!trailOn(id)) return;
      live.add(id);
      let group = view.trails.get(id);
      if (!group) {
        group = el('g');
        view.tracks.appendChild(group);
        view.trails.set(id, group);
      }
      const lines = [];
      track.segs.forEach((seg) => {
        for (let i = 1; i < seg.length; i += 1) {
          if (crosses(seg[i - 1].lon, seg[i].lon)) continue;
          lines.push([seg[i - 1], seg[i], i / seg.length]);
        }
      });
      const stale = [];
      group.childNodes.forEach((node) => {
        if (!node.getAttribute('data-lead')) stale.push(node);
      });
      while (stale.length > lines.length) {
        const node = stale.pop();
        node.remove();
      }
      lines.forEach((item, index) => {
        let line = stale[index];
        if (!line) {
          line = el('line');
          group.appendChild(line);
        }
        const a = project(item[0].lon, item[0].lat);
        const b = project(item[1].lon, item[1].lat);
        line.setAttribute('x1', a[0].toFixed(1));
        line.setAttribute('y1', a[1].toFixed(1));
        line.setAttribute('x2', b[0].toFixed(1));
        line.setAttribute('y2', b[1].toFixed(1));
        line.setAttribute('stroke-opacity', (0.18 + item[2] * 0.72).toFixed(2));
      });
      if (!group._lead) {
        const lead = el('line');
        lead.setAttribute('data-lead', '1');
        lead.setAttribute('stroke-opacity', '0');
        group._lead = lead;
        group.appendChild(lead);
      }
    });
    view.trails.forEach((group, id) => {
      if (live.has(id)) return;
      group.remove();
      view.trails.delete(id);
    });
  }

  function viewOn(view) {
    if (view.page) {
      const page = document.getElementById('app-flight');
      return !!(page && page.classList.contains('is-on'));
    }
    const layer = document.getElementById('layer-status');
    return !!(layer && layer.classList.contains('is-on'));
  }

  function drawLead(view, id, at) {
    const group = view.trails.get(id);
    const track = tracks.get(id);
    if (!group || !track) return;
    const lead = group._lead || group.querySelector('[data-lead]');
    if (!lead) return;
    group._lead = lead;
    const seg = track.segs[track.segs.length - 1];
    const last = seg && seg[seg.length - 1];
    if (!last || !at || crosses(last.lon, at.lon)) {
      lead.setAttribute('stroke-opacity', '0');
      return;
    }
    const a = project(last.lon, last.lat);
    const b = project(at.lon, at.lat);
    lead.setAttribute('x1', a[0].toFixed(1));
    lead.setAttribute('y1', a[1].toFixed(1));
    lead.setAttribute('x2', b[0].toFixed(1));
    lead.setAttribute('y2', b[1].toFixed(1));
    lead.setAttribute('stroke-opacity', '0.9');
  }

  function drawPlanes() {
    const now = performance.now();
    const wall = Date.now();
    const removed = dropStale(wall, new Set(latest.keys()));
    if (removed) views.forEach((view) => { if (viewOn(view)) drawTrails(view); });
    views.forEach((view) => {
      if (!viewOn(view)) {
        view.wasOn = false;
        return;
      }
      if (!view.wasOn) {
        view.wasOn = true;
        drawTrails(view);
      }
      drawCraft(view, now);
      if (selected && trailOn(selected)) drawLead(view, selected, currentPose(selected, now));
      if (latest.size <= 800) {
        latest.forEach((_plane, id) => {
          if (id === selected) return;
          const at = currentPose(id, now);
          if (at) drawLead(view, id, at);
        });
      }
    });
    placeTag();
    paintChrome(false);
    if (document.visibilityState === 'hidden') {
      raf = 0;
      return;
    }
    raf = requestAnimationFrame(drawPlanes);
  }

  let pollTimer = 0;

  function armPoll() {
    clearTimeout(pollTimer);
    const has = payload && payload.aircraft && payload.aircraft.length;
    const wait = !has ? 1200 : (payload.stale ? 3000 : POLL_MS);
    pollTimer = setTimeout(poll, wait);
  }

  async function poll() {
    clearTimeout(pollTimer);
    if (busy) {
      armPoll();
      return;
    }
    const crt = document.getElementById('crt-monitor');
    if (crt && !crt.classList.contains('is-on')) {
      armPoll();
      return;
    }
    if (document.visibilityState === 'hidden') {
      armPoll();
      return;
    }
    busy = true;
    const ctrl = new AbortController();
    const kill = setTimeout(() => ctrl.abort(), 8000);
    try {
      const res = await fetch('/api/flights', { signal: ctrl.signal });
      if (!res.ok) throw new Error(String(res.status));
      apply(await res.json());
    } catch {
      applyFail();
    } finally {
      clearTimeout(kill);
      busy = false;
      armPoll();
    }
  }

  function mapBox(svg) {
    if (svg === homeSvg) return viewBox;
    return { x: 0, y: 0, w: VB_W, h: VB_H };
  }

  function refreshCities() {
    const zoom = VB_W / Math.max(viewBox.w, 1);
    views.forEach((view) => {
      if (!view.cityNodes.length) return;
      const width = view.svg.getBoundingClientRect().width;
      if (width < 8) return;
      const box = mapBox(view.svg);
      const span = Math.max(box.w, 1);
      const localZoom = view.svg === homeSvg ? zoom : 1;
      const font = (16 / width) * span;
      const dot = (2.4 / width) * span;
      const gap = (4 / width) * span;
      view.cityNodes.forEach((node) => {
        const city = node.city;
        const onMap = localZoom > 1.05
          && city.x >= box.x - 80
          && city.x <= box.x + box.w + 80
          && city.y >= box.y - 40
          && city.y <= box.y + box.h + 40;
        if (!onMap) {
          node.g.setAttribute('display', 'none');
          return;
        }
        const here = city.n === '北京';
        node.g.removeAttribute('display');
        node.text.setAttribute('text-anchor', 'start');
        node.text.setAttribute('font-size', font.toFixed(2));
        node.text.setAttribute('dx', (here ? (20 / width) * span : gap).toFixed(2));
        node.text.setAttribute('dy', (font * 0.32).toFixed(2));
        node.dot.setAttribute('r', here ? '0' : dot.toFixed(2));
      });
    });
  }

  function mountCities(list) {
    views.forEach((view) => {
      if (!view.cities || view.cityNodes.length) return;
      list.forEach((city) => {
        const g = el('g');
        g.setAttribute('transform', `translate(${city.x} ${city.y})`);
        g.setAttribute('display', 'none');
        const dot = el('circle');
        dot.setAttribute('cx', '0');
        dot.setAttribute('cy', '0');
        const text = el('text');
        text.textContent = city.n;
        g.append(dot, text);
        view.cities.appendChild(g);
        view.cityNodes.push({ g, dot, text, city });
      });
    });
    refreshCities();
  }

  function loadBorders() {
    fetch('/assets/world-borders.svg')
      .then((res) => (res.ok ? res.text() : Promise.reject(new Error('borders'))))
      .then((text) => {
        const doc = new DOMParser().parseFromString(text, 'image/svg+xml');
        const path = doc.querySelector('path');
        if (!path) return;
        views.forEach((view) => {
          if (!view.borders || view.borders.childNodes.length) return;
          view.borders.appendChild(path.cloneNode(true));
        });
      })
      .catch(() => {});
  }

  function loadCities() {
    fetch('/assets/world-cities.json')
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error('cities'))))
      .then((list) => {
        if (!Array.isArray(list)) return;
        mountCities(list);
      })
      .catch(() => {});
  }

  function loadLand() {
    fetch('/assets/world-land.svg')
      .then((res) => (res.ok ? res.text() : Promise.reject(new Error('map'))))
      .then((text) => {
        const doc = new DOMParser().parseFromString(text, 'image/svg+xml');
        const path = doc.querySelector('path');
        if (!path) return;
        views.forEach((view) => {
          if (!view.land || view.land.childNodes.length) return;
          const node = path.cloneNode(true);
          node.setAttribute('fill-rule', 'evenodd');
          view.land.appendChild(node);
        });
      })
      .catch(() => {});
  }

  if (homeStage && homeSvg) {
    let drag = null;

    function planeAt(clientX, clientY) {
      return planeAtPoint(homeSvg, clientX, clientY);
    }

    function primeRoute(clientX, clientY, immediate) {
      const plane = planeAt(clientX, clientY);
      if (!plane) return;
      if (immediate) askRoute(plane.callsign);
      else enqueueRoute(plane.callsign, true);
    }

    homeStage.addEventListener('pointerdown', (event) => {
      if (event.button !== 0) return;
      try { homeStage.setPointerCapture(event.pointerId); } catch (_) { /* 指针已松开 */ }
      drag = {
        x: event.clientX,
        y: event.clientY,
        vx: viewBox.x,
        vy: viewBox.y,
        moved: false,
      };
      primeRoute(event.clientX, event.clientY, true);
    });

    let hoverAt = 0;
    homeStage.addEventListener('pointermove', (event) => {
      if (!drag) {
        const now = performance.now();
        if (now - hoverAt > 80) {
          hoverAt = now;
          primeRoute(event.clientX, event.clientY, false);
        }
        return;
      }
      const dx = event.clientX - drag.x;
      const dy = event.clientY - drag.y;
      if (Math.hypot(dx, dy) > 4) drag.moved = true;
      if (!drag.moved) return;
      const rect = homeSvg.getBoundingClientRect();
      if (rect.width < 8 || rect.height < 8) return;
      homeStage.classList.add('is-panning');
      viewBox.x = drag.vx - (dx / rect.width) * viewBox.w;
      viewBox.y = drag.vy - (dy / rect.height) * viewBox.h;
      clampView();
      applyView();
    });

    function endDrag(event) {
      if (!drag) return;
      const moved = drag.moved;
      drag = null;
      homeStage.classList.remove('is-panning');
      if (moved) return;
      const hit = document.elementFromPoint(event.clientX, event.clientY);
      if (hit && hit.closest && hit.closest('.flight-tag')) return;
      const plane = planeAt(event.clientX, event.clientY);
      if (plane) selectPlane(plane.icao24 || '');
      else hideTag();
    }

    homeStage.addEventListener('pointerup', endDrag);
    homeStage.addEventListener('pointercancel', () => {
      drag = null;
      homeStage.classList.remove('is-panning');
    });

    homeStage.addEventListener('wheel', (event) => {
      event.preventDefault();
      const factor = event.deltaY > 0 ? 1.25 : 1 / 1.25;
      zoomAt(event.clientX, event.clientY, factor);
    }, { passive: false });
  }

  document.addEventListener('pointerdown', (event) => {
    const inside = home && home.contains(event.target);
    if (inside) {
      const node = event.target;
      if (node.closest && (node.closest('#flight-stage') || node.closest('.flight-tag'))) return;
      hideTag();
      return;
    }
    if (!selected && viewBox.w >= VB_W - 0.5) return;
    clearFlight();
  });

  if (pageStage) {
    pageStage.addEventListener('click', (event) => {
      const plane = planeAtPoint(pageSvg, event.clientX, event.clientY);
      if (plane) {
        askRoute(plane.callsign);
        selectPlane(plane.icao24 || '');
        return;
      }
      selected = '';
      paintDetail();
    });
  }

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible') return;
    poll();
    if (!raf) raf = requestAnimationFrame(drawPlanes);
  });

  const hereBtn = document.getElementById('flight-here');
  if (hereBtn) {
    hereBtn.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      goNearHome();
    });
  }
  requestAnimationFrame(refreshMe);

  function readLimit(el) {
    const raw = String(el && el.value || '').trim();
    if (!raw) return null;
    const number = Number(raw);
    if (!Number.isFinite(number) || number <= 0) return null;
    return Math.round(number);
  }

  function paintLimits(data, force) {
    if (!data) return;
    Object.entries(limitEls).forEach(([key, el]) => {
      if (!el) return;
      if (!force && document.activeElement === el) return;
      const value = data[key];
      el.value = value == null || value === '' ? '' : String(value);
    });
    routeDraw = data.route_draw == null || data.route_draw === '' ? null : Number(data.route_draw);
    if (!Number.isFinite(routeDraw) || routeDraw <= 0) routeDraw = null;
  }

  function collectLimits() {
    return {
      max_draw: readLimit(limitEls.max_draw),
      warm_max: readLimit(limitEls.warm_max),
      route_draw: readLimit(limitEls.route_draw),
    };
  }

  function saveLimits() {
    const seq = ++limitSeq;
    const body = collectLimits();
    routeDraw = body.route_draw;
    scheduleWarm();
    fetch('/api/flights/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then((res) => {
        if (!res.ok) throw new Error(String(res.status));
        return res.json();
      })
      .then((data) => {
        if (seq !== limitSeq) return;
        paintLimits(data, false);
        scheduleWarm();
        poll();
      })
      .catch(() => {});
  }

  function queueLimits() {
    limitSeq += 1;
    clearTimeout(limitTimer);
    limitTimer = setTimeout(saveLimits, 400);
  }

  function bumpLimit(key, dir) {
    const el = limitEls[key];
    if (!el) return;
    const step = LIMIT_STEP[key] || 1;
    const raw = el.value.trim();
    if (!raw) {
      if (dir > 0) el.value = String(LIMIT_FALLBACK[key] || step);
      else return;
    } else {
      const next = Number(raw) + dir * step;
      el.value = next <= 0 ? '' : String(next);
    }
    clearTimeout(limitTimer);
    saveLimits();
  }

  Object.entries(limitEls).forEach(([key, el]) => {
    if (!el) return;
    el.addEventListener('input', () => {
      el.value = el.value.replace(/\D/g, '').slice(0, 6);
      queueLimits();
    });
    el.addEventListener('change', () => {
      clearTimeout(limitTimer);
      saveLimits();
    });
    el.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter') return;
      event.preventDefault();
      clearTimeout(limitTimer);
      saveLimits();
    });
  });

  document.querySelectorAll('[data-flight-step]').forEach((btn) => {
    btn.addEventListener('click', () => {
      bumpLimit(btn.dataset.flightStep, Number(btn.dataset.dir) || 0);
    });
  });

  document.querySelectorAll('[data-flight-none]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const el = limitEls[btn.dataset.flightNone];
      if (!el) return;
      el.value = '';
      clearTimeout(limitTimer);
      saveLimits();
    });
  });

  fetch('/api/flights/settings')
    .then((res) => (res.ok ? res.json() : null))
    .then((data) => {
      if (!data) return;
      paintLimits(data, true);
      scheduleWarm();
    })
    .catch(() => {});

  loadLand();
  loadBorders();
  loadCities();
  poll();
  raf = requestAnimationFrame(drawPlanes);
})();
