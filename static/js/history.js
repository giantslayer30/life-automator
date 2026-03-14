/* ──────────────────────────────────────────────────────
   JobFlow — Application History JS
   ────────────────────────────────────────────────────── */

const PRESET_STATUSES = [
  'Applied', 'Interviewing – R1', 'Interviewing – R2',
  'HR Round', 'Assignment', 'Offer', 'Rejected', 'Ghosted',
];

const TERMINAL = new Set(['Offer', 'Rejected', 'Ghosted']);

let allApps = [];
let editingAppId = null;

document.addEventListener('DOMContentLoaded', async () => {
  await loadStats();
  await loadApplications();
  bindStatusModal();
  bindFilters();
});

// ── Load Stats ────────────────────────────────────────
async function loadStats() {
  try {
    const data = await api('/api/analytics');
    const dist = {};
    (data.status_distribution || []).forEach(s => { dist[s.status] = s.count; });

    document.getElementById('statTotal').textContent      = data.total_applications || 0;
    document.getElementById('statInterviewing').textContent =
      (dist['Interviewing – R1'] || 0) + (dist['Interviewing – R2'] || 0) + (dist['HR Round'] || 0);
    document.getElementById('statOffers').textContent     = dist['Offer'] || 0;
    document.getElementById('statRejected').textContent   = dist['Rejected'] || 0;
    document.getElementById('statGhosted').textContent    = dist['Ghosted'] || 0;
    document.getElementById('statAvgDays').textContent    =
      data.rejection_stats?.avg_days_to_rejection != null
        ? data.rejection_stats.avg_days_to_rejection + 'd'
        : '–';
  } catch {}
}

// ── Load Applications ─────────────────────────────────
async function loadApplications() {
  const tbody = document.getElementById('appTableBody');
  tbody.innerHTML = `<tr><td colspan="9" class="table-empty">Loading…</td></tr>`;

  try {
    const statusFilter = document.getElementById('histFilterStatus').value;
    const apps = await api(`/api/applications${statusFilter ? '?status=' + encodeURIComponent(statusFilter) : ''}`);
    allApps = apps;

    renderApplications(apps);
    populateStatusFilter(apps);
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="9" class="table-empty">Error: ${e.message}</td></tr>`;
  }
}

function renderApplications(apps) {
  const search = document.getElementById('histSearch').value.toLowerCase();
  const filtered = apps.filter(a =>
    !search ||
    a.company?.toLowerCase().includes(search) ||
    a.title?.toLowerCase().includes(search)
  );

  const tbody = document.getElementById('appTableBody');

  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="9" class="table-empty">No applications found.</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map(app => {
    const statusClass = getStatusClass(app.status);
    const aiTag = app.ai_skills_needed
      ? `<span class="badge badge-ai" title="${(app.ai_skills_tags || []).join(', ')}">🤖</span>`
      : '–';

    return `
      <tr>
        <td style="color:var(--text-3)">#${app.app_id}</td>
        <td><strong>${esc(app.company)}</strong></td>
        <td>${esc(app.title)}</td>
        <td><span class="badge badge-source">${esc(app.source)}</span></td>
        <td style="color:var(--text-2)">${formatDate(app.applied_at)}</td>
        <td>
          <span class="status-pill ${statusClass}" onclick="openStatusModal(${app.app_id}, '${esc(app.company)}')">
            ${esc(app.status)}
          </span>
        </td>
        <td style="color:var(--text-2)">${app.days_to_outcome != null ? app.days_to_outcome + 'd' : '–'}</td>
        <td>${aiTag}</td>
        <td>
          <div style="display:flex; gap:6px; flex-wrap:wrap">
            <a href="${esc(app.job_url)}" target="_blank" class="btn btn-ghost btn-sm">JD ↗</a>
            ${app.superfolio_url
              ? `<a href="${esc(app.superfolio_url)}" target="_blank" class="btn btn-ghost btn-sm">Superfolio ↗</a>`
              : ''}
          </div>
        </td>
      </tr>`;
  }).join('');
}

function getStatusClass(status) {
  if (!status) return 'status-custom';
  if (status === 'Applied') return 'status-Applied';
  if (status.startsWith('Interviewing')) return 'status-Interviewing';
  if (status === 'HR Round') return 'status-HR';
  if (status === 'Assignment') return 'status-Assignment';
  if (status === 'Offer') return 'status-Offer';
  if (status === 'Rejected') return 'status-Rejected';
  if (status === 'Ghosted') return 'status-Ghosted';
  return 'status-custom';
}

// ── Status Modal ──────────────────────────────────────
function openStatusModal(appId, company) {
  editingAppId = appId;
  const app = allApps.find(a => a.app_id === appId);

  document.getElementById('statusModalTitle').textContent = `Update: ${company}`;
  document.getElementById('statusModal').style.display = 'flex';
  document.getElementById('customStatusInput').value = '';
  document.getElementById('feedbackSection').style.display = 'none';
  document.getElementById('feedbackText').value = '';
  document.getElementById('statusSuperfolio').value = app?.superfolio_url || '';

  // Render status chips
  const chipsEl = document.getElementById('statusChips');
  chipsEl.innerHTML = PRESET_STATUSES.map(s => `
    <span class="status-chip ${app?.status === s ? 'selected' : ''}" data-status="${esc(s)}">${esc(s)}</span>
  `).join('');

  chipsEl.querySelectorAll('.status-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      chipsEl.querySelectorAll('.status-chip').forEach(c => c.classList.remove('selected'));
      chip.classList.add('selected');
      document.getElementById('customStatusInput').value = '';
      const isTerminal = TERMINAL.has(chip.dataset.status);
      document.getElementById('feedbackSection').style.display = isTerminal ? 'block' : 'none';
    });
  });

  document.getElementById('customStatusInput').addEventListener('input', (e) => {
    if (e.target.value) {
      chipsEl.querySelectorAll('.status-chip').forEach(c => c.classList.remove('selected'));
    }
  });
}

function bindStatusModal() {
  document.getElementById('closeStatusModal').onclick = closeStatusModal;
  document.getElementById('cancelStatus').onclick = closeStatusModal;
  document.getElementById('saveStatus').onclick = saveStatusUpdate;
}

function closeStatusModal() {
  document.getElementById('statusModal').style.display = 'none';
  editingAppId = null;
}

async function saveStatusUpdate() {
  if (!editingAppId) return;

  const selectedChip = document.querySelector('.status-chip.selected');
  const customInput = document.getElementById('customStatusInput').value.trim();
  const newStatus = customInput || selectedChip?.dataset.status;

  if (!newStatus) return alert('Select or type a status.');

  const btn = document.getElementById('saveStatus');
  btn.disabled = true; btn.textContent = 'Saving…';

  try {
    await api(`/api/applications/${editingAppId}/status`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: newStatus }),
    });

    // Save feedback if provided
    const feedbackText = document.getElementById('feedbackText').value.trim();
    const feedbackChannel = document.querySelector('input[name="fbChannel"]:checked')?.value || 'none';
    if (feedbackText && TERMINAL.has(newStatus)) {
      await api(`/api/applications/${editingAppId}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ feedback_text: feedbackText, feedback_channel: feedbackChannel }),
      });
    }

    // Save Superfolio URL if provided
    const sfUrl = document.getElementById('statusSuperfolio').value.trim();
    if (sfUrl) {
      await api(`/api/applications/${editingAppId}/superfolio`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: sfUrl }),
      });
    }

    closeStatusModal();
    await loadStats();
    await loadApplications();
  } catch (e) {
    alert('Error: ' + e.message);
  } finally {
    btn.disabled = false; btn.textContent = 'Save';
  }
}

// ── Filters ───────────────────────────────────────────
function bindFilters() {
  document.getElementById('histFilterStatus').addEventListener('change', loadApplications);
  document.getElementById('histSearch').addEventListener('input', () => renderApplications(allApps));
}

function populateStatusFilter(apps) {
  const statuses = [...new Set(apps.map(a => a.status))].sort();
  const sel = document.getElementById('histFilterStatus');
  const current = sel.value;
  sel.innerHTML = '<option value="">All Statuses</option>' +
    statuses.map(s => `<option value="${esc(s)}" ${s === current ? 'selected' : ''}>${esc(s)}</option>`).join('');
}

// ── Utilities ─────────────────────────────────────────
async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

function esc(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatDate(iso) {
  if (!iso) return '–';
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}
