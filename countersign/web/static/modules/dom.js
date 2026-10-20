export const names = {
  planner: 'Planning',
  'plan-reviewer': 'Plan review',
  implementer: 'Implementation',
  check: 'Built-in checks',
  reviewer: 'Result review',
};
export const statuses = {
  TOKEN_BUDGET_EXCEEDED: 'Token budget reached',
  STAGE_BUDGET_EXCEEDED: 'Stage allowance exhausted',
  STARTING: 'Starting',
  LAUNCH_ERROR: 'Launch error',
  INTERRUPTED: 'Interrupted',
  RUNNING: 'Running',
  WAITING_APPROVAL: 'Your decision required',
  NO_CHANGES_REQUIRED: 'No changes required',
  TASKS_READY: 'Tasks ready',
  READY_FOR_REVIEW: 'Ready for your review',
  RESULT_VALID: 'Result validated',
  PLAN_READY: 'Plan ready',
  APPROVE: 'Approved',
  IMPLEMENTED: 'Changes implemented',
  BLOCKED_PERMISSION: 'Permission denied',
  TOOL_ERROR: 'Tool error',
  CONTEXT_EXCEEDED: 'Context window exceeded',
  INVALID_RESULT: 'Invalid result',
  BLOCKED: 'Blocked',
  REQUEST_CHANGES: 'Changes requested',
  CHECK_COMPLETED: 'Checks complete',
  PASS: 'Passed',
  FAIL: 'Error',
  SKIPPED: 'Skipped',
  TIMEOUT: 'Timed out',
};

// Treat every task, model message and file as text, never executable markup.
export function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
export function badge(text) {
  const good = [
    'NO_CHANGES_REQUIRED',
    'READY_FOR_REVIEW',
    'TASKS_READY',
    'APPROVE',
    'PASS',
  ].includes(text);
  const cls = good ? 'good' : /ERROR|BLOCKED|FAIL|INVALID|TIMEOUT/.test(text) ? 'bad' : '';
  return el('span', statuses[text] || text, 'badge ' + cls);
}
export function detail(parent, title, text) {
  if (!text) return;
  const node = el('details');
  node.append(el('summary', title), el('pre', text));
  parent.append(node);
  return node;
}
export function list(parent, title, values) {
  if (!values?.length) return;
  parent.append(el('h3', title));
  const ul = el('ul');
  for (const value of values)
    ul.append(el('li', typeof value === 'string' ? value : JSON.stringify(value)));
  parent.append(ul);
}
export function showError(error) {
  document.getElementById('connection').textContent = 'Update failed: ' + error.message;
}
export function durationLabel(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return 'Unavailable';
  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = total % 60;
  if (hours) return `${hours} h ${minutes} min ${remainder} s`;
  if (minutes) return `${minutes} min ${remainder} s`;
  return `${total} s`;
}
export function timeLabel(value) {
  if (value === undefined || value === null || value === '') return 'Time unavailable';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Time unavailable' : date.toLocaleString('en-GB');
}
export function timeNode(value) {
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
