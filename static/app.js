// ── State ──────────────────────────────────────────
let currentPage = 'dashboard';
let jobsPage = 0;
let jobsTotal = 0;
const JOBS_PER_PAGE = 50;
let configCache = null;
let pollTimer = null;
let dashMinScore = 0;

// ── Init ──────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    showPage('dashboard');
    startStatPolling();
});

// ── Navigation ────────────────────────────────────
function showPage(page) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    document.getElementById('page-' + page)?.classList.add('active');
    document.querySelector(`.nav-link[data-page="${page}"]`)?.classList.add('active');
    currentPage = page;

    if (page === 'dashboard') loadDashboard();
    else if (page === 'jobs') { loadSources(); loadJobs(); }
    else if (page === 'settings') { loadConfig(); loadCVStatus(); }
    else if (page === 'logs') loadLogs();
}

// ── Dashboard ─────────────────────────────────────
function onMinScoreChange(val) {
    dashMinScore = parseInt(val);
    document.getElementById('minScoreLabel').textContent = dashMinScore;
    loadDashboard();
}

async function loadDashboard() {
    try {
        const scoreParam = dashMinScore > 0 ? `?min_score=${dashMinScore}` : '';
        const stats = await api(`/api/stats${scoreParam}`);

        document.getElementById('statTotal').textContent = stats.total_jobs;
        const filterNote = dashMinScore > 0 ? ` (of ${stats.total_jobs_unfiltered})` : '';
        document.getElementById('statToday').textContent = `${stats.today_jobs} today${filterNote}`;
        document.getElementById('statPerfect').textContent = stats.perfect_matches;
        document.getElementById('statStrong').textContent = stats.strong_matches;
        document.getElementById('statWorth').textContent = stats.worth_a_look;
        document.getElementById('statAvgScore').textContent = stats.avg_score;
        document.getElementById('statSources').textContent = `${stats.sources_count} sources`;

        // Score filter info
        const infoEl = document.getElementById('scoreFilterInfo');
        if (dashMinScore > 0) {
            infoEl.textContent = `Showing ${stats.total_jobs} of ${stats.total_jobs_unfiltered} jobs`;
        } else {
            infoEl.textContent = `Showing all ${stats.total_jobs} jobs`;
        }

        updatePipelineStatus(stats);
        renderPipelineFunnel(stats);
        renderScoreDistribution(stats);
        renderSourcesTable(stats);
        renderBarChart('chartCategories', stats.by_category, null, {
            'Perfect Match': 'c-green', 'Strong Match': 'c-blue',
            'Worth a Look': 'c-yellow', 'Weak Match': 'c-red'
        });

        loadTopMatches();
    } catch (e) {
        console.error('Failed to load dashboard:', e);
    }
}

function renderPipelineFunnel(stats) {
    const funnel = stats.pipeline_funnel || {};
    const stages = [
        { key: 'new', label: 'New', color: '#3b82f6' },
        { key: 'saved', label: 'Saved', color: '#eab308' },
        { key: 'applied', label: 'Applied', color: '#8b5cf6' },
        { key: 'interviewing', label: 'Interviewing', color: '#06b6d4' },
        { key: 'offer', label: 'Offer', color: '#22c55e' },
        { key: 'rejected', label: 'Rejected', color: '#ef4444' },
    ];

    const total = Object.values(funnel).reduce((a, b) => a + b, 0) || 1;

    // Track bar
    const trackEl = document.getElementById('pipelineTrack');
    trackEl.innerHTML = stages.map(s => {
        const pct = ((funnel[s.key] || 0) / total) * 100;
        return pct > 0 ? `<div class="pipeline-segment" style="width:${pct}%;background:${s.color}" title="${s.label}: ${funnel[s.key] || 0}"></div>` : '';
    }).join('');

    // Stage cards
    const stagesEl = document.getElementById('pipelineStages');
    stagesEl.innerHTML = stages.map(s => {
        const count = funnel[s.key] || 0;
        return `<div class="pipeline-stage" onclick="showPage('jobs'); document.getElementById('filterStatus').value='${s.key}'; loadJobs();">
            <div class="stage-count" style="color:${s.color}">${count}</div>
            <div class="stage-label"><span class="stage-dot" style="background:${s.color}"></span>${s.label}</div>
        </div>`;
    }).join('');
}

function renderScoreDistribution(stats) {
    const dist = stats.score_distribution || {};
    const el = document.getElementById('chartScoreDist');
    if (!dist || Object.keys(dist).length === 0) {
        el.innerHTML = '<div style="text-align:center;color:var(--text-dim);padding:20px">No data yet</div>';
        return;
    }
    const max = Math.max(...Object.values(dist), 1);
    const colorForBucket = (label) => {
        const lo = parseInt(label);
        if (lo >= 80) return '#22c55e';
        if (lo >= 60) return '#3b82f6';
        if (lo >= 40) return '#eab308';
        return '#ef4444';
    };
    el.innerHTML = '<div class="bar-chart">' + Object.entries(dist).map(([label, val]) => {
        const pct = Math.max((val / max) * 100, val > 0 ? 3 : 0);
        const color = colorForBucket(label);
        return `<div class="bar-row">
            <div class="bar-label">${label}</div>
            <div class="bar-track"><div class="bar-fill" style="width:${pct}%;background:${color}">${val || ''}</div></div>
        </div>`;
    }).join('') + '</div>';
}

function updatePipelineStatus(stats) {
    const el = document.getElementById('pipelineStatus');
    const btn = document.getElementById('runPipelineBtn');
    if (stats.pipeline_running) {
        el.textContent = stats.pipeline_progress || 'Running...';
        el.className = 'pipeline-status running';
        btn.disabled = true;
    } else {
        const last = stats.last_run ? new Date(stats.last_run).toLocaleString() : 'Never';
        el.textContent = `Last run: ${last}`;
        el.className = 'pipeline-status';
        btn.disabled = false;
    }
}

async function renderSourcesTable(stats) {
    const bySource = stats.by_source || {};
    const total = Object.values(bySource).reduce((a, b) => a + b, 0);
    const max = Math.max(...Object.values(bySource), 1);

    // Fetch config to know which scrapers are enabled
    let scraperConfig = {};
    try {
        const config = await api('/api/config');
        scraperConfig = config.scrapers || {};
    } catch (e) {}

    const sourceInfo = {
        // Free APIs
        remotive: { label: 'Remotive', desc: 'Remote jobs API', color: '#10b981' },
        arbeitnow: { label: 'Arbeitnow', desc: 'EU & global jobs API', color: '#3b82f6' },
        themuse: { label: 'The Muse', desc: 'Curated job listings', color: '#a855f7' },
        jobicy: { label: 'Jobicy', desc: 'Remote jobs with salary', color: '#06b6d4' },
        himalayas: { label: 'Himalayas', desc: 'Remote jobs platform', color: '#14b8a6' },
        remoteok_api: { label: 'RemoteOK API', desc: 'Full remote job listings', color: '#f97316' },
        workingnomads: { label: 'Working Nomads', desc: 'Curated remote jobs', color: '#eab308' },
        landingjobs: { label: 'Landing.jobs', desc: 'European tech jobs', color: '#8b5cf6' },
        hn_hiring: { label: 'HN Who\'s Hiring', desc: 'Hacker News monthly thread', color: '#ff6600' },
        // RSS feeds
        rss_wwr_backend: { label: 'WWR Backend', desc: 'WeWorkRemotely RSS', color: '#22c55e' },
        rss_wwr_full_stack: { label: 'WWR Full-Stack', desc: 'WeWorkRemotely RSS', color: '#22c55e' },
        'rss_wwr_full-stack': { label: 'WWR Full-Stack', desc: 'WeWorkRemotely RSS', color: '#22c55e' },
        rss_wwr_front_end: { label: 'WWR Front-End', desc: 'WeWorkRemotely RSS', color: '#22c55e' },
        'rss_wwr_front-end': { label: 'WWR Front-End', desc: 'WeWorkRemotely RSS', color: '#22c55e' },
        rss_wwr_devops: { label: 'WWR DevOps', desc: 'WeWorkRemotely RSS', color: '#22c55e' },
        rss_weworkremotely: { label: 'WeWorkRemotely', desc: 'RSS feed', color: '#22c55e' },
        rss_remoteok: { label: 'RemoteOK RSS', desc: 'RSS feed', color: '#f97316' },
        rss_dribbble: { label: 'Dribbble', desc: 'Design & tech jobs RSS', color: '#ea4c89' },
        rss_larajobs: { label: 'Larajobs', desc: 'Laravel/PHP jobs RSS', color: '#ef4444' },
        // Paid API key
        adzuna: { label: 'Adzuna', desc: 'Global aggregator (key required)', color: '#6c63ff' },
        serpapi_google: { label: 'Google Jobs', desc: 'SerpAPI (key required)', color: '#ea4335' },
        linkedin_rapid: { label: 'LinkedIn', desc: 'RapidAPI (key required)', color: '#0a66c2' },
    };

    // Merge all known sources (enabled + those with data)
    const allSources = new Set([
        ...Object.keys(scraperConfig),
        ...Object.keys(bySource),
    ]);

    // Map RSS config to actual RSS source keys
    const rssEnabled = scraperConfig.rss_feeds?.enabled || false;

    document.getElementById('sourcesTotal').textContent = `${total} total jobs from ${Object.keys(bySource).length} sources`;

    const tbody = document.getElementById('sourcesBody');
    const rows = [];

    // Sort: sources with data first (by count desc), then enabled without data, then disabled
    const sorted = [...allSources].sort((a, b) => {
        const aCount = bySource[a] || 0;
        const bCount = bySource[b] || 0;
        if (aCount !== bCount) return bCount - aCount;
        return a.localeCompare(b);
    });

    for (const key of sorted) {
        const info = sourceInfo[key] || { label: key, desc: '', color: 'var(--primary)' };
        const count = bySource[key] || 0;
        const pct = total > 0 ? ((count / total) * 100).toFixed(1) : '0.0';
        const barPct = Math.max((count / max) * 100, count > 0 ? 3 : 0);

        // Determine enabled status
        let enabled = false;
        if (key.startsWith('rss_')) {
            enabled = rssEnabled;
        } else if (scraperConfig[key]) {
            enabled = scraperConfig[key].enabled || false;
        } else if (count > 0) {
            enabled = true; // has data so must have been enabled
        }

        rows.push(`<tr>
            <td>
                <div class="source-name">${esc(info.label)}</div>
                <div class="source-desc">${esc(info.desc)}</div>
            </td>
            <td>
                <span class="source-enabled">
                    <span class="source-dot ${enabled ? 'on' : 'off'}"></span>
                    ${enabled ? 'Active' : 'Disabled'}
                </span>
            </td>
            <td><strong>${count.toLocaleString()}</strong></td>
            <td>${pct}%</td>
            <td class="source-bar-cell">
                <div class="source-bar-track">
                    <div class="source-bar-fill" style="width:${barPct}%; background:${info.color}">${count > 0 ? count : ''}</div>
                </div>
            </td>
        </tr>`);
    }

    tbody.innerHTML = rows.join('');
}

function renderBarChart(containerId, data, defaultColor, colorMap) {
    const el = document.getElementById(containerId);
    if (!data || Object.keys(data).length === 0) {
        el.innerHTML = '<div style="text-align:center;color:var(--text-dim);padding:20px">No data yet</div>';
        return;
    }
    const max = Math.max(...Object.values(data), 1);
    const sorted = Object.entries(data).sort((a, b) => b[1] - a[1]);
    el.innerHTML = '<div class="bar-chart">' + sorted.map(([label, val]) => {
        const pct = Math.max((val / max) * 100, 2);
        const color = colorMap ? (colorMap[label] || 'c-primary') : (defaultColor || 'c-primary');
        return `<div class="bar-row">
            <div class="bar-label" title="${label}">${label}</div>
            <div class="bar-track"><div class="bar-fill ${color}" style="width:${pct}%">${val}</div></div>
        </div>`;
    }).join('') + '</div>';
}

async function loadTopMatches() {
    const minScore = Math.max(dashMinScore, 1);
    const data = await api(`/api/jobs?sort_by=score&sort_dir=DESC&limit=10&min_score=${minScore}`);
    const tbody = document.getElementById('topMatchesBody');
    if (!data.jobs.length) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-dim);padding:24px">No matches yet. Run the scraper!</td></tr>';
        return;
    }
    tbody.innerHTML = data.jobs.map(j => `<tr>
        <td>${scoreBadge(j.score, j.category)}</td>
        <td><a href="#" onclick="showJobDetail(${j.id}); return false;">${esc(j.title)}</a></td>
        <td>${esc(j.company)}</td>
        <td>${esc(j.location)}</td>
        <td><span class="skill-tag">${esc(j.source)}</span></td>
        <td><a href="${esc(j.url)}" target="_blank" class="btn btn-sm btn-outline">Apply</a></td>
    </tr>`).join('');
}

// ── Jobs Page ─────────────────────────────────────
async function loadJobs() {
    const params = new URLSearchParams({
        search: document.getElementById('searchInput')?.value || '',
        category: document.getElementById('filterCategory')?.value || 'all',
        source: document.getElementById('filterSource')?.value || 'all',
        status: document.getElementById('filterStatus')?.value || 'all',
        sort_by: document.getElementById('sortBy')?.value || 'score',
        sort_dir: document.getElementById('sortBy')?.value === 'scraped_at' ? 'DESC' :
                  (document.getElementById('sortBy')?.value === 'score' ? 'DESC' : 'ASC'),
        limit: JOBS_PER_PAGE,
        offset: jobsPage * JOBS_PER_PAGE,
    });

    const data = await api('/api/jobs?' + params);
    jobsTotal = data.total;
    const tbody = document.getElementById('jobsBody');

    if (!data.jobs.length) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-dim);padding:32px">No jobs found</td></tr>';
        renderPagination();
        return;
    }

    tbody.innerHTML = data.jobs.map(j => {
        const skills = j.skill_matches ? j.skill_matches.split(',').filter(s => s.trim()).slice(0, 4) : [];
        return `<tr>
            <td>${scoreBadge(j.score, j.category)}</td>
            <td><a href="#" onclick="showJobDetail(${j.id}); return false;">${esc(j.title)}</a></td>
            <td>${esc(j.company)}</td>
            <td>${esc(j.location)}${j.remote ? ' <span class="skill-tag">Remote</span>' : ''}</td>
            <td><div class="skill-tags">${skills.map(s => `<span class="skill-tag">${esc(s.trim())}</span>`).join('')}</div></td>
            <td><select class="status-select" onchange="updateJobStatus(${j.id}, this.value)">
                ${['new','saved','applied','interviewing','rejected','offer'].map(s =>
                    `<option value="${s}" ${j.application_status === s ? 'selected' : ''}>${s.charAt(0).toUpperCase() + s.slice(1)}</option>`
                ).join('')}
            </select></td>
            <td>
                <a href="${esc(j.url)}" target="_blank" class="btn btn-sm btn-outline" title="Apply">Apply</a>
                <button class="btn-icon" onclick="deleteJob(${j.id})" title="Remove">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:16px;height:16px"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                </button>
            </td>
        </tr>`;
    }).join('');

    renderPagination();
}

async function loadSources() {
    const sources = await api('/api/sources');
    const select = document.getElementById('filterSource');
    const current = select.value;
    select.innerHTML = '<option value="all">All Sources</option>' +
        sources.map(s => `<option value="${s}">${s}</option>`).join('');
    select.value = current;
}

function renderPagination() {
    const totalPages = Math.ceil(jobsTotal / JOBS_PER_PAGE);
    const el = document.getElementById('pagination');
    if (totalPages <= 1) { el.innerHTML = ''; return; }

    let html = `<button class="page-btn" onclick="goToPage(${jobsPage - 1})" ${jobsPage === 0 ? 'disabled' : ''}>Prev</button>`;
    html += `<span class="page-info">Page ${jobsPage + 1} of ${totalPages} (${jobsTotal} jobs)</span>`;
    html += `<button class="page-btn" onclick="goToPage(${jobsPage + 1})" ${jobsPage >= totalPages - 1 ? 'disabled' : ''}>Next</button>`;
    el.innerHTML = html;
}

function goToPage(page) {
    if (page < 0) return;
    jobsPage = page;
    loadJobs();
}

async function updateJobStatus(id, status) {
    await api(`/api/jobs/${id}/status`, { method: 'PUT', body: { status } });
    toast('Status updated', 'success');
}

async function deleteJob(id) {
    if (!confirm('Remove this job?')) return;
    await api(`/api/jobs/${id}`, { method: 'DELETE' });
    toast('Job removed', 'success');
    loadJobs();
}

// ── Job Detail Modal ──────────────────────────────
async function showJobDetail(id) {
    const job = await api(`/api/jobs/${id}`);
    if (!job) return;

    document.getElementById('modalTitle').textContent = job.title;
    const skills = job.skill_matches ? job.skill_matches.split(',').filter(s => s.trim()) : [];

    document.getElementById('modalBody').innerHTML = `
        <div class="detail-row"><div class="detail-label">Company</div><div class="detail-value">${esc(job.company)}</div></div>
        <div class="detail-row"><div class="detail-label">Location</div><div class="detail-value">${esc(job.location)}${job.remote ? ' (Remote)' : ''}</div></div>
        <div class="detail-row"><div class="detail-label">Source</div><div class="detail-value"><span class="skill-tag">${esc(job.source)}</span></div></div>
        <div class="detail-row"><div class="detail-label">Score</div><div class="detail-value">${scoreBadge(job.score, job.category)} <span style="font-size:12px;color:var(--text-dim);margin-left:8px">${job.llm_reasoning ? 'AI scored' : 'Rule-based'}</span></div></div>
        ${job.llm_reasoning ? `<div class="detail-row"><div class="detail-label">AI Analysis</div><div class="detail-value"><div class="llm-reasoning">${esc(job.llm_reasoning)}</div></div></div>` : ''}
        ${job.salary_min ? `<div class="detail-row"><div class="detail-label">Salary</div><div class="detail-value">${job.salary_currency || ''}${Number(job.salary_min).toLocaleString()}${job.salary_max ? ' - ' + Number(job.salary_max).toLocaleString() : ''}</div></div>` : ''}
        <div class="detail-row"><div class="detail-label">Skills</div><div class="detail-value"><div class="skill-tags">${skills.map(s => `<span class="skill-tag">${esc(s.trim())}</span>`).join('') || 'None detected'}</div></div></div>
        <div class="detail-row"><div class="detail-label">Status</div><div class="detail-value">
            <select class="status-select" onchange="updateJobStatus(${job.id}, this.value)">
                ${['new','saved','applied','interviewing','rejected','offer'].map(s =>
                    `<option value="${s}" ${job.application_status === s ? 'selected' : ''}>${s.charAt(0).toUpperCase() + s.slice(1)}</option>`
                ).join('')}
            </select>
        </div></div>
        <div class="detail-row"><div class="detail-label">Scraped</div><div class="detail-value">${new Date(job.scraped_at).toLocaleString()}</div></div>
        <div class="detail-row"><div class="detail-label">Link</div><div class="detail-value"><a href="${esc(job.url)}" target="_blank">${esc(job.url)}</a></div></div>
        <div style="margin-top:16px"><div class="detail-label" style="margin-bottom:8px">Description</div>
        <div class="desc-text">${formatDescription(job.description)}</div></div>
        <div style="margin-top:16px;text-align:right"><a href="${esc(job.url)}" target="_blank" class="btn btn-primary">Apply Now</a></div>
    `;

    document.getElementById('jobModal').classList.add('active');
}

function closeModal() {
    document.getElementById('jobModal').classList.remove('active');
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

// ── Settings ──────────────────────────────────────
async function loadConfig() {
    const config = await api('/api/config');
    configCache = config;
    const p = config.preferences || {};

    document.getElementById('cfgSearchStatement').value = config.job_search_statement || '';
    document.getElementById('cfgTitles').value = (p.job_titles || []).join('\n');
    document.getElementById('cfgSkills').value = (p.skills || []).join('\n');
    document.getElementById('cfgLocations').value = (p.locations || []).join('\n');
    document.getElementById('cfgRemote').value = p.remote_preference || 'remote_preferred';
    document.getElementById('cfgExperience').value = p.experience_level || 'mid';
    document.getElementById('cfgSalaryMin').value = p.salary_range?.min || '';
    document.getElementById('cfgSalaryMax').value = p.salary_range?.max || '';
    document.getElementById('cfgSalaryCurrency').value = p.salary_range?.currency || 'USD';

    // Email
    const em = config.email || {};
    document.getElementById('cfgEmailEnabled').checked = em.enabled || false;
    document.getElementById('cfgSmtpHost').value = em.smtp_host || 'smtp.gmail.com';
    document.getElementById('cfgSmtpPort').value = em.smtp_port || 587;
    document.getElementById('cfgSmtpUser').value = em.smtp_user || '';
    document.getElementById('cfgSmtpPassword').value = em.smtp_password || '';
    document.getElementById('cfgFromAddr').value = em.from_address || '';
    document.getElementById('cfgToAddrs').value = (em.to_addresses || []).join('\n');
    document.getElementById('cfgScheduleTime').value = config.schedule?.run_time || '08:00';

    // Weights
    const w = config.scoring?.weights || {};
    document.getElementById('wSkills').value = (w.skills_match || 0.35) * 100;
    document.getElementById('wTitle').value = (w.title_match || 0.25) * 100;
    document.getElementById('wLocation').value = (w.location_match || 0.20) * 100;
    document.getElementById('wSalary').value = (w.salary_match || 0.10) * 100;
    document.getElementById('wExp').value = (w.experience_match || 0.10) * 100;
    updateWeightDisplay();

    // Scrapers
    renderScraperToggles(config.scrapers || {});

    // API Keys
    const sc = config.scrapers || {};
    document.getElementById('cfgLinkedinKey').value = sc.linkedin_rapid?.rapidapi_key || '';
    document.getElementById('cfgAdzunaId').value = sc.adzuna?.app_id || '';
    document.getElementById('cfgAdzunaKey').value = sc.adzuna?.app_key || '';
    document.getElementById('cfgSerpApiKey').value = sc.serpapi_google?.api_key || '';

    // LLM settings
    const llm = config.llm || {};
    document.getElementById('cfgLlmEnabled').checked = llm.enabled || false;
    document.getElementById('cfgLlmApiKey').value = llm.api_key || '';
    document.getElementById('cfgLlmModel').value = llm.model || 'claude-haiku-4-5-20251001';
    document.getElementById('cfgLlmTopN').value = llm.top_n || 30;
}

function renderScraperToggles(scrapers) {
    const el = document.getElementById('scraperToggles');
    const info = {
        remotive: 'Remote jobs (free, no key)',
        arbeitnow: 'EU/global jobs (free, no key)',
        themuse: 'Curated jobs (free, key optional)',
        jobicy: 'Remote jobs with salary data (free)',
        himalayas: 'Remote jobs platform (free)',
        remoteok_api: 'RemoteOK full API - all listings (free)',
        workingnomads: 'Curated remote jobs (free)',
        landingjobs: 'European tech jobs with salary (free)',
        hn_hiring: 'Hacker News "Who is Hiring?" threads (free)',
        rss_feeds: 'RSS feeds - WWR, Dribbble, Larajobs + more',
        adzuna: 'Global aggregator (free key required)',
        serpapi_google: 'Google Jobs (100 free/month, key required)',
        linkedin_rapid: 'LinkedIn via RapidAPI (key required)',
    };
    el.innerHTML = Object.entries(scrapers).map(([name, conf]) => `
        <div class="scraper-item">
            <div>
                <div class="scraper-name">${name}</div>
                <div class="scraper-desc">${info[name] || ''}</div>
            </div>
            <label class="toggle-label">
                <input type="checkbox" id="scraper_${name}" ${conf.enabled ? 'checked' : ''}>
                <span>Enabled</span>
            </label>
        </div>
    `).join('');
}

async function saveConfig() {
    if (!configCache) await loadConfig();
    const config = JSON.parse(JSON.stringify(configCache));

    config.job_search_statement = document.getElementById('cfgSearchStatement').value.trim();
    config.preferences.job_titles = textareaToList('cfgTitles');
    config.preferences.skills = textareaToList('cfgSkills');
    config.preferences.locations = textareaToList('cfgLocations');
    config.preferences.remote_preference = document.getElementById('cfgRemote').value;
    config.preferences.experience_level = document.getElementById('cfgExperience').value;
    config.preferences.salary_range = {
        min: parseInt(document.getElementById('cfgSalaryMin').value) || 0,
        max: parseInt(document.getElementById('cfgSalaryMax').value) || 0,
        currency: document.getElementById('cfgSalaryCurrency').value || 'USD',
    };

    config.email.enabled = document.getElementById('cfgEmailEnabled').checked;
    config.email.smtp_host = document.getElementById('cfgSmtpHost').value;
    config.email.smtp_port = parseInt(document.getElementById('cfgSmtpPort').value) || 587;
    config.email.smtp_user = document.getElementById('cfgSmtpUser').value;
    config.email.smtp_password = document.getElementById('cfgSmtpPassword').value;
    config.email.from_address = document.getElementById('cfgFromAddr').value;
    config.email.to_addresses = textareaToList('cfgToAddrs');
    config.schedule.run_time = document.getElementById('cfgScheduleTime').value;

    config.scoring.weights = {
        skills_match: parseInt(document.getElementById('wSkills').value) / 100,
        title_match: parseInt(document.getElementById('wTitle').value) / 100,
        location_match: parseInt(document.getElementById('wLocation').value) / 100,
        salary_match: parseInt(document.getElementById('wSalary').value) / 100,
        experience_match: parseInt(document.getElementById('wExp').value) / 100,
    };

    // Scraper toggles
    for (const name of Object.keys(config.scrapers)) {
        const chk = document.getElementById('scraper_' + name);
        if (chk) config.scrapers[name].enabled = chk.checked;
    }

    // API Keys — save and auto-enable if key is provided
    const linkedinKey = document.getElementById('cfgLinkedinKey').value.trim();
    config.scrapers.linkedin_rapid = config.scrapers.linkedin_rapid || {};
    config.scrapers.linkedin_rapid.rapidapi_key = linkedinKey;
    if (linkedinKey) config.scrapers.linkedin_rapid.enabled = true;

    const adzunaId = document.getElementById('cfgAdzunaId').value.trim();
    const adzunaKey = document.getElementById('cfgAdzunaKey').value.trim();
    config.scrapers.adzuna = config.scrapers.adzuna || {};
    config.scrapers.adzuna.app_id = adzunaId;
    config.scrapers.adzuna.app_key = adzunaKey;
    if (adzunaId && adzunaKey) config.scrapers.adzuna.enabled = true;

    const serpKey = document.getElementById('cfgSerpApiKey').value.trim();
    config.scrapers.serpapi_google = config.scrapers.serpapi_google || {};
    config.scrapers.serpapi_google.api_key = serpKey;
    if (serpKey) config.scrapers.serpapi_google.enabled = true;

    // LLM config
    config.llm = config.llm || {};
    config.llm.enabled = document.getElementById('cfgLlmEnabled').checked;
    config.llm.api_key = document.getElementById('cfgLlmApiKey').value.trim();
    config.llm.model = document.getElementById('cfgLlmModel').value;
    config.llm.top_n = parseInt(document.getElementById('cfgLlmTopN').value) || 30;

    await api('/api/config', { method: 'PUT', body: config });
    configCache = config;
    toast('Settings saved!', 'success');
}

function updateWeightDisplay() {
    const ids = ['wSkills', 'wTitle', 'wLocation', 'wSalary', 'wExp'];
    const valIds = ['wSkillsVal', 'wTitleVal', 'wLocationVal', 'wSalaryVal', 'wExpVal'];
    let total = 0;
    ids.forEach((id, i) => {
        const v = parseInt(document.getElementById(id).value) / 100;
        document.getElementById(valIds[i]).textContent = v.toFixed(2);
        total += v;
    });
    const el = document.getElementById('weightTotal');
    el.textContent = `Total: ${total.toFixed(2)}`;
    el.style.color = Math.abs(total - 1.0) < 0.01 ? 'var(--green)' : 'var(--red)';
}

// ── CV Upload ─────────────────────────────────────
async function loadCVStatus() {
    const data = await api('/api/cv');
    const el = document.getElementById('cvStatus');
    const extractedEl = document.getElementById('cvExtracted');

    if (data.files.length === 0) {
        el.innerHTML = '<div style="color:var(--text-dim)">No CV uploaded yet. Upload your resume to improve job matching.</div>';
        extractedEl.style.display = 'none';
    } else {
        el.innerHTML = data.files.map(f => `
            <div class="cv-file">
                <svg viewBox="0 0 24 24" fill="none" stroke="var(--primary)" stroke-width="2" style="width:20px;height:20px;flex-shrink:0"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                <span class="cv-file-name">${esc(f.name)}</span>
                <span class="cv-file-size">${formatSize(f.size)}</span>
                <button class="btn-icon" onclick="deleteCV('${esc(f.name)}')" title="Remove">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </button>
            </div>
        `).join('') + `<div style="margin-top:8px;font-size:12px;color:var(--text-dim)">${data.text_length.toLocaleString()} characters extracted</div>`;

        // Show detected skills
        extractedEl.style.display = 'block';
        const skillsEl = document.getElementById('cvDetectedSkills');
        const configSkills = data.detected_skills || [];
        const extraSkills = data.extra_skills_found || [];

        const matched = configSkills.filter(s => s.found);
        const unmatched = configSkills.filter(s => !s.found);

        document.getElementById('cvMatchInfo').textContent =
            `${matched.length}/${configSkills.length} config skills found in CV`;

        let skillsHtml = '';
        // Config skills found in CV
        skillsHtml += matched.map(s =>
            `<span class="skill-tag cv-skill-matched" title="Found in your CV">${esc(s.name)}</span>`
        ).join('');
        // Config skills NOT in CV
        skillsHtml += unmatched.map(s =>
            `<span class="skill-tag cv-skill-unmatched" title="In your preferences but not found in CV">${esc(s.name)}</span>`
        ).join('');
        // Extra skills detected in CV but not in config
        skillsHtml += extraSkills.map(s =>
            `<span class="skill-tag" title="Found in CV - click to add to preferences" style="cursor:pointer" onclick="addSkillToConfig('${esc(s)}')">${esc(s)} +</span>`
        ).join('');

        skillsEl.innerHTML = skillsHtml;

        // Text preview
        document.getElementById('cvPreviewText').textContent = data.preview || 'No text extracted.';
    }
}

function toggleCVPreview() {
    const el = document.getElementById('cvPreviewText');
    el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

function addSkillToConfig(skill) {
    const textarea = document.getElementById('cfgSkills');
    const current = textarea.value.split('\n').map(s => s.trim()).filter(s => s);
    if (!current.includes(skill)) {
        current.push(skill);
        textarea.value = current.join('\n');
        toast(`Added "${skill}" to skills — remember to Save Settings`, 'info');
        loadCVStatus();
    }
}

async function deleteCV(filename) {
    if (!confirm(`Remove ${filename}?`)) return;
    await api(`/api/cv/delete/${encodeURIComponent(filename)}`, { method: 'DELETE' });
    toast('CV removed', 'success');
    loadCVStatus();
}

function handleDrop(event) {
    const files = event.dataTransfer.files;
    if (!files.length) return;
    // Upload each file
    for (const file of files) {
        const ext = file.name.split('.').pop().toLowerCase();
        if (!['pdf', 'docx', 'txt'].includes(ext)) {
            toast(`${file.name}: only PDF, DOCX, TXT allowed`, 'error');
            continue;
        }
        const form = new FormData();
        form.append('file', file);
        fetch('/api/cv/upload', { method: 'POST', body: form })
            .then(r => r.json())
            .then(data => {
                if (data.ok) {
                    toast(`Uploaded ${file.name}`, 'success');
                    loadCVStatus();
                } else {
                    toast(data.error || 'Upload failed', 'error');
                }
            });
    }
}

async function uploadCV(input) {
    if (!input.files.length) return;
    for (const file of input.files) {
        const form = new FormData();
        form.append('file', file);
        try {
            const resp = await fetch('/api/cv/upload', { method: 'POST', body: form });
            const data = await resp.json();
            if (data.ok) {
                toast(`Uploaded ${file.name}`, 'success');
            } else {
                toast(data.error || 'Upload failed', 'error');
            }
        } catch (e) {
            toast('Upload failed', 'error');
        }
    }
    loadCVStatus();
    input.value = '';
}

// ── Pipeline ──────────────────────────────────────
async function runPipeline() {
    try {
        await api('/api/pipeline/run', { method: 'POST' });
        toast('Pipeline started!', 'info');
        document.getElementById('runPipelineBtn').disabled = true;
    } catch (e) {
        toast('Failed to start pipeline', 'error');
    }
}

async function reprocessJobs() {
    try {
        await api('/api/pipeline/reprocess', { method: 'POST' });
        toast('Re-scoring all jobs...', 'info');
    } catch (e) {
        toast('Failed to reprocess', 'error');
    }
}

async function testEmail() {
    try {
        const data = await api('/api/email/test', { method: 'POST' });
        toast('Test email sent!', 'success');
    } catch (e) {
        toast('Email test failed', 'error');
    }
}

// ── Logs ──────────────────────────────────────────
async function loadLogs() {
    const data = await api('/api/logs');
    const el = document.getElementById('logViewer');
    el.textContent = data.lines.join('') || 'No logs yet.';
    el.scrollTop = el.scrollHeight;
}

// ── Polling ───────────────────────────────────────
function startStatPolling() {
    setInterval(async () => {
        if (currentPage === 'dashboard') {
            try {
                const stats = await api('/api/stats');
                updatePipelineStatus(stats);
                if (!stats.pipeline_running && document.getElementById('runPipelineBtn').disabled) {
                    document.getElementById('runPipelineBtn').disabled = false;
                    loadDashboard();
                }
            } catch (e) {}
        }
    }, 3000);
}

// ── Helpers ───────────────────────────────────────
async function api(url, opts = {}) {
    const fetchOpts = { method: opts.method || 'GET', headers: {} };
    if (opts.body) {
        fetchOpts.headers['Content-Type'] = 'application/json';
        fetchOpts.body = JSON.stringify(opts.body);
    }
    const resp = await fetch(url, fetchOpts);
    return resp.json();
}

function scoreBadge(score, category) {
    if (score == null) return '<span class="score-badge weak">--</span>';
    let cls = 'weak';
    if (score >= 80) cls = 'perfect';
    else if (score >= 60) cls = 'strong';
    else if (score >= 40) cls = 'worth';
    return `<span class="score-badge ${cls}">${Math.round(score)}</span>`;
}

function esc(str) {
    if (!str) return '';
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

function formatDescription(desc) {
    if (!desc) return 'No description available.';
    // Strip HTML tags but keep text
    const tmp = document.createElement('div');
    tmp.innerHTML = desc;
    let text = tmp.textContent || tmp.innerText;
    // Truncate very long descriptions
    if (text.length > 3000) text = text.substring(0, 3000) + '...';
    return esc(text);
}

function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
}

function textareaToList(id) {
    return document.getElementById(id).value.split('\n').map(s => s.trim()).filter(s => s);
}

function toast(msg, type = 'info') {
    const container = document.getElementById('toastContainer');
    const t = document.createElement('div');
    t.className = `toast ${type}`;
    t.textContent = msg;
    container.appendChild(t);
    setTimeout(() => t.remove(), 4000);
}

let _debounceTimers = {};
function debounce(fn, ms) {
    return function (...args) {
        clearTimeout(_debounceTimers[fn.name]);
        _debounceTimers[fn.name] = setTimeout(() => fn(...args), ms);
    };
}
