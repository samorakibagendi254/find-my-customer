const qs = (selector, root = document) => root.querySelector(selector);
const qsa = (selector, root = document) => [...root.querySelectorAll(selector)];

const TERMINAL_STATES = new Set(['completed', 'failed', 'cancelled']);
const STAGE_ORDER = ['queued', 'researching', 'qualifying', 'validating', 'rendering', 'completed'];

function submitState(button, state) {
  const idle = qs('[data-idle]', button);
  const loading = qs('[data-loading]', button);
  const done = qs('[data-done]', button);
  if (!idle || !loading || !done) return;
  idle.hidden = state !== 'idle';
  loading.hidden = state !== 'loading';
  done.hidden = state !== 'done';
  button.disabled = state === 'loading';
  button.setAttribute('aria-busy', state === 'loading' ? 'true' : 'false');
}

function showError(element, message) {
  element.textContent = message;
  element.hidden = false;
  element.classList.remove('shake');
  requestAnimationFrame(() => element.classList.add('shake'));
  element.focus?.();
}

function humanize(value) {
  return String(value || '').replaceAll('-', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function safePublicUrl(value) {
  if (!value) return null;
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

function makeElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined && text !== null) element.textContent = String(text);
  return element;
}

function makeLink(label, href, className = '') {
  const safeHref = safePublicUrl(href);
  if (!safeHref) return makeElement('span', className, label || 'No public route found');
  const link = makeElement('a', className, label || 'Open public route ↗');
  link.href = safeHref;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  return link;
}

class DiscoveryCanvas {
  constructor(root) {
    this.root = root;
    this.empty = qs('#canvas-empty');
    this.live = qs('#canvas-live');
    this.results = qs('#canvas-results');
    this.failure = qs('#canvas-failure');
    this.source = null;
    this.timer = null;
    this.requestToken = 0;
    this.seenEvents = new Set();
    this.currentRun = null;
    this.bindControls();
  }

  bindControls() {
    qsa('[data-run-select]').forEach((button) => {
      button.addEventListener('click', () => this.activateRun(button.dataset.runId));
    });
    qsa('[data-new-mission]').forEach((button) => {
      button.addEventListener('click', () => this.reset());
    });
  }

  switchMobile(view) {
    const shell = qs('.workspace-shell');
    if (!shell) return;
    shell.dataset.mobileView = view;
    qsa('[data-workspace-tab]').forEach((button) => {
      const active = button.dataset.workspaceTab === view;
      button.classList.toggle('active', active);
      button.setAttribute('aria-selected', active ? 'true' : 'false');
    });
  }

  stopLiveConnection() {
    this.source?.close();
    this.source = null;
    if (this.timer) window.clearInterval(this.timer);
    this.timer = null;
  }

  show(panel) {
    [this.empty, this.live, this.results, this.failure].forEach((node) => {
      if (node) node.hidden = node !== panel;
    });
  }

  setStatus(status, stage = status) {
    const statusNode = qs('#canvas-status');
    if (!statusNode) return;
    statusNode.dataset.state = status || 'ready';
    qs('span', statusNode).textContent = humanize(stage || 'ready');
  }

  setLinks(runId) {
    const audit = qs('#audit-link');
    const report = qs('#full-report-link');
    if (audit) {
      audit.href = runId ? `/runs/${encodeURIComponent(runId)}` : '#';
      audit.hidden = !runId;
    }
    if (report) report.href = runId ? `/runs/${encodeURIComponent(runId)}/report` : '#';
  }

  selectHistory(runId, status) {
    qsa('[data-run-select]').forEach((button) => {
      button.classList.toggle('selected', button.dataset.runId === runId);
    });
    const selected = qs(`[data-run-select][data-run-id="${CSS.escape(runId)}"]`);
    if (selected && status) selected.dataset.runStatus = status;
  }

  async fetchJson(url) {
    const response = await fetch(url, { headers: { Accept: 'application/json' }, cache: 'no-store' });
    if (!response.ok) {
      let message = 'Could not load this mission.';
      try {
        const payload = await response.json();
        message = payload.detail || message;
      } catch {}
      throw new Error(message);
    }
    return response.json();
  }

  reset() {
    this.requestToken += 1;
    this.stopLiveConnection();
    this.currentRun = null;
    this.root.dataset.runId = '';
    this.setStatus('ready', 'ready');
    this.setLinks(null);
    this.selectHistory('', '');
    this.show(this.empty);
    history.replaceState(null, '', '/');
    this.switchMobile('mission');
    qs('#startup-url')?.focus();
  }

  async activateRun(runId) {
    if (!runId) return;
    const token = ++this.requestToken;
    this.stopLiveConnection();
    this.seenEvents.clear();
    const activity = qs('#canvas-activity');
    if (activity) activity.replaceChildren();
    qs('#event-count').textContent = '0';
    this.currentRun = runId;
    this.root.dataset.runId = runId;
    this.setLinks(runId);
    this.selectHistory(runId);
    history.replaceState(null, '', `/?run=${encodeURIComponent(runId)}`);
    this.switchMobile('canvas');
    try {
      const run = await this.fetchJson(`/api/runs/${encodeURIComponent(runId)}`);
      if (token !== this.requestToken) return;
      this.root.dataset.runStatus = run.status;
      this.root.dataset.runStage = run.stage;
      this.setStatus(run.status, run.stage);
      this.selectHistory(runId, run.status);
      if (run.status === 'completed') {
        await this.loadResults(runId, token);
      } else if (['failed', 'cancelled'].includes(run.status)) {
        this.showFailure(run);
      } else {
        this.startLive(run, token);
      }
    } catch (error) {
      if (token !== this.requestToken) return;
      this.showFailure({ error_message: error.message });
    }
  }

  startLive(run, token) {
    this.show(this.live);
    qs('#live-mission-url').textContent = run.startup_url;
    this.updateStage(run.stage, run.stage === 'queued' ? 'The mission is queued and will begin shortly.' : 'Connecting to the live workflow…');
    const createdAt = new Date(run.created_at).getTime();
    const updateElapsed = () => {
      const seconds = Math.max(0, Math.floor((Date.now() - createdAt) / 1000));
      const minutes = Math.floor(seconds / 60);
      qs('#elapsed-time').textContent = `${String(minutes).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
    };
    updateElapsed();
    this.timer = window.setInterval(updateElapsed, 1000);

    this.source = new EventSource(`/api/runs/${encodeURIComponent(run.id)}/events`);
    this.source.addEventListener('run', (event) => {
      if (token !== this.requestToken) return;
      try {
        const payload = JSON.parse(event.data);
        this.updateStage(payload.stage, payload.message);
        this.addActivity(payload);
      } catch {
        this.updateStage(run.stage, 'A live update could not be read. Waiting for the next event…');
      }
    });
    this.source.addEventListener('end', async (event) => {
      if (token !== this.requestToken) return;
      this.stopLiveConnection();
      let status = 'completed';
      try { status = JSON.parse(event.data).status || status; } catch {}
      if (status === 'completed') await this.loadResults(run.id, token);
      else {
        try { this.showFailure(await this.fetchJson(`/api/runs/${encodeURIComponent(run.id)}`)); }
        catch (error) { this.showFailure({ error_message: error.message }); }
      }
    });
    this.source.onerror = () => {
      if (token === this.requestToken) qs('#live-stage-message').textContent = 'Live connection paused. Reconnecting automatically…';
    };
  }

  updateStage(stage, message) {
    const normalized = STAGE_ORDER.includes(stage) ? stage : 'queued';
    const currentIndex = STAGE_ORDER.indexOf(normalized);
    qsa('#canvas-stage-track li').forEach((node, index) => {
      node.classList.toggle('current', index === currentIndex);
      node.classList.toggle('done', index < currentIndex || normalized === 'completed');
    });
    qsa('[data-stage-visual]').forEach((node) => {
      const index = STAGE_ORDER.indexOf(node.dataset.stageVisual);
      node.classList.toggle('current', index === currentIndex);
      node.classList.toggle('done', index < currentIndex);
    });
    qs('#live-stage-title').textContent = humanize(normalized);
    qs('#live-stage-message').textContent = message || 'Working on this stage.';
    this.setStatus('running', normalized);
  }

  addActivity(payload) {
    const key = String(payload.id);
    if (this.seenEvents.has(key)) return;
    this.seenEvents.add(key);
    const list = qs('#canvas-activity');
    const item = makeElement('li', 'activity-item');
    item.dataset.eventId = key;
    const marker = makeElement('span', 'activity-marker');
    const body = makeElement('div');
    const top = makeElement('div', 'activity-topline');
    top.append(makeElement('b', '', humanize(payload.stage)));
    const time = makeElement('time', '', new Date(payload.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
    top.append(time);
    body.append(top, makeElement('p', '', payload.message));
    item.append(marker, body);
    list.prepend(item);
    qs('#event-count').textContent = String(this.seenEvents.size);
  }

  async loadResults(runId, token) {
    this.setStatus('completed', 'complete');
    try {
      const report = await this.fetchJson(`/api/runs/${encodeURIComponent(runId)}/result`);
      if (token !== this.requestToken) return;
      this.renderResults(report);
    } catch (error) {
      if (token !== this.requestToken) return;
      this.showFailure({ error_message: error.message });
    }
  }

  renderResults(report) {
    this.show(this.results);
    const prospects = Array.isArray(report.prospects) ? report.prospects : [];
    const verdict = report.verdict && typeof report.verdict === 'object' ? report.verdict : {};
    qs('#results-title').textContent = report.product?.name ? `Best first customers for ${report.product.name}` : 'Qualified customer leads';
    qs('#results-verdict').textContent = verdict.summary || 'The mission completed with an evidence-backed shortlist.';
    qs('#lead-count').textContent = String(prospects.length);
    qs('#confidence-level').textContent = humanize(verdict.confidence || 'not stated');
    const list = qs('#lead-list');
    list.replaceChildren();
    let reachable = 0;
    prospects.forEach((prospect, index) => {
      if (safePublicUrl(prospect.contact?.route_url)) reachable += 1;
      list.append(this.buildLead(prospect, index));
    });
    qs('#reachable-count').textContent = String(reachable);
    if (!prospects.length) list.append(makeElement('p', 'results-empty', 'No leads passed the evidence and fit checks for this mission.'));
  }

  buildLead(prospect, index) {
    const details = makeElement('details', 'lead-card');
    details.style.setProperty('--lead-index', index);
    const summary = makeElement('summary', 'lead-summary');

    const who = makeElement('div', 'lead-who lead-cell');
    const rank = makeElement('span', 'lead-rank', String(index + 1).padStart(2, '0'));
    const identity = makeElement('div');
    identity.append(makeElement('h4', '', prospect.name || 'Unnamed prospect'));
    const tags = makeElement('p', 'lead-tags');
    [prospect.type, humanize(prospect.stage), prospect.score != null ? `${prospect.score}/100` : null]
      .filter(Boolean).forEach((tag) => tags.append(makeElement('span', '', tag)));
    identity.append(tags);
    who.append(rank, identity);

    const how = makeElement('div', 'lead-how lead-cell');
    how.append(makeElement('span', 'cell-label', 'Best public route'));
    how.append(makeLink(humanize(prospect.contact?.route_type || 'No public route'), prospect.contact?.route_url, 'contact-route'));
    how.append(makeElement('small', '', prospect.contact?.target_role || 'Confirm the right owner'));

    const why = makeElement('div', 'lead-why lead-cell');
    why.append(makeElement('span', 'cell-label', 'Selection reason'));
    why.append(makeElement('p', '', prospect.why_fit || prospect.pain_signal || 'Selected by the evidence audit.'));

    summary.append(who, how, why, makeElement('span', 'lead-toggle', '+'));
    details.append(summary);

    const expanded = makeElement('div', 'lead-expanded');
    const evidence = makeElement('section');
    evidence.append(makeElement('h5', '', 'Signal and timing'));
    evidence.append(makeElement('p', '', prospect.pain_signal || 'No pain signal was recorded.'));
    if (prospect.why_now) evidence.append(makeElement('p', 'why-now', `Why now: ${prospect.why_now}`));
    const sources = makeElement('div', 'source-links');
    (Array.isArray(prospect.sources) ? prospect.sources : []).forEach((source) => {
      sources.append(makeLink(source.title || source.type || 'Evidence source', source.url));
    });
    evidence.append(sources);

    const outreach = makeElement('section');
    outreach.append(makeElement('h5', '', 'Thoughtful opener'));
    outreach.append(makeElement('blockquote', '', prospect.outreach?.opener || 'Review the public signal before starting a conversation.'));
    if (prospect.contact?.rationale) outreach.append(makeElement('p', 'contact-rationale', prospect.contact.rationale));

    const caution = makeElement('section', 'lead-caution');
    caution.append(makeElement('h5', '', 'Use with care'));
    caution.append(makeElement('p', '', prospect.caution || 'Verify the evidence and context before outreach.'));
    expanded.append(evidence, outreach, caution);
    details.append(expanded);
    details.addEventListener('toggle', () => { qs('.lead-toggle', details).textContent = details.open ? '−' : '+'; });
    return details;
  }

  showFailure(run) {
    this.stopLiveConnection();
    this.show(this.failure);
    this.setStatus('failed', 'interrupted');
    qs('#failure-message').textContent = run.error_message || 'Review the audit trail, adjust the mission, and try again.';
  }
}

const canvasRoot = qs('#discovery-canvas');
const canvas = canvasRoot ? new DiscoveryCanvas(canvasRoot) : null;

qsa('[data-workspace-tab]').forEach((button) => {
  button.addEventListener('click', () => canvas?.switchMobile(button.dataset.workspaceTab));
});

const form = qs('#run-form');
if (form) {
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = qs('[data-submit]', form);
    const errorBox = qs('#form-error', form);
    errorBox.hidden = true;
    if (!form.reportValidity()) return;
    submitState(button, 'loading');
    const data = new FormData(form);
    const body = {
      startup_url: data.get('startup_url'),
      description: data.get('description'),
      mode: data.get('mode'),
      focus: data.get('focus'),
    };
    try {
      const response = await fetch('/api/runs', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': qs('meta[name="csrf-token"]')?.content || '',
        },
        body: JSON.stringify(body),
      });
      const payload = await response.json();
      if (!response.ok) {
        const detail = Array.isArray(payload.detail) ? payload.detail[0]?.msg : payload.detail;
        throw new Error(detail || 'Could not create the run.');
      }
      if (!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(payload.id)) {
        throw new Error('The server returned an invalid run identifier.');
      }
      submitState(button, 'done');
      await canvas?.activateRun(payload.id);
      window.setTimeout(() => submitState(button, 'idle'), 900);
    } catch (error) {
      submitState(button, 'idle');
      showError(errorBox, error.message || 'Could not create the run.');
    }
  });
}

if (canvasRoot?.dataset.runId) canvas.activateRun(canvasRoot.dataset.runId);

// The standalone audit page keeps its compact live event view.
const runShell = qs('.run-shell[data-run-id]');
if (runShell && !TERMINAL_STATES.has(runShell.dataset.runStatus)) {
  const eventList = qs('#event-list');
  const liveMessage = qs('#live-message');
  const stageState = qs('#stage-state');
  const seen = new Set(qsa('[data-event-id]', eventList).map((node) => node.dataset.eventId));
  const source = new EventSource(`/api/runs/${encodeURIComponent(runShell.dataset.runId)}/events`);
  source.addEventListener('run', (event) => {
    const payload = JSON.parse(event.data);
    liveMessage.textContent = payload.message;
    stageState.textContent = humanize(payload.stage);
    const currentIndex = STAGE_ORDER.indexOf(payload.stage);
    qsa('#stage-track li').forEach((node, index) => {
      node.classList.toggle('current', index === currentIndex);
      node.classList.toggle('done', index < currentIndex || payload.stage === 'completed');
    });
    if (!seen.has(String(payload.id))) {
      seen.add(String(payload.id));
      const item = makeElement('li');
      item.dataset.eventId = payload.id;
      const time = makeElement('time', '', new Date(payload.created_at).toLocaleTimeString([], { hour12: false }));
      const body = makeElement('div');
      body.append(makeElement('b', '', humanize(payload.stage)), makeElement('p', '', payload.message));
      item.append(time, body);
      eventList.append(item);
    }
  });
  source.addEventListener('end', () => {
    source.close();
    window.setTimeout(() => window.location.reload(), 450);
  });
  source.onerror = () => { liveMessage.textContent = 'Live connection paused. Reconnecting…'; };
}
