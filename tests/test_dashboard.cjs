// DOM structure regression checks without a browser or third-party dependencies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
class Node {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.textContent = '';
    this.style = {};
  }
  replaceChildren(...children) {
    this.children = children;
  }
  append(...children) {
    this.children.push(...children);
  }
  querySelectorAll(tag) {
    return this.children.flatMap((n) => [
      ...(n.tagName === tag ? [n] : []),
      ...n.querySelectorAll(tag),
    ]);
  }
  querySelector(tag) {
    return this.querySelectorAll(tag)[0];
  }
  setAttribute(name, value) {
    this[name] = value;
  }
}
const monitor = new Node('aside');
const context = vm.createContext({
  document: { createElement: (tag) => new Node(tag), getElementById: () => monitor },
  location: { hash: '' },
});
const script = fs.readFileSync(
  path.join(__dirname, '../countersign/web/static/dashboard.js'),
  'utf8',
);
vm.runInContext(
  script.slice(0, script.indexOf("document.getElementById('new-task').onclick")),
  context,
);
const stamp = 1791790000000;
const stage = {
  number: 5,
  stage: 'reviewer',
  role: 'reviewer',
  status: 'RESULT_VALID',
  verdict: 'APPROVE',
  elapsed_seconds: 264.9,
  started_at: '2026-10-12T08:00:00Z',
  finished_at: '2026-10-12T08:04:25Z',
  result: { summary: 'Verified source', findings: [], unverified: [] },
  directory: '05-review',
  messages: { items: [{ text: '<script>untrusted</script>', timestamp: stamp }], truncated: false },
};
const card = context.stageCard(stage);
function all(node) {
  return [node, ...node.children.flatMap(all)];
}
const header = all(card).find((n) => n.className === 'stage-header');
assert.equal(header.children[0].textContent, '05 · Result review');
assert.equal(header.children[1].className, 'stage-meta muted');
assert.equal(header.children[1].children[0].textContent, 'reviewer · 4 min 24 s');
const times = all(card).filter((n) => n.tagName === 'time');
assert.equal(times.length, 2);
assert.equal(times[0].dateTime, '2026-10-12T08:04:25.000Z');
assert.equal(times[1].dateTime, new Date(stamp).toISOString());
assert.equal(all(card).find((n) => n.textContent === '<script>untrusted</script>').tagName, 'div');
assert.equal(context.timeNode(null).textContent, 'Time unavailable');
const css = fs.readFileSync(
  path.join(__dirname, '../countersign/web/static/dashboard.css'),
  'utf8',
);
assert.match(css, /\.stage-meta\s*\{[^}]*margin-left:\s*auto;[^}]*text-align:\s*right/);
console.log('Dashboard structure: timestamps, aligned metadata, and text-only rendering passed.');

const telemetry = {
  tokens: { input: 80, output: 20, cache_read: 10, cache_write: 0, reasoning: 0, total: 100 },
  tool_calls: 1,
  tool_errors: 0,
  repeated_reads: 0,
  compaction_completed: 0,
  compaction_markers: 0,
  usage_steps: 1,
  model_steps: 1,
  timeline: [
    {
      kind: 'tool',
      tool: 'read',
      status: 'completed',
      timestamp: stamp,
      input: '{"filePath":"/repo/file"}',
      output: '<script>not executable</script>',
      duration_seconds: 1.5,
    },
  ],
  usage_coverage: 'reported_steps_only',
};
const traced = context.stageCard({ ...stage, telemetry });
assert.ok(all(traced).some((n) => n.textContent === 'Tool · read · completed'));
assert.ok(all(traced).some((n) => n.textContent === '<script>not executable</script>'));
context.renderMonitor({
  stages: [{ ...stage, telemetry }],
  status: 'READY_FOR_REVIEW',
  started_at: stage.started_at,
  finished_at: stage.finished_at,
  monitoring: {},
});
assert.ok(all(monitor).some((n) => n.textContent === '100'));
assert.ok(all(monitor).some((n) => n.textContent === 'Unknown / not observed'));
assert.ok(all(monitor).some((n) => n.textContent === 'By stage'));
console.log('Monitoring and tool-call timeline passed.');

monitor.querySelector('details').open = true;
context.renderMonitor({
  stages: [{ ...stage, telemetry }],
  status: 'READY_FOR_REVIEW',
  started_at: stage.started_at,
  finished_at: stage.finished_at,
  monitoring: {},
});
assert.equal(monitor.querySelector('details').open, true);
console.log('Expanded monitoring details survive refresh.');

// Restart must prefill an editable form and perform no network request.
const fields = Object.fromEntries(
  [
    'title',
    'goal',
    'criteria',
    'verification',
    'constraints',
    'current_behavior',
    'entry_points',
  ].map((name) => [name, new Node('input')]),
);
const nodes = Object.fromEntries(
  [
    'task-form',
    'project-roots',
    'task-read-only',
    'composer',
    'chat',
    'followup-panel',
    'form-error',
    'task-goal',
  ].map((name) => [name, new Node('div')]),
);
nodes['task-form'].elements = { namedItem: (name) => fields[name] };
nodes['task-form'].reset = () => {
  for (const field of Object.values(fields)) field.value = '';
  nodes['task-read-only'].checked = false;
};
nodes['task-goal'].focus = () => {};
context.document.getElementById = (name) => nodes[name];
context.openComposer(
  {
    title: 'Previous task',
    goal: 'Original goal',
    criteria: 'Check existing work',
    roots: [{ alias: 'qa', path: '/projects/qa' }],
    read_only: true,
  },
  { parent_run: 'prior', submission_mode: 'restart' },
);
assert.equal(fields.goal.value, 'Original goal');
assert.equal(fields.criteria.value, 'Check existing work');
assert.equal(nodes['task-read-only'].checked, true);
assert.equal(nodes.composer.hidden, false);
assert.equal(nodes.chat.hidden, true);
assert.equal(nodes['project-roots'].children[0].children[1].value, '/projects/qa');
fields.goal.value = 'Edited before launch';
assert.equal(fields.goal.value, 'Edited before launch');
context.openComposer();
assert.equal(fields.goal.value, '');
assert.equal(nodes['task-read-only'].checked, false);
assert.equal(nodes['project-roots'].children.length, 1);
console.log('Restart prefill and clean new-task form passed without launching a worker.');

const structured = context.stageCard({
  ...stage,
  contract_version: 1,
  agent_source: '/custom/agents/reviewer.md',
  agent_sha256: 'role-hash',
  contract_sha256: 'contract-hash',
  instruction_sha256: 'request-hash',
  budget: { attempts_remaining: 1, timeout: 3600 },
  telemetry,
  result: {
    summary: 'Validated',
    steps: [
      {
        id: 'S1',
        action: 'Fix behavior',
        files: ['/repo/a.py'],
        criteria: ['R1'],
        checks: ['Static review'],
        depends_on: [],
      },
    ],
    coverage: [
      {
        id: 'R1',
        outcome: 'satisfied',
        evidence_ids: ['E1'],
        explanation: '<script>source only</script>',
      },
    ],
    evidence: [],
  },
});
assert.ok(all(structured).some((n) => n.textContent === 'S1 · Fix behavior'));
assert.ok(all(structured).some((n) => n.textContent === 'R1 · satisfied'));
assert.ok(all(structured).some((n) => n.textContent === '<script>source only</script>'));
assert.ok(
  all(structured).some((n) =>
    n.textContent.includes('Frozen role source: /custom/agents/reviewer.md'),
  ),
);
assert.ok(all(structured).some((n) => n.textContent.includes('/ 1 h')));
assert.ok(!all(structured).some((n) => n.textContent.includes('Remaining launches:')));

// A budget-paused run exposes both continuation choices and reversible deletion.
for (const name of ['reply-goal', 'send-reply', 'monitor']) nodes[name] = new Node('div');
context.scrollY = 0;
context.scrollTo = () => {};
context.render({
  id: 'paused',
  status: 'STAGE_BUDGET_EXCEEDED',
  actions: { resume: true, resume_budget: true, delete: true },
  task: { text: 'Task' },
  roots: {},
  stages: [],
  diff: { text: '' },
  report: { text: '' },
});
const buttons = all(nodes.chat).filter((node) => node.tagName === 'button');
for (const label of [
  'Continue from checkpoint',
  'Continue with extra budget',
  'Delete from history',
]) {
  assert.equal(buttons.find((node) => node.textContent === label).disabled, false);
}
assert.equal(buttons.find((node) => node.textContent === 'Stop task').disabled, true);
console.log('Budget continuation and deletion controls passed.');

const toolToggle = all(nodes.chat).find((node) => node.type === 'checkbox');
assert.equal(toolToggle, undefined);

// Polling must not detach selected nodes or a drag's initial anchor.
const beforeSelection = nodes.chat.children[0];
context.document.getSelection = () => ({ isCollapsed: false });
context.render({ id: 'deferred' });
assert.equal(nodes.chat.children[0], beforeSelection);
const beforeMonitor = nodes.monitor.children[0];
context.renderMonitor({ stages: [] });
assert.equal(nodes.monitor.children[0], beforeMonitor);
context.document.getSelection = () => ({ isCollapsed: true });
vm.runInContext('pointerSelecting = true', context);
context.render({ id: 'dragging' });
assert.equal(nodes.chat.children[0], beforeSelection);
vm.runInContext('pointerSelecting = false', context);
context.render({
  id: 'resumed',
  status: 'RUNNING',
  actions: {},
  task: { text: 'Updated' },
  roots: {},
  stages: [],
  diff: { text: '' },
  report: { text: '' },
  server_time: 'one',
});
assert.notEqual(nodes.chat.children[0], beforeSelection);
const afterSelection = nodes.chat.children[0];
context.render({
  id: 'resumed',
  status: 'RUNNING',
  actions: {},
  task: { text: 'Updated' },
  roots: {},
  stages: [],
  diff: { text: '' },
  report: { text: '' },
  server_time: 'two',
});
assert.equal(nodes.chat.children[0], afterSelection);
console.log('Selection survives polling; updates resume after selection clears.');

const sshCard = context.executionCard({
  id: 'ticket-123',
  status: 'PENDING_APPROVAL',
  action: {
    reason: 'Inspect host',
    targets: ['qa'],
    script: 'uname -a',
    files: { 'play.yml': '<script>literal</script>' },
  },
});
assert.ok(
  all(sshCard).some((node) =>
    node.textContent.includes('sudo -k /usr/local/bin/countersign-executor-approve ticket-123'),
  ),
);
assert.ok(
  all(sshCard).some(
    (node) => node.tagName === 'pre' && node.textContent === '<script>literal</script>',
  ),
);
assert.equal(all(sshCard).filter((node) => node.tagName === 'button').length, 0);
console.log('SSH request display is text-only and cannot approve actions.');

assert.equal(context.durationLabel(2637.3), '43 min 57 s');
assert.equal(context.durationLabel(578.6), '9 min 38 s');
assert.equal(context.durationLabel(3600), '1 h 0 min 0 s');
assert.equal(context.durationLabel(59.9), '59 s');
assert.equal(context.durationLabel(NaN), 'Unavailable');

assert.equal(
  context.stageClockLabel(
    {
      role: 'planner',
      status: 'RUNNING',
      started_at: '2026-10-15T00:00:00Z',
      budget: { timeout: 3600 },
    },
    Date.parse('2026-10-15T00:05:05Z'),
  ),
  'planner · 5 min 5 s / 1 h · 54 min 55 s left',
);
assert.match(
  context.stageClockLabel(
    {
      role: 'planner',
      status: 'RUNNING',
      started_at: '2026-10-15T00:00:00Z',
      budget: { timeout: 60 },
    },
    Date.parse('2026-10-15T00:05:05Z'),
  ),
  /Timeout pending/,
);
assert.equal(
  context.stageClockLabel({
    role: 'planner',
    status: 'RESULT_VALID',
    elapsed_seconds: 305,
    budget: { timeout: 3600 },
  }),
  'planner · 5 min 5 s / 1 h',
);
assert.doesNotMatch(script, /Remaining launches:|Attempt time limit:/);

const decisionCard = context.approvalCard({
  ticket: 'unique-ticket',
  request: { argv: ['bash', '-n', 'script.sh'], cwd: '/project' },
});
assert.deepEqual(
  all(decisionCard)
    .filter((n) => n.tagName === 'button')
    .map((n) => n.textContent),
  ['Allow', 'Deny and continue', 'Send alternative'],
);
assert.ok(all(decisionCard).some((n) => n.textContent.includes('"bash"')));
const waitingStage = {
  ...stage,
  status: 'WAITING_APPROVAL',
  elapsed_seconds: 50,
  paused_seconds: 7200,
  budget: { timeout: 3600 },
};
assert.equal(
  context.stageClockLabel(waitingStage, Date.now()),
  'reviewer · 50 s / 1 h · Waiting for approval',
);
assert.equal(
  context.stageClockLabel(waitingStage, Date.now() + 86400000),
  context.stageClockLabel(waitingStage, Date.now()),
);
assert.ok(!script.includes('High cumulative token usage'));
console.log('Approval controls and paused stage timer passed.');
