// ================= Common helpers =================
function clampImages(arr) {
  return (arr || []).map(s => s.trim()).filter(Boolean).slice(0, 15);
}
function thumb(url) {
  return url
    ? `<img src="${url}" alt="" style="width:28px;height:28px;object-fit:cover;border-radius:6px;border:1px solid #e5e7eb;vertical-align:middle;margin-left:6px">`
    : "";
}

// ================= Backend (localStorage fallback) =================
const LS_KEY = 'kb_items';

function lsLoad() { return JSON.parse(localStorage.getItem(LS_KEY) || '[]'); }
function lsSave(items) { localStorage.setItem(LS_KEY, JSON.stringify(items)); }

const apiLocal = {
  async search(q, limit, offset) {
    let items = lsLoad();
    if (q) {
      const ql = q.toLowerCase();
      items = items.filter(it =>
        it.id.toLowerCase().includes(ql) ||
        (it.name || '').toLowerCase().includes(ql) ||
        (it.desc || '').toLowerCase().includes(ql) ||
        (it.tags || []).join(',').toLowerCase().includes(ql) ||
        (it.images || []).join(',').toLowerCase().includes(ql)
      );
    }
    const total = items.length;
    const paged = items.slice(offset, offset + limit);
    return { total, items: paged };
  },

  async create(it) {
    const items = lsLoad();
    if (items.find(x => x.id === it.id)) throw new Error('ID already exists');
    it.images = clampImages(it.images);
    items.push(it);
    lsSave(items);
  },

  async get(id) {
    const items = lsLoad();
    const found = items.find(x => x.id === id);
    if (!found) throw new Error('Not found');
    return found;
  },

  async update(id, newItem) {
    let items = lsLoad();
    const idx = items.findIndex(x => x.id === id);
    if (idx === -1) throw new Error('Not found');
    const images = newItem.images !== undefined ? clampImages(newItem.images) : items[idx].images;
    items[idx] = { ...items[idx], ...newItem, images };
    lsSave(items);
  },

  async remove(id) {
    let items = lsLoad();
    items = items.filter(x => x.id !== id);
    lsSave(items);
  }

    
};

async function uploadFilesIfAny(itemId) {
  const fileInput = document.getElementById('f_files');
  if (!fileInput || !fileInput.files || fileInput.files.length === 0) return;

  const files = Array.from(fileInput.files).slice(0, 15);
  const fd = new FormData();
  files.forEach(f => fd.append('files', f));
  // include name for auto-create
  const nameEl = document.getElementById('f_name');
  if (nameEl && nameEl.value) fd.append('name', nameEl.value);

  const base = (typeof window !== 'undefined' && window.API_BASE) ? window.API_BASE : '';
  const r = await fetch(`${base}/api/items/${encodeURIComponent(itemId)}/images`, {
    method: 'POST',
    body: fd
  });
  if (!r.ok) throw new Error(await r.text());
}


// ================= Optional: real API backend =================

function mkApiHttp(base) {
  const prefix = (base ?? "");
  return {
    async search(q, limit, offset) {
      const r = await fetch(`${prefix}/api/search?q=${encodeURIComponent(q||'')}&limit=${limit}&offset=${offset}`);
      if (!r.ok) throw new Error(await r.text());
      return r.json();
    },
    async create(it) {
      const r = await fetch(`${prefix}/api/items`, {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify(it)
      });
      if (!r.ok) throw new Error(await r.text());
    },
    async get(id) {
      const r = await fetch(`${prefix}/api/items/${encodeURIComponent(id)}`);
      if (!r.ok) throw new Error(await r.text());
      return r.json();
    },
    async update(id, it) {
      const r = await fetch(`${prefix}/api/items/${encodeURIComponent(id)}`, {
        method: 'PUT', headers: {'Content-Type':'application/json'},
        body: JSON.stringify(it)
      });
      if (!r.ok) throw new Error(await r.text());
    },
    async remove(id) {
      const r = await fetch(`${prefix}/api/items/${encodeURIComponent(id)}`, { method: 'DELETE' });
      if (!r.ok) throw new Error(await r.text());
    }
  };
}


// If you set window.API_BASE = "https://your-render-service.onrender.com",
// the code below will talk to your FastAPI instead of localStorage.
const apiHttp = (function () {
  const base = (typeof window !== 'undefined' && window.API_BASE) ? window.API_BASE : null;
  if (!base) return null;
  return {
    async search(q, limit, offset) {
      const url = `${base}/api/search?q=${encodeURIComponent(q||'')}&limit=${limit}&offset=${offset}`;
      const r = await fetch(url);
      if (!r.ok) throw new Error(await r.text());
      return r.json(); // {total, items}
    },
    async create(it) {
      const r = await fetch(`${base}/api/items`, {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ ...it, images: clampImages(it.images) })
      });
      if (!r.ok) throw new Error(await r.text());
    },
    async get(id) {
      const r = await fetch(`${base}/api/items/${encodeURIComponent(id)}`);
      if (!r.ok) throw new Error(await r.text());
      return r.json();
    },
    async update(id, it) {
      const r = await fetch(`${base}/api/items/${encodeURIComponent(id)}`, {
        method: 'PUT', headers: {'Content-Type':'application/json'},
        body: JSON.stringify(it.images ? { ...it, images: clampImages(it.images) } : it)
      });
      if (!r.ok) throw new Error(await r.text());
    },
    async remove(id) {
      const r = await fetch(`${base}/api/items/${encodeURIComponent(id)}`, { method: 'DELETE' });
      if (!r.ok) throw new Error(await r.text());
    }
  };
})();

// Choose backend: real API if API_BASE set; otherwise localStorage
//const api = apiHttp || apiLocal;
// ---- Choose backend: API by default; localStorage only if explicitly requested
const wantApi = (typeof window !== 'undefined' ? window.USE_API !== false : true);
const api = wantApi ? mkApiHttp((typeof window !== 'undefined' ? window.API_BASE : "")) : apiLocal;

// ================= UI logic =================
const qEl = document.getElementById('q');
const btnAdd = document.getElementById('btnAdd');
const prevBtn = document.getElementById('prevBtn');
const nextBtn = document.getElementById('nextBtn');
const pageSizeEl = document.getElementById('pageSize');
const pageInfo = document.getElementById('pageInfo');
const meta = document.getElementById('meta');
const grid = document.getElementById('grid');
const dlg = document.getElementById('dlg');
const dlgTitle = document.getElementById('dlgTitle');
const f_id = document.getElementById('f_id');
const f_name = document.getElementById('f_name');
const f_desc = document.getElementById('f_desc');
const f_tags = document.getElementById('f_tags');
// The images input may or may not exist depending on your HTML—handle both
const f_images = document.getElementById('f_images');

const btnCancel = document.getElementById('btnCancel');
const btnSave = document.getElementById('btnSave');

// Dialog polyfill
if (!dlg.showModal && typeof dialogPolyfill !== 'undefined') {
  dialogPolyfill.registerDialog(dlg);
}

let currentEditId = null;
let currPage = 1;

async function doSearch() {
  const q = qEl?.value?.trim() || '';
  const pageSize = parseInt(pageSizeEl.value, 10) || 20;
  const offset = (currPage - 1) * pageSize;
  const resp = await api.search(q, pageSize, offset);
  render(resp);
}

function render({ total, items }) {
  meta.innerText = `${total} item(s)`;
  grid.innerHTML = '';
  items.forEach(it => {
    const imgs = it.images || [];
    const extra = Math.max(0, imgs.length - 1);
    const badge = imgs.length ? `<span class="text-gray-500 text-xs align-middle ml-1">+${extra} more</span>` : '';
    const nameCell = `${it.name || ''}${thumb(imgs[0])}${badge}`;

    const tr = document.createElement('tr');
    tr.setAttribute('data-id', it.id);
    tr.innerHTML = `
      <td class="p-3 border border-gray-200">${it.id}</td>
      <td class="p-3 border border-gray-200">${nameCell}</td>
      <td class="p-3 border border-gray-200">${it.desc || ''}</td>
      <td class="p-3 border border-gray-200">${(it.tags||[]).join(', ')}</td>
      <td class="p-3 border border-gray-200 space-x-2">
        <button class="text-blue-600 hover:underline btn-edit" data-id="${it.id}">Edit</button>
        <button class="text-red-600 hover:underline btn-del" data-id="${it.id}">Delete</button>
      </td>`;
    grid.appendChild(tr);
  });

  const pageSize = parseInt(pageSizeEl.value, 10) || 20;
  const pages = Math.ceil(total / pageSize) || 1;
  pageInfo.innerText = `Page ${currPage} / ${pages}`;
  prevBtn.disabled = currPage <= 1;
  nextBtn.disabled = currPage >= pages;

  // Edit/Delete button handlers
  grid.querySelectorAll('.btn-edit').forEach(b => {
    b.onclick = async (e) => {
      e.stopPropagation(); // prevent row click
      currentEditId = b.dataset.id;
      const rec = await api.get(currentEditId);
      dlgTitle.innerText = 'Edit product';
      f_id.value = rec.id; f_id.disabled = true;
      f_name.value = rec.name || '';
      f_desc.value = rec.desc || '';
      f_tags.value = (rec.tags || []).join(', ');
      if (f_images) f_images.value = (rec.images || []).join(', ');
      dlg.showModal();
    };
  });
  grid.querySelectorAll('.btn-del').forEach(b => {
    b.onclick = async (e) => {
      e.stopPropagation(); // prevent row click
      if (confirm(`Delete ${b.dataset.id}?`)) {
        await api.remove(b.dataset.id);
        doSearch();
      }
    };
  });

  // Row click -> navigate to detail page
  grid.querySelectorAll('tr[data-id]').forEach(tr => {
    tr.onclick = (e) => {
      // ignore clicks on buttons/links inside the row
      if (e.target.closest('button,a')) return;
      const id = tr.getAttribute('data-id');
      if (id) window.location.href = `/item/${encodeURIComponent(id)}`;
    };
  });
}

btnAdd.onclick = () => {
  currentEditId = null;
  dlgTitle.innerText = 'Add product';
  f_id.disabled = false;
  f_id.value = '';
  f_name.value = '';
  f_desc.value = '';
  f_tags.value = '';
  if (f_images) f_images.value = '';
  dlg.showModal();
};

btnCancel.onclick = () => dlg.close();

btnSave.onclick = async () => {
  const rec = {
    id: (f_id.value || '').trim(),
    name: (f_name.value || '').trim(),
    desc: (f_desc.value || '').trim(),
    tags: (f_tags.value || '').split(',').map(s => s.trim()).filter(Boolean)
  };
  if (f_images) {
    rec.images = clampImages((f_images.value || '').split(',')); // keep this if you still want URL-based images too
  }

  try {
    if (!rec.id || !rec.name) throw new Error('ID and Name are required');

    if (currentEditId) {
      await api.update(currentEditId, rec);
      await uploadFilesIfAny(currentEditId);   // ← upload new files
    } else {
      await api.create(rec);
      await uploadFilesIfAny(rec.id);          // ← upload new files
    }

    dlg.close();
    doSearch();  // reload -> server now returns /media/{id} URLs in images
  } catch (err) {
    alert(err.message || 'Error');
  }
};


qEl.oninput = () => { currPage = 1; doSearch(); };
pageSizeEl.onchange = () => { currPage = 1; doSearch(); };
prevBtn.onclick = () => { if (currPage > 1) { currPage--; doSearch(); } };
nextBtn.onclick = () => { currPage++; doSearch(); };

// initial
doSearch();
