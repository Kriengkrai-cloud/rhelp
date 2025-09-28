// ========== Fake backend with localStorage ==========
const LS_KEY = 'kb_items';

function loadItems() {
  return JSON.parse(localStorage.getItem(LS_KEY) || '[]');
}
function saveItems(items) {
  localStorage.setItem(LS_KEY, JSON.stringify(items));
}

const api = {
  async search(q, limit, offset) {
    let items = loadItems();
    if (q) {
      const ql = q.toLowerCase();
      items = items.filter(it =>
        it.id.toLowerCase().includes(ql) ||
        (it.name || '').toLowerCase().includes(ql) ||
        (it.desc || '').toLowerCase().includes(ql) ||
        (it.tags || []).join(',').toLowerCase().includes(ql)
      );
    }
    const total = items.length;
    const paged = items.slice(offset, offset + limit);
    return { total, items: paged };
  },

  async create(it) {
    const items = loadItems();
    if (items.find(x => x.id === it.id)) throw new Error('ID already exists');
    items.push(it);
    saveItems(items);
  },

  async get(id) {
    const items = loadItems();
    const found = items.find(x => x.id === id);
    if (!found) throw new Error('Not found');
    return found;
  },

  async update(id, newItem) {
    let items = loadItems();
    const idx = items.findIndex(x => x.id === id);
    if (idx === -1) throw new Error('Not found');
    items[idx] = { ...items[idx], ...newItem };
    saveItems(items);
  },

  async remove(id) {
    let items = loadItems();
    items = items.filter(x => x.id !== id);
    saveItems(items);
  }
};

// ===== UI logic and event handlers =====
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
const btnCancel = document.getElementById('btnCancel');
const btnSave = document.getElementById('btnSave');

// Register dialog polyfill if needed
if (!dlg.showModal) {
  dialogPolyfill.registerDialog(dlg);
}

let currentEditId = null;
let currPage = 1;

async function doSearch() {
  const q = qEl.value.trim();
  const pageSize = parseInt(pageSizeEl.value, 10) || 20;
  const offset = (currPage - 1) * pageSize;
  const resp = await api.search(q, pageSize, offset);
  render(resp);
}

function render({ total, items }) {
  meta.innerText = `${total} item(s)`;
  grid.innerHTML = '';
  items.forEach(it => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="p-3 border border-gray-200">${it.id}</td>
      <td class="p-3 border border-gray-200">${it.name}</td>
      <td class="p-3 border border-gray-200">${it.desc}</td>
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

  // attach edit / delete
  grid.querySelectorAll('.btn-edit').forEach(b => {
    b.onclick = async () => {
      currentEditId = b.dataset.id;
      const rec = await api.get(currentEditId);
      dlgTitle.innerText = 'Edit product';
      f_id.value = rec.id;
      f_id.disabled = true;
      f_name.value = rec.name;
      f_desc.value = rec.desc;
      f_tags.value = (rec.tags || []).join(', ');
      dlg.showModal();
    };
  });
  grid.querySelectorAll('.btn-del').forEach(b => {
    b.onclick = async () => {
      if (confirm(`Delete ${b.dataset.id}?`)) {
        await api.remove(b.dataset.id);
        doSearch();
      }
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
  dlg.showModal();
};

btnCancel.onclick = () => dlg.close();

btnSave.onclick = async () => {
  const rec = {
    id: f_id.value.trim(),
    name: f_name.value.trim(),
    desc: f_desc.value.trim(),
    tags: f_tags.value.split(',').map(s => s.trim()).filter(s => s)
  };
  try {
    if (currentEditId) {
      await api.update(currentEditId, rec);
    } else {
      await api.create(rec);
    }
    dlg.close();
    doSearch();
  } catch (err) {
    alert(err.message || 'Error');
  }
};

qEl.oninput = () => {
  currPage = 1;
  doSearch();
};
pageSizeEl.onchange = () => {
  currPage = 1;
  doSearch();
};
prevBtn.onclick = () => {
  if (currPage > 1) {
    currPage--;
    doSearch();
  }
};
nextBtn.onclick = () => {
  currPage++;
  doSearch();
};

// initial
doSearch();
