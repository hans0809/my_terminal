/**
 * Desk OS — 桌面图标格 + 四个 App
 */

(function () {
  const POM_SEC = 25 * 60;

  document.querySelectorAll('.app-tile').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (window.DeskOS && typeof window.DeskOS.openApp === 'function') {
        window.DeskOS.openApp(btn.dataset.app);
      }
    });
  });

  const noteEl = document.getElementById('note-text');
  let noteTimer = 0;
  let noteLoaded = false;

  function saveNote(text) {
    try {
      localStorage.setItem('desk-os-note', text);
    } catch {
      /* ignore */
    }
    fetch('/api/note', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    }).catch(() => {});
  }

  async function loadNote() {
    let text = '';
    try {
      const res = await fetch('/api/note');
      if (res.ok) {
        const data = await res.json();
        text = data.text || '';
      }
    } catch {
      try {
        text = localStorage.getItem('desk-os-note') || '';
      } catch {
        text = '';
      }
    }
    if (noteEl) noteEl.value = text;
    noteLoaded = true;
  }

  if (noteEl) {
    noteEl.addEventListener('input', () => {
      if (!noteLoaded) return;
      clearTimeout(noteTimer);
      noteTimer = setTimeout(() => saveNote(noteEl.value), 400);
    });
  }

  const pomFace = document.getElementById('pom-face');
  const pomReset = document.getElementById('pom-reset');
  let pomLeft = POM_SEC;
  let pomRunning = false;
  let pomLast = 0;
  let pomEnded = false;

  function pomLabel(sec) {
    const s = Math.max(0, Math.ceil(sec));
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`;
  }

  function drawPom() {
    if (pomFace) pomFace.textContent = pomLabel(pomLeft);
  }

  function tickPom(ts) {
    if (!pomRunning) return;
    if (!pomLast) pomLast = ts;
    const dt = (ts - pomLast) / 1000;
    pomLast = ts;
    pomLeft -= dt;
    if (pomLeft <= 0) {
      pomLeft = 0;
      pomRunning = false;
      pomEnded = true;
      drawPom();
      if (window.DeskOS && typeof window.DeskOS.flashEink === 'function') {
        window.DeskOS.flashEink();
      }
      return;
    }
    drawPom();
    requestAnimationFrame(tickPom);
  }

  function togglePom() {
    if (pomEnded || pomLeft <= 0) {
      pomLeft = POM_SEC;
      pomEnded = false;
      pomRunning = true;
      pomLast = 0;
      drawPom();
      requestAnimationFrame(tickPom);
      return;
    }
    pomRunning = !pomRunning;
    if (pomRunning) {
      pomLast = 0;
      requestAnimationFrame(tickPom);
    }
  }

  function resetPom() {
    pomRunning = false;
    pomEnded = false;
    pomLeft = POM_SEC;
    pomLast = 0;
    drawPom();
  }

  if (pomFace) pomFace.addEventListener('click', togglePom);
  if (pomReset) pomReset.addEventListener('click', resetPom);
  drawPom();

  const clipEl = document.getElementById('clip-text');

  async function loadClip() {
    if (!clipEl) return;
    clipEl.textContent = '';
    try {
      const res = await fetch('/api/clipboard');
      if (!res.ok) throw new Error('clip');
      const data = await res.json();
      const text = (data.text || '').trim();
      clipEl.textContent = text || '—';
    } catch {
      clipEl.textContent = '—';
    }
  }

  const calcDisplay = document.getElementById('calc-display');
  let calcAcc = null;
  let calcOp = '';
  let calcInput = '0';
  let calcFresh = true;

  function showCalc() {
    if (!calcDisplay) return;
    const raw = calcFresh && calcAcc != null && calcOp ? String(calcAcc) : calcInput;
    const text = raw.length > 12 ? raw.slice(0, 12) : raw;
    calcDisplay.textContent = text;
  }

  function calcNum(n) {
    if (calcFresh) {
      calcInput = n === '.' ? '0.' : n;
      calcFresh = false;
    } else if (n === '.') {
      if (!calcInput.includes('.')) calcInput += '.';
    } else if (calcInput === '0') {
      calcInput = n;
    } else if (calcInput.length < 12) {
      calcInput += n;
    }
    showCalc();
  }

  function calcApply() {
    const cur = Number(calcInput);
    if (calcAcc == null || !calcOp) {
      calcAcc = cur;
      return;
    }
    let next = calcAcc;
    if (calcOp === '+') next += cur;
    else if (calcOp === '-') next -= cur;
    else if (calcOp === '*') next *= cur;
    else if (calcOp === '/') next = cur === 0 ? 0 : calcAcc / cur;
    calcAcc = Number.isFinite(next) ? Number(next.toPrecision(10)) : 0;
    calcInput = String(calcAcc);
  }

  function calcPress(key) {
    if (key === 'C') {
      calcAcc = null;
      calcOp = '';
      calcInput = '0';
      calcFresh = true;
      showCalc();
      return;
    }
    if (key === '=' ) {
      calcApply();
      calcOp = '';
      calcFresh = true;
      showCalc();
      return;
    }
    if ('+-*/'.includes(key)) {
      if (!calcFresh) calcApply();
      calcOp = key;
      calcFresh = true;
      showCalc();
      return;
    }
    calcNum(key);
  }

  document.querySelectorAll('.app-calc__pad button').forEach((btn) => {
    btn.addEventListener('click', () => calcPress(btn.dataset.key));
  });
  showCalc();

  const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
                  'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
  const taskRows = document.getElementById('task-rows');
  const taskList = document.getElementById('task-list');
  const taskDetail = document.getElementById('task-detail');
  const taskNew = document.getElementById('task-new');
  const taskNewInput = document.getElementById('task-new-input');
  const taskHeading = document.getElementById('task-heading');
  const taskName = document.getElementById('task-detail-name');
  const taskTimeline = document.getElementById('task-timeline');
  const taskLog = document.getElementById('task-log');
  const taskLogInput = document.getElementById('task-log-input');
  const taskDrop = document.getElementById('task-drop');
  const taskDropAsk = document.getElementById('task-drop-ask');
  const taskDropAskText = document.getElementById('task-drop-ask-text');
  const taskDropKeep = document.getElementById('task-drop-keep');
  const taskDropYes = document.getElementById('task-drop-yes');
  let tasks = [];
  let taskOpenId = '';
  let taskLoaded = false;
  let tasksDirty = false;

  function taskId() {
    return `t${Date.now().toString(36)}${Math.floor(Math.random() * 36).toString(36)}`;
  }

  function readLocalTasks() {
    try {
      const next = JSON.parse(localStorage.getItem('desk-os-tasks') || '[]');
      return Array.isArray(next) ? next : [];
    } catch {
      return [];
    }
  }

  function saveTasks() {
    tasksDirty = false;
    try {
      localStorage.setItem('desk-os-tasks', JSON.stringify(tasks));
    } catch {
      /* ignore */
    }
    return fetch('/api/tasks', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tasks }),
    }).then((res) => {
      if (!res.ok) throw new Error(`tasks ${res.status}`);
    }).catch((err) => {
      tasksDirty = true;
      console.warn('[desk-os] tasks save failed', err);
    });
  }

  async function loadTasks() {
    let next = null;
    try {
      const res = await fetch('/api/tasks');
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data.tasks)) next = data.tasks;
      }
    } catch {
      next = null;
    }
    if (!Array.isArray(next)) next = readLocalTasks();
    tasks = next;
    taskLoaded = true;
    tasksDirty = false;
    try {
      localStorage.setItem('desk-os-tasks', JSON.stringify(tasks));
    } catch {
      /* ignore */
    }
    renderTaskList();
    if (taskOpenId) renderTaskDetail();
  }

  function fmtDay(d) {
    return `${String(d.getDate()).padStart(2, '0')} ${MONTHS[d.getMonth()]}`;
  }

  function fmtTime(d) {
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  }

  function lastBeat(task) {
    const log = task.log || [];
    if (!log.length) return 'no marks yet';
    const d = new Date(log[log.length - 1].t);
    if (Number.isNaN(d.getTime())) return `${log.length} marks`;
    return `${log.length} mark${log.length === 1 ? '' : 's'} · ${fmtDay(d)} ${fmtTime(d)}`;
  }

  function renderTaskList() {
    if (!taskRows) return;
    const rows = tasks.slice().reverse();
    taskRows.innerHTML = rows.map((task) => `
      <button class="task-row" type="button" data-id="${task.id}">
        <span class="task-row__name">${escapeHtml(task.title || 'untitled')}</span>
        <span class="task-row__mark">${escapeHtml(lastBeat(task))}</span>
      </button>
    `).join('');
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function groupLog(log) {
    const days = [];
    log.forEach((beat, i) => {
      const d = new Date(beat.t);
      if (Number.isNaN(d.getTime())) return;
      const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
      let day = days.find((x) => x.key === key);
      if (!day) {
        day = { key, label: fmtDay(d), beats: [] };
        days.push(day);
      }
      day.beats.push({ i, time: fmtTime(d), text: beat.text });
    });
    days.forEach((day) => day.beats.reverse());
    return days.reverse();
  }

  function syncTaskHeading() {
    if (!taskHeading) return;
    taskHeading.textContent = taskOpenId ? '← TASK' : 'TASK';
  }

  let beatEditing = false;
  let beatDropArmed = -1;
  let beatDropTimer = 0;

  function disarmBeatDrop() {
    beatDropArmed = -1;
    clearTimeout(beatDropTimer);
    document.querySelectorAll('.task-beat__drop.is-sure').forEach((btn) => {
      btn.classList.remove('is-sure');
      btn.textContent = '×';
    });
  }

  function renderTaskDetail(opts) {
    const task = tasks.find((x) => x.id === taskOpenId);
    if (!task || !taskTimeline) return;
    const keepScroll = !!(opts && opts.keepScroll);
    const y = taskTimeline.scrollTop;
    beatEditing = false;
    disarmBeatDrop();
    if (taskName && document.activeElement !== taskName) {
      taskName.value = task.title || '';
    }
    const days = groupLog(task.log || []);
    taskTimeline.innerHTML = days.map((day) => `
      <section class="task-day">
        <h2 class="task-day__date">${day.label}</h2>
        <div class="task-day__beats">
          ${day.beats.map((beat) => `
            <article class="task-beat">
              <span class="task-beat__time">${beat.time}</span>
              <span class="task-beat__node"></span>
              <p class="task-beat__text" data-i="${beat.i}">${escapeHtml(beat.text)}</p>
              <button class="task-beat__drop" type="button" data-i="${beat.i}" aria-label="drop mark">×</button>
            </article>
          `).join('')}
        </div>
      </section>
    `).join('');
    taskTimeline.scrollTop = keepScroll ? y : 0;
  }

  function dropBeat(i) {
    const task = tasks.find((x) => x.id === taskOpenId);
    if (!task || !task.log || !task.log[i]) return;
    if (beatDropArmed !== i) {
      disarmBeatDrop();
      const btn = document.querySelector(`.task-beat__drop[data-i="${i}"]`);
      if (btn) {
        btn.classList.add('is-sure');
        btn.textContent = '?';
      }
      beatDropArmed = i;
      beatDropTimer = setTimeout(disarmBeatDrop, 2800);
      return;
    }
    beatEditing = false;
    task.log.splice(i, 1);
    disarmBeatDrop();
    saveTasks();
    renderTaskDetail({ keepScroll: true });
  }

  function commitBeatEdit(input, cancel) {
    if (!input || !input.isConnected) return;
    const i = Number(input.dataset.i);
    const task = tasks.find((x) => x.id === taskOpenId);
    beatEditing = false;
    if (cancel || !task || !task.log || !task.log[i]) {
      renderTaskDetail();
      return;
    }
    const next = input.value.trim();
    if (!next) task.log.splice(i, 1);
    else task.log[i].text = next.slice(0, 200);
    saveTasks();
    renderTaskDetail({ keepScroll: true });
  }

  function beginBeatEdit(el) {
    if (!el || beatEditing) return;
    const i = Number(el.dataset.i);
    const task = tasks.find((x) => x.id === taskOpenId);
    if (!task || !task.log || !task.log[i]) return;
    beatEditing = true;
    const input = document.createElement('input');
    input.className = 'task-beat__edit';
    input.maxLength = 200;
    input.value = task.log[i].text;
    input.dataset.i = String(i);
    input.spellcheck = false;
    el.replaceWith(input);
    input.focus();
    const caret = input.value.length;
    input.setSelectionRange(caret, caret);
    input.addEventListener('blur', () => commitBeatEdit(input, false));
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        input.blur();
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        commitBeatEdit(input, true);
      }
    });
  }

  function flushBeatEdit(cancel) {
    if (!beatEditing) return;
    const input = document.querySelector('.task-beat__edit');
    if (input) commitBeatEdit(input, !!cancel);
    else beatEditing = false;
  }

  function hideDropAsk() {
    if (taskDetail) taskDetail.classList.remove('is-asking');
    if (taskDropAsk) taskDropAsk.classList.remove('is-on');
  }

  function showDropAsk() {
    const task = tasks.find((x) => x.id === taskOpenId);
    const name = ((task && task.title) || 'THIS').trim() || 'THIS';
    const short = name.length > 18 ? `${name.slice(0, 17)}...` : name;
    if (taskDropAskText) taskDropAskText.textContent = `DROP ${short}?`;
    if (taskDetail) taskDetail.classList.add('is-asking');
    if (taskDropAsk) taskDropAsk.classList.add('is-on');
  }

  function dropOpenTask() {
    if (!taskOpenId) return;
    tasks = tasks.filter((x) => x.id !== taskOpenId);
    hideDropAsk();
    saveTasks();
    showTaskList();
  }

  function showTaskList() {
    flushBeatEdit(false);
    hideDropAsk();
    taskOpenId = '';
    beatEditing = false;
    if (taskList) taskList.classList.add('is-on');
    if (taskDetail) taskDetail.classList.remove('is-on');
    syncTaskHeading();
    renderTaskList();
    if (taskNewInput) setTimeout(() => taskNewInput.focus(), 40);
  }

  function openTask(id) {
    const task = tasks.find((x) => x.id === id);
    if (!task) return;
    taskOpenId = id;
    if (taskList) taskList.classList.remove('is-on');
    if (taskDetail) taskDetail.classList.add('is-on');
    syncTaskHeading();
    renderTaskDetail();
    if (taskLogInput) setTimeout(() => taskLogInput.focus(), 40);
  }

  if (taskRows) {
    taskRows.addEventListener('click', (e) => {
      const row = e.target.closest('.task-row');
      if (row) openTask(row.dataset.id);
    });
  }

  if (taskTimeline) {
    taskTimeline.addEventListener('mousedown', (e) => {
      if (e.target.closest('.task-beat__drop')) e.preventDefault();
    });
    taskTimeline.addEventListener('click', (e) => {
      const drop = e.target.closest('.task-beat__drop');
      if (drop) {
        dropBeat(Number(drop.dataset.i));
        return;
      }
      const text = e.target.closest('.task-beat__text');
      if (text) beginBeatEdit(text);
    });
  }

  if (taskHeading) {
    taskHeading.addEventListener('click', () => {
      if (taskOpenId) showTaskList();
    });
  }

  if (taskNew) {
    taskNew.addEventListener('submit', (e) => {
      e.preventDefault();
      const title = (taskNewInput.value || '').trim();
      if (!title) return;
      const task = { id: taskId(), title, log: [] };
      tasks.push(task);
      taskNewInput.value = '';
      saveTasks();
      renderTaskList();
      if (taskRows) taskRows.scrollTop = 0;
      taskNewInput.focus();
    });
  }

  if (taskLog) {
    taskLog.addEventListener('submit', (e) => {
      e.preventDefault();
      const task = tasks.find((x) => x.id === taskOpenId);
      const text = (taskLogInput.value || '').trim();
      if (!task || !text) return;
      if (!Array.isArray(task.log)) task.log = [];
      task.log.push({ t: new Date().toISOString(), text });
      taskLogInput.value = '';
      saveTasks();
      renderTaskDetail();
    });
  }

  if (taskName) {
    taskName.addEventListener('input', () => {
      const task = tasks.find((x) => x.id === taskOpenId);
      if (!task) return;
      task.title = taskName.value;
      saveTasks();
    });
  }

  if (taskDrop) {
    taskDrop.addEventListener('click', () => {
      if (!taskOpenId) return;
      showDropAsk();
    });
  }

  if (taskDropKeep) {
    taskDropKeep.addEventListener('click', () => hideDropAsk());
  }

  if (taskDropYes) {
    taskDropYes.addEventListener('click', () => dropOpenTask());
  }

  window.addEventListener('pagehide', () => {
    if (taskLoaded && tasksDirty) saveTasks();
  });
  document.addEventListener('visibilitychange', () => {
    if (!taskLoaded) return;
    if (document.visibilityState === 'hidden') {
      if (tasksDirty) saveTasks();
      return;
    }
    if (!tasksDirty && !beatEditing) loadTasks();
  });

  window.DeskApps = {
    onEnter(id) {
      if (id === 'note' && !noteLoaded) loadNote();
      if (id === 'note' && noteEl) {
        setTimeout(() => noteEl.focus(), 40);
      }
      if (id === 'clip') loadClip();
      if (id === 'task') {
        showTaskList();
        loadTasks();
        if (taskNewInput) setTimeout(() => taskNewInput.focus(), 40);
      }
    },
    onLeave(id) {
      if (id === 'note' && noteEl) {
        clearTimeout(noteTimer);
        saveNote(noteEl.value);
        noteEl.blur();
      }
      if (id === 'task') {
        if (taskLoaded) saveTasks();
        beatEditing = false;
        showTaskList();
        if (taskNewInput) taskNewInput.blur();
        if (taskLogInput) taskLogInput.blur();
      }
    },
    onHome() {
      if (window.DeskOS && window.DeskOS.app() === 'task' && taskOpenId) {
        showTaskList();
        return true;
      }
      return false;
    },
    onEscape(e) {
      if (!(window.DeskOS && window.DeskOS.app() === 'task')) return false;
      if (beatEditing) {
        const input = document.querySelector('.task-beat__edit');
        commitBeatEdit(input, true);
        return true;
      }
      if (beatDropArmed >= 0) {
        disarmBeatDrop();
        return true;
      }
      if (taskDropAsk && taskDropAsk.classList.contains('is-on')) {
        hideDropAsk();
        return true;
      }
      if (taskOpenId) {
        showTaskList();
        return true;
      }
      return false;
    },
  };
})();
