(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];

  /* Toast */
  function toast(title, type = 'info', text = '', icon = '') {
    const box = $('#toasts'); if (!box) return;
    const t = document.createElement('div');
    t.className = 'toast ' + type;
    const body = document.createElement('div');
    const b = document.createElement('b'); b.textContent = (icon ? icon + ' ' : '') + title; body.append(b);
    if (text) { const s = document.createElement('small'); s.textContent = text; body.append(s); }
    t.append(body); box.append(t);
    setTimeout(() => { t.classList.add('out'); setTimeout(() => t.remove(), 400); }, 5200);
  }
  (window.FLASH || []).forEach(([c, m]) => toast(m, c === 'message' ? 'info' : c));

  /* Tema */
  $('#theme')?.addEventListener('click', () => {
    const n = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = n;
    try { localStorage.setItem('theme', n); } catch (e) {}
  });

  /* Modal */
  $$('[data-open]').forEach(b => b.addEventListener('click', () => {
    const m = $('#' + b.dataset.open); if (!m) return;
    if (b.hasAttribute('data-swap')) b.closest('dialog')?.close();
    if (b.dataset.course) { const s = $('select[name=course_id]', m); if (s) s.value = b.dataset.course; }
    m.showModal();
  }));
  $$('[data-close]').forEach(b => b.addEventListener('click', () => b.closest('dialog').close()));
  $$('dialog.modal').forEach(m => m.addEventListener('click', e => { if (e.target === m) m.close(); }));

  /* Konfirmasi hapus */
  document.addEventListener('submit', e => {
    const msg = e.target.dataset?.confirm;
    if (msg && !confirm(msg)) e.preventDefault();
  });

  /* Tab jadwal */
  $$('[data-tabs]').forEach(tabs => {
    $$('[data-tab]', tabs).forEach(btn => btn.addEventListener('click', () => {
      $$('[data-tab]', tabs).forEach(b => b.classList.toggle('on', b === btn));
      $$('[data-panel]').forEach(p => p.classList.toggle('on', p.dataset.panel === btn.dataset.tab));
    }));
  });

  /* Dropzone */
  const drop = $('#drop');
  if (drop) {
    const inp = $('input[type=file]', drop), txt = $('#drop-text');
    inp.addEventListener('change', () => { if (inp.files[0]) txt.textContent = inp.files[0].name; });
    ['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('over'); }));
    ['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('over'); }));
    drop.addEventListener('drop', e => { if (e.dataTransfer.files.length) { inp.files = e.dataTransfer.files; inp.dispatchEvent(new Event('change')); } });
  }

  /* Transisi antar halaman */
  document.addEventListener('click', e => {
    const a = e.target.closest('a[href]');
    if (!a || a.target || a.hasAttribute('data-plain') || a.hasAttribute('download') || e.metaKey || e.ctrlKey || e.shiftKey || e.button) return;
    const u = new URL(a.href, location.href);
    if (u.origin !== location.origin || (u.pathname === location.pathname && u.search === location.search)) return;
    e.preventDefault();
    $('#page')?.classList.add('leaving');
    setTimeout(() => (location.href = a.href), 180);
  });
  window.addEventListener('pageshow', () => $('#page')?.classList.remove('leaving'));

  /* Notifikasi pengingat */
  const bell = $('#bell'); if (!bell) return;
  const panel = $('#notif-panel'), list = $('#notif-list'), badge = $('#bell-badge');
  bell.addEventListener('click', e => { e.stopPropagation(); panel.classList.toggle('open'); });
  document.addEventListener('click', e => { if (!panel.contains(e.target)) panel.classList.remove('open'); });

  const push = $('#enable-push');
  const syncPush = () => { if (!('Notification' in window) || Notification.permission !== 'default') push.hidden = true; };
  push.addEventListener('click', async () => { await Notification.requestPermission(); syncPush(); });
  syncPush();

  const getSeen = () => { try { return JSON.parse(localStorage.getItem('seen') || '[]'); } catch (e) { return []; } };
  const setSeen = v => { try { localStorage.setItem('seen', JSON.stringify(v.slice(-200))); } catch (e) {} };

  function render(items) {
    badge.textContent = items.length; badge.hidden = !items.length;
    list.innerHTML = '';
    if (!items.length) { list.innerHTML = '<p class="muted pad">Tidak ada pengingat. Santai dulu 🎉</p>'; return; }
    const seen = getSeen();
    items.forEach(i => {
      const a = document.createElement('a'); a.className = 'notif ' + i.level; a.href = i.url;
      const ic = document.createElement('i'); ic.textContent = i.icon;
      const d = document.createElement('div');
      const b = document.createElement('b'); b.textContent = i.title;
      const s = document.createElement('small'); s.textContent = i.text;
      d.append(b, s); a.append(ic, d); list.append(a);
      if (!seen.includes(i.key)) {
        toast(i.title, i.level, i.text, i.icon);
        if ('Notification' in window && Notification.permission === 'granted') new Notification(i.title, { body: i.text });
        seen.push(i.key);
      }
    });
    setSeen(seen);
  }
  async function poll() {
    try { const r = await fetch('/api/notifications', { credentials: 'same-origin' }); if (r.ok) render((await r.json()).items); } catch (e) {}
  }
  poll(); setInterval(poll, 60000);
})();
