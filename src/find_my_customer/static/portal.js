const qs = (selector, root = document) => root.querySelector(selector);

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
      window.setTimeout(() => window.location.assign(`/runs/${encodeURIComponent(payload.id)}`), 420);
    } catch (error) {
      submitState(button, 'idle');
      showError(errorBox, error.message || 'Could not create the run.');
    }
  });
}

const runShell = qs('[data-run-id]');
if (runShell && !['completed', 'failed', 'cancelled'].includes(runShell.dataset.runStatus)) {
  const order = ['queued', 'researching', 'qualifying', 'validating', 'rendering', 'completed'];
  const eventList = qs('#event-list');
  const liveMessage = qs('#live-message');
  const stageState = qs('#stage-state');
  const seen = new Set([...eventList.querySelectorAll('[data-event-id]')].map((node) => node.dataset.eventId));
  const source = new EventSource(`/api/runs/${runShell.dataset.runId}/events`);

  source.addEventListener('run', (event) => {
    const payload = JSON.parse(event.data);
    liveMessage.textContent = payload.message;
    stageState.textContent = payload.stage.replaceAll('-', ' ');
    const currentIndex = order.indexOf(payload.stage);
    qs('#stage-track').querySelectorAll('li').forEach((node, index) => {
      node.classList.toggle('current', index === currentIndex);
      node.classList.toggle('done', index < currentIndex || payload.stage === 'completed');
    });
    if (!seen.has(String(payload.id))) {
      seen.add(String(payload.id));
      const item = document.createElement('li');
      item.dataset.eventId = payload.id;
      const time = new Date(payload.created_at).toLocaleTimeString([], { hour12: false });
      const timeNode = document.createElement('time');
      const body = document.createElement('div');
      const stage = document.createElement('b');
      const message = document.createElement('p');
      timeNode.textContent = time;
      stage.textContent = payload.stage.replaceAll('-', ' ');
      message.textContent = payload.message;
      body.append(stage, message);
      item.append(timeNode, body);
      eventList.append(item);
    }
  });
  source.addEventListener('end', () => {
    source.close();
    window.setTimeout(() => window.location.reload(), 450);
  });
  source.onerror = () => {
    liveMessage.textContent = 'Live connection paused. Reconnecting…';
  };
}
