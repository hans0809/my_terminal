/**
 * Desk NPC — 主页是当前对话，App 里管理每次记录和参数。
 * 轮询状态不会调用模型。
 */

(function () {
  const POLL_MS = 8000;
  const box = document.getElementById('desk-npc');
  const stateEl = document.getElementById('npc-state');
  const linesEl = document.getElementById('npc-lines');
  const faceSlot = document.getElementById('npc-face');
  const enabledEl = document.getElementById('npc-enabled');
  const baseEl = document.getElementById('npc-base');
  const keyEl = document.getElementById('npc-key');
  const modelEl = document.getElementById('npc-model');
  const coolEl = document.getElementById('npc-cooldown');
  const capEl = document.getElementById('npc-cap');
  const retryEl = document.getElementById('npc-retry');
  const callsEl = document.getElementById('npc-calls');
  const saveEl = document.getElementById('npc-save');
  const pingEl = document.getElementById('npc-ping');
  const linkEl = document.getElementById('npc-link');
  const rankBox = document.getElementById('npc-ranks');
  const talkForm = document.getElementById('npc-talk');
  const talkInput = document.getElementById('npc-talk-input');
  const chatForm = document.getElementById('npc-chat-form');
  const chatInput = document.getElementById('npc-chat-input');
  const sessionsEl = document.getElementById('npc-sessions');
  const newEl = document.getElementById('npc-new');
  const clearEl = document.getElementById('npc-clear');
  const slipKindEl = document.getElementById('slip-kind');
  const slipFromEl = document.getElementById('slip-from');
  const slipLineEl = document.getElementById('slip-line');
  const slipEnabledEl = document.getElementById('slip-enabled');
  const slipMinEl = document.getElementById('slip-min');
  const slipDrawEl = document.getElementById('slip-draw');
  const slipQuoteEl = document.querySelector('.desk-slip__quote');
  const slipKindsEl = document.getElementById('slip-kinds');
  const slipKindForm = document.getElementById('slip-kind-form');
  const slipKindInput = document.getElementById('slip-kind-input');
  const slipKindAdd = document.getElementById('slip-kind-add');
  const slipKindNote = document.getElementById('slip-kind-note');
  const slipNextEl = document.getElementById('slip-next');
  const slipLogEl = document.getElementById('slip-log');
  const SLIP_LABEL = { sci: '科学', wit: '幽默', math: '数学', lit: '文学' };

  const LABELS = {
    idle: 'IDLE',
    observing: 'OBSERVING...',
    curious: 'CURIOUS',
    alert: 'ALERT',
    thinking: 'THINKING...',
  };

  let posted = '';
  let rank = 2;
  let enabled = true;
  let saveLabel = 'SAVE';
  let sending = false;
  let sessions = [];
  let openId = '';
  let activeId = '';
  let fresh = false;
  let clearArmed = false;
  let draft = '';
  let draftTime = '';
  let liveMessage = '';
  let liveAt = '';
  let sessionsStamp = '';
  let homeStamp = '';
  let slipOn = true;
  let slipStamp = '';
  let slipShown = '';
  let slipDrawTimer = 0;
  let slipDrawToken = 0;
  let slipKinds = [];
  let kindBusy = false;
  let kindQueue = Promise.resolve();
  let paintingKinds = false;

  function clamp(raw, min, max, fallback) {
    const n = Math.round(Number(raw));
    if (!Number.isFinite(n)) return fallback;
    return Math.min(max, Math.max(min, n));
  }

  function noteView(layer, app) {
    const body = JSON.stringify({
      layer: layer || 'status',
      app: app || '',
    });
    if (layer === 'status') requestAnimationFrame(() => parkLatest());
    if (body === posted) return;
    posted = body;
    fetch('/api/npc/view', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
    }).catch(() => {});
  }

  function paint(data, fromPoll) {
    if (!box || !stateEl) return;
    if (!(fromPoll && sending)) {
      const state = LABELS[data.state] ? data.state : 'idle';
      stateEl.textContent = LABELS[state];
      box.classList.toggle('is-alert', state === 'alert');
      liveMessage = String(data.message || '').trim();
      liveAt = data.timestamp || '';
      paintHome();
    }
    if (callsEl && document.activeElement !== capEl) {
      const used = Number(data.calls_today);
      const cap = capEl && capEl.value ? capEl.value : '--';
      callsEl.textContent = `TODAY ${Number.isFinite(used) ? used : '--'} / ${cap}`;
    }
  }

  function paintRank() {
    if (!rankBox) return;
    rankBox.querySelectorAll('[data-rank]').forEach((btn) => {
      const on = Number(btn.dataset.rank) === rank;
      btn.classList.toggle('is-on', on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  function paintEnabled() {
    if (!enabledEl) return;
    enabledEl.textContent = enabled ? 'ON' : 'OFF';
    enabledEl.setAttribute('aria-pressed', enabled ? 'true' : 'false');
  }

  function fill(cfg) {
    if (!cfg) return;
    enabled = cfg.enabled !== false;
    rank = [2, 3, 4].includes(Number(cfg.min_importance)) ? Number(cfg.min_importance) : 2;
    paintEnabled();
    paintRank();
    if (baseEl && document.activeElement !== baseEl) baseEl.value = cfg.base_url || '';
    if (keyEl && document.activeElement !== keyEl) keyEl.value = cfg.api_key || '';
    if (modelEl && document.activeElement !== modelEl) modelEl.value = cfg.model || '';
    if (coolEl && document.activeElement !== coolEl) coolEl.value = String(cfg.cooldown_min ?? 3);
    if (capEl && document.activeElement !== capEl) capEl.value = String(cfg.daily_cap ?? 120);
    if (retryEl && document.activeElement !== retryEl) retryEl.value = String(cfg.llm_retries ?? 3);
    slipOn = cfg.slip_enabled !== false;
    paintSlipEnabled();
    if (slipKindsEl && !slipKindsEl.contains(document.activeElement)) {
      slipKinds = readKinds(cfg.slip_kinds);
      paintKinds();
    }
    if (slipMinEl && document.activeElement !== slipMinEl) slipMinEl.value = String(cfg.slip_min ?? 30);
    if (slipDrawEl && document.activeElement !== slipDrawEl) slipDrawEl.value = String(cfg.slip_draw_ms ?? 520);
  }

  function loadSettings() {
    return fetch('/api/npc/settings')
      .then((res) => (res.ok ? res.json() : null))
      .then((cfg) => {
        fill(cfg);
        return cfg;
      })
      .catch(() => null);
  }

  function payload() {
    return {
      enabled,
      base_url: baseEl ? baseEl.value.trim() : '',
      api_key: keyEl ? keyEl.value.trim() : '',
      model: modelEl ? modelEl.value.trim() : '',
      cooldown_min: clamp(coolEl && coolEl.value, 1, 180, 3),
      daily_cap: clamp(capEl && capEl.value, 1, 400, 120),
      llm_retries: clamp(retryEl && retryEl.value, 1, 8, 3),
      min_importance: rank,
      slip_enabled: slipOn,
      slip_min: clamp(slipMinEl && slipMinEl.value, 1, 720, 30),
      slip_draw_ms: clamp(slipDrawEl && slipDrawEl.value, 0, 2000, 520),
      slip_kinds: slipKindList(),
    };
  }

  function save() {
    if (!saveEl) return;
    const body = payload();
    if (coolEl) coolEl.value = String(body.cooldown_min);
    if (capEl) capEl.value = String(body.daily_cap);
    if (retryEl) retryEl.value = String(body.llm_retries);
    if (slipMinEl) slipMinEl.value = String(body.slip_min);
    if (slipDrawEl) slipDrawEl.value = String(body.slip_draw_ms);
    saveEl.disabled = true;
    const packed = JSON.stringify(body);
    const run = kindQueue.catch(() => {}).then(() => fetch('/api/npc/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: packed,
    }));
    kindQueue = run.catch(() => {});
    run
      .then((res) => (res.ok ? res.json() : null))
      .then((cfg) => {
        if (cfg) fill(cfg);
        saveEl.textContent = cfg ? 'SAVED' : 'FAIL';
      })
      .catch(() => {
        saveEl.textContent = 'FAIL';
      })
      .finally(() => {
        saveEl.disabled = false;
        setTimeout(() => {
          if (saveEl) saveEl.textContent = saveLabel;
        }, 1200);
      });
  }

  function ping() {
    if (!pingEl || !linkEl) return;
    pingEl.disabled = true;
    linkEl.classList.remove('is-ok');
    linkEl.textContent = 'CHECKING';
    fetch('/api/npc/ping', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        base_url: baseEl ? baseEl.value.trim() : '',
        api_key: keyEl ? keyEl.value.trim() : '',
        model: modelEl ? modelEl.value.trim() : '',
      }),
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!data) {
          linkEl.textContent = 'FAIL';
          return;
        }
        if (data.ok) {
          const sec = (Number(data.ms) || 0) / 1000;
          linkEl.textContent = `OK ${sec.toFixed(1)}s`;
          linkEl.classList.add('is-ok');
          return;
        }
        const detail = data.detail ? ` ${data.detail}` : '';
        linkEl.textContent = `FAIL${detail}`;
      })
      .catch(() => {
        linkEl.textContent = 'FAIL';
      })
      .finally(() => {
        pingEl.disabled = false;
      });
  }

  function paintSlipEnabled() {
    if (!slipEnabledEl) return;
    slipEnabledEl.textContent = slipOn ? 'ON' : 'OFF';
    slipEnabledEl.setAttribute('aria-pressed', slipOn ? 'true' : 'false');
  }

  function kindName(raw) {
    const text = String(raw || '').trim().slice(0, 16);
    return SLIP_LABEL[text] || SLIP_LABEL[text.toLowerCase()] || text;
  }

  function readKinds(value) {
    const rows = Array.isArray(value) ? value : [];
    const seen = [];
    rows.forEach((item) => {
      const name = kindName(typeof item === 'string' ? item : (item && item.name));
      const prompt = typeof item === 'string' ? '' : String((item && item.prompt) || '');
      if (!name || seen.some((row) => row.name === name)) return;
      seen.push({ name, prompt: prompt.trim().slice(0, 240) });
    });
    return seen.slice(0, 12);
  }

  function slipKindList() {
    return slipKinds
      .map((row) => ({
        name: kindName(row.name),
        prompt: String(row.prompt || '').trim().slice(0, 240),
      }))
      .filter((row) => row.name)
      .slice(0, 12);
  }

  function kindNote(text) {
    if (!slipKindNote) return;
    slipKindNote.hidden = !text;
    slipKindNote.textContent = text || '';
  }

  function persistKinds() {
    const body = JSON.stringify({ slip_kinds: slipKindList() });
    const run = kindQueue.catch(() => {}).then(() => fetch('/api/npc/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body,
    }).then((res) => (res.ok ? res.json() : null)));
    kindQueue = run;
    return run;
  }

  function paintKinds() {
    if (!slipKindsEl) return;
    paintingKinds = true;
    slipKindsEl.replaceChildren();
    try {
    slipKinds.forEach((row, index) => {
      const card = document.createElement('article');
      card.className = 'kind-card';

      const head = document.createElement('header');
      const name = document.createElement('span');
      name.className = 'kind-name';
      name.textContent = row.name;
      const del = document.createElement('button');
      del.type = 'button';
      del.textContent = 'DEL';
      del.disabled = slipKinds.length < 2;
      del.addEventListener('click', () => {
        slipKinds.splice(index, 1);
        paintKinds();
        persistKinds().then((cfg) => {
          kindNote(cfg ? '已记下' : '没存上');
        }).catch(() => kindNote('没存上'));
      });

      const area = document.createElement('textarea');
      area.className = 'kind-prompt';
      area.maxLength = 240;
      area.rows = 3;
      area.spellcheck = false;
      area.value = row.prompt || '';
      area.setAttribute('aria-label', `${row.name} 的提示词`);
      area.addEventListener('keydown', (event) => event.stopPropagation());
      area.addEventListener('pointerdown', (event) => event.stopPropagation());
      area.addEventListener('input', () => {
        slipKinds[index].prompt = area.value.slice(0, 240);
      });
      area.addEventListener('blur', () => {
        if (paintingKinds || !slipKinds[index]) return;
        slipKinds[index].prompt = area.value.slice(0, 240);
        persistKinds().then((cfg) => {
          kindNote(cfg ? '已记下' : '没存上');
        }).catch(() => kindNote('没存上'));
      });

      head.append(name, del);
      card.append(head, area);
      slipKindsEl.appendChild(card);
    });
    } finally {
      paintingKinds = false;
    }
  }

  function addKind(event) {
    event.preventDefault();
    const name = kindName(slipKindInput && slipKindInput.value);
    if (!name || kindBusy) return;
    if (slipKinds.some((row) => row.name === name)) {
      kindNote('已有这个类型');
      return;
    }
    if (slipKinds.length >= 12) {
      kindNote('最多 12 个');
      return;
    }
    kindBusy = true;
    if (slipKindAdd) slipKindAdd.disabled = true;
    kindNote('正在写提示词');
    const fallback = `按「${name}」写一句。不要罗列，不要编造你不确定的事实。`;
    fetch('/api/npc/kinds/prompt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
      .then((res) => (res.ok ? res.json() : Promise.reject(res.status)))
      .then((data) => {
        const prompt = data && data.prompt ? String(data.prompt) : fallback;
        slipKinds.push({ name: kindName((data && data.name) || name), prompt: prompt.slice(0, 240) });
        if (slipKindInput) slipKindInput.value = '';
        paintKinds();
        return persistKinds().then((cfg) => {
          if (!cfg) {
            kindNote('写好了，但没存上');
            return;
          }
          kindNote(data && data.ok ? '已写好，可以直接改' : '模型没写出来，先放了一句');
        });
      })
      .catch(() => {
        slipKinds.push({ name, prompt: fallback });
        if (slipKindInput) slipKindInput.value = '';
        paintKinds();
        persistKinds().then((cfg) => {
          kindNote(cfg ? '连不上，先放了一句，可以直接改' : '没存上');
        }).catch(() => kindNote('没存上'));
      })
      .finally(() => {
        kindBusy = false;
        if (slipKindAdd) slipKindAdd.disabled = false;
      });
  }

  function slipName(kind) {
    return SLIP_LABEL[kind] || kind || '';
  }

  function drawMs() {
    return clamp(slipDrawEl && slipDrawEl.value, 0, 2000, 520);
  }

  function applySlip(text, name) {
    slipLineEl.textContent = text;
    slipKindEl.textContent = name;
    if (slipFromEl) slipFromEl.hidden = !name;
  }

  function clearRedraw() {
    window.clearTimeout(slipDrawTimer);
    slipDrawTimer = 0;
    if (!slipQuoteEl) return;
    slipQuoteEl.classList.remove('is-hold', 'is-redraw');
  }

  function paintSlipHome(current) {
    if (!slipLineEl || !slipKindEl) return;
    const text = current && current.text ? String(current.text) : '';
    const name = current ? slipName(current.kind) : '';
    const mark = `${current && current.id ? current.id : ''}|${text}`;
    if (mark === slipShown) return;
    const first = !slipShown;
    slipShown = mark;
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const ms = drawMs();
    if (first || reduce || ms <= 0 || !slipLineEl.textContent || !slipQuoteEl) {
      clearRedraw();
      applySlip(text, name);
      return;
    }
    const hold = Math.max(0, Math.round(ms * 0.32));
    const reveal = Math.max(0, ms - hold);
    const token = ++slipDrawToken;
    slipQuoteEl.style.setProperty('--slip-hold', `${hold}ms`);
    slipQuoteEl.style.setProperty('--slip-reveal', `${reveal}ms`);
    slipQuoteEl.classList.remove('is-redraw');
    void slipQuoteEl.offsetWidth;
    slipQuoteEl.classList.add('is-hold');
    window.clearTimeout(slipDrawTimer);
    slipDrawTimer = window.setTimeout(() => {
      if (token !== slipDrawToken) return;
      slipQuoteEl.classList.remove('is-hold');
      slipQuoteEl.classList.add('is-redraw');
      applySlip(text, name);
      slipDrawTimer = window.setTimeout(() => {
        if (token !== slipDrawToken) return;
        slipQuoteEl.classList.remove('is-redraw');
      }, reveal + 40);
    }, hold);
  }

  function paintSlipLog(items) {
    if (!slipLogEl) return;
    const rows = items || [];
    const stamp = rows.map((item) => item.id).join('\n');
    if (stamp === slipStamp) return;
    slipStamp = stamp;
    slipLogEl.replaceChildren();
    rows.forEach((item) => {
      const li = document.createElement('li');
      const kind = document.createElement('span');
      kind.className = 'slip-log__kind';
      kind.textContent = slipName(item.kind);
      const time = document.createElement('span');
      time.className = 'slip-log__time';
      time.textContent = clock(item.timestamp);
      const text = document.createElement('span');
      text.className = 'slip-log__text';
      text.textContent = item.text || '';
      const del = document.createElement('button');
      del.type = 'button';
      del.className = 'slip-log__del';
      del.dataset.slipDel = item.id || '';
      del.textContent = 'DEL';
      li.append(kind, time, text, del);
      slipLogEl.appendChild(li);
    });
  }

  function loadSlips() {
    return fetch('/api/npc/slips')
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!data) return;
        paintSlipHome(data.current);
        paintSlipLog(data.items);
      })
      .catch(() => {});
  }

  function poll() {
    fetch('/api/npc/status')
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data) paint(data, true);
      })
      .catch(() => {});
    loadSessions();
    loadSlips();
  }

  function when(iso) {
    const match = String(iso || '').match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2})/);
    if (!match) return '';
    const now = new Date();
    const today = [
      now.getFullYear(),
      String(now.getMonth() + 1).padStart(2, '0'),
      String(now.getDate()).padStart(2, '0'),
    ].join('-');
    if (`${match[1]}-${match[2]}-${match[3]}` === today) return match[4];
    return `${match[2]}-${match[3]} ${match[4]}`;
  }

  function clock(iso) {
    const match = String(iso || '').match(/T(\d{2}:\d{2})/);
    return match ? match[1] : '';
  }

  function nowClock() {
    const now = new Date();
    return `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
  }

  function shownTalk() {
    if (fresh) return null;
    if (activeId) {
      const hit = sessions.find((item) => item.id === activeId);
      if (hit) return hit;
    }
    return sessions[0] || null;
  }

  function paintHome() {
    if (!linesEl) return;
    const lines = [];
    if (!fresh) {
      const talk = shownTalk();
      (talk && talk.messages ? talk.messages : []).forEach((line) => {
        const text = String(line.message || '').trim();
        if (!text) return;
        lines.push({
          user: line.event_type === 'user',
          text,
          time: clock(line.timestamp),
          at: line.timestamp || '',
        });
      });
      const newest = !talk || !sessions[0] || talk.id === sessions[0].id;
      if (liveMessage && newest && !lines.some((line) => !line.user && line.text === liveMessage)) {
        const row = { user: false, text: liveMessage, time: clock(liveAt), at: liveAt || '' };
        const at = Date.parse(row.at) || 0;
        let index = lines.length;
        if (at) {
          const found = lines.findIndex((line) => (Date.parse(line.at || '') || 0) > at);
          if (found >= 0) index = found;
        }
        lines.splice(index, 0, row);
      }
    }
    if (draft && !(lines.length && lines[lines.length - 1].user && lines[lines.length - 1].text === draft)) {
      lines.push({ user: true, text: draft, time: draftTime });
    }
    lines.forEach((line, index) => {
      line.key = `${index}:${line.user ? 'u' : 'n'}:${line.time}:${line.text}`;
    });
    if (sending) lines.push({ typing: true, key: 'typing' });
    const signature = lines.map((line) => line.key).join('\n');
    if (signature === homeStamp) return;
    const nodes = [...linesEl.children];
    const prefix = nodes.length <= lines.length && nodes.every((node, index) => node.dataset.key === lines[index].key);
    if (prefix && nodes.length) {
      for (let index = nodes.length; index < lines.length; index += 1) {
        linesEl.appendChild(makeLine(lines[index], true));
      }
    } else {
      linesEl.replaceChildren(...lines.map((line) => makeLine(line, false)));
    }
    homeStamp = signature;
    requestAnimationFrame(() => parkLatest());
  }

  function parkLatest() {
    if (!linesEl || linesEl.offsetParent === null) return;
    linesEl.style.maxHeight = '';
    const last = linesEl.lastElementChild;
    if (!last) return;
    const anchor = last.classList.contains('is-typing') && last.previousElementSibling
      ? last.previousElementSibling
      : last;
    const view = linesEl.getBoundingClientRect().top;
    const top = anchor.getBoundingClientRect().top - view + linesEl.scrollTop;
    linesEl.scrollTop = Math.max(0, top);
  }

  function robotSvg() {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 32 32');
    svg.innerHTML = '<line x1="16" y1="2" x2="16" y2="6" stroke="currentColor" stroke-width="1.6"/>'
      + '<circle cx="16" cy="2" r="1.3" fill="currentColor"/>'
      + '<rect x="6" y="6.5" width="20" height="16" rx="3" fill="none" stroke="currentColor" stroke-width="1.6"/>'
      + '<circle cx="12.5" cy="13.5" r="1.5" fill="currentColor"/>'
      + '<circle cx="19.5" cy="13.5" r="1.5" fill="currentColor"/>'
      + '<path d="M11.5 18.2h9" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>';
    return svg;
  }

  function robotFace() {
    const mark = document.createElement('span');
    mark.className = 'desk-npc__face';
    mark.setAttribute('aria-hidden', 'true');
    mark.appendChild(robotSvg());
    return mark;
  }

  function whoMark() {
    const mark = document.createElement('span');
    mark.className = 'desk-npc__who';
    mark.textContent = 'YOU';
    return mark;
  }

  function makeLine(line, arrive) {
    const li = document.createElement('li');
    if (line.typing) {
      li.className = 'is-npc is-typing';
      li.dataset.key = 'typing';
      const time = document.createElement('span');
      time.className = 'desk-npc__time';
      const dots = document.createElement('span');
      dots.className = 'desk-npc__dots';
      dots.setAttribute('aria-label', '正在打字');
      dots.append(document.createElement('i'), document.createElement('i'), document.createElement('i'));
      li.append(robotFace(), time, dots);
      return li;
    }
    li.className = line.user ? 'is-user' : 'is-npc';
    if (arrive) li.classList.add('is-new');
    li.dataset.key = line.key;
    const time = document.createElement('span');
    time.className = 'desk-npc__time';
    time.textContent = line.time || '';
    const say = document.createElement('span');
    say.className = 'desk-npc__say';
    say.textContent = line.text;
    li.append(line.user ? whoMark() : robotFace(), time, say);
    return li;
  }

  function paintSessions(items) {
    sessions = items || [];
    if (openId && !sessions.some((item) => item.id === openId)) openId = '';
    if (activeId && !sessions.some((item) => item.id === activeId)) activeId = '';
    paintHome();
    if (!sessionsEl) return;
    sessionsEl.replaceChildren();
    sessions.forEach((item) => {
      const rec = document.createElement('article');
      rec.className = 'npc-rec';
      if (item.id === openId) rec.classList.add('is-open');
      if (item.id === activeId) rec.classList.add('is-on');

      const head = document.createElement('div');
      head.className = 'npc-rec__head';

      const open = document.createElement('button');
      open.type = 'button';
      open.className = 'npc-rec__open';
      open.dataset.open = item.id;

      const time = document.createElement('span');
      time.className = 'npc-rec__time';
      time.textContent = when(item.started) || '--';

      const preview = document.createElement('span');
      preview.className = 'npc-rec__preview';
      preview.textContent = item.preview || '';

      const del = document.createElement('button');
      del.type = 'button';
      del.className = 'npc-rec__del';
      del.dataset.del = item.id;
      del.textContent = 'DEL';

      const body = document.createElement('ol');
      body.className = 'npc-rec__body';
      (item.messages || []).forEach((line) => {
        const text = String(line.message || '').trim();
        if (!text) return;
        const li = document.createElement('li');
        const user = line.event_type === 'user';
        li.className = user ? 'is-user' : 'is-npc';
        li.appendChild(user ? whoMark() : robotFace());
        const say = document.createElement('span');
        say.className = 'desk-npc__say';
        say.textContent = text;
        li.appendChild(say);
        body.appendChild(li);
      });

      open.append(time, preview);
      head.append(open, del);
      rec.append(head, body);
      sessionsEl.appendChild(rec);
    });
  }

  function loadSessions() {
    return fetch('/api/npc/sessions')
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        const items = (data && data.items) || [];
        const stamp = JSON.stringify(items);
        if (stamp === sessionsStamp) {
          paintHome();
          return;
        }
        sessionsStamp = stamp;
        paintSessions(items);
      })
      .catch(() => {});
  }

  function dropSession(id) {
    if (!id) return;
    fetch(`/api/npc/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' })
      .then((res) => (res.ok ? res.json() : null))
      .then(() => loadSessions())
      .then(() => poll())
      .catch(() => {});
  }

  function clearSessions() {
    if (!clearEl) return;
    if (!clearArmed) {
      clearArmed = true;
      clearEl.textContent = 'SURE';
      setTimeout(() => {
        clearArmed = false;
        if (clearEl) clearEl.textContent = 'CLEAR';
      }, 1600);
      return;
    }
    clearArmed = false;
    clearEl.textContent = 'CLEAR';
    fetch('/api/npc/sessions', { method: 'DELETE' })
      .then((res) => (res.ok ? res.json() : null))
      .then(() => {
        openId = '';
        activeId = '';
        fresh = true;
        return loadSessions();
      })
      .then(() => poll())
      .catch(() => {});
  }

  function setBusy(on) {
    sending = on;
    if (talkInput) talkInput.disabled = on;
    if (chatInput) chatInput.disabled = on;
  }

  function send(text, source) {
    const said = String(text || '').trim();
    if (!said || sending) return;
    setBusy(true);
    if (talkInput) talkInput.value = '';
    if (chatInput) chatInput.value = '';
    if (stateEl) stateEl.textContent = LABELS.thinking;
    const fromApp = source === chatInput;
    const talk = shownTalk();
    draft = said;
    draftTime = nowClock();
    homeStamp = '';
    paintHome();
    fetch('/api/npc/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: said,
        session: fromApp ? (fresh ? '' : activeId) : (fresh || !talk ? '' : talk.id),
        new: fromApp ? fresh : fresh || !talk,
      }),
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        const line = data && data.result && data.result.message;
        setBusy(false);
        draft = '';
        draftTime = '';
        homeStamp = '';
        if (data && data.ok && line) {
          paint({
            state: data.result.mood === 'alert' ? 'alert' : 'curious',
            message: line,
            timestamp: new Date().toISOString(),
          });
        } else if (stateEl) {
          stateEl.textContent = 'FAIL';
        }
        if (data && data.session) {
          activeId = data.session;
          openId = data.session;
          fresh = false;
        }
        return loadSessions();
      })
      .catch(() => {
        setBusy(false);
        homeStamp = '';
        if (stateEl && stateEl.textContent === LABELS.thinking) stateEl.textContent = 'FAIL';
        paintHome();
      })
      .finally(() => {
        if (talkInput) talkInput.disabled = false;
        if (chatInput) chatInput.disabled = false;
        if (source) source.focus();
      });
  }

  function bindTalk(form, input) {
    if (!form || !input) return;
    input.addEventListener('keydown', (event) => event.stopPropagation());
    input.addEventListener('pointerdown', (event) => event.stopPropagation());
    form.addEventListener('pointerdown', (event) => {
      event.stopPropagation();
      if (document.activeElement !== input) input.focus();
    });
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      send(input.value, input);
    });
  }

  if (enabledEl) {
    enabledEl.addEventListener('click', () => {
      enabled = !enabled;
      paintEnabled();
    });
  }

  if (slipEnabledEl) {
    slipEnabledEl.addEventListener('click', () => {
      slipOn = !slipOn;
      paintSlipEnabled();
    });
  }

  if (slipKindForm) {
    slipKindForm.addEventListener('pointerdown', (event) => event.stopPropagation());
    slipKindForm.addEventListener('submit', addKind);
  }
  if (slipKindInput) {
    slipKindInput.addEventListener('keydown', (event) => event.stopPropagation());
    slipKindInput.addEventListener('pointerdown', (event) => event.stopPropagation());
  }

  if (slipNextEl) {
    slipNextEl.addEventListener('click', () => {
      slipNextEl.disabled = true;
      slipNextEl.textContent = 'WAIT';
      fetch('/api/npc/slips', { method: 'POST' })
        .then((res) => (res.ok ? res.json() : null))
        .then(() => loadSlips())
        .catch(() => {})
        .finally(() => {
          slipNextEl.disabled = false;
          slipNextEl.textContent = 'NEXT';
        });
    });
  }

  if (slipLogEl) {
    slipLogEl.addEventListener('click', (event) => {
      const del = event.target.closest('[data-slip-del]');
      if (!del || !del.dataset.slipDel) return;
      fetch(`/api/npc/slips/${encodeURIComponent(del.dataset.slipDel)}`, { method: 'DELETE' })
        .then(() => {
          slipStamp = '';
          return loadSlips();
        })
        .catch(() => {});
    });
  }

  document.querySelectorAll('[data-npc-step]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const dir = Number(btn.dataset.dir) || 0;
      const step = btn.dataset.npcStep;
      if (step === 'draw') {
        if (!slipDrawEl) return;
        slipDrawEl.value = String(clamp(Number(slipDrawEl.value) + dir * 40, 0, 2000, 520));
        return;
      }
      const spec = {
        cap: [capEl, 400, 120],
        slip: [slipMinEl, 720, 30],
        retry: [retryEl, 8, 3],
      }[step] || [coolEl, 180, 3];
      const target = spec[0];
      if (!target) return;
      const max = spec[1];
      const fallback = spec[2];
      target.value = String(clamp(Number(target.value) + dir, 1, max, fallback));
    });
  });

  if (rankBox) {
    rankBox.addEventListener('click', (event) => {
      const btn = event.target.closest('[data-rank]');
      if (!btn) return;
      rank = Number(btn.dataset.rank) || 2;
      paintRank();
    });
  }

  if (saveEl) saveEl.addEventListener('click', save);
  if (pingEl) pingEl.addEventListener('click', ping);
  bindTalk(talkForm, talkInput);
  bindTalk(chatForm, chatInput);

  if (newEl) {
    newEl.addEventListener('click', () => {
      fresh = true;
      openId = '';
      activeId = '';
      paintSessions(sessions);
      if (chatInput) chatInput.focus();
    });
  }

  if (clearEl) clearEl.addEventListener('click', clearSessions);

  if (sessionsEl) {
    sessionsEl.addEventListener('click', (event) => {
      const del = event.target.closest('[data-del]');
      if (del) {
        if (del.dataset.del === activeId) activeId = '';
        if (del.dataset.del === openId) openId = '';
        dropSession(del.dataset.del);
        return;
      }
      const open = event.target.closest('[data-open]');
      if (!open) return;
      const id = open.dataset.open || '';
      fresh = false;
      activeId = id;
      openId = openId === id ? '' : id;
      paintSessions(sessions);
    });
  }

  if (window.DeskApps && typeof window.DeskApps.register === 'function') {
    window.DeskApps.register('npc', {
      onEnter() {
        loadSettings();
        loadSessions();
      },
    });
  }

  window.DeskNpc = { noteView };

  if (faceSlot) faceSlot.appendChild(robotSvg());

  const desk = window.DeskOS;
  noteView(
    desk && typeof desk.layer === 'function' ? desk.layer() : 'status',
    desk && typeof desk.app === 'function' ? desk.app() : ''
  );
  loadSettings();
  poll();
  setInterval(poll, POLL_MS);
})();
