// The tasks of a split and the phases of a delivery as one dependency graph.
// Columns follow depends_on depth, then the phases run left to right. A node opens its
// run inside the parent card; earlier attempts collapse into one expandable line.
import { badge, el, statuses } from './dom.js';

const SVG = 'http://www.w3.org/2000/svg';
const NODE_WIDTH = 200;
const NODE_HEIGHT = 64;
const GAP_X = 44;
const GAP_Y = 14;
const ARROW = 6;

const PHASE_TITLES = {
  integration: 'Integration review',
  validation: 'Jenkins validation',
  confirm: 'Your confirmation',
  server: 'Server checks',
};
const PHASE_WAITING = {
  integration: 'Starts after every child task finishes.',
  validation: 'Starts when the code is done.',
  confirm: 'Confirm once you have reviewed the changes.',
  server: 'Run after you confirm the changes; each action needs root approval.',
};
// A finished check run means its checks ran and were reviewed; its summary has the results.
const PHASE_LABELS = {
  NO_CHANGES_REQUIRED: 'CHECK_COMPLETED',
  READY_FOR_REVIEW: 'CHECK_COMPLETED',
  skipped: 'SKIPPED',
};
const TONES = {
  good: ['READY_FOR_REVIEW', 'NO_CHANGES_REQUIRED', 'CHECK_COMPLETED', 'CONFIRMED', 'SKIPPED'],
  active: ['STARTING', 'RUNNING'],
  attention: ['WAITING_APPROVAL', 'NEXT', 'CONFIRM'],
  pending: ['NOT_STARTED', 'WAITING'],
};

function tone(status) {
  for (const [name, values] of Object.entries(TONES)) if (values.includes(status)) return name;
  return 'bad';
}

function phaseNames(delivery) {
  const names = [];
  if (delivery.tasks) names.push('integration');
  if (delivery.checks.jenkins.length) names.push('validation');
  const confirming = delivery.step === 'confirm' || delivery.confirmed;
  if (confirming || delivery.checks.server.length) names.push('confirm');
  if (delivery.checks.server.length) names.push('server');
  return names;
}

function phaseStatus(delivery, name) {
  if (name === 'confirm') {
    if (delivery.confirmed) return 'CONFIRMED';
    return delivery.step === 'confirm' ? 'CONFIRM' : 'WAITING';
  }
  const record = delivery.phases[name];
  if (!record) return 'WAITING';
  return PHASE_LABELS[record.status] || record.status;
}

function taskNodes(delivery) {
  const tasks = delivery.tasks || [];
  const byId = new Map(tasks.map((task) => [task.id, task]));
  const depth = new Map();
  const level = (task) => {
    if (depth.has(task.id)) return depth.get(task.id);
    depth.set(task.id, 0);
    const parents = (task.depends_on || []).filter((id) => byId.has(id));
    const value = parents.length ? 1 + Math.max(...parents.map((id) => level(byId.get(id)))) : 0;
    depth.set(task.id, value);
    return value;
  };
  return tasks.map((task) => ({
    key: 'task:' + task.id,
    kind: 'task',
    id: task.id,
    label: task.id + ' · ' + task.title,
    status: task.status || (task.id === delivery.next ? 'NEXT' : 'NOT_STARTED'),
    column: level(task),
    after: (task.depends_on || []).filter((id) => byId.has(id)),
    run: task.run,
    attempts: task.attempts || [],
    task,
  }));
}

// Nodes with their columns and rows, and edges between node IDs.
export function graphLayout(delivery) {
  const nodes = taskNodes(delivery);
  const dependents = new Set(nodes.flatMap((node) => node.after));
  const sinks = nodes.filter((node) => !dependents.has(node.id)).map((node) => node.id);
  let column = nodes.length ? Math.max(...nodes.map((node) => node.column)) + 1 : 0;
  let previous = sinks;
  for (const name of phaseNames(delivery)) {
    const record = delivery.phases[name] || {};
    nodes.push({
      key: 'phase:' + name,
      kind: 'phase',
      id: name,
      label: PHASE_TITLES[name],
      status: phaseStatus(delivery, name),
      column,
      after: previous,
      run: record.run || null,
      attempts: record.attempts || [],
      record,
    });
    previous = [name];
    column += 1;
  }
  const rows = new Map();
  for (const node of nodes) {
    node.row = rows.get(node.column) || 0;
    rows.set(node.column, node.row + 1);
  }
  const edges = nodes.flatMap((node) => node.after.map((from) => [from, node.id]));
  return { nodes, edges };
}

function position(node) {
  return { x: node.column * (NODE_WIDTH + GAP_X), y: node.row * (NODE_HEIGHT + GAP_Y) };
}

function svgNode(tag, attributes) {
  const node = document.createElementNS(SVG, tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
  return node;
}

function edgeShapes(from, to) {
  const start = position(from);
  const end = position(to);
  const x1 = start.x + NODE_WIDTH;
  const y1 = start.y + NODE_HEIGHT / 2;
  const x2 = end.x - ARROW;
  const y2 = end.y + NODE_HEIGHT / 2;
  const middle = (x1 + x2) / 2;
  const curve = `M ${x1} ${y1} C ${middle} ${y1}, ${middle} ${y2}, ${x2} ${y2}`;
  const head = `${x2} ${y2 - ARROW / 2}, ${x2 + ARROW} ${y2}, ${x2} ${y2 + ARROW / 2}`;
  return [svgNode('path', { d: curve }), svgNode('polygon', { points: head })];
}

// The node a focus key, current run or earlier attempt belongs to.
export function focusedNode(nodes, focus) {
  if (!focus) return null;
  return (
    nodes.find(
      (node) =>
        node.key === focus ||
        node.run === focus ||
        node.attempts.some((attempt) => attempt.run === focus),
    ) || null
  );
}

// The first run that waits for your decision, so its approval shows without a click.
export function attentionRun(delivery) {
  if (!delivery) return '';
  const { nodes } = graphLayout(delivery);
  const waiting = nodes.find((node) => node.run && node.status === 'WAITING_APPROVAL');
  return waiting ? waiting.run : '';
}

function graphNode(node, selected, pick) {
  const button = el('button', undefined, ['graph-node', 'tone-' + tone(node.status)].join(' '));
  if (selected) button.className += ' selected';
  button.type = 'button';
  button.title = node.label;
  const place = position(node);
  button.style.left = place.x + 'px';
  button.style.top = place.y + 'px';
  button.style.width = NODE_WIDTH + 'px';
  button.style.height = NODE_HEIGHT + 'px';
  button.append(el('strong', node.label), badge(node.status));
  if (node.attempts.length) {
    const retries = el('span', '↻ ' + node.attempts.length, 'graph-retries');
    retries.title = node.attempts.length + ' earlier attempts';
    button.append(retries);
  }
  button.onclick = () => pick(node.run || node.key);
  return button;
}

export function graphView(layout, focus, pick) {
  const { nodes, edges } = layout;
  const columns = Math.max(...nodes.map((node) => node.column)) + 1;
  const rows = Math.max(...nodes.map((node) => node.row)) + 1;
  const width = columns * NODE_WIDTH + (columns - 1) * GAP_X;
  const height = rows * NODE_HEIGHT + (rows - 1) * GAP_Y;
  const canvas = el('div', undefined, 'graph');
  canvas.style.width = width + 'px';
  canvas.style.height = height + 'px';
  const lines = svgNode('svg', {
    class: 'graph-edges',
    width,
    height,
    viewBox: `0 0 ${width} ${height}`,
    'aria-hidden': 'true',
  });
  const byId = new Map(nodes.map((node) => [node.id, node]));
  for (const [from, to] of edges) lines.append(...edgeShapes(byId.get(from), byId.get(to)));
  canvas.append(lines);
  const selected = focusedNode(nodes, focus);
  for (const node of nodes) canvas.append(graphNode(node, node === selected, pick));
  const scroll = el('div', undefined, 'graph-scroll');
  scroll.append(canvas);
  return scroll;
}

// Earlier attempts of one node: one line, expandable to open any of them.
export function attemptsLine(node, focus, pick) {
  const count = node.attempts.length;
  const box = el('details', undefined, 'attempts');
  box.csKey = 'attempts:' + node.key;
  const parts = node.attempts.map(
    (attempt, index) => '#' + (index + 1) + ' ' + (statuses[attempt.status] || attempt.status),
  );
  const noun = count === 1 ? ' earlier attempt · ' : ' earlier attempts · ';
  box.append(el('summary', count + noun + parts.join(' · ')));
  const list = el('ol');
  node.attempts.forEach((attempt, index) => {
    const item = el('li');
    item.append(el('strong', '#' + (index + 1) + ' '), badge(attempt.status));
    if (attempt.reason) item.append(el('span', ' ' + attempt.reason, 'muted'));
    const open = el('button', attempt.run === focus ? 'Shown below' : 'Open');
    open.type = 'button';
    open.disabled = attempt.run === focus;
    open.onclick = () => pick(attempt.run);
    item.append(open);
    list.append(item);
  });
  box.append(list);
  return box;
}

function plannedTask(task, actions) {
  const part = el('div', undefined, 'graph-planned');
  part.append(el('p', task.goal, 'text'));
  if (task.done_when?.length) {
    const done = el('ul');
    for (const line of task.done_when) done.append(el('li', line));
    part.append(el('h4', 'Done when'), done);
  }
  if (task.files?.length) part.append(el('p', 'Files: ' + task.files.join(', '), 'muted'));
  if (task.depends_on?.length) part.append(el('p', 'After ' + task.depends_on.join(', '), 'muted'));
  const pause = el('input');
  pause.type = 'checkbox';
  pause.checked = task.pause_before;
  pause.onchange = () =>
    actions.act(pause.checked ? 'epic_pause' : 'epic_unpause', { task: task.id });
  const label = el('label', undefined, 'epic-pause');
  label.append(pause, el('span', ' Pause before this task (auto-continue waits for you)'));
  part.append(label);
  return part;
}

function plannedPhase(node, delivery) {
  const part = el('div', undefined, 'graph-planned');
  const keys = { integration: null, validation: 'jenkins', server: 'server' };
  const checks = keys[node.id] ? [...delivery.checks[keys[node.id]]] : [];
  if (node.id === 'integration') {
    checks.push('Original goal, acceptance criteria and interactions between tasks');
  }
  if (checks.length) {
    const list = el('ul');
    for (const check of checks) list.append(el('li', check));
    part.append(list);
  }
  const reason = node.record?.status === 'skipped' ? node.record.summary : PHASE_WAITING[node.id];
  part.append(el('p', reason, 'muted'));
  return part;
}

// The selected node: its plan, earlier attempts and the selected run in this card.
export function nodePanel(layout, delivery, actions) {
  const node = focusedNode(layout.nodes, actions.focus);
  if (!node) return el('p', 'Select a task or phase to see its run here.', 'muted graph-hint');
  const panel = el('div', undefined, 'graph-panel');
  const heading = el('div', undefined, 'graph-panel-head');
  heading.append(el('h4', node.label), badge(node.status));
  const close = el('button', 'Close');
  close.type = 'button';
  close.onclick = () => actions.pick('');
  heading.append(close);
  panel.append(heading);
  if (node.attempts.length) panel.append(attemptsLine(node, actions.focus, actions.pick));
  const shown = node.run === actions.focus ? node.run : '';
  const earlier = node.attempts.find((attempt) => attempt.run === actions.focus);
  if (earlier && node.run) {
    const back = el('button', 'Show the current attempt');
    back.type = 'button';
    back.onclick = () => actions.pick(node.run);
    const note = el('p', 'You are viewing an earlier attempt. ', 'muted');
    note.append(back);
    panel.append(note);
  }
  const run = shown || earlier?.run;
  if (run) {
    const child = actions.child?.id === run ? actions.child : null;
    if (child) panel.append(...actions.embed(child));
    else panel.append(el('p', 'Loading the run…', 'muted'));
  } else if (node.kind === 'task') panel.append(plannedTask(node.task, actions));
  else if (node.id !== 'confirm') panel.append(plannedPhase(node, delivery));
  return panel;
}
