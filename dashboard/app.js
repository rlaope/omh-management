const state = {
  candidates: [],
  audit: [],
  filter: 'all',
  apiMode: false,
};

const gates = [
  ['Preview generated', true],
  ['Dedupe evidence attached', false],
  ['Owner confirmation attached', false],
  ['Audit event required', true],
  ['GitHub write enabled', false],
];

async function requestJson(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'content-type': 'application/json' },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok || payload.ok === false) throw new Error(payload.error || `Request failed: ${path}`);
  return payload;
}

async function loadJson(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Failed to load ${path}: ${response.status}`);
  return response.json();
}

async function loadState() {
  try {
    const [candidatePayload, auditPayload] = await Promise.all([
      requestJson('/api/candidates'),
      requestJson('/api/audit'),
    ]);
    state.candidates = candidatePayload.candidates;
    state.audit = auditPayload.audit;
    state.apiMode = true;
  } catch (_error) {
    [state.candidates, state.audit] = await Promise.all([
      loadJson('../data/sample-candidates.json'),
      loadJson('../data/sample-audit-log.json'),
    ]);
    state.apiMode = false;
  }
}

function metric(label, value) {
  return `<div class="metric"><strong>${value}</strong><span>${label}</span></div>`;
}

function renderSummary() {
  const total = state.candidates.length;
  const adopt = state.candidates.filter((item) => item.triage_state === 'adopt').length;
  const issueReady = state.candidates.filter((item) => item.issue_candidate).length;
  const observed = state.candidates.filter((item) => item.observed_evidence.length > 0).length;
  document.querySelector('#summary').innerHTML = [
    metric('total candidates', total),
    metric('adopt candidates', adopt),
    metric('issue previews', issueReady),
    metric('locally observed', observed),
  ].join('');
  const mode = document.querySelector('#mode-status');
  if (mode) mode.textContent = state.apiMode ? 'persisted API mode' : 'static preview mode';
}

function renderCandidates() {
  const list = document.querySelector('#candidate-list');
  const visible = state.filter === 'all'
    ? state.candidates
    : state.candidates.filter((item) => item.triage_state === state.filter);
  list.innerHTML = visible.map((item) => `
    <article class="card">
      <div class="card-header">
        <div>
          <h3>${escapeHtml(item.title)}</h3>
          <p class="muted">${escapeHtml(item.user_facing_intent)}</p>
        </div>
        <div class="tags">
          <span class="tag ${item.triage_state}">${item.triage_state}</span>
          <span class="tag">${item.target_surface}</span>
          <span class="tag">${item.evidence_type}</span>
          <span class="tag">${item.implementation_status}</span>
        </div>
      </div>
      <div><strong>Changed contract:</strong> ${escapeHtml(item.changed_contract)}</div>
      <div><strong>Blocked by:</strong> ${item.blocked_by.length ? item.blocked_by.map(escapeHtml).join(', ') : 'none'}</div>
      <div class="boundary">${escapeHtml(item.claim_boundary)}</div>
      <div class="card-actions">
        <button data-candidate="${item.candidate_id}" data-action="adopt">Mark adopt</button>
        <button data-candidate="${item.candidate_id}" data-action="watch">Mark watch</button>
        <button data-candidate="${item.candidate_id}" data-action="ignore">Mark ignore</button>
        <button data-candidate="${item.candidate_id}" data-action="preview" ${item.issue_candidate ? '' : 'disabled'}>Issue preview</button>
        <button data-candidate="${item.candidate_id}" data-action="create" ${item.issue_candidate && state.apiMode ? '' : 'disabled'}>Dry-run create gate</button>
      </div>
    </article>
  `).join('');
}

function renderAudit() {
  document.querySelector('#audit-log').innerHTML = state.audit.slice().reverse().map((event) => `
    <div class="audit">
      <strong>${escapeHtml(event.event_type)}</strong>
      <span>${escapeHtml(event.recorded_at)} · ${escapeHtml(event.actor)} · ${escapeHtml(event.candidate_id)}</span>
    </div>
  `).join('');
}

function renderPreview(preview) {
  document.querySelector('#preview-title').textContent = preview.title || 'No issue draft';
  document.querySelector('#issue-preview').textContent = `${preview.body}\n\nDedupe query:\n${preview.dedupe_query}`;
  document.querySelector('#issue-gates').innerHTML = gates.map(([label, ok]) => `
    <div class="gate">${ok ? '✓' : '□'} ${label}</div>
  `).join('');
}

function localPreview(candidate) {
  return {
    title: candidate.issue_draft.title,
    body: candidate.issue_draft.body,
    dedupe_query: candidate.issue_draft.dedupe_query,
  };
}

function addLocalAudit(eventType, candidateId, details = {}) {
  state.audit.push({
    schema_version: 'audit_event/v1',
    event_id: `ui_${eventType}_${candidateId}_${Date.now()}`,
    event_type: eventType,
    actor: 'dashboard-preview',
    candidate_id: candidateId,
    recorded_at: new Date().toISOString(),
    details,
  });
  renderAudit();
}

async function setTriage(candidate, triageState) {
  if (state.apiMode) {
    const payload = await requestJson('/api/triage', {
      method: 'POST',
      body: JSON.stringify({ candidate_id: candidate.candidate_id, state: triageState, actor: 'dashboard' }),
    });
    Object.assign(candidate, payload.candidate);
    state.audit.push(payload.audit_event);
  } else {
    const previous = candidate.triage_state;
    candidate.triage_state = triageState;
    addLocalAudit('triage_changed', candidate.candidate_id, { previous, next: triageState, persisted: false });
  }
  renderSummary();
  renderCandidates();
  renderAudit();
}

async function previewIssue(candidate) {
  if (state.apiMode) {
    const payload = await requestJson('/api/issue-preview', {
      method: 'POST',
      body: JSON.stringify({ candidate_id: candidate.candidate_id, actor: 'dashboard' }),
    });
    renderPreview(payload.preview);
    state.audit.push(payload.audit_event);
  } else {
    renderPreview(localPreview(candidate));
    addLocalAudit('issue_previewed', candidate.candidate_id, { persisted: false, github_write_enabled: false });
  }
  renderAudit();
}

async function dryRunCreate(candidate) {
  const dedupeEvidence = window.prompt('Dedupe evidence required before any GitHub write:', 'operator checked: no duplicate found');
  if (!dedupeEvidence) return;
  const confirmation = window.prompt('Type CONFIRM_CREATE_GITHUB_ISSUE to pass the create gate. This still dry-runs unless backend execute is true:', '');
  const payload = await requestJson('/api/issue-create', {
    method: 'POST',
    body: JSON.stringify({
      candidate_id: candidate.candidate_id,
      repo: 'rlaope/omh-management',
      source: 'dashboard',
      owner_confirmation: confirmation,
      dedupe_evidence: dedupeEvidence,
      actor: 'dashboard',
      execute: false,
    }),
  });
  renderPreview(payload.preview);
  state.audit.push(payload.audit_event);
  renderAudit();
}

function wireEvents() {
  document.querySelectorAll('.toolbar button').forEach((button) => {
    button.addEventListener('click', () => {
      document.querySelectorAll('.toolbar button').forEach((item) => item.classList.remove('active'));
      button.classList.add('active');
      state.filter = button.dataset.filter;
      renderCandidates();
    });
  });
  document.querySelector('#candidate-list').addEventListener('click', async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement)) return;
    const candidate = state.candidates.find((item) => item.candidate_id === target.dataset.candidate);
    if (!candidate) return;
    try {
      if (['adopt', 'watch', 'ignore'].includes(target.dataset.action)) {
        await setTriage(candidate, target.dataset.action);
        return;
      }
      if (target.dataset.action === 'preview') {
        await previewIssue(candidate);
        return;
      }
      if (target.dataset.action === 'create') {
        await dryRunCreate(candidate);
      }
    } catch (error) {
      window.alert(error.message || String(error));
    }
  });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

async function main() {
  await loadState();
  renderSummary();
  renderCandidates();
  renderAudit();
  wireEvents();
}

main().catch((error) => {
  document.body.innerHTML = `<pre>${escapeHtml(error.stack || error.message)}</pre>`;
});
