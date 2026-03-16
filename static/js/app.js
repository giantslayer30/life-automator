// ─── STATE ───────────────────────────────────────────────────────
let currentJobs = [];
let currentDetailJobId = null;
let initialLoadDone = false;

const SOURCE_COLORS = {
  remote_ok:          '#2B2B2B',
  we_work_remotely:   '#FF5850',
  himalayas:          '#6366F1',
  jsearch:            '#0A66C2',
  visa_search:        '#10B981',
  wellfound:          '#000000',
  naukri:             '#4A90D9',
  behance:            '#1769FF',
  arc_dev:            '#6E56CF',
  foundit:            '#F97316',
  aiga:               '#222222',
};

// ─── HELPERS ─────────────────────────────────────────────────────
function timeAgo(isoString) {
  if (!isoString) return 'Recently';
  const secs = Math.floor((Date.now() - new Date(isoString)) / 1000);
  if (secs < 60) return 'just now';
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function formatSalary(job) {
  if (!job.salary_min && !job.salary_max) return null;
  const cur = job.salary_currency || '';
  const min = job.salary_min ? `${cur}${Number(job.salary_min).toLocaleString()}` : '';
  const max = job.salary_max ? `${cur}${Number(job.salary_max).toLocaleString()}` : '';
  return min && max ? `${min}–${max}` : min || max;
}

const SOURCE_LABELS = {
  remote_ok:          'Remote OK',
  we_work_remotely:   'We Work Remotely',
  himalayas:          'Himalayas',
  jsearch:            'LinkedIn / Indeed',
  visa_search:        'Visa Sponsorship',
  wellfound:          'Wellfound',
  naukri:             'Naukri',
  behance:            'Behance',
  arc_dev:            'Arc.dev',
  foundit:            'Foundit',
  aiga:               'AIGA',
};

function jobToDisplay(job) {
  const tags = [];
  if (job.employment_type) tags.push(job.employment_type);
  if (job.remote)          tags.push('Remote');
  if (job.location && !job.remote) tags.push(job.location);

  return {
    logo:         (job.company || '?')[0].toUpperCase(),
    logoColor:    SOURCE_COLORS[job.source] || '#3B6EF6',
    sourceLabel:  SOURCE_LABELS[job.source] || job.source,
    posted:       timeAgo(job.scraped_at),
    location:     job.location || (job.remote ? 'Remote' : ''),
    tags,
    salary:       formatSalary(job),
    hasAI:        !!job.ai_skills_needed,
    aiKeywords:   Array.isArray(job.ai_skills_tags) ? job.ai_skills_tags.join(', ') : '',
    hasVisa:      !!job.visa_sponsorship,
    visaKeywords: Array.isArray(job.visa_tags) ? job.visa_tags.join(', ') : '',
    glassdoorUrl: job.company ? `https://www.glassdoor.com/Search/results.htm?keyword=${encodeURIComponent(job.company)}` : null,
  };
}

// ─── FETCH JOBS ──────────────────────────────────────────────────
async function fetchJobs(params = {}) {
  const qs = new URLSearchParams();
  if (params.search)            qs.set('search', params.search);
  if (params.source)            qs.set('source', params.source);
  if (params.remote    != null) qs.set('remote', params.remote);
  if (params.ai_skills != null) qs.set('ai_skills', params.ai_skills);
  if (params.page)              qs.set('page', params.page);

  const res = await fetch(`/api/jobs?${qs}`);
  if (!res.ok) throw new Error('Failed to fetch jobs');
  return res.json();
}

// ─── RENDER JOB LIST ─────────────────────────────────────────────
function renderJobs(jobs) {
  const list = document.getElementById('job-list');
  document.getElementById('job-count').textContent  = jobs.length;
  document.getElementById('stat-total').textContent = jobs.length;

  if (jobs.length === 0) {
    list.innerHTML = `
      <div class="empty-state">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
          <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/><path d="M8 11h6"/>
        </svg>
        <h3>No jobs found</h3>
        <p>Try adjusting your filters or search terms</p>
      </div>`;
    return;
  }

  list.innerHTML = jobs.map(job => {
    const d = jobToDisplay(job);
    const appliedBadge = job.application_status
      ? `<span class="job-tag status-applied">${job.application_status}</span>`
      : '';
    return `
    <div class="job-card${job.application_status ? ' selected' : ''}" data-id="${job.id}" onclick="openDetail(${job.id})">
      <div class="job-card-header">
        <div class="company-logo" style="color:${d.logoColor};font-size:18px;font-weight:800;">${d.logo}</div>
        <div style="flex:1;min-width:0">
          <div class="job-card-title">${job.title}</div>
          <div class="job-card-company">
            ${job.company}
            <span class="dot"></span>
            ${d.posted}
          </div>
        </div>
        <span class="source-badge" style="background:${d.logoColor}">${d.sourceLabel}</span>
      </div>
      <div class="job-card-meta">
        ${d.location ? `<span class="meta-item"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>${d.location}</span>` : ''}
        ${d.salary ? `<span class="meta-item"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>${d.salary}</span>` : ''}
      </div>
      <div class="job-card-footer">
        <div class="job-tags">
          ${d.tags.map(t => `<span class="job-tag">${t}</span>`).join('')}
          ${d.hasAI   ? `<span class="job-tag badge-ai"  data-tooltip="${d.aiKeywords}">AI</span>`   : ''}
          ${d.hasVisa ? `<span class="job-tag badge-visa" data-tooltip="${d.visaKeywords}">Visa</span>` : ''}
          ${appliedBadge}
        </div>
        ${d.glassdoorUrl ? `<a href="${d.glassdoorUrl}" target="_blank" class="glassdoor-link" onclick="event.stopPropagation()" title="Search on Glassdoor">Glassdoor</a>` : ''}
      </div>
    </div>`;
  }).join('');
}

// ─── DETAIL PANEL ────────────────────────────────────────────────
async function openDetail(id) {
  currentDetailJobId = id;
  const job = currentJobs.find(j => j.id === id);
  if (!job) return;

  const d = jobToDisplay(job);
  document.getElementById('detail-logo').textContent    = d.logo;
  document.getElementById('detail-logo').style.color    = d.logoColor;
  document.getElementById('detail-title').textContent   = job.title;
  document.getElementById('detail-company').textContent = `${job.company} · ${d.posted}`;
  document.getElementById('detail-desc').textContent    = 'Loading…';
  document.getElementById('claude-prompt').textContent  = '';

  const meta = document.getElementById('detail-meta');
  meta.innerHTML = [
    ...d.tags.map(t => `<span class="job-tag">${t}</span>`),
    d.hasAI   ? `<span class="job-tag badge-ai">🤖 AI Skills</span>`  : '',
    d.hasVisa ? `<span class="job-tag badge-visa">✈ Visa</span>`       : '',
    d.salary  ? `<span class="job-tag" style="font-weight:600;">${d.salary}</span>` : '',
    job.application_status ? `<span class="job-tag status-applied">${job.application_status}</span>` : '',
  ].filter(Boolean).join('');

  // "Did you apply?" prompt state
  const promptEl      = document.getElementById('applied-prompt');
  const superfolioEl  = document.getElementById('applied-superfolio');
  const doneEl        = document.getElementById('applied-done');

  if (job.application_status) {
    promptEl.style.display     = 'none';
    superfolioEl.style.display = 'none';
    doneEl.style.display       = 'flex';
    doneEl.querySelector('.applied-check').textContent = `Applied — ${job.application_status}`;
  } else {
    promptEl.style.display     = 'flex';
    superfolioEl.style.display = 'none';
    doneEl.style.display       = 'none';

    document.getElementById('btn-applied-yes').onclick = () => {
      promptEl.style.display     = 'none';
      superfolioEl.style.display = 'flex';
      document.getElementById('superfolio-input').value = '';
    };
    document.getElementById('btn-applied-no').onclick = () => {
      promptEl.style.display = 'none';
    };
    document.getElementById('btn-save-applied').onclick = () => markApplied(id);
  }

  // External link button
  const linkBtn = document.getElementById('detail-link-btn');
  if (linkBtn) linkBtn.onclick = () => job.url && window.open(job.url, '_blank');

  document.getElementById('detail-overlay').classList.add('open');
  document.body.style.overflow = 'hidden';

  // Async: load full description
  try {
    const res = await fetch(`/api/jobs/${id}`);
    if (res.ok) {
      const full = await res.json();
      const desc = full.description || 'No description available.';
      document.getElementById('detail-desc').textContent  = desc;
      document.getElementById('claude-prompt').textContent =
        `Paste this job description into Claude along with your resume to get a tailored version:\n\n${desc}`;
    }
  } catch (_) {
    document.getElementById('detail-desc').textContent = 'Could not load description.';
  }
}

function closeDetail() {
  document.getElementById('detail-overlay').classList.remove('open');
  document.body.style.overflow = '';
  currentDetailJobId = null;
}

document.getElementById('detail-overlay').addEventListener('click', function (e) {
  if (e.target === this) closeDetail();
});

// ─── MARK APPLIED ────────────────────────────────────────────────
async function markApplied(jobId) {
  const sfUrl = document.getElementById('superfolio-input').value.trim();
  const saveBtn = document.getElementById('btn-save-applied');
  saveBtn.disabled = true;
  saveBtn.textContent = 'Saving…';

  try {
    const res = await fetch(`/api/apply/${jobId}`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ superfolio_url: sfUrl || null }),
    });

    if (res.ok || res.status === 409) {
      document.getElementById('applied-superfolio').style.display = 'none';
      const doneEl = document.getElementById('applied-done');
      doneEl.style.display = 'flex';
      doneEl.querySelector('.applied-check').textContent = 'Applied';
      const job = currentJobs.find(j => j.id === jobId);
      if (job) job.application_status = 'Applied';
      renderJobs(currentJobs);
      loadApplicationStats();
    }
  } catch (_) {}

  saveBtn.disabled = false;
  saveBtn.textContent = 'Save';
}

// ─── SEARCH ──────────────────────────────────────────────────────
let _searchTimer;
document.getElementById('search-input').addEventListener('input', function () {
  clearTimeout(_searchTimer);
  const q = this.value.trim();
  _searchTimer = setTimeout(() => {
    document.querySelector('.results-title span').textContent = q || 'All Jobs';
    loadJobs({ search: q || undefined });
  }, 350);
});

// ─── FILTERS ─────────────────────────────────────────────────────
function getFilterParams() {
  const allSourceBoxes = [...document.querySelectorAll('[data-source]')];
  const checkedSources = allSourceBoxes.filter(cb => cb.checked).map(cb => cb.dataset.source);
  // Only filter by source if user has unchecked at least one — otherwise show all
  const allChecked = checkedSources.length === allSourceBoxes.length;
  const noneChecked = checkedSources.length === 0;

  const toggles  = [...document.querySelectorAll('.toggle')];
  const remoteOn = toggles[0]?.classList.contains('active');
  const aiOn     = toggles[1]?.classList.contains('active');
  const search   = document.getElementById('search-input').value.trim();
  return {
    source:    (!allChecked && !noneChecked) ? checkedSources.join(',') : undefined,
    remote:    remoteOn  || undefined,
    ai_skills: aiOn      || undefined,
    search:    search    || undefined,
  };
}

function applyFilters() { loadJobs(getFilterParams()); }

document.querySelectorAll('[data-source]').forEach(cb =>
  cb.addEventListener('change', applyFilters)
);

document.querySelectorAll('.toggle').forEach(toggle =>
  toggle.addEventListener('click', function () {
    this.classList.toggle('active');
    applyFilters();
  })
);

document.querySelector('.btn-apply').addEventListener('click', applyFilters);

document.querySelector('.btn-clear').addEventListener('click', () => {
  document.querySelectorAll('[data-source]').forEach(cb => (cb.checked = false));
  document.querySelectorAll('.toggle').forEach(t => t.classList.remove('active'));
  document.getElementById('search-input').value = '';
  document.querySelector('.results-title span').textContent = 'All Jobs';
  loadJobs({});
});

// ─── BLOCK KEYWORDS ──────────────────────────────────────────────
async function loadNegativeKeywords() {
  try {
    const res = await fetch('/api/keywords/negative');
    if (!res.ok) return;
    const data = await res.json();
    const wrap = document.getElementById('keyword-wrap');
    const input = document.getElementById('keyword-input');
    // Remove existing tags (but not the input itself)
    wrap.querySelectorAll('.keyword-tag').forEach(t => t.remove());
    data.keywords.forEach(({ id, keyword }) => {
      const tag = document.createElement('span');
      tag.className = 'keyword-tag';
      tag.dataset.id = id;
      tag.innerHTML = `${keyword} <button>&times;</button>`;
      tag.querySelector('button').onclick = () => removeNegativeKeyword(id, tag);
      wrap.insertBefore(tag, input);
    });
  } catch (_) {}
}

async function removeNegativeKeyword(id, tagEl) {
  tagEl.remove();
  try {
    await fetch(`/api/keywords/negative/${id}`, { method: 'DELETE' });
    loadJobs(getFilterParams());
  } catch (_) {}
}

document.getElementById('keyword-input').addEventListener('keydown', async function (e) {
  if (e.key === 'Enter' && this.value.trim()) {
    const kw = this.value.trim();
    this.value = '';
    try {
      const res = await fetch('/api/keywords/negative', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ keyword: kw }),
      });
      if (res.ok) {
        await loadNegativeKeywords();
        loadJobs(getFilterParams());
      }
    } catch (_) {}
  }
});

// ─── MOBILE FILTER TOGGLE ────────────────────────────────────────
const filterToggleBtn = document.getElementById('filter-toggle-btn');
if (filterToggleBtn) filterToggleBtn.addEventListener('click', () =>
  document.getElementById('filter-panel').classList.toggle('open')
);
document.getElementById('filter-close-btn').addEventListener('click', () =>
  document.getElementById('filter-panel').classList.remove('open')
);

// ─── KEYBOARD SHORTCUTS ──────────────────────────────────────────
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    closeDetail();
    document.getElementById('filter-panel').classList.remove('open');
  }
});

// ─── RECENT APPLICATIONS SIDEBAR ─────────────────────────────────
async function loadApplicationStats() {
  try {
    const res = await fetch('/api/applications?limit=5');
    if (!res.ok) return;
    const apps = await res.json();

    document.getElementById('stat-applied').textContent = apps.length;

    const container = document.getElementById('recent-apps');
    if (!apps.length) {
      container.innerHTML = '<p style="font-size:13px;color:var(--text-muted)">No applications yet.</p>';
      return;
    }

    const STATUS_CLASS = {
      applied:      'status-applied',
      interviewing: 'status-interviewing',
      offer:        'status-offer',
      rejected:     'status-rejected',
    };

    container.innerHTML = apps.map(app => {
      const cls = STATUS_CLASS[(app.status || '').toLowerCase()] || 'status-applied';
      return `
      <div class="app-history-item">
        <div>
          <div class="app-history-company">${app.company || '—'}</div>
          <div class="app-history-role">${app.title || '—'}</div>
        </div>
        <span class="status-badge ${cls}">${app.status || 'Applied'}</span>
      </div>`;
    }).join('');
  } catch (_) { /* silent */ }
}

// ─── MAIN LOADER ─────────────────────────────────────────────────
async function loadJobs(params = {}) {
  const list = document.getElementById('job-list');
  // Only show loading placeholder on first load, not during poll refreshes
  if (!initialLoadDone) {
    list.innerHTML = `<div style="padding:40px;text-align:center;color:var(--text-muted)">Loading jobs…</div>`;
  }

  try {
    const data  = await fetchJobs(params);
    currentJobs = data.jobs || [];
    const total = data.total ?? currentJobs.length;
    document.getElementById('job-count').textContent  = total;
    document.getElementById('stat-total').textContent = total;
    renderJobs(currentJobs);
    initialLoadDone = true;
  } catch (_) {
    if (!initialLoadDone) {
      list.innerHTML = `<div style="padding:40px;text-align:center;color:var(--red)">
        Failed to load jobs. Is the server running?
      </div>`;
    }
  }
}

// ─── SCRAPE STATS ────────────────────────────────────────────────
async function loadScrapeStats() {
  try {
    const res = await fetch('/api/scrape/stats');
    if (!res.ok) return;
    const data = await res.json();
    const container = document.getElementById('scrape-stats');
    if (!data.sources || !data.sources.length) {
      container.innerHTML = '<p style="font-size:13px;color:var(--text-muted)">No data yet.</p>';
      return;
    }
    container.innerHTML = data.sources.map(s => {
      const label = SOURCE_LABELS[s.source] || s.source;
      const color = SOURCE_COLORS[s.source] || '#6B7185';
      const when  = s.last_scraped ? timeAgo(s.last_scraped) : 'never';
      return `
      <div class="portal-stat-row">
        <span class="portal-dot" style="background:${color}"></span>
        <div class="portal-stat-info">
          <span class="portal-stat-name">${label}</span>
          <span class="portal-stat-meta">${s.count} jobs · ${when}</span>
        </div>
      </div>`;
    }).join('');
  } catch (_) { /* silent */ }
}

async function triggerScrape() {
  const btn = document.getElementById('scrape-btn');
  btn.disabled = true;
  btn.innerHTML = `
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" class="spin">
      <path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/>
      <path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/>
    </svg>
    Scraping…`;

  try {
    await fetch('/api/scrape/run', { method: 'POST' });
  } catch (_) {}

  startScrapeStatusPoll();
}

// ─── SCRAPE STATUS POLLING ───────────────────────────────────────
let scrapePollInterval = null;

function startScrapeStatusPoll() {
  if (scrapePollInterval) return; // already polling
  scrapePollInterval = setInterval(pollScrapeStatus, 2000);
  pollScrapeStatus(); // immediate first check
}

async function pollScrapeStatus() {
  const banner = document.getElementById('scrape-banner');
  const btn = document.getElementById('scrape-btn');

  try {
    const res = await fetch('/api/scrape/status');
    if (!res.ok) return;
    const data = await res.json();

    if (!data.active && data.completed.length === 0) {
      // No scrape running or completed
      banner.style.display = 'none';
      clearInterval(scrapePollInterval);
      scrapePollInterval = null;
      return;
    }

    if (data.active) {
      banner.style.display = 'block';
      const done = data.completed.length;
      const total = data.total_sources;
      const pct = total > 0 ? Math.round((done / total) * 100) : 0;
      const currentLabel = SOURCE_LABELS[data.current_source] || data.current_source || '…';
      const elapsed = data.started_at ? Math.round((Date.now() - new Date(data.started_at)) / 1000) : 0;
      const avgPerSource = done > 0 ? elapsed / done : 8; // estimate ~8s per source
      const remaining = Math.max(0, Math.round(avgPerSource * (total - done)));

      document.getElementById('scrape-banner-status').textContent = `Scraping ${currentLabel}…`;
      document.getElementById('scrape-banner-detail').textContent =
        remaining > 60 ? `~${Math.ceil(remaining / 60)} min remaining` : `~${remaining}s remaining`;
      document.getElementById('scrape-banner-count').textContent = `${done}/${total}`;
      document.getElementById('scrape-banner-fill').style.width = `${pct}%`;

      // Refresh job list and stats while scraping
      await Promise.all([loadJobs(getFilterParams()), loadScrapeStats()]);
    } else {
      // Scrape just finished — stop polling immediately
      clearInterval(scrapePollInterval);
      scrapePollInterval = null;

      const totalNew = data.completed.reduce((sum, s) => sum + (s.new || 0), 0);
      document.getElementById('scrape-banner-status').textContent = 'Scrape complete';
      document.getElementById('scrape-banner-detail').textContent =
        `Found ${totalNew} new job${totalNew !== 1 ? 's' : ''} from ${data.completed.length} sources`;
      document.getElementById('scrape-banner-count').textContent = '';
      document.getElementById('scrape-banner-fill').style.width = '100%';
      document.getElementById('scrape-banner').querySelector('svg').classList.remove('spin');

      // Final refresh — once only
      await Promise.all([loadJobs(getFilterParams()), loadScrapeStats()]);

      // Reset button
      btn.disabled = false;
      btn.innerHTML = `
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
          <path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/>
          <path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/>
        </svg>
        Refresh`;

      // Hide banner after a few seconds
      setTimeout(() => { banner.style.display = 'none'; }, 5000);
    }
  } catch (_) {}
}

// ─── INIT ─────────────────────────────────────────────────────────
loadJobs();
loadApplicationStats();
loadScrapeStats();
loadNegativeKeywords();

// If a scrape is already running (e.g. startup auto-scrape), start polling
fetch('/api/scrape/status').then(r => r.json()).then(data => {
  if (data.active) startScrapeStatusPoll();
}).catch(() => {});
