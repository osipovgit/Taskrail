import { badge, detail, el, list, showError } from './dom.js';
import { renderMonitor } from './monitor.js';
import { executionCard, stageCard, tickStageTimers } from './stages.js';
import { deliverySection } from './epic.js';
import { attentionRun } from './graph.js';
import { preserveSelection, state } from './state.js';
import { taskSection } from './task.js';

const approvalDrafts = new Map();

export async function get(url) {
  const response = await fetch(url, { cache: 'no-store' });
  if (!response.ok) {
    const value = await response.json().catch(() => ({}));
    throw Error(value.error || 'HTTP ' + response.status);
  }
  return response.json();
}

// Every mutation carries the per-session CSRF token; a rejected token is fetched again.
export async function post(url, payload, failure) {
  if (!state.sessionToken) state.sessionToken = (await get('/api/session')).token;
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Countersign-Token': state.sessionToken },
    body: JSON.stringify(payload),
  });
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 403) state.sessionToken = null;
    throw Error(result.error || failure);
  }
  return result;
}

// Groups are computed by the server; Done is collapsed unless opened or searched.
const GROUPS = [
  ['running', 'Running'],
  ['attention', 'Needs you'],
  ['review', 'Ready for review'],
  ['done', 'Done'],
];

export function menu() {
  if (preserveSelection()) return;
  const nav = document.getElementById('runs');
  nav.replaceChildren();
  const query = document.getElementById('filter').value.toLowerCase();
  const visible = state.runs.filter((run) =>
    [run.title, run.id, ...(run.members || [])].join(' ').toLowerCase().includes(query),
  );
  for (const [group, label] of GROUPS) {
    const runs = visible.filter((run) => (run.group || 'attention') === group);
    if (!runs.length) continue;
    const heading = label + ' · ' + runs.length;
    const holder = group === 'done' ? doneGroup(heading, Boolean(query)) : nav;
    if (holder === nav) nav.append(el('h4', heading, 'run-group'));
    else nav.append(holder);
    for (const run of runs) holder.append(runButton(run));
  }
  if (!state.runs.length) nav.append(el('p', 'No runs yet.'));
}

function doneGroup(heading, searching) {
  const group = el('details', undefined, 'run-group-done');
  group.open = searching || state.doneOpen;
  group.ontoggle = () => {
    if (!searching) state.doneOpen = group.open;
  };
  group.append(el('summary', heading, 'run-group'));
  return group;
}

function runButton(run) {
  const classes = [
    run.id === state.selected ? 'active' : '',
    run.group === 'attention' ? 'needs-you' : '',
  ];
  const button = el('button', undefined, classes.join(' ').trim());
  button.append(el('strong', run.title), el('small', run.id), badge(run.status || ''));
  if (run.mode && run.mode !== 'develop') button.append(el('span', MODE_LABELS[run.mode], 'badge'));
  if (run.progress) button.append(el('span', 'Tasks ' + run.progress, 'badge'));
  button.onclick = () => {
    closeComposer();
    select(run.id);
    menu();
    refreshRun().catch(showError);
  };
  return button;
}

function select(id, focus = '') {
  state.selected = id;
  state.focus = focus;
  const parts = focus ? [id, focus] : [id];
  location.hash = parts.map(encodeURIComponent).join('/');
  state.last = '';
}

// Show a task or phase run, or a planned node, inside the parent card; again to close.
function pick(focus) {
  select(state.selected, focus === state.focus ? '' : focus);
  refreshRun().catch(showError);
}

export async function showRun(id, focus = '') {
  select(id, focus);
  state.runs = await get('/api/runs');
  menu();
  await refreshRun();
}

export function approvalCard(pending, runId = state.selected) {
  const card = el('section', undefined, 'approval-card');
  card.append(
    el('h3', 'Your decision required'),
    el('p', 'The stage timer is paused. Waiting has no time limit.'),
  );
  if (pending.request?.notice) card.append(el('p', pending.request.notice, 'approval-notice'));
  const jenkins = pending.request?.status === 'JENKINS_REQUEST';
  card.append(
    el('pre', JSON.stringify(pending.request, null, 2)),
    el(
      'p',
      jenkins
        ? 'A read-only Jenkins request: build status, console log or test results. Starting a build always needs root approval in a terminal.'
        : 'Local programs run as the application user and may execute project code. Review the exact command and its effects. This is not a sandbox.',
    ),
  );
  const input = el('textarea', undefined, 'approval-alternative');
  input.placeholder = 'Suggest an alternative action';
  input.value = approvalDrafts.get(pending.ticket) || '';
  input.oninput = () => approvalDrafts.set(pending.ticket, input.value);
  const allowAll = el('input');
  allowAll.type = 'checkbox';
  const allowAllLabel = el('label', undefined, 'approval-allow-all');
  allowAllLabel.append(allowAll, el('span', ' Allow all further actions in this run'));
  card.append(input, allowAllLabel);
  for (const [decision, label] of [
    ['allow', 'Allow'],
    ['deny', 'Deny and continue'],
    ['alternative', 'Send alternative'],
  ]) {
    const button = el('button', label, decision === 'allow' ? 'primary' : '');
    button.disabled = state.actionPending;
    button.onclick = async () => {
      state.actionPending = true;
      try {
        const payload = { id: runId, ticket: pending.ticket, decision };
        payload.alternative = input.value;
        if (decision === 'allow' && allowAll.checked) payload.allow_all = true;
        await post('/api/decision', payload, 'Decision failed');
        approvalDrafts.delete(pending.ticket);
        input.blur();
        state.last = '';
        await refreshRun();
      } catch (error) {
        showError(error);
      } finally {
        state.actionPending = false;
      }
    };
    card.append(button);
  }
  return card;
}

const CHECKBOXES = new Set(['worktree', 'auto_approve']);

const MODE_LABELS = {
  develop: 'Develop',
  answer: 'Answer only',
  design: 'Design discussion',
  decompose: 'Split into tasks',
};

function draftMode(draft) {
  if (draft.design) return 'design';
  return draft.read_only ? 'answer' : 'develop';
}

export function openComposer(draft = null, context = {}) {
  state.composerContext = context;
  const form = document.getElementById('task-form');
  form.reset();
  document.getElementById('project-roots').replaceChildren();
  if (draft) {
    for (const [key, value] of Object.entries(draft)) {
      const input = form.elements.namedItem(key);
      if (input && !CHECKBOXES.has(key)) input.value = value;
    }
    document.getElementById('task-mode').value = draftMode(draft);
    document.getElementById('task-worktree').checked = !!draft.worktree;
    document.getElementById('task-auto-approve').checked = !!draft.auto_approve;
    draft.roots.forEach((root) => addRoot(root.alias, root.path));
  } else addRoot();
  state.composing = true;
  document.getElementById('composer').hidden = false;
  document.getElementById('chat').hidden = true;
  document.getElementById('followup-panel').hidden = true;
  document.getElementById('form-error').textContent = '';
  document.getElementById('task-goal').focus();
}

export function closeComposer() {
  state.composing = false;
  document.getElementById('composer').hidden = true;
  document.getElementById('chat').hidden = false;
}

export function addRoot(alias = '', path = '') {
  const holder = document.getElementById('project-roots');
  if (holder.children.length >= 8) return;
  const row = el('div', undefined, 'root-row');
  const name = el('input');
  name.value = alias;
  name.placeholder = 'name (auto)';
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

const ACTIONS = [
  ['restart', 'Restart from scratch'],
  ['resume', 'Continue from checkpoint'],
  ['resume_budget', 'Continue with extra budget'],
  ['stop', 'Stop task'],
  ['done', 'Mark as done'],
  ['reopen', 'Move back from Done'],
  ['revoke_auto_approve', 'Stop allowing all actions'],
  ['delete', 'Delete from history'],
];
const ACTION_TITLES = {
  resume_budget: 'Adds two attempts and one attempt timeout. Existing usage is retained.',
  restart: 'Edit the task before starting a new run. No rollback.',
  stop: 'Stop the worker and save a checkpoint. Partial edits are preserved.',
  done: 'Move this run to Done. Nothing in the project changes.',
  reopen: 'Return this run to its computed group.',
  revoke_auto_approve:
    'Ask before local commands and the change limit again; applies before the next decision and on Continue.',
  delete: 'Move run history to local trash. Project files are preserved.',
};

// A task or phase run restarts under its parent; deleting it would break the attempt chain.
const ASSIGNED_RESTARTS = {
  task: [
    'Restart reviewed task',
    'Retry this task under its approved parent plan. Existing edits are preserved.',
  ],
  integration: ['Restart this phase', 'Run this phase again under the same delivery.'],
  validation: ['Restart this phase', 'Run this phase again under the same delivery.'],
  server: ['Restart this phase', 'Run this phase again under the same delivery.'],
};

function actionButtons(data, embedded = false) {
  const actions = el('div', undefined, 'run-actions');
  const assigned = ASSIGNED_RESTARTS[data.phase];
  for (const [action, label] of ACTIONS) {
    const assignedRestart = action === 'restart' && Boolean(assigned);
    const button = el('button', assignedRestart ? assigned[0] : label);
    const available = data.actions?.[action] && !(embedded && action === 'delete');
    button.disabled = state.actionPending || !available;
    // Unavailable actions are hidden rather than shown disabled.
    button.hidden = !available;
    if (action === 'delete') button.className = 'danger';
    button.title = action === 'resume' ? data.actions?.resume_reason || '' : ACTION_TITLES[action];
    if (assignedRestart) button.title = assigned[1];
    button.onclick = () =>
      action === 'restart' && !assignedRestart
        ? openComposer(data.draft, { parent_run: data.id, submission_mode: 'restart' })
        : runAction(action, {}, data.id);
    actions.append(button);
  }
  if (data.actions?.resume) {
    const note = el('textarea', undefined, 'resume-note');
    note.id = 'resume-note';
    note.maxLength = 4000;
    note.placeholder =
      'Optional note for the agents when continuing, e.g. "python3 is installed now"';
    note.value = state.resumeNote || '';
    note.oninput = () => (state.resumeNote = note.value);
    actions.append(note);
  }
  return actions;
}

function materialsSection(data) {
  const materials = el('section');
  materials.append(el('h3', 'Artifacts'));
  list(materials, 'Changed files', data.changed_files);
  list(materials, 'Deferred checks', data.unverified);
  if (data.design?.text) detail(materials, 'Design document', data.design.text);
  detail(materials, 'Diff' + (data.diff.truncated ? ' (last part)' : ''), data.diff.text);
  if (data.console)
    detail(
      materials,
      'Worker console' + (data.console.truncated ? ' (last part)' : ''),
      data.console.text,
    );
  detail(materials, 'Report' + (data.report.truncated ? ' (last part)' : ''), data.report.text);
  return materials;
}

// Files a split task found changed outside the split's tasks; they never stop it.
function outsideSection(outside) {
  const section = el('section');
  section.append(
    el('h3', 'Changed outside this task'),
    el(
      'p',
      'Changed by you or another tool, not by the tasks of this split, before this task ' +
        'started. The task checked them first and kept edits unrelated to it; its diff may ' +
        'include them.',
      'muted',
    ),
  );
  const files = el('ul');
  for (const name of outside.files) files.append(el('li', name));
  if (outside.git) files.append(el('li', 'Git state (commits, branch or index) also changed.'));
  section.append(files);
  return section;
}

// The parent's header, or a compact header for a run shown inside its parent's card.
function runHeader(data, embedded) {
  const nodes = embedded
    ? [el('p', data.id, 'muted run-id'), badge(data.status || '')]
    : [
        el('h2', state.runs.find((run) => run.id === data.id)?.title || data.id),
        el('p', data.id, 'muted run-id'),
        badge(data.status || ''),
      ];
  if (data.draft && !embedded) {
    const mode = data.draft.decompose ? 'decompose' : draftMode(data.draft);
    nodes.push(el('span', 'Mode: ' + MODE_LABELS[mode], 'badge'));
  }
  if (data.auto_approve) nodes.push(el('span', 'All actions allowed', 'badge auto-approve'));
  return nodes;
}

// The run shown in the parent's card: the one you picked, else one waiting for you.
function currentFocus(data) {
  return state.focus || attentionRun(data.delivery);
}

const isRun = (focus) => Boolean(focus) && !focus.includes(':');

// Everything one run shows; a run inside its parent's card has no delivery of its own.
export function runBody(data, embedded = false, child = null) {
  const nodes = [...runHeader(data, embedded), actionButtons(data, embedded)];
  if (data.pending_approval) nodes.push(approvalCard(data.pending_approval, data.id));
  const delivery =
    !embedded &&
    data.delivery &&
    deliverySection(data.delivery, {
      act: (action, extra) => runAction(action, extra, data.id),
      pick,
      focus: currentFocus(data),
      child,
      embed: (view) => runBody(view, true),
    });
  if (delivery) nodes.push(delivery);
  for (const job of data.execution_jobs || []) nodes.push(executionCard(job));
  if (data.actions?.stop_requested)
    nodes.push(el('p', 'Stop requested. Waiting for process cleanup and checkpoint.', 'muted'));
  for (const turn of data.conversation || []) {
    const previous = el('section');
    previous.append(
      el('h3', 'Earlier Goal'),
      el('div', turn.goal, 'text'),
      el('h3', 'Earlier conclusion'),
      el('div', turn.summary, 'text'),
    );
    nodes.push(previous);
  }
  if (data.summary) {
    const summary = el('section');
    summary.append(el('h3', 'Conclusion'), el('div', data.summary, 'text'));
    nodes.push(summary);
  }
  if (data.outside_changes) nodes.push(outsideSection(data.outside_changes));
  nodes.push(taskSection(data));
  for (const stage of data.stages) nodes.push(stageCard(stage));
  nodes.push(materialsSection(data));
  return nodes;
}

export function render(data, child = null) {
  if (preserveSelection()) return;
  if (state.currentRun?.id !== data.id) document.getElementById('reply-goal').value = '';
  state.currentRun = data;
  document.getElementById('followup-panel').hidden = !data.actions?.followup;
  document.getElementById('send-reply').disabled = state.actionPending;
  renderMonitor(child || data);
  const timeless = (view) => view && { ...view, server_time: undefined };
  const signature = JSON.stringify([timeless(data), timeless(child), state.focus]);
  if (signature === state.last) return;
  state.last = signature;
  const view = document.getElementById('chat');
  const openTitles = new Set(
    [...view.querySelectorAll('details')]
      .filter((node) => node.open)
      .map((node) => node.csKey || node.querySelector('summary').textContent),
  );
  const y = scrollY;
  view.replaceChildren(...runBody(data, false, child));
  for (const node of view.querySelectorAll('details')) {
    if (openTitles.has(node.csKey || node.querySelector('summary').textContent)) node.open = true;
  }
  scrollTo(0, y);
}

export async function refreshRun() {
  if (!state.selected || state.composing) return;
  const id = state.selected;
  const data = await get('/api/run?id=' + encodeURIComponent(id));
  if (id !== state.selected) return;
  // A task or phase run opens inside its parent's card.
  if (data.parent && data.parent.run !== id) {
    select(data.parent.run, id);
    return refreshRun();
  }
  const focus = currentFocus(data);
  const child = isRun(focus)
    ? await get('/api/run?id=' + encodeURIComponent(focus)).catch(() => null)
    : null;
  if (id !== state.selected) return;
  state.serverClockOffset = new Date(data.server_time).getTime() - Date.now();
  if (!Number.isFinite(state.serverClockOffset)) state.serverClockOffset = 0;
  render(data, child);
  tickStageTimers();
}

export async function refresh() {
  try {
    state.runs = await get('/api/runs');
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

const CONFIRMATIONS = {
  delete: 'Move this run and its logs to local trash? Project files will not be changed.',
  resume_budget:
    'Grant two extra attempts and one attempt timeout, then continue? Token caps and permissions are unchanged.',
};

export async function runAction(action, extra = {}, runId = state.selected) {
  if (state.actionPending) return;
  if (CONFIRMATIONS[action] && !confirm(CONFIRMATIONS[action])) return;
  state.actionPending = true;
  document.querySelectorAll('.run-actions button').forEach((button) => (button.disabled = true));
  try {
    const payload = { id: runId, action, ...extra };
    if (action.startsWith('resume') && state.resumeNote?.trim()) payload.note = state.resumeNote;
    const result = await post('/api/actions', payload, 'Action failed');
    if (action.startsWith('resume')) state.resumeNote = '';
    if (action === 'delete') {
      state.currentRun = null;
      document.getElementById('chat').replaceChildren(el('p', 'Task removed from history.'));
      document.getElementById('followup-panel').hidden = true;
      document.getElementById('monitor').replaceChildren();
    }
    // A new or continued task run opens inside its parent; the parent keeps its focus.
    if (action === 'delete' || result.id !== state.selected) select(result.id);
    state.runs = await get('/api/runs');
    menu();
  } catch (error) {
    showError(error);
  } finally {
    state.actionPending = false;
    state.last = '';
    await refreshRun().catch(showError);
  }
}

export async function submitTask(event) {
  event.preventDefault();
  const button = document.getElementById('create-task');
  const error = document.getElementById('form-error');
  if (button.disabled) return;
  button.disabled = true;
  button.textContent = 'Starting…';
  error.textContent = '';
  try {
    const payload = Object.fromEntries(new FormData(event.target).entries());
    const mode = document.getElementById('task-mode').value;
    payload.read_only = mode === 'answer';
    payload.design = mode === 'design';
    payload.worktree = document.getElementById('task-worktree').checked;
    payload.auto_approve = document.getElementById('task-auto-approve').checked;
    Object.assign(payload, state.composerContext);
    payload.roots = [...document.querySelectorAll('.root-row')].map((row) => ({
      alias: row.querySelector('.root-alias').value.trim(),
      path: row.querySelector('.root-path').value.trim(),
    }));
    const result = await post('/api/tasks', payload, 'Unable to start task');
    closeComposer();
    event.target.reset();
    document.getElementById('project-roots').replaceChildren();
    addRoot();
    await showRun(result.id);
  } catch (failure) {
    error.textContent = failure.message;
    showError(failure);
  } finally {
    button.disabled = false;
    button.textContent = 'Create and run';
  }
}

export async function submitFollowup(event) {
  event.preventDefault();
  if (state.actionPending || !state.currentRun?.actions?.followup) return;
  state.actionPending = true;
  document.getElementById('send-reply').disabled = true;
  document.getElementById('reply-error').textContent = '';
  try {
    const payload = {
      ...state.currentRun.draft,
      goal: document.getElementById('reply-goal').value,
      criteria: 'Address the latest Goal with evidence and report verification limits.',
      parent_run: state.currentRun.id,
      submission_mode: document.getElementById('reply-intent').value,
    };
    payload.read_only = payload.submission_mode === 'answer';
    payload.design = payload.submission_mode === 'design';
    const result = await post('/api/tasks', payload, 'Unable to continue conversation');
    await showRun(result.id);
  } catch (error) {
    document.getElementById('reply-error').textContent = error.message;
  } finally {
    state.actionPending = false;
    document.getElementById('send-reply').disabled = false;
  }
}
