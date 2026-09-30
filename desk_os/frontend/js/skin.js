/**
 * 皮肤注册表。
 * 新增：css/skins/<id>.css + index.html 的 link + 下面 SKINS 一项。
 * 桌面上的切换条在有两套及以上时才出现。
 */
(function () {
  const KEY = 'desk-skin';
  const FALLBACK = 'crt';
  const SKINS = [
    { id: 'crt', name: 'CRT' },
  ];

  function known(id) {
    return SKINS.some((skin) => skin.id === id);
  }

  function readSaved() {
    try {
      const id = localStorage.getItem(KEY);
      return known(id) ? id : '';
    } catch {
      return '';
    }
  }

  function current() {
    const id = document.documentElement.dataset.skin;
    return known(id) ? id : FALLBACK;
  }

  function paint() {
    const id = current();
    document.querySelectorAll('[data-skin-id]').forEach((btn) => {
      const on = btn.dataset.skinId === id;
      btn.classList.toggle('is-on', on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  function apply(id) {
    const next = known(id) ? id : FALLBACK;
    document.documentElement.dataset.skin = next;
    try {
      localStorage.setItem(KEY, next);
    } catch {
      /* 隐私模式写不进也照样换肤 */
    }
    paint();
    document.dispatchEvent(new CustomEvent('desk-skin', { detail: { id: next } }));
    return next;
  }

  function mount() {
    const nav = document.getElementById('skin-set');
    if (!nav || SKINS.length < 2) return;
    nav.replaceChildren();
    SKINS.forEach((skin) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'skin-set__btn';
      btn.dataset.skinId = skin.id;
      btn.textContent = skin.name;
      nav.appendChild(btn);
    });
    nav.hidden = false;
    nav.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-skin-id]');
      if (!btn) return;
      apply(btn.dataset.skinId);
    });
    paint();
  }

  const saved = readSaved();
  if (saved) document.documentElement.dataset.skin = saved;
  else if (!known(document.documentElement.dataset.skin)) {
    document.documentElement.dataset.skin = FALLBACK;
  }

  mount();

  window.DeskSkins = {
    list: () => SKINS.slice(),
    current,
    apply,
  };
})();
