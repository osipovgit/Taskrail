'use strict';

let pointerSelecting = false;
function preserveSelection() {
  return (
    pointerSelecting ||
    document.activeElement?.className === 'approval-alternative' ||
    Boolean(document.getSelection?.()?.isCollapsed === false)
  );
}

const names = {
  planner: 'Planning',
  'plan-reviewer': 'Plan review',
  implementer: 'Implementation',
  check: 'Built-in checks',
  reviewer: 'Result review',
};
const statuses = {
  TOKEN_BUDGET_EXCEEDED: 'Token budget reached',
  STAGE_BUDGET_EXCEEDED: 'Stage allowance exhausted',
  STARTING: 'Starting',
  LAUNCH_ERROR: 'Launch error',
  INTERRUPTED: 'Interrupted',
  RUNNING: 'Running',
  WAITING_APPROVAL: 'Your decision required',
  NO_CHANGES_REQUIRED: 'No changes required',
  READY_FOR_REVIEW: 'Ready for your review',
  RESULT_VALID: 'Result validated',
  PLAN_READY: 'Plan ready',
  APPROVE: 'Approved',
  IMPLEMENTED: 'Changes implemented',
  BLOCKED_PERMISSION: 'Permission denied',
  TOOL_ERROR: 'Tool error',
  INVALID_RESULT: 'Invalid result',
  BLOCKED: 'Blocked',
  REQUEST_CHANGES: 'Changes requested',
  CHECK_COMPLETED: 'Checks complete',
  PASS: 'Passed',
  FAIL: 'Error',
  SKIPPED: 'Skipped',
  TIMEOUT: 'Timed out',
};
let actionPending = false;
let selected = location.hash.slice(1),
  runs = [],
  last = '',
  composing = false,
  sessionToken = null;
try {
  selected = decodeURIComponent(selected);
} catch {
  selected = '';
}

// Treat every task, model message and file as text, never executable markup.
function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function badge(text) {
  const good = ['NO_CHANGES_REQUIRED', 'READY_FOR_REVIEW', 'APPROVE', 'PASS'].includes(text);
  const cls = good ? 'good' : /ERROR|BLOCKED|FAIL|INVALID|TIMEOUT/.test(text) ? 'bad' : '';
  return el('span', statuses[text] || text, 'badge ' + cls);
}
function detail(parent, title, text) {
  if (!text) return;
  const node = el('details');
  node.append(el('summary', title), el('pre', text));
  parent.append(node);
  return node;
}
function list(parent, title, values) {
  if (!values?.length) return;
  parent.append(el('h3', title));
  const ul = el('ul');
  for (const value of values)
    ul.append(el('li', typeof value === 'string' ? value : JSON.stringify(value)));
  parent.append(ul);
}
function showError(error) {
  document.getElementById('connection').textContent = 'Update failed: ' + error.message;
}
function menu() {
  if (preserveSelection()) return;
  const nav = document.getElementById('runs');
  nav.replaceChildren();
  const query = document.getElementById('filter').value.toLowerCase();
  for (const run of runs) {
    if (!(run.title + ' ' + run.id).toLowerCase().includes(query)) continue;
    const button = el('button', undefined, run.id === selected ? 'active' : '');
    button.append(el('strong', run.title), el('small', run.id), badge(run.status || ''));
    button.onclick = () => {
      closeComposer();
      selected = run.id;
      location.hash = encodeURIComponent(selected);
      last = '';
      menu();
      refreshRun().catch(showError);
    };
    nav.append(button);
  }
  if (!runs.length) nav.append(el('p', 'No runs yet.'));
}
const approvalDrafts = new Map();
function approvalCard(pending) {
  const card = el('section', undefined, 'approval-card');
  card.append(
    el('h3', 'Your decision required'),
    el('p', 'The stage timer is paused. Waiting has no time limit.'),
    el('pre', JSON.stringify(pending.request, null, 2)),
    el(
      'p',
      'Local programs run as the application user and may execute project code. Review the exact command and its effects. This is not a sandbox.',
    ),
  );
  const input = el('textarea', undefined, 'approval-alternative');
  input.placeholder = 'Suggest an alternative action';
  input.value = approvalDrafts.get(pending.ticket) || '';
  input.oninput = () => approvalDrafts.set(pending.ticket, input.value);
  card.append(input);
  for (const [decision, label] of [
    ['allow', 'Allow'],
    ['deny', 'Deny and continue'],
    ['alternative', 'Send alternative'],
  ]) {
    const button = el('button', label);
    button.disabled = actionPending;
    button.onclick = async () => {
      actionPending = true;
      try {
        const response = await fetch('/api/decision', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Countersign-Token': sessionToken },
          body: JSON.stringify({
            id: selected,
            ticket: pending.ticket,
            decision,
            alternative: input.value,
          }),
        });
        const result = await response.json();
        if (!response.ok) throw Error(result.error || 'Decision failed');
        approvalDrafts.delete(pending.ticket);
        input.blur();
        last = '';
        await refreshRun();
      } catch (error) {
        showError(error);
      } finally {
        actionPending = false;
      }
    };
    card.append(button);
  }
  return card;
}
function durationLabel(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return 'Unavailable';
  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = total % 60;
  if (hours) return `${hours} h ${minutes} min ${remainder} s`;
  if (minutes) return `${minutes} min ${remainder} s`;
  return `${total} s`;
}
function timeLabel(value) {
  if (value === undefined || value === null || value === '') return 'Time unavailable';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Time unavailable' : date.toLocaleString('en-GB');
}
function timeNode(value) {
  const node = el('time', timeLabel(value), 'message-time');
  if (
    value !== undefined &&
    value !== null &&
    value !== '' &&
    !Number.isNaN(new Date(value).getTime())
  ) {
    node.dateTime = new Date(value).toISOString();
    node.title = node.dateTime + ' · displayed in your browser timezone';
  }
  return node;
}
function messageCard(message) {
  const node = el('div', undefined, 'message');
  const header = el('div', undefined, 'message-header');
  header.append(timeNode(message.timestamp));
  node.append(header, el('div', message.text, 'text'));
  return node;
}
function renderPlan(parent, steps) {
  if (!steps?.length) return;
  parent.append(el('h3', 'Plan'));
  for (const step of steps) {
    const box = el('div', undefined, 'message');
    box.append(el('strong', step.id + ' · ' + step.action));
    list(box, 'Files', step.files);
    list(box, 'Criteria', step.criteria);
    list(box, 'Dependencies', step.depends_on);
    list(box, 'Checks', step.checks);
    parent.append(box);
  }
}
function renderCoverage(parent, entries) {
  if (!entries?.length) return;
  parent.append(el('h3', 'Requirement coverage'));
  for (const entry of entries) {
    const box = el('div', undefined, 'message');
    box.append(
      el(
        'strong',
        entry.id + ' · ' + (entry.outcome === 'not_evaluated' ? 'Not evaluated' : entry.outcome),
      ),
    );
    box.append(el('p', entry.explanation, 'text'));
    if (entry.evidence_ids?.length)
      box.append(el('small', 'Evidence: ' + entry.evidence_ids.join(', ')));
    parent.append(box);
  }
}
function stageProvenance(parent, stage) {
  if (!stage.agent_source) return;
  detail(
    parent,
    'Effective instructions',
    [
      'Frozen role source: ' + stage.agent_source,
      'Role SHA-256: ' + stage.agent_sha256,
      'Contract version: ' + stage.contract_version,
      'Contract SHA-256: ' + stage.contract_sha256,
      'Request SHA-256: ' + stage.instruction_sha256,
      'Selected modules: ' + JSON.stringify(stage.instruction_modules || []),
      'Runtime policy overrides custom-role formats.',
    ].join('\n'),
  );
}
function stageClockLabel(stage, now = Date.now()) {
  const limit = stage.budget?.timeout;
  const running = stage.status === 'RUNNING';
  const started = new Date(stage.started_at).getTime();
  const elapsed =
    running && Number.isFinite(started)
      ? Math.max(0, (now - started) / 1000 - (stage.paused_seconds || 0))
      : stage.elapsed_seconds;
  let label = stage.role || 'System';
  if (Number.isFinite(elapsed)) label += ' · ' + durationLabel(elapsed);
  if (Number.isFinite(limit)) {
    label += ' / ' + durationLabel(limit).replace(' h 0 min 0 s', ' h');
    if (running && Number.isFinite(elapsed))
      label +=
        ' · ' + (elapsed < limit ? durationLabel(limit - elapsed) + ' left' : 'Timeout pending');
  }
  if (stage.status === 'WAITING_APPROVAL') label += ' · Waiting for approval';
  return label;
}
function tickStageTimers() {
  if (preserveSelection()) return;
  for (const node of document.querySelectorAll('.stage-clock'))
    node.textContent = stageClockLabel(node.csStage, Date.now() + serverClockOffset);
}
function stageCard(stage) {
  const card = el('section', undefined, stage.status === 'RUNNING' ? 'running' : '');
  const heading = el('div', undefined, 'stage-header');
  const meta = el('div', undefined, 'stage-meta muted');
  const timer = el('span', stageClockLabel(stage, Date.now() + serverClockOffset), 'stage-clock');
  timer.csStage = stage;
  meta.append(timer);
  heading.append(
    el('h3', String(stage.number).padStart(2, '0') + ' · ' + (names[stage.stage] || stage.stage)),
    meta,
  );
  card.append(heading, badge(stage.status));
  if (stage.verdict) card.append(badge(stage.verdict));
  const modes = {
    import: 'Imported plan',
    'format-repair': 'Format repair',
    'scope-repair': 'Scoped retry',
    'access-recovery': 'Access denied; continuing with allowed sources',
    'research-recovery': 'Recovery from recorded evidence',
  };
  const context = [
    modes[stage.mode],
    stage.model,
    stage.started_at ? timeLabel(stage.started_at) : null,
  ].filter(Boolean);
  if (context.length) card.append(el('p', context.join(' · '), 'muted text'));
  if (stage.status === 'RUNNING' && stage.activity) {
    const activity = el('p', undefined, 'muted text');
    activity.append(
      el('span', stage.activity.detail + ' · last event '),
      timeNode(stage.activity.observed_at),
    );
    card.append(activity);
  }
  stageProvenance(card, stage);
  const result = stage.result;
  if (result && !Array.isArray(result)) {
    const conclusion = el('div', undefined, 'conclusion-header');
    conclusion.append(el('h3', 'Conclusion'), timeNode(stage.finished_at));
    card.append(conclusion, el('div', result.summary || '', 'text'));
    renderPlan(card, result.steps);
    renderCoverage(card, result.coverage);
    list(card, 'Completed steps', result.completed_steps);
    list(card, 'Changed files', result.changed_files);
    detail(
      card,
      'Source evidence',
      result.evidence?.length ? JSON.stringify(result.evidence, null, 2) : '',
    );
    list(card, 'Proposed files', result.proposed_change_files);
    list(card, 'Findings', result.findings);
    list(card, 'Missing evidence', result.blocking_gaps);
    list(card, 'Not verified', result.unverified);
  } else if (Array.isArray(result)) {
    for (const check of result) {
      const line = el('p');
      line.append(badge(check.status), el('span', check.file + ' — ' + check.detail));
      card.append(line);
    }
  }
  list(card, 'Errors', stage.errors);
  list(
    card,
    'Warnings',
    (stage.warnings || []).map(
      (w) =>
        w.resolution ||
        (w.input?.filePath || '') + ': ' + w.error + ' → subsequent full read confirmed',
    ),
  );
  if (stage.contract_error) card.append(el('p', stage.contract_error, 'text'));
  const events =
    stage.telemetry?.timeline ||
    stage.messages.items.map((message) => ({ ...message, kind: 'text' }));
  if (stage.status === 'RUNNING' && stage.messages.items.length) {
    card.append(
      el('h3', 'Latest message · provisional'),
      messageCard(stage.messages.items[stage.messages.items.length - 1]),
    );
  }
  if (events.length) {
    const log = el('details');
    log.append(el('summary', 'Activity log · ' + stage.directory));
    for (const event of events) {
      if (event.kind === 'text') log.append(messageCard(event));
      else {
        const box = el('div', undefined, 'message tool-event');
        const heading = el('div', undefined, 'tool-heading');
        heading.append(
          el(
            'strong',
            event.kind === 'tool' ? 'Tool · ' + event.tool + ' · ' + event.status : event.text,
          ),
          timeNode(event.timestamp),
        );
        box.append(heading);
        if (event.kind === 'tool') {
          box.append(el('pre', event.input));
          if (typeof event.duration_seconds === 'number')
            box.append(el('small', durationLabel(event.duration_seconds)));
          if (event.error) box.append(el('p', event.error, 'text'));
          const output = detail(
            box,
            'Tool output' + (event.output_truncated ? ' (truncated)' : ''),
            event.output,
          );
          if (output) output.csKey = stage.directory + '/' + event.call_id;
        }
        log.append(box);
      }
    }
    if (stage.telemetry?.timeline_omitted || stage.messages.truncated)
      log.append(el('p', 'Recent events shown. Full history is in events.jsonl.', 'muted'));
    card.append(log);
  }
  if (!result && stage.status === 'RUNNING')
    card.append(el('p', 'Waiting for the conclusion. Agent messages are provisional.', 'muted'));
  return card;
}
let currentRun = null;
let serverClockOffset = 0;
let composerContext = {};
function openComposer(draft = null, context = {}) {
  composerContext = context;
  const form = document.getElementById('task-form');
  form.reset();
  document.getElementById('project-roots').replaceChildren();
  if (draft) {
    for (const [key, value] of Object.entries(draft)) {
      const input = form.elements.namedItem(key);
      if (input && key !== 'read_only') input.value = value;
    }
    document.getElementById('task-read-only').checked = !!draft.read_only;
    draft.roots.forEach((root) => addRoot(root.alias, root.path));
  } else addRoot('project');
  composing = true;
  document.getElementById('composer').hidden = false;
  document.getElementById('chat').hidden = true;
  document.getElementById('followup-panel').hidden = true;
  document.getElementById('form-error').textContent = '';
  document.getElementById('task-goal').focus();
}
function render(data) {
  if (preserveSelection()) return;
  if (currentRun?.id !== data.id) document.getElementById('reply-goal').value = '';
  currentRun = data;
  document.getElementById('followup-panel').hidden = !data.actions?.followup;
  document.getElementById('send-reply').disabled = actionPending;
  renderMonitor(data);
  const signature = JSON.stringify({ ...data, server_time: undefined });
  if (signature === last) return;
  last = signature;
  const view = document.getElementById('chat');
  const openTitles = new Set(
    [...view.querySelectorAll('details')]
      .filter((node) => node.open)
      .map((node) => node.csKey || node.querySelector('summary').textContent),
  );
  const y = scrollY;
  view.replaceChildren();
  view.append(
    el('h2', runs.find((run) => run.id === selected)?.title || data.id),
    el('p', data.id, 'muted'),
    badge(data.status || ''),
  );
  const actions = el('div', undefined, 'run-actions');
  for (const [action, label] of [
    ['restart', 'Restart from scratch'],
    ['resume', 'Continue from checkpoint'],
    ['resume_budget', 'Continue with extra budget'],
    ['stop', 'Stop task'],
    ['delete', 'Delete from history'],
  ]) {
    const button = el('button', label);
    button.disabled = actionPending || !data.actions?.[action];
    button.title =
      action === 'resume'
        ? data.actions?.resume_reason || ''
        : {
            resume_budget: 'Adds two attempts and one attempt timeout. Existing usage is retained.',
            restart: 'Edit the task before starting a new run. No rollback.',
            stop: 'Stop the worker and save a checkpoint. Partial edits are preserved.',
            delete: 'Move run history to local trash. Project files are preserved.',
          }[action];
    button.onclick = () =>
      action === 'restart'
        ? openComposer(data.draft, { parent_run: data.id, submission_mode: 'restart' })
        : runAction(action);
    actions.append(button);
  }
  view.append(actions);
  if (data.pending_approval) view.append(approvalCard(data.pending_approval));
  for (const job of data.execution_jobs || []) view.append(executionCard(job));
  if (data.actions?.stop_requested)
    view.append(el('p', 'Stop requested. Waiting for process cleanup and checkpoint.', 'muted'));
  for (const turn of data.conversation || []) {
    const previous = el('section');
    previous.append(
      el('h3', 'Earlier Goal'),
      el('div', turn.goal, 'text'),
      el('h3', 'Earlier conclusion'),
      el('div', turn.summary, 'text'),
    );
    view.append(previous);
  }
  if (data.summary) {
    const summary = el('section');
    summary.append(el('h3', 'Conclusion'), el('div', data.summary, 'text'));
    view.append(summary);
  }
  const task = el('section');
  task.append(el('h3', 'Task'));
  detail(
    task,
    'Original task' + (data.task.truncated ? ' (end of file shown)' : ''),
    data.task.text,
  );
  for (const [alias, path] of Object.entries(data.roots))
    task.append(el('p', alias + ': ' + path, 'text muted'));
  list(
    task,
    'Requirement IDs',
    (data.requirements || []).map((entry) => entry.id + ' · ' + entry.text),
  );
  view.append(task);
  for (const stage of data.stages) view.append(stageCard(stage));
  const materials = el('section');
  materials.append(el('h3', 'Artifacts'));
  list(materials, 'Changed files', data.changed_files);
  list(materials, 'Deferred checks', data.unverified);
  detail(materials, 'Diff' + (data.diff.truncated ? ' (last part)' : ''), data.diff.text);
  if (data.console)
    detail(
      materials,
      'Worker console' + (data.console.truncated ? ' (last part)' : ''),
      data.console.text,
    );
  detail(materials, 'Report' + (data.report.truncated ? ' (last part)' : ''), data.report.text);
  view.append(materials);
  for (const node of view.querySelectorAll('details')) {
    if (openTitles.has(node.csKey || node.querySelector('summary').textContent)) node.open = true;
  }
  scrollTo(0, y);
}
async function get(url) {
  const response = await fetch(url, { cache: 'no-store' });
  if (!response.ok) {
    const value = await response.json().catch(() => ({}));
    throw Error(value.error || 'HTTP ' + response.status);
  }
  return response.json();
}
async function refreshRun() {
  if (!selected || composing) return;
  const id = selected;
  const data = await get('/api/run?id=' + encodeURIComponent(id));
  if (id === selected) {
    serverClockOffset = new Date(data.server_time).getTime() - Date.now();
    if (!Number.isFinite(serverClockOffset)) serverClockOffset = 0;
    render(data);
    tickStageTimers();
  }
}
async function refresh() {
  try {
    runs = await get('/api/runs');
    menu();
    await refreshRun();
    document.getElementById('connection').textContent =
      'Updated ' + new Date().toLocaleTimeString('en-GB');
  } catch (error) {
    showError(error);
  } finally {
    setTimeout(refresh, 3000);
  }
}
async function runAction(action) {
  if (actionPending) return;
  if (
    action === 'delete' &&
    !confirm('Move this run and its logs to local trash? Project files will not be changed.')
  )
    return;
  if (
    action === 'resume_budget' &&
    !confirm(
      'Grant two extra attempts and one attempt timeout, then continue? Token caps and permissions are unchanged.',
    )
  )
    return;
  actionPending = true;
  document.querySelectorAll('.run-actions button').forEach((button) => (button.disabled = true));
  try {
    if (!sessionToken) sessionToken = (await get('/api/session')).token;
    const response = await fetch('/api/actions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Countersign-Token': sessionToken },
      body: JSON.stringify({ id: selected, action }),
    });
    const result = await response.json();
    if (!response.ok) {
      if (response.status === 403) sessionToken = null;
      throw Error(result.error || 'Action failed');
    }
    selected = result.id;
    if (action === 'delete') {
      currentRun = null;
      document.getElementById('chat').replaceChildren(el('p', 'Task removed from history.'));
      document.getElementById('followup-panel').hidden = true;
      document.getElementById('monitor').replaceChildren();
    }
    location.hash = encodeURIComponent(selected);
    last = '';
    runs = await get('/api/runs');
    menu();
  } catch (error) {
    showError(error);
  } finally {
    actionPending = false;
    last = '';
    await refreshRun().catch(showError);
  }
}
function renderMonitor(data) {
  if (preserveSelection()) return;
  const panel = document.getElementById('monitor');
  const expanded = new Set(
    [...panel.querySelectorAll('details')].filter((node) => node.open).map((node) => node.csKey),
  );
  const panelScroll = panel.scrollTop;
  panel.replaceChildren(el('h2', 'Monitoring'));
  const rows = data.stages.filter((s) => s.telemetry && s.mode !== 'builtin');
  const sums = { input: 0, output: 0, reasoning: 0, cache_read: 0, cache_write: 0, total: 0 };
  let calls = 0,
    errors = 0,
    repeats = 0,
    compactions = 0,
    markers = 0,
    reported = 0,
    steps = 0;
  for (const row of rows) {
    const t = row.telemetry;
    for (const key of Object.keys(sums)) sums[key] += t.tokens[key] || 0;
    calls += t.tool_calls;
    errors += t.tool_errors;
    repeats += t.repeated_reads;
    compactions += t.compaction_completed;
    markers += t.compaction_markers;
    reported += t.usage_steps;
    steps += t.model_steps;
  }
  const fmt = (value) =>
    typeof value === 'number'
      ? value.toLocaleString('en-GB', { maximumFractionDigits: 1 })
      : 'Unavailable';
  const metric = (label, value) => {
    const line = el('div', undefined, 'metric');
    line.append(el('span', label), el('strong', value));
    panel.append(line);
  };
  const end =
    data.finished_at ||
    (data.status === 'RUNNING' ? data.server_time : data.stages.at(-1)?.finished_at);
  const wall =
    data.started_at && end ? Math.max(0, (new Date(end) - new Date(data.started_at)) / 1000) : null;
  metric('Wall time (incl. pauses)', wall === null ? 'Unavailable' : durationLabel(wall));
  const active = data.stages.reduce(
    (total, s) =>
      total +
      (typeof s.elapsed_seconds === 'number'
        ? s.elapsed_seconds
        : s.status === 'RUNNING' && s.started_at
          ? Math.max(0, (new Date(data.server_time) - new Date(s.started_at)) / 1000)
          : 0),
    0,
  );
  metric('Stage execution time', durationLabel(active));
  metric('Observed tokens', reported ? fmt(sums.total) : 'Not reported yet');
  for (const [key, label] of [
    ['input', 'Input (reported)'],
    ['output', 'Output (reported)'],
    ['cache_read', 'Cache read'],
    ['cache_write', 'Cache write'],
    ['reasoning', 'Reasoning (reported)'],
  ])
    metric(label, reported ? fmt(sums[key]) : 'Unavailable');
  metric('Model steps / usage records', fmt(steps) + ' / ' + fmt(reported));
  metric('Tool calls / errors', fmt(calls) + ' / ' + fmt(errors));
  metric('Repeated identical reads', fmt(repeats));
  const retries = rows.filter((r, i) => rows.slice(0, i).some((p) => p.stage === r.stage));
  metric('Repeat stage attempts', fmt(retries.length));
  metric(
    'Tokens in repeat attempts',
    fmt(retries.reduce((n, r) => n + r.telemetry.tokens.total, 0)),
  );
  metric(
    'Compaction completed',
    compactions ? fmt(compactions) + ' observed' : 'Unknown / not observed',
  );
  metric('Compaction markers', fmt(markers));
  const failed = rows.filter((r) => /ERROR|BLOCKED|FAIL|INVALID|TIMEOUT/.test(r.status));
  metric(
    'Tokens in failed attempts',
    fmt(failed.reduce((n, r) => n + r.telemetry.tokens.total, 0)),
  );
  const limit = data.monitoring?.max_observed_tokens || 0;
  metric('Observed-token limit', limit ? fmt(limit) : 'Not set');
  if (repeats > 2)
    panel.append(
      el(
        'p',
        'Repeated reads detected. Narrow the task entry points or inspect whether research is revisiting the same evidence.',
        'hint',
      ),
    );
  panel.append(
    el(
      'p',
      'Usage updates on reported step completions. In-flight or interrupted usage may be missing. Cumulative tokens are not context size. Cache/reasoning categories may overlap provider totals.',
      'hint',
    ),
  );
  panel.append(
    el(
      'p',
      'Compaction requires an explicit structured event. No marker does not prove no compaction; this CLI may omit it. No cost estimate without verified prices.',
      'hint',
    ),
  );
  panel.append(el('h3', 'By stage'));
  for (const row of rows) {
    const t = row.telemetry,
      box = el('div', undefined, 'metric-stage');
    box.append(
      el('strong', row.directory),
      el(
        'p',
        (t.usage_steps ? fmt(t.tokens.total) : 'Unreported') +
          ' tokens · ' +
          fmt(t.tool_calls) +
          ' tools',
        'muted',
      ),
    );
    box.append(
      el(
        'small',
        'Input ' +
          fmt(t.tokens.input) +
          ' · output ' +
          fmt(t.tokens.output) +
          ' · cache ' +
          fmt(t.tokens.cache_read),
      ),
    );
    const bar = el('div', undefined, 'token-bar');
    bar.style.width = (sums.total ? (100 * t.tokens.total) / sums.total : 0) + '%';
    box.append(bar);
    const more = detail(
      box,
      'More metrics',
      JSON.stringify(
        {
          model: row.model,
          tokens: t.tokens,
          last_reported_input: t.last_input,
          peak_reported_input: t.peak_input,
          reported_cost_unverified: t.reported_cost,
          compaction_completed: t.compaction_completed,
          usage_coverage: t.usage_coverage,
        },
        null,
        2,
      ),
    );
    more.csKey = row.directory;
    more.open = expanded.has(row.directory);
    panel.append(box);
  }
  panel.scrollTop = panelScroll;
}
function closeComposer() {
  composing = false;
  document.getElementById('composer').hidden = true;
  document.getElementById('chat').hidden = false;
}
function addRoot(alias = '', path = '') {
  const holder = document.getElementById('project-roots');
  if (holder.children.length >= 8) return;
  const row = el('div', undefined, 'root-row');
  const name = el('input');
  name.value = alias;
  name.placeholder = 'project';
  name.required = true;
  name.pattern = '[A-Za-z0-9_-]+';
  name.setAttribute('aria-label', 'Project alias');
  name.className = 'root-alias';
  const directory = el('input');
  directory.value = path;
  directory.placeholder = '~/src/my-project';
  directory.required = true;
  directory.setAttribute('aria-label', 'Project directory');
  directory.className = 'root-path';
  const remove = el('button', 'Remove');
  remove.type = 'button';
  remove.onclick = () => row.remove();
  row.append(name, directory, remove);
  holder.append(row);
}

function executionCard(job) {
  const card = el('section', undefined, 'card');
  card.append(el('h3', 'SSH action · ' + job.status));
  card.append(el('p', job.action?.reason || job.request?.action?.reason || 'Submitting request'));
  if (job.id) {
    card.append(el('p', 'Ticket: ' + job.id, 'muted'));
    if (job.status === 'PENDING_APPROVAL') {
      card.append(
        el('p', 'Review and approve in your terminal. The UI cannot grant server access.'),
      );
      card.append(el('pre', 'sudo -k /usr/local/bin/countersign-executor-approve ' + job.id));
    }
  }
  const action = job.action || job.request?.action;
  if (action) {
    card.append(el('p', 'SSH targets: ' + action.targets.join(', ')));
    card.append(el('pre', action.script));
    for (const [name, text] of Object.entries(action.files || {})) {
      const file = el('details');
      file.append(el('summary', name), el('pre', text));
      card.append(file);
    }
  }
  const details = el('details');
  details.append(el('summary', 'Exact request and target results'));
  details.append(el('pre', JSON.stringify(job, null, 2)));
  card.append(details);
  card.append(
    el('p', 'Stopping the task does not cancel an already approved remote command.', 'muted'),
  );
  if (job.status === 'UNKNOWN')
    card.append(el('p', 'Remote effects are uncertain. Inspect the server before a new action.'));
  return card;
}

document.getElementById('new-task').onclick = () => openComposer();
document.getElementById('cancel-task').onclick = () => {
  closeComposer();
  refreshRun().catch(showError);
};
document.getElementById('add-root').onclick = () => addRoot();
document.getElementById('task-form').onsubmit = async (event) => {
  event.preventDefault();
  const button = document.getElementById('create-task');
  const error = document.getElementById('form-error');
  if (button.disabled) return;
  button.disabled = true;
  button.textContent = 'Starting…';
  error.textContent = '';
  try {
    const payload = Object.fromEntries(new FormData(event.target).entries());
    payload.read_only = document.getElementById('task-read-only').checked;
    Object.assign(payload, composerContext);
    payload.roots = [...document.querySelectorAll('.root-row')].map((row) => ({
      alias: row.querySelector('.root-alias').value.trim(),
      path: row.querySelector('.root-path').value.trim(),
    }));
    if (!sessionToken) sessionToken = (await get('/api/session')).token;
    const response = await fetch('/api/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Countersign-Token': sessionToken },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) {
      if (response.status === 403) sessionToken = null;
      throw Error(result.error || 'Unable to start task');
    }
    selected = result.id;
    location.hash = encodeURIComponent(selected);
    last = '';
    closeComposer();
    event.target.reset();
    document.getElementById('project-roots').replaceChildren();
    addRoot('project');
    runs = await get('/api/runs');
    menu();
    await refreshRun();
  } catch (failure) {
    error.textContent = failure.message;
    showError(failure);
  } finally {
    button.disabled = false;
    button.textContent = 'Create and run';
  }
};
addRoot('project');
document.getElementById('filter').oninput = menu;
refresh();

document.getElementById('followup-form').onsubmit = async (event) => {
  event.preventDefault();
  if (actionPending || !currentRun?.actions?.followup) return;
  actionPending = true;
  document.getElementById('send-reply').disabled = true;
  document.getElementById('reply-error').textContent = '';
  try {
    const payload = {
      ...currentRun.draft,
      goal: document.getElementById('reply-goal').value,
      criteria: 'Address the latest Goal with evidence and report verification limits.',
      parent_run: currentRun.id,
      submission_mode: document.getElementById('reply-intent').value,
    };
    payload.read_only = payload.submission_mode === 'answer';
    if (!sessionToken) sessionToken = (await get('/api/session')).token;
    const response = await fetch('/api/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Countersign-Token': sessionToken },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) {
      if (response.status === 403) sessionToken = '';
      throw Error(result.error || 'Unable to continue conversation');
    }
    selected = result.id;
    location.hash = encodeURIComponent(selected);
    last = '';
    runs = await get('/api/runs');
    menu();
    await refreshRun();
  } catch (error) {
    document.getElementById('reply-error').textContent = error.message;
  } finally {
    actionPending = false;
    document.getElementById('send-reply').disabled = false;
  }
};

// Keep DOM nodes stable throughout a drag and while copied text remains selected.
document.addEventListener('pointerdown', (event) => {
  if (event.button === 0) pointerSelecting = true;
});
document.addEventListener('pointerup', () => {
  pointerSelecting = false;
});
document.addEventListener('pointercancel', () => {
  pointerSelecting = false;
});
window.addEventListener('blur', () => {
  pointerSelecting = false;
});

setInterval(tickStageTimers, 1000);
