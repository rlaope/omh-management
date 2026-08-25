const state = {
  candidates: [],
  audit: [],
  filter: 'all',
};

const gates = [
  ['Preview generated', true],
  ['Dedupe evidence attached', false],
  ['Owner confirmation attached', false],
  ['Audit event required', true],
  ['GitHub write enabled', false],
];

async function loadJson(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Failed to load ${path}: ${response.status}`);
  return response.json();
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
        <button disabled>Confirmed create disabled in skeleton</button>
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

function renderPreview(candidate) {
  document.querySelector('#preview-title').textContent = candidate.issue_draft.title || 'No issue draft';
  document.querySelector('#issue-preview').textContent = candidate.issue_candidate
    ? `${candidate.issue_draft.body}\n\nDedupe query:\n${candidate.issue_draft.dedupe_query}`
    : 'This candidate is not marked issue_candidate.';
  document.querySelector('#issue-gates').innerHTML = gates.map(([label, ok]) => `
    <div class="gate">${ok ? '✓' : '□'} ${label}</div>
  `).join('');
}

function addAudit(eventType, candidateId, details = {}) {
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

function setTriage(candidate, triageState) {
  const previous = candidate.triage_state;
  candidate.triage_state = triageState;
  addAudit('triage_changed', candidate.candidate_id, { previous, next: triageState, persisted: false });
  renderSummary();
  renderCandidates();
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
  document.querySelector('#candidate-list').addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement)) return;
    const candidate = state.candidates.find((item) => item.candidate_id === target.dataset.candidate);
    if (!candidate) return;
    if (['adopt', 'watch', 'ignore'].includes(target.dataset.action)) {
      setTriage(candidate, target.dataset.action);
      return;
    }
    if (target.dataset.action === 'preview') {
      renderPreview(candidate);
      addAudit('issue_previewed', candidate.candidate_id, { persisted: false, github_write_enabled: false });
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
  [state.candidates, state.audit] = await Promise.all([
    loadJson('../data/sample-candidates.json'),
    loadJson('../data/sample-audit-log.json'),
  ]);
  renderSummary();
  renderCandidates();
  renderAudit();
  wireEvents();
}

main().catch((error) => {
  document.body.innerHTML = `<pre>${escapeHtml(error.stack || error.message)}</pre>`;
});
