/**
 * Desk OS — WorldMap
 * 与 FLIGHT 同一套等距圆柱投影和 3600×1800 底图。
 *
 * WorldMap
 * ├── FlightLayer      flight.js（既有航迹 / 飞机）
 * └── EarthquakeLayer  earthquake.js
 */
(function (global) {
  const NS = 'http://www.w3.org/2000/svg';
  const VB_W = 3600;
  const VB_H = 1800;

  function el(name) {
    return document.createElementNS(NS, name);
  }

  function project(lon, lat) {
    return [
      ((Number(lon) + 180) / 360) * VB_W,
      ((90 - Number(lat)) / 180) * VB_H,
    ];
  }

  function viewBoxOf(svg) {
    const box = svg && svg.viewBox && svg.viewBox.baseVal;
    if (!box || !box.width) return { x: 0, y: 0, w: VB_W, h: VB_H };
    return { x: box.x, y: box.y, w: box.width, h: box.height };
  }

  function pxToUser(svg, px) {
    const width = svg.getBoundingClientRect().width;
    const span = Math.max(viewBoxOf(svg).w, 1);
    if (width < 8) return (px / 400) * span;
    return (px / width) * span;
  }

  function layer(svg, className, before) {
    if (!svg) return null;
    let group = svg.querySelector('.' + className);
    if (group) return group;
    group = el('g');
    group.setAttribute('class', className);
    const hook = before ? svg.querySelector(before) : null;
    if (hook) svg.insertBefore(group, hook);
    else svg.appendChild(group);
    return group;
  }

  let current = 'all';

  function hosts() {
    return document.querySelectorAll('#flight-home, #app-flight');
  }

  function applyLayer(name) {
    current = name === 'earth' || name === 'flight' ? name : 'all';
    hosts().forEach((node) => {
      node.dataset.layer = current;
    });
    document.querySelectorAll('[data-map-goto]').forEach((node) => {
      const on = current !== 'all' && node.dataset.mapGoto === current;
      node.classList.toggle('is-on', on);
      node.setAttribute('aria-pressed', String(on));
    });
    try {
      window.dispatchEvent(new CustomEvent('desk-map-layer', { detail: { layer: current } }));
    } catch (_) { /* 旧环境 */ }
    return current;
  }

  function bindLayers() {
    document.querySelectorAll('[data-map-goto]').forEach((node) => {
      node.addEventListener('click', (event) => {
        if (event.target.closest && event.target.closest('#flight-here')) return;
        event.preventDefault();
        event.stopPropagation();
        applyLayer(node.dataset.mapGoto);
      });
    });
    document.addEventListener('pointerdown', (event) => {
      if (current === 'all') return;
      const node = event.target;
      if (node.closest && (
        node.closest('[data-map-goto]')
        || node.closest('#flight-stage')
        || node.closest('#flight-page-stage')
        || node.closest('#flight-tag')
        || node.closest('#earth-tag')
        || node.closest('#flight-here')
      )) return;
      applyLayer('all');
    });
    applyLayer('all');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindLayers);
  } else {
    bindLayers();
  }

  global.DeskWorldMap = {
    NS,
    VB_W,
    VB_H,
    el,
    project,
    viewBoxOf,
    pxToUser,
    layer,
    applyLayer,
    layerName() {
      return current;
    },
  };
})(window);
