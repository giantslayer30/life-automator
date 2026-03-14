/* ──────────────────────────────────────────────────────
   JobFlow — Job Board JS
   ────────────────────────────────────────────────────── */

const API = '';  // same-origin

// State
let allJobs = [];
let currentPage = 1;
let selectedJobId = null;
let applyingJobId = null;
let activeResumeId = null;
let activeResumeLabel = 'No resume uploaded';
let applyAllJobIds = [];
let selectedSources = new Set();
let selectedLocations = new Set();

// ── Boot ──────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  await Promise.all([loadSources(), loadLocations(), loadResumes(), loadNegativeKeywords()]);
  await loadJobs();
  bindFilters();
  bindResumeModal();
  bindApplyModal();
  bindScrapeButton();
  bindBlockInput();
  // Close multi-select dropdowns when clicking outside
  document.addEventListener('click', e => {
    if (!e.target.closest('.ms-wrap')) {
      document.querySelectorAll('.ms-list').forEach(d => d.style.display = 'none');
    }
  });
});

// ── Multi-select helpers ───────────────────────────────
function toggleDropdown(id) {
  const el = document.getElementById(id);
  const isOpen = el.style.display !== 'none';
  document.querySelectorAll('.ms-list').forEach(d => d.style.display = 'none');
  if (!isOpen) el.style.display = 'block';
}

function updateTriggerLabel(triggerId, set, defaultLabel) {
  const btn = document.getElementById(triggerId);
  if (set.size === 0) {
    btn.textContent = defaultLabel + ' ▾';
    btn.classList.remove('has-selection');
  } else {
    btn.textContent = `${set.size} selected ▾`;
    btn.classList.add('has-selection');
  }
}

function onSourceChange(checkbox) {
  if (checkbox.checked) selectedSources.add(checkbox.value);
  else selectedSources.delete(checkbox.value);
  updateTriggerLabel('filterSourceTrigger', selectedSources, 'All Sources');
  loadJobs();
}

function onLocationChange(checkbox) {
  if (checkbox.checked) selectedLocations.add(checkbox.value);
  else selectedLocations.delete(checkbox.value);
  updateTriggerLabel('filterLocationTrigger', selectedLocations, 'All Locations');
  loadJobs();
}

// ── Load sources into multi-select ─────────────────────
async function loadSources() {
  try {
    const data = await api('/api/sources');
    const list = document.getElementById('filterSourceList');
    const seen = new Set();
    data.sources.forEach(s => {
      if (!seen.has(s.name)) {
        seen.add(s.name);
        list.innerHTML += `<label class="ms-item"><input type="checkbox" value="${esc(s.name)}" onchange="onSourceChange(this)"> ${esc(s.name)}</label>`;
      }
    });
  } catch {}
}

// ── Load locations into multi-select ───────────────────
async function loadLocations() {
  try {
    const data = await api('/api/locations');
    const list = document.getElementById('filterLocationList');
    if (!data.locations.length) {
      list.innerHTML = '<div class="ms-item" style="color:var(--text-3);cursor:default">No locations yet</div>';
      return;
    }
    data.locations.forEach(loc => {
      list.innerHTML += `<label class="ms-item"><input type="checkbox" value="${esc(loc)}" onchange="onLocationChange(this)"> ${esc(loc)}</label>`;
    });
  } catch {}
}

// ── Load Jobs ─────────────────────────────────────────
async function loadJobs(page = 1) {
  currentPage = page;
  const params = buildJobParams();
  const list = document.getElementById('jobList');
  list.innerHTML = `<div class="loading-state"><div class="spinner"></div><p>Loading jobs…</p></div>`;

  try {
    const data = await api(`/api/jobs?${params}`);
    allJobs = data.jobs;

    document.getElementById('jobCount').textContent =
      `${data.total.toLocaleString()} job${data.total !== 1 ? 's' : ''}`;

    if (!data.jobs.length) {
      list.innerHTML = `<div class="loading-state"><p>No jobs found. Try adjusting filters or refresh.</p></div>`;
      return;
    }

    list.innerHTML = data.jobs.map(renderJobCard).join('');
    bindCardClicks();

    // Add Apply All button if >1 unapplied job
    const unapplied = data.jobs.filter(j => !j.application_status);
    if (unapplied.length > 1) {
      const applyAllBtn = document.createElement('button');
      applyAllBtn.className = 'btn btn-secondary';
      applyAllBtn.style.cssText = 'margin: 0 0 8px; width:100%;';
      applyAllBtn.textContent = `Apply to all ${unapplied.length} listed jobs`;
      applyAllBtn.onclick = () => confirmApplyAll(unapplied.map(j => j.id));
      list.prepend(applyAllBtn);
    }
  } catch (e) {
    list.innerHTML = `<div class="loading-state"><p>Failed to load jobs: ${e.message}</p></div>`;
  }
}

function buildJobParams() {
  const p = new URLSearchParams();
  p.set('page', currentPage);
  p.set('per_page', 30);
  if (selectedSources.size)   p.set('source',   [...selectedSources].join(','));
  if (selectedLocations.size) p.set('location', [...selectedLocations].join(','));
  const remote = document.getElementById('filterRemote').checked;
  const ai     = document.getElementById('filterAI').checked;
  const search = document.getElementById('searchInput').value.trim();
  if (remote)  p.set('remote', 'true');
  if (ai)      p.set('ai_skills', 'true');
  if (search)  p.set('search', search);
  return p.toString();
}

function renderJobCard(job) {
  const applied = job.application_status;
  const aiTag   = job.ai_skills_needed ? renderAIBadge(job) : '';
  const visaTag = job.visa_sponsorship  ? renderVisaBadge(job) : '';
  const remoteBadge = job.remote ? `<span class="badge badge-remote">Remote</span>` : '';
  const salary = formatSalary(job);
  const dateStr = job.scraped_at ? `<span class="job-date">${formatDate(job.scraped_at)}</span>` : '';

  return `
    <div class="job-card ${applied ? 'applied' : ''}" data-id="${job.id}" ${applied ? `data-applied="${applied}"` : ''}>
      ${applied ? `<div class="applied-overlay">✓ ${applied}</div>` : ''}
      <div class="job-card-header">
        <div>
          <div class="job-title">${esc(job.title)}</div>
          <div class="job-company">${esc(job.company)}${job.location ? ` · ${esc(job.location)}` : ''}</div>
        </div>
      </div>
      <div class="job-meta">
        <span class="badge badge-source">${esc(job.source)}</span>
        ${remoteBadge}
        ${aiTag}
        ${visaTag}
        ${salary ? `<span class="job-salary">${salary}</span>` : ''}
        ${job.closed_at ? `<span class="badge badge-closed">Closed</span>` : ''}
        ${dateStr}
      </div>
    </div>`;
}

function renderAIBadge(job) {
  const terms = Array.isArray(job.ai_skills_tags) ? job.ai_skills_tags : [];
  const tooltip = terms.length
    ? `Keywords: ${terms.slice(0, 4).map(t => `"${t}"`).join(', ')}`
    : 'AI skills required';
  return `
    <span class="badge badge-ai ai-tooltip">
      🤖 AI skills needed
      <span class="tooltip-text">${esc(tooltip)}</span>
    </span>`;
}

function renderVisaBadge(job) {
  const terms = Array.isArray(job.visa_tags) ? job.visa_tags : [];
  const tooltip = terms.length
    ? `Keywords: ${terms.slice(0, 3).map(t => `"${t}"`).join(', ')}`
    : 'Visa / relocation support mentioned';
  return `
    <span class="badge badge-visa ai-tooltip">
      ✈ Visa / Relocation
      <span class="tooltip-text">${esc(tooltip)}</span>
    </span>`;
}

function formatSalary(job) {
  if (!job.salary_min && !job.salary_max) return '';
  const curr = job.salary_currency === 'INR' ? '₹' : '$';
  const fmt = n => n >= 100000 ? `${(n/100000).toFixed(1)}L` : n >= 1000 ? `${(n/1000).toFixed(0)}K` : n;
  if (job.salary_min && job.salary_max && job.salary_min !== job.salary_max)
    return `${curr}${fmt(job.salary_min)} – ${curr}${fmt(job.salary_max)}`;
  if (job.salary_min) return `${curr}${fmt(job.salary_min)}+`;
  return '';
}

function bindCardClicks() {
  document.querySelectorAll('.job-card').forEach(card => {
    card.addEventListener('click', () => {
      document.querySelectorAll('.job-card').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
      const id = parseInt(card.dataset.id);
      showJobDetail(id);
    });
  });
}

// ── Job Detail Panel ──────────────────────────────────
async function showJobDetail(jobId) {
  selectedJobId = jobId;
  const panel = document.getElementById('detailPanel');
  panel.innerHTML = `<div class="loading-state"><div class="spinner"></div></div>`;

  try {
    const job = await api(`/api/jobs/${jobId}`);
    const applied = job.application_status;
    const salary = formatSalary(job);

    panel.innerHTML = `
      <div class="detail-header">
        <div class="detail-title">${esc(job.title)}</div>
        <div class="detail-company">${esc(job.company)}${job.location ? ` · ${esc(job.location)}` : ''}</div>
        <div class="detail-meta">
          <span class="badge badge-source">${esc(job.source)}</span>
          ${job.remote ? '<span class="badge badge-remote">Remote</span>' : ''}
          ${job.ai_skills_needed ? renderAIBadge(job) : ''}
          ${job.visa_sponsorship  ? renderVisaBadge(job) : ''}
          ${salary ? `<span class="badge badge-source">${salary}</span>` : ''}
          ${job.employment_type ? `<span class="badge badge-source">${esc(job.employment_type)}</span>` : ''}
        </div>
      </div>

      ${job.ai_skills_needed && Array.isArray(job.ai_skills_tags) && job.ai_skills_tags.length ? `
        <div class="detail-section">
          <h4>AI Skills Required</h4>
          <div style="display:flex; gap:6px; flex-wrap:wrap">
            ${job.ai_skills_tags.map(t => `<span class="badge badge-ai">${esc(t)}</span>`).join('')}
          </div>
        </div>` : ''}

      <div class="detail-section">
        <h4>Description</h4>
        <div class="detail-description">${job.description ? esc(job.description).replace(/\n/g, '<br>') : 'No description available.'}</div>
      </div>

      <div class="claude-prompt-section">
        <div class="claude-prompt-header">
          <span class="claude-prompt-title">✦ Tailor your resume with Claude</span>
          <button class="btn btn-sm btn-secondary" onclick="copyClaudePrompt()">Copy prompt</button>
        </div>
        <p class="claude-prompt-hint">Copy this and paste it into <a href="https://claude.ai" target="_blank" rel="noopener">claude.ai</a> along with your resume to get honest, specific tailoring suggestions.</p>
        <textarea class="claude-prompt-text" id="claudePromptText" readonly></textarea>
      </div>

      <div class="detail-section">
        <h4>Posted</h4>
        <small style="color:var(--text-2)">${formatDate(job.scraped_at)} via ${esc(job.source)}</small>
      </div>

      <div class="detail-actions">
        ${applied
          ? `<span class="badge badge-applied" style="font-size:13px">✓ ${esc(applied)}</span>
             <a href="/history" class="btn btn-ghost btn-sm">View Application →</a>`
          : `<a href="${esc(job.url)}" target="_blank" rel="noopener" class="btn btn-ghost">Open JD ↗</a>
             <button class="btn btn-primary" onclick="openApplyModal(${job.id}, '${esc(job.title)}', '${esc(job.company)}')">
               Apply
             </button>`
        }
      </div>`;
    // Set Claude prompt text after innerHTML (avoids HTML encoding issues)
    const promptEl = document.getElementById('claudePromptText');
    if (promptEl) {
      promptEl.value = buildClaudePrompt(job);
    }
  } catch (e) {
    panel.innerHTML = `<div class="loading-state"><p>Error: ${e.message}</p></div>`;
  }
}

function buildClaudePrompt(job) {
  const lines = [
    `I'm applying for a job and want to tailor my resume for this role without falsifying anything.`,
    ``,
    `ROLE: ${job.title} at ${job.company}`,
    job.location ? `LOCATION: ${job.location}` : null,
    job.employment_type ? `TYPE: ${job.employment_type}` : null,
    ``,
    `=== JOB DESCRIPTION ===`,
    job.description || 'No description provided.',
    `=== END ===`,
    ``,
    `Please help me:`,
    `1. List the top 8–10 keywords and skills from this JD I should include in my resume if they honestly apply to me`,
    `2. Suggest specific rewrite ideas for resume bullet points to better match this role's language and priorities`,
    `3. Highlight any notable requirements I should address in a cover note`,
    `4. Flag any gaps so I can decide whether to apply or prepare better first`,
  ].filter(l => l !== null).join('\n');
  return lines;
}

function copyClaudePrompt() {
  const el = document.getElementById('claudePromptText');
  if (!el) return;
  el.select();
  navigator.clipboard.writeText(el.value).then(() => {
    const btn = el.closest('.claude-prompt-section').querySelector('button');
    const orig = btn.textContent;
    btn.textContent = 'Copied!';
    setTimeout(() => btn.textContent = orig, 2000);
  }).catch(() => document.execCommand('copy'));
}

// ── Filters ───────────────────────────────────────────
function bindFilters() {
  let searchTimeout;
  document.getElementById('searchInput').addEventListener('input', () => {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => loadJobs(), 400);
  });
  ['filterRemote', 'filterAI'].forEach(id => {
    document.getElementById(id).addEventListener('change', () => loadJobs());
  });
}

// ── Apply Modal ───────────────────────────────────────
function openApplyModal(jobId, title, company) {
  applyingJobId = jobId;
  document.getElementById('applyModalTitle').textContent = `Apply to ${title} @ ${company}`;
  document.getElementById('applyModal').style.display = 'flex';
  document.getElementById('resumeLabel').textContent = activeResumeLabel;
  document.getElementById('superfolioInput').value = '';

  if (activeResumeId) {
    document.getElementById('previewPdfLink').style.display = 'inline';
    document.getElementById('previewPdfLink').href = `/api/resume/${activeResumeId}/pdf`;
  }
}

function bindApplyModal() {
  document.getElementById('closeApplyModal').onclick = closeApplyModal;
  document.getElementById('cancelApply').onclick = closeApplyModal;
  document.getElementById('confirmApply').onclick = submitApplication;
}

function closeApplyModal() {
  document.getElementById('applyModal').style.display = 'none';
  applyingJobId = null;
}


async function submitApplication() {
  if (!applyingJobId) return;
  const btn = document.getElementById('confirmApply');
  btn.disabled = true;
  btn.textContent = 'Applying…';

  try {
    const sfUrl = document.getElementById('superfolioInput').value.trim() || null;
    await api(`/api/apply/${applyingJobId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ resume_id: activeResumeId, superfolio_url: sfUrl }),
    });

    closeApplyModal();
    await loadJobs(currentPage);
    if (selectedJobId === applyingJobId) showJobDetail(applyingJobId);
  } catch (e) {
    alert(e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Apply Now';
  }
}

// ── Apply All ─────────────────────────────────────────
function confirmApplyAll(jobIds) {
  applyAllJobIds = jobIds;
  const toast = document.getElementById('applyAllToast');
  document.getElementById('applyAllMsg').textContent = `Apply to ${jobIds.length} jobs?`;
  toast.style.display = 'flex';

  document.getElementById('confirmApplyAll').onclick = async () => {
    toast.style.display = 'none';
    const result = await api('/api/apply/bulk', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_ids: applyAllJobIds, resume_id: activeResumeId }),
    });
    alert(`Applied to ${result.applied.length} jobs. Skipped ${result.skipped.length} (already applied).`);
    await loadJobs(currentPage);
  };

  document.getElementById('cancelApplyAll').onclick = () => {
    toast.style.display = 'none';
    applyAllJobIds = [];
  };
}

// ── Resume Modal ──────────────────────────────────────
function bindResumeModal() {
  document.getElementById('btnUploadResume').onclick = openResumeModal;
  document.getElementById('closeResumeModal').onclick = closeResumeModal;

  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      document.querySelectorAll('.tab-content').forEach(t => t.style.display = 'none');
      document.getElementById(`tab${btn.dataset.tab.charAt(0).toUpperCase() + btn.dataset.tab.slice(1)}`).style.display = 'block';

      if (btn.dataset.tab === 'versions') loadVersionList();
    });
  });

  document.getElementById('saveResumeBtn').onclick = saveResume;

  // Show chosen filename when file selected
  document.getElementById('resumeFile').addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file) {
      document.getElementById('fileUploadPrompt').style.display = 'none';
      const nameEl = document.getElementById('fileUploadName');
      nameEl.textContent = '📄 ' + file.name;
      nameEl.style.display = 'block';
    }
  });
}

function openResumeModal() {
  document.getElementById('resumeModal').style.display = 'flex';
}
function closeResumeModal() {
  document.getElementById('resumeModal').style.display = 'none';
}

function previewHtml() {
  const html = document.getElementById('resumeHtml').value;
  const win = window.open('', '_blank');
  win.document.write(html);
  win.document.close();
}

async function saveResume() {
  const fileInput = document.getElementById('resumeFile');
  const label = document.getElementById('resumeLabelInput').value.trim();
  const statusEl = document.getElementById('resumeSaveStatus');

  if (!fileInput.files || !fileInput.files[0]) {
    return alert('Please select a .docx file first.');
  }

  const btn = document.getElementById('saveResumeBtn');
  btn.disabled = true; btn.textContent = 'Uploading…';
  statusEl.style.display = 'none';

  try {
    const fd = new FormData();
    fd.append('file', fileInput.files[0]);
    if (label) fd.append('label', label);

    const res = await fetch('/api/resume/upload', { method: 'POST', body: fd });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Upload failed' }));
      throw new Error(err.detail || 'Upload failed');
    }
    const result = await res.json();

    activeResumeId = result.resume_id;
    activeResumeLabel = `Resume v${result.version}${label ? ' — ' + label : ''}`;

    statusEl.className = 'status-msg status-ok';
    statusEl.textContent = `✓ Saved as Resume v${result.version}. ${result.diff_result?.message || ''}`;
    statusEl.style.display = 'block';
  } catch (e) {
    statusEl.className = 'status-msg status-err';
    statusEl.textContent = `Error: ${e.message}`;
    statusEl.style.display = 'block';
  } finally {
    btn.disabled = false; btn.textContent = 'Save & Generate PDF';
  }
}

async function loadResumes() {
  try {
    const versions = await api('/api/resume/versions');
    const active = versions.find(v => v.is_active);
    if (active) {
      activeResumeId = active.id;
      activeResumeLabel = `Resume v${active.version}${active.label ? ' — ' + active.label : ''}`;
    }
  } catch {}
}

async function loadVersionList() {
  const el = document.getElementById('versionList');
  el.innerHTML = 'Loading…';
  try {
    const versions = await api('/api/resume/versions');
    if (!versions.length) { el.innerHTML = '<p style="color:var(--text-3)">No resumes yet.</p>'; return; }
    el.innerHTML = versions.map(v => `
      <div class="version-item">
        <div class="version-num">v${v.version}</div>
        <div class="version-info">
          <div class="version-label">${v.label || 'Untitled'}</div>
          <div class="version-date">${formatDate(v.created_at)}</div>
        </div>
        ${v.is_active ? '<span class="version-active">Active</span>' : ''}
        ${v.local_path ? `<a href="/api/resume/${v.id}/pdf" target="_blank" class="btn btn-ghost btn-sm">Preview PDF ↗</a>` : ''}
      </div>`).join('');
  } catch {
    el.innerHTML = 'Failed to load versions.';
  }
}

// ── Scrape ────────────────────────────────────────────
function bindScrapeButton() {
  document.getElementById('btnScrapeNow').onclick = async () => {
    const btn = document.getElementById('btnScrapeNow');
    btn.disabled = true; btn.textContent = '↻ Scraping…';
    try {
      await api('/api/scrape/run', { method: 'POST' });
      setTimeout(() => { btn.disabled = false; btn.textContent = '↻ Refresh Jobs'; loadJobs(); }, 3000);
    } catch {
      btn.disabled = false; btn.textContent = '↻ Refresh Jobs';
    }
  };
}

// ── Blocked keywords ──────────────────────────────────
async function loadNegativeKeywords() {
  const { keywords } = await api('/api/keywords/negative');
  renderBlockTags(keywords);
}

function renderBlockTags(keywords) {
  const container = document.getElementById('blockTags');
  container.innerHTML = keywords.map(k => `
    <span class="block-tag">
      ${esc(k.keyword)}
      <button class="block-tag-remove" onclick="removeKeyword(${k.id})" title="Remove">×</button>
    </span>`).join('');
}

async function removeKeyword(id) {
  await api(`/api/keywords/negative/${id}`, { method: 'DELETE' });
  loadNegativeKeywords();
}

function bindBlockInput() {
  const input = document.getElementById('blockKeywordInput');
  input.addEventListener('keydown', async e => {
    if (e.key !== 'Enter' && e.key !== ',') return;
    e.preventDefault();
    const kw = input.value.trim().replace(/,$/, '');
    if (!kw) return;
    input.value = '';
    try {
      await api('/api/keywords/negative', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keyword: kw }),
      });
      loadNegativeKeywords();
    } catch {
      // duplicate or empty — ignore
    }
  });
}

// ── Utilities ─────────────────────────────────────────
async function api(path, opts = {}) {
  const res = await fetch(API + path, opts);
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
