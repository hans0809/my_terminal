/**
 * Desk OS — FLOW RSS 阅读器
 */

(function () {
  const CATS = ['AI', 'BIO', 'PAPER', 'TECH', 'HARDWARE', 'OTHER'];
  const PAGE_SIZE = 40;
  const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
                  'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];

  const heading = document.getElementById('flow-heading');
  const flashEl = document.getElementById('flow-flash');
  const listPanel = document.getElementById('flow-list');
  const readPanel = document.getElementById('flow-read');
  const feedsPanel = document.getElementById('flow-feeds');
  const formPanel = document.getElementById('flow-form');
  const rows = document.getElementById('flow-rows');
  const catsEl = document.getElementById('flow-cats');
  const feedRows = document.getElementById('flow-feed-rows');
  const searchForm = document.getElementById('flow-search');
  const searchInput = document.getElementById('flow-search-input');
  const readTitle = document.getElementById('flow-read-title');
  const readMeta = document.getElementById('flow-read-meta');
  const readBody = document.getElementById('flow-read-body');
  const readLabel = document.getElementById('flow-read-label');
  const saveBtn = document.getElementById('flow-save');
  const laterBtn = document.getElementById('flow-later');
  const openBtn = document.getElementById('flow-open');
  const formName = document.getElementById('flow-form-name');
  const formUrl = document.getElementById('flow-form-url');
  const formCats = document.getElementById('flow-form-cats');
  const formOk = document.getElementById('flow-form-ok');
  const formCancel = document.getElementById('flow-form-cancel');
  const pruneBtn = document.getElementById('flow-prune');
  const sourceEl = document.getElementById('flow-source');
  const pageEl = document.getElementById('flow-page');
  const prevBtn = document.getElementById('flow-prev');
  const nextBtn = document.getElementById('flow-next');

  let view = 'list';
  let tab = 'all';
  let range = 'all';
  let category = '';
  let lang = '';
  let feedId = 0;
  let search = '';
  let page = 1;
  let pages = 1;
  let total = 0;
  let articles = [];
  let feeds = [];
  let sources = [];
  let counts = { all: 0, unread: 0, saved: 0, later: 0, categories: {} };
  let openId = 0;
  let openItem = null;
  let fetching = false;
  let dropArmed = 0;
  let dropTimer = 0;
  let pruneArmed = false;
  let editId = 0;
  let formCat = 'OTHER';
  let flashTimer = 0;

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function ago(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '—';
    const min = Math.max(0, Math.round((Date.now() - d.getTime()) / 60000));
    if (min < 1) return 'now';
    if (min < 60) return `${min} min`;
    const hr = Math.round(min / 60);
    if (hr < 24) return `${hr} h`;
    if (hr < 48) return 'Yesterday';
    return `${String(d.getDate()).padStart(2, '0')} ${MONTHS[d.getMonth()]}`;
  }

  function fmtDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  function isFlow() {
    return window.DeskOS && window.DeskOS.app() === 'flow';
  }

  function flash(text) {
    if (!flashEl) return;
    flashEl.textContent = text || '';
    clearTimeout(flashTimer);
    if (text) flashTimer = setTimeout(() => {
      if (flashEl.textContent === text) flashEl.textContent = '';
    }, 4200);
  }

  function setView(name) {
    view = name;
    if (listPanel) listPanel.classList.toggle('is-on', name === 'list');
    if (readPanel) readPanel.classList.toggle('is-on', name === 'read');
    if (feedsPanel) feedsPanel.classList.toggle('is-on', name === 'feeds');
    if (formPanel) formPanel.classList.toggle('is-on', name === 'form');
    if (heading) heading.textContent = name === 'list' ? 'FLOW' : '← FLOW';
  }

  function markOf(item) {
    if (item.is_saved) return '★';
    return item.is_read ? '○' : '●';
  }

  function query() {
    const params = new URLSearchParams();
    if (category) params.set('category', category);
    if (tab === 'unread') params.set('unread', 'true');
    if (tab === 'saved') params.set('saved', 'true');
    if (tab === 'later') params.set('read_later', 'true');
    if (search) params.set('search', search);
    if (range && range !== 'all') params.set('date_range', range);
    if (lang) params.set('lang', lang);
    if (feedId) params.set('feed_id', String(feedId));
    params.set('limit', String(PAGE_SIZE));
    params.set('offset', String((Math.max(1, page) - 1) * PAGE_SIZE));
    return params.toString();
  }

  function renderTabs() {
    document.querySelectorAll('#flow-tabs .flow-tab').forEach((btn) => {
      btn.classList.toggle('is-on', btn.dataset.tab === tab);
    });
    document.querySelectorAll('#flow-range .flow-tab').forEach((btn) => {
      btn.classList.toggle('is-on', btn.dataset.range === range);
    });
    document.querySelectorAll('#flow-lang .flow-tab').forEach((btn) => {
      btn.classList.toggle('is-on', (btn.dataset.lang || '') === lang);
    });
  }

  function renderCats() {
    if (!catsEl) return;
    const map = counts.categories || {};
    const allBtn = `
      <button class="flow-cat${category === '' ? ' is-on' : ''}" type="button" data-cat="">
        <span>ALL</span>
        <span class="flow-cat__n">${counts.all || 0}</span>
      </button>
    `;
    catsEl.innerHTML = allBtn + CATS.map((cat) => {
      const n = map[cat] || 0;
      return `
        <button class="flow-cat${category === cat ? ' is-on' : ''}" type="button" data-cat="${cat}">
          <span>${cat}</span>
          <span class="flow-cat__n">${n}</span>
        </button>
      `;
    }).join('');
  }

  function renderSources() {
    if (!sourceEl) return;
    const opts = ['<option value="">ALL SOURCES</option>'];
    sources.forEach((src) => {
      const id = Number(src.id);
      const label = `${src.name || 'feed'} · ${Number(src.n) || 0}`;
      opts.push(`<option value="${id}"${id === feedId ? ' selected' : ''}>${escapeHtml(label)}</option>`);
    });
    sourceEl.innerHTML = opts.join('');
    if (feedId && !sources.some((src) => Number(src.id) === feedId)) {
      feedId = 0;
      sourceEl.value = '';
    }
  }

  function renderPager() {
    if (pageEl) pageEl.textContent = total ? `${page} / ${pages}` : '0 / 0';
    if (prevBtn) prevBtn.disabled = page <= 1;
    if (nextBtn) nextBtn.disabled = page >= pages || !total;
  }

  function renderList() {
    renderTabs();
    renderCats();
    renderSources();
    renderPager();
    if (!rows) return;
    if (search) {
      flash(`${total} RESULTS`);
    }
    if (!articles.length) {
      rows.innerHTML = `<p class="flow-empty">${search ? 'NO RESULTS' : 'NO FLOW YET'}</p>`;
      return;
    }
    rows.innerHTML = articles.map((item) => `
      <button class="flow-row${item.is_read ? ' is-read' : ''}" type="button" data-id="${item.id}">
        <span class="flow-row__mark">${markOf(item)}</span>
        <span>
          <span class="flow-row__name">${escapeHtml(item.title || 'untitled')}</span>
          <span class="flow-row__meta">${escapeHtml(item.source || item.category || 'feed')} · ${escapeHtml(ago(item.published_at || item.fetched_at))}</span>
        </span>
      </button>
    `).join('');
    rows.scrollTop = 0;
  }

  function renderRead(item) {
    if (!item) return;
    openItem = item;
    if (readTitle) readTitle.textContent = item.title || 'untitled';
    const bits = [item.source, item.category, item.author, fmtDate(item.published_at || item.fetched_at)];
    if (readMeta) readMeta.textContent = bits.filter(Boolean).join(' · ').toUpperCase();
    if (readBody) {
      const html = (item.body_html || '').trim();
      if (html) {
        readBody.classList.add('is-html');
        readBody.innerHTML = html;
        if (readLabel) readLabel.textContent = '';
      } else if (item.loading) {
        readBody.classList.remove('is-html');
        readBody.textContent = 'LOADING...';
        if (readLabel) readLabel.textContent = '';
      } else {
        readBody.classList.remove('is-html');
        readBody.textContent = (item.summary || item.excerpt || '').trim() || 'NO ABSTRACT';
        if (readLabel) readLabel.textContent = 'ABSTRACT';
      }
      readBody.scrollTop = 0;
    }
    if (saveBtn) saveBtn.textContent = item.is_saved ? '★ SAVED' : 'SAVE';
    if (laterBtn) laterBtn.textContent = item.is_read_later ? 'LATER ✓' : 'READ LATER';
  }

  function renderFeeds() {
    if (!feedRows) return;
    if (!feeds.length) {
      feedRows.innerHTML = '<p class="flow-empty">NO SOURCES</p>';
      renderPrune();
      return;
    }
    const groups = {};
    CATS.forEach((cat) => { groups[cat] = []; });
    feeds.forEach((feed) => {
      const cat = CATS.includes(feed.category) ? feed.category : 'OTHER';
      groups[cat].push(feed);
    });
    feedRows.innerHTML = CATS.map((cat) => {
      const list = groups[cat] || [];
      if (!list.length) return '';
      return `
        <section class="flow-group">
          <h2 class="flow-group__name">${cat}</h2>
          ${list.map((feed) => `
            <article class="flow-feed${feed.enabled ? '' : ' is-off'}${feed.error ? ' is-err' : ''}" data-id="${feed.id}">
              <div class="flow-feed__top">
                <span class="flow-row__mark">${feed.enabled ? '●' : '○'}</span>
                <div>
                  <div class="flow-feed__name">${escapeHtml(feed.name || feed.url || 'feed')}</div>
                  <span class="flow-feed__meta">${Number(feed.n) || 0} articles · Last update: ${escapeHtml(ago(feed.last_fetch_at))}${feed.error ? ' · ERR' : ''}</span>
                </div>
              </div>
              <div class="flow-feed__acts">
                <button class="flow-act" type="button" data-act="enable" data-id="${feed.id}">${feed.enabled ? 'DISABLE' : 'ENABLE'}</button>
                <button class="flow-act" type="button" data-act="refresh" data-id="${feed.id}">REFRESH</button>
                <button class="flow-act" type="button" data-act="edit" data-id="${feed.id}">EDIT</button>
                <button class="flow-act" type="button" data-act="drop" data-id="${feed.id}">DELETE</button>
              </div>
            </article>
          `).join('')}
        </section>
      `;
    }).join('');
    renderPrune();
  }

  function invalidFeeds() {
    return feeds.filter((feed) => String(feed.error || '').trim());
  }

  function renderPrune() {
    if (!pruneBtn || pruneArmed) return;
    const n = invalidFeeds().length;
    pruneBtn.textContent = n ? `CLEAR INVALID · ${n}` : 'CLEAR INVALID';
    pruneBtn.classList.remove('is-sure');
  }

  function renderFormCats() {
    if (!formCats) return;
    formCats.innerHTML = CATS.map((cat) => `
      <button class="flow-tab${formCat === cat ? ' is-on' : ''}" type="button" data-form-cat="${cat}">${cat}</button>
    `).join('');
  }

  function resetList() {
    page = 1;
    loadList();
  }

  async function loadList() {
    try {
      const res = await fetch(`/api/articles?${query()}`);
      if (!res.ok) throw new Error(`articles ${res.status}`);
      const data = await res.json();
      articles = Array.isArray(data.articles) ? data.articles : [];
      counts = data.counts || counts;
      sources = Array.isArray(data.sources) ? data.sources : sources;
      total = Number(data.total) || 0;
      pages = Math.max(1, Number(data.pages) || 1);
      page = Math.max(1, Number(data.page) || page);
    } catch (err) {
      console.warn('[desk-os] flow load failed', err);
    }
    if (view === 'list') renderList();
  }

  async function loadFeeds() {
    try {
      const res = await fetch('/api/feeds');
      if (!res.ok) throw new Error(`feeds ${res.status}`);
      const data = await res.json();
      feeds = Array.isArray(data.feeds) ? data.feeds : [];
      counts = data.counts || counts;
    } catch (err) {
      console.warn('[desk-os] flow feeds failed', err);
    }
    renderFeeds();
  }

  function resultFlash(data) {
    if (!data) {
      flash('FETCH ERROR');
      return;
    }
    if (!data.ok) {
      flash((data.error || 'FETCH ERROR').toUpperCase());
      return;
    }
    const n = Number(data.new) || 0;
    flash(n ? `UPDATED  +${n} ARTICLES` : 'UP TO DATE');
  }

  async function refreshAll() {
    if (fetching) return;
    fetching = true;
    flash('FETCHING...');
    try {
      const res = await fetch('/api/feeds/refresh', { method: 'POST' });
      const data = await res.json();
      resultFlash(data);
    } catch (err) {
      flash('FETCH ERROR');
      console.warn('[desk-os] flow refresh failed', err);
    }
    fetching = false;
    await loadList();
    if (view === 'feeds') await loadFeeds();
  }

  async function openArticle(id) {
    const local = articles.find((x) => x.id === id);
    openId = id;
    if (local) {
      local.is_read = true;
      renderRead({ ...local, loading: true, body_html: '' });
    }
    setView('read');
    flash('LOADING...');
    try {
      const res = await fetch(`/api/articles/${id}`);
      const data = await res.json();
      if (data && data.article) renderRead(data.article);
      else if (local) renderRead(local);
      flash('');
      await fetch(`/api/articles/${id}/read`, { method: 'POST' });
    } catch (err) {
      flash('FETCH ERROR');
      console.warn('[desk-os] flow article failed', err);
      if (local) renderRead(local);
    }
  }

  function showList() {
    openId = 0;
    openItem = null;
    dropArmed = 0;
    editId = 0;
    setView('list');
    loadList();
  }

  function showFeeds() {
    openId = 0;
    dropArmed = 0;
    setView('feeds');
    flash('');
    loadFeeds();
  }

  function showForm(feed) {
    editId = feed ? feed.id : 0;
    formCat = (feed && feed.category) || 'OTHER';
    if (formName) formName.value = feed ? (feed.name || '') : '';
    if (formUrl) formUrl.value = feed ? (feed.url || '') : '';
    renderFormCats();
    setView('form');
    flash(editId ? 'EDIT FEED' : 'ADD FEED');
    if (formName) setTimeout(() => formName.focus(), 40);
  }

  function disarmDrop() {
    dropArmed = 0;
    pruneArmed = false;
    clearTimeout(dropTimer);
    document.querySelectorAll('.flow-act.is-sure').forEach((btn) => {
      btn.classList.remove('is-sure');
      if (btn.dataset.act === 'drop') btn.textContent = 'DELETE';
    });
    renderPrune();
  }

  async function pruneInvalid() {
    const n = invalidFeeds().length;
    if (!n) {
      flash('NO INVALID');
      return;
    }
    if (!pruneArmed) {
      dropArmed = 0;
      document.querySelectorAll('.flow-act.is-sure').forEach((btn) => {
        btn.classList.remove('is-sure');
        if (btn.dataset.act === 'drop') btn.textContent = 'DELETE';
      });
      pruneArmed = true;
      if (pruneBtn) {
        pruneBtn.classList.add('is-sure');
        pruneBtn.textContent = `SURE? · ${n}`;
      }
      clearTimeout(dropTimer);
      dropTimer = setTimeout(disarmDrop, 2800);
      return;
    }
    pruneArmed = false;
    if (pruneBtn) pruneBtn.classList.remove('is-sure');
    flash('PRUNING...');
    try {
      const res = await fetch('/api/feeds/prune', { method: 'POST' });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        flash((data.error || 'PRUNE ERROR').toUpperCase());
      } else {
        flash(`DROPPED ${Number(data.dropped) || 0}`);
      }
    } catch (err) {
      flash('PRUNE ERROR');
      console.warn('[desk-os] flow prune failed', err);
    }
    await loadFeeds();
  }

  async function onFeedAct(act, id) {
    if (act === 'enable') {
      const feed = feeds.find((x) => x.id === id);
      await fetch(`/api/feeds/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !(feed && feed.enabled) }),
      });
      await loadFeeds();
      return;
    }
    if (act === 'refresh') {
      flash('FETCHING...');
      try {
        const res = await fetch(`/api/feeds/${id}/refresh`, { method: 'POST' });
        resultFlash(await res.json());
      } catch (err) {
        flash('FETCH ERROR');
      }
      await loadFeeds();
      return;
    }
    if (act === 'edit') {
      const feed = feeds.find((x) => x.id === id);
      if (feed) showForm(feed);
      return;
    }
    if (act === 'drop') {
      if (dropArmed !== id) {
        disarmDrop();
        const btn = document.querySelector(`.flow-act[data-act="drop"][data-id="${id}"]`);
        if (btn) {
          btn.classList.add('is-sure');
          btn.textContent = 'SURE?';
        }
        dropArmed = id;
        dropTimer = setTimeout(disarmDrop, 2800);
        return;
      }
      disarmDrop();
      await fetch(`/api/feeds/${id}`, { method: 'DELETE' });
      await loadFeeds();
    }
  }

  async function saveForm() {
    const name = (formName && formName.value || '').trim();
    const url = (formUrl && formUrl.value || '').trim();
    if (!url) {
      flash('INVALID FEED');
      return;
    }
    flash('FETCHING...');
    try {
      const payload = { name, url, category: formCat };
      const res = await fetch(editId ? `/api/feeds/${editId}` : '/api/feeds', {
        method: editId ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!data.ok && !data.feed) {
        flash((data.error || 'INVALID FEED').toUpperCase());
        return;
      }
      if (editId) {
        flash('UPDATED');
        showFeeds();
        return;
      }
      resultFlash(data);
      showFeeds();
    } catch (err) {
      flash('INVALID FEED');
    }
  }

  if (rows) {
    rows.addEventListener('click', (e) => {
      const row = e.target.closest('.flow-row');
      if (row) openArticle(Number(row.dataset.id));
    });
  }

  if (catsEl) {
    catsEl.addEventListener('click', (e) => {
      const btn = e.target.closest('.flow-cat');
      if (!btn) return;
      category = btn.dataset.cat || '';
      resetList();
    });
  }

  document.getElementById('flow-tabs')?.addEventListener('click', (e) => {
    const btn = e.target.closest('.flow-tab');
    if (!btn || !btn.dataset.tab) return;
    tab = btn.dataset.tab;
    resetList();
  });

  document.getElementById('flow-range')?.addEventListener('click', (e) => {
    const btn = e.target.closest('.flow-tab');
    if (!btn || !btn.dataset.range) return;
    range = btn.dataset.range;
    resetList();
  });

  document.getElementById('flow-lang')?.addEventListener('click', (e) => {
    const btn = e.target.closest('.flow-tab');
    if (!btn || btn.dataset.lang === undefined) return;
    lang = btn.dataset.lang || '';
    resetList();
  });

  sourceEl?.addEventListener('change', () => {
    feedId = Number(sourceEl.value) || 0;
    resetList();
  });

  prevBtn?.addEventListener('click', () => {
    if (page <= 1) return;
    page -= 1;
    loadList();
  });

  nextBtn?.addEventListener('click', () => {
    if (page >= pages) return;
    page += 1;
    loadList();
  });

  if (searchForm) {
    searchForm.addEventListener('submit', (e) => {
      e.preventDefault();
      search = (searchInput.value || '').trim();
      resetList();
    });
  }

  if (heading) {
    heading.addEventListener('click', () => {
      if (view === 'list') return;
      if (view === 'form') showFeeds();
      else showList();
    });
  }

  document.getElementById('flow-refresh')?.addEventListener('click', () => refreshAll());
  document.getElementById('flow-sources')?.addEventListener('click', () => showFeeds());
  document.getElementById('flow-add')?.addEventListener('click', () => showForm(null));
  pruneBtn?.addEventListener('click', () => pruneInvalid());
  formCancel?.addEventListener('click', () => showFeeds());
  formOk?.addEventListener('click', () => saveForm());

  if (formCats) {
    formCats.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-form-cat]');
      if (!btn) return;
      formCat = btn.dataset.formCat;
      renderFormCats();
    });
  }

  if (feedRows) {
    feedRows.addEventListener('click', (e) => {
      const btn = e.target.closest('.flow-act');
      if (!btn) return;
      onFeedAct(btn.dataset.act, Number(btn.dataset.id));
    });
  }

  if (saveBtn) {
    saveBtn.addEventListener('click', async () => {
      if (!openId) return;
      const res = await fetch(`/api/articles/${openId}/save`, { method: 'POST' });
      const data = await res.json();
      if (data.article) renderRead(data.article);
    });
  }

  if (laterBtn) {
    laterBtn.addEventListener('click', async () => {
      if (!openId) return;
      const res = await fetch(`/api/articles/${openId}/read-later`, { method: 'POST' });
      const data = await res.json();
      if (data.article) renderRead(data.article);
    });
  }

  if (openBtn) {
    openBtn.addEventListener('click', () => {
      if (!openId) return;
      fetch(`/api/articles/${openId}/open`, { method: 'POST' }).catch((err) => {
        console.warn('[desk-os] flow open failed', err);
      });
    });
  }

  window.FlowApp = {
    onEnter() {
      showList();
      loadList().then(() => {
        if (!articles.length) refreshAll();
      });
    },
    onLeave() {
      disarmDrop();
      showList();
      if (searchInput) searchInput.blur();
      if (formName) formName.blur();
      if (formUrl) formUrl.blur();
    },
    onHome() {
      if (!isFlow()) return false;
      if (view === 'form') {
        showFeeds();
        return true;
      }
      if (view !== 'list') {
        showList();
        return true;
      }
      return false;
    },
    onEscape() {
      if (!isFlow()) return false;
      if (dropArmed || pruneArmed) {
        disarmDrop();
        return true;
      }
      if (view === 'form') {
        showFeeds();
        return true;
      }
      if (view !== 'list') {
        showList();
        return true;
      }
      return false;
    },
  };
})();
