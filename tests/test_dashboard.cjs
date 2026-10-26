// DOM structure regression checks without a browser or third-party dependencies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { pathToFileURL } = require('node:url');
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
globalThis.document = {
  createElement: (tag) => new Node(tag),
  createElementNS: (namespace, tag) => new Node(tag),
  getElementById: () => monitor,
};
globalThis.location = { hash: '' };
const staticDir = path.join(__dirname, '../taskrail/web/static');
const moduleNames = ['state', 'dom', 'stages', 'monitor', 'app'];
const script = ['dashboard.js', ...moduleNames.map((name) => `modules/${name}.js`)]
  .map((name) => fs.readFileSync(path.join(staticDir, name), 'utf8'))
  .join('\n');
const load = (name) => import(pathToFileURL(path.join(staticDir, 'modules', name + '.js')).href);

async function main() {
  const [{ state }, dom, stages, monitorModule, app] = await Promise.all(moduleNames.map(load));
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
    messages: {
      items: [{ text: '<script>untrusted</script>', timestamp: stamp }],
      truncated: false,
    },
  };
  const card = stages.stageCard(stage);
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
  assert.equal(
    all(card).find((n) => n.textContent === '<script>untrusted</script>').tagName,
    'div',
  );
  assert.equal(dom.timeNode(null).textContent, 'Time unavailable');
  const css = fs.readFileSync(path.join(__dirname, '../taskrail/web/static/dashboard.css'), 'utf8');
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
  const traced = stages.stageCard({ ...stage, telemetry });
  assert.ok(all(traced).some((n) => n.textContent === 'Tool · read · completed'));
  assert.ok(all(traced).some((n) => n.textContent === '<script>not executable</script>'));
  monitorModule.renderMonitor({
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
  monitorModule.renderMonitor({
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
      'task-mode',
      'task-worktree',
      'task-auto-approve',
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
    nodes['task-mode'].value = 'develop';
    nodes['task-worktree'].checked = false;
    nodes['task-auto-approve'].checked = false;
  };
  nodes['task-goal'].focus = () => {};
  globalThis.document.getElementById = (name) => nodes[name];
  app.openComposer(
    {
      title: 'Previous task',
      goal: 'Original goal',
      criteria: 'Check existing work',
      roots: [{ alias: 'qa', path: '/projects/qa' }],
      read_only: true,
      worktree: true,
      design: true,
      auto_approve: true,
    },
    { parent_run: 'prior', submission_mode: 'restart' },
  );
  assert.equal(fields.goal.value, 'Original goal');
  assert.equal(fields.criteria.value, 'Check existing work');
  assert.equal(nodes['task-mode'].value, 'design');
  assert.equal(nodes['task-worktree'].checked, true);
  assert.equal(nodes['task-auto-approve'].checked, true);
  assert.equal(fields.worktree, undefined);
  assert.equal(nodes.composer.hidden, false);
  assert.equal(nodes.chat.hidden, true);
  assert.equal(nodes['project-roots'].children[0].children[1].value, '/projects/qa');
  fields.goal.value = 'Edited before launch';
  assert.equal(fields.goal.value, 'Edited before launch');
  app.openComposer();
  assert.equal(fields.goal.value, '');
  assert.equal(nodes['task-mode'].value, 'develop');
  assert.equal(nodes['task-worktree'].checked, false);
  assert.equal(nodes['task-auto-approve'].checked, false);
  assert.equal(nodes['project-roots'].children.length, 1);
  assert.equal(nodes['project-roots'].children[0].children[0].value, '');
  app.openComposer({ goal: 'Explain', roots: [], read_only: true });
  assert.equal(nodes['task-mode'].value, 'answer');
  console.log('Restart prefill and clean new-task form passed without launching a worker.');

  const structured = stages.stageCard({
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

  // The run list groups runs and marks the ones that need the operator.
  nodes.runs = new Node('div');
  nodes.filter = Object.assign(new Node('input'), { value: '' });
  state.runs = [
    { id: 'r1', title: 'Building', status: 'RUNNING', group: 'running' },
    { id: 'r2', title: 'Approve me', status: 'WAITING_APPROVAL', group: 'attention' },
    { id: 'r3', title: 'Changed', status: 'READY_FOR_REVIEW', group: 'review' },
    { id: 'r4', title: 'Answered', status: 'NO_CHANGES_REQUIRED', group: 'done' },
  ];
  app.menu();
  const headings = all(nodes.runs)
    .filter((n) => n.className === 'run-group')
    .map((n) => n.textContent);
  assert.deepEqual(headings, ['Running · 1', 'Needs you · 1', 'Ready for review · 1', 'Done · 1']);
  const waiting = all(nodes.runs).find(
    (n) => n.tagName === 'button' && n.className === 'needs-you',
  );
  assert.equal(waiting.children[0].textContent, 'Approve me');
  const done = all(nodes.runs).find((n) => n.tagName === 'details');
  assert.equal(done.open, false);
  nodes.filter.value = 'answered';
  app.menu();
  assert.equal(all(nodes.runs).find((n) => n.tagName === 'details').open, true);
  nodes.filter.value = '';
  state.runs = [];
  console.log('Run groups and the Needs you highlight passed.');

  const { deliverySection } = await load('epic');
  const graph = await load('graph');
  const acted = [];
  const picked = [];
  const embedded = [];
  const delivery = {
    step: 'confirm',
    confirmed: false,
    progress: '1/2',
    next: 'S-2',
    auto_continue: false,
    checks: { jenkins: ['ci/tests: passes'], server: ['health returns 200'] },
    phases: {
      validation: { run: 'val-1', status: 'NO_CHANGES_REQUIRED', summary: 'Passed', attempts: [] },
    },
    tasks: [
      {
        id: 'S-1',
        title: 'Change hello',
        status: 'READY_FOR_REVIEW',
        run: 'child-1',
        summary: 'Done',
        attempts: [{ run: 'child-0', status: 'INVALID_RESULT', reason: 'Duplicate coverage ID' }],
      },
      {
        id: 'S-2',
        title: 'Document hello',
        goal: 'Describe hello in the README',
        done_when: ['README mentions hello'],
        files: ['README.md'],
        depends_on: ['S-1'],
        status: null,
        run: null,
        summary: '',
        pause_before: false,
        attempts: [],
      },
    ],
  };
  const layout = graph.graphLayout(delivery);
  assert.deepEqual(
    layout.nodes.map((node) => [node.label, node.status, node.column, node.row]),
    [
      ['S-1 · Change hello', 'COMPLETED', 0, 0],
      ['S-2 · Document hello', 'NEXT', 1, 0],
      ['Integration review', 'WAITING', 2, 0],
      ['Jenkins validation', 'CHECK_COMPLETED', 3, 0],
      ['Your confirmation', 'CONFIRM', 4, 0],
      ['Server checks', 'WAITING', 5, 0],
    ],
  );
  assert.deepEqual(layout.edges, [
    ['S-1', 'S-2'],
    ['S-2', 'integration'],
    ['integration', 'validation'],
    ['validation', 'confirm'],
    ['confirm', 'server'],
  ]);
  const actions = (focus, child = null) => ({
    act: (action, extra) => acted.push(extra ? action + ' ' + extra.task : action),
    pick: (key) => picked.push(key),
    focus,
    child,
    embed: (view) => {
      embedded.push(view.id);
      return [new Node('section')];
    },
  });
  const panel = deliverySection(delivery, actions(''));
  const svg = all(panel).find((n) => n.tagName === 'svg');
  assert.equal(svg.children.filter((n) => n.tagName === 'path').length, 5);
  const graphNodes = all(panel).filter((n) => n.className?.startsWith('graph-node'));
  assert.deepEqual(
    graphNodes.map((n) => n.className),
    [
      'graph-node tone-good',
      'graph-node tone-attention',
      'graph-node tone-pending',
      'graph-node tone-good',
      'graph-node tone-attention',
      'graph-node tone-pending',
    ],
  );
  assert.equal(graphNodes[0].style.left, '0px');
  assert.equal(graphNodes[1].style.left, '244px');
  assert.ok(all(graphNodes[0]).some((n) => n.textContent === '↻ 1'));
  graphNodes.forEach((node) => node.onclick());
  assert.deepEqual(picked, [
    'child-1',
    'task:S-2',
    'phase:integration',
    'val-1',
    'phase:confirm',
    'phase:server',
  ]);
  assert.ok(
    all(panel).some((n) => n.textContent === 'Select a task or phase to see its run here.'),
  );
  const controls = all(panel)
    .filter((n) => n.tagName === 'button' && !(n.className || '').startsWith('graph-node'))
    .map((n) => n.textContent);
  assert.deepEqual(controls, ['Start S-2', 'Repeat integration review', 'Confirm changes']);
  all(panel)
    .filter((n) =>
      ['Start S-2', 'Repeat integration review', 'Confirm changes'].includes(n.textContent),
    )
    .forEach((button) => button.onclick());
  const toggle = all(panel).find((n) => n.type === 'checkbox');
  toggle.checked = true;
  toggle.onchange();
  assert.ok(all(panel).some((n) => n.textContent === 'Delivery · Waiting for your confirmation'));

  // A planned task shows its plan and the pause choice in the card.
  const planned = deliverySection(delivery, actions('task:S-2'));
  assert.ok(all(planned).some((n) => n.textContent === 'README mentions hello'));
  const pause = all(planned)
    .filter((n) => n.type === 'checkbox')
    .at(-1);
  pause.checked = true;
  pause.onchange();
  assert.deepEqual(acted, [
    'epic_next',
    'integration_review',
    'confirm',
    'epic_auto_on',
    'epic_pause S-2',
  ]);
  const serverPanel = deliverySection(delivery, actions('phase:server'));
  assert.ok(
    all(serverPanel).some((n) => n.textContent.includes('each action needs root approval')),
  );

  // A started task opens its run inside the card; earlier attempts collapse into one line.
  picked.length = 0;
  const opened = deliverySection(delivery, actions('child-1', { id: 'child-1' }));
  assert.deepEqual(embedded, ['child-1']);
  const attempts = all(opened).find((n) => n.className === 'attempts');
  assert.equal(attempts.children[0].textContent, '1 earlier attempt · #1 Invalid result');
  assert.ok(all(attempts).some((n) => n.textContent === ' Duplicate coverage ID'));
  all(attempts)
    .find((n) => n.textContent === 'Open')
    .onclick();
  all(opened)
    .find((n) => n.textContent === 'Close')
    .onclick();
  assert.deepEqual(picked, ['child-0', '']);
  const older = deliverySection(delivery, actions('child-0', null));
  assert.ok(all(older).some((n) => n.textContent === 'Show the current attempt'));
  assert.ok(all(older).some((n) => n.textContent === 'Loading the run…'));
  assert.ok(all(older).some((n) => n.className === 'graph-node tone-good selected'));

  // A run that waits for your decision is shown without a click.
  const awaiting = structuredClone(delivery);
  awaiting.tasks[1] = { ...awaiting.tasks[1], run: 'child-2', status: 'WAITING_APPROVAL' };
  assert.equal(graph.attentionRun(awaiting), 'child-2');
  assert.equal(graph.attentionRun(delivery), '');

  const quiet = { step: 'implementing', confirmed: false, checks: { jenkins: [], server: [] } };
  assert.equal(deliverySection(quiet, {}), null);
  const blockedDelivery = deliverySection(
    { ...delivery, step: 'integration_failed', launch_error: 'Child contract is too large' },
    actions(''),
  );
  assert.ok(all(blockedDelivery).some((n) => n.textContent === 'Integration review'));
  assert.ok(all(blockedDelivery).some((n) => n.textContent === 'Child contract is too large'));
  assert.ok(!all(blockedDelivery).some((n) => n.textContent === 'Confirm changes'));
  console.log('Delivery graph, in-card runs and collapsed attempts passed.');

  // A budget-paused run exposes both continuation choices and reversible deletion.
  for (const name of ['reply-goal', 'send-reply', 'monitor']) nodes[name] = new Node('div');
  globalThis.scrollY = 0;
  globalThis.scrollTo = () => {};
  app.render({
    id: 'paused',
    status: 'STAGE_BUDGET_EXCEEDED',
    auto_approve: true,
    draft: { decompose: true, roots: [] },
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
  assert.ok(all(nodes.chat).some((node) => node.className === 'resume-note'));
  assert.ok(all(nodes.chat).some((node) => node.textContent === 'All actions allowed'));
  assert.ok(all(nodes.chat).some((node) => node.textContent === 'Mode: Split into tasks'));
  console.log('Budget continuation and deletion controls passed.');

  const assigned = {
    ...state.currentRun,
    id: 'child',
    phase: 'task',
    actions: { restart: true },
  };
  app.render(assigned);
  const restartChild = all(nodes.chat).find((node) => node.textContent === 'Restart reviewed task');
  assert.equal(restartChild.disabled, false);
  const calls = [];
  state.selected = assigned.id;
  state.sessionToken = 'test-token';
  nodes.runs = new Node('nav');
  nodes.filter = { value: '' };
  globalThis.document.querySelectorAll = () => [];
  globalThis.fetch = async (url, options) => {
    calls.push([url, options?.body && JSON.parse(options.body)]);
    const value =
      url === '/api/actions'
        ? { id: 'retry', status: 'STARTING' }
        : url === '/api/runs'
          ? []
          : { ...assigned, id: 'retry' };
    return { ok: true, json: async () => value };
  };
  state.composing = false;
  await restartChild.onclick();
  assert.deepEqual(calls[0], ['/api/actions', { id: 'child', action: 'restart' }]);
  assert.equal(state.selected, 'retry');
  assert.equal(state.composing, false);
  console.log('Assigned task restart uses the action API without opening a detached draft.');

  // A task or phase run opens inside its parent's card, with its own decision and actions.
  const { parseHash } = await load('state');
  assert.deepEqual(parseHash('#a%2Fb/c'), { selected: 'a/b', focus: 'c' });
  assert.deepEqual(parseHash('#solo'), { selected: 'solo', focus: '' });
  const base = { ...assigned, phase: null, parent: null, pending_approval: null };
  const familyTasks = [
    delivery.tasks[0],
    { ...delivery.tasks[1], run: 'child-2', status: 'WAITING_APPROVAL' },
  ];
  const parentView = {
    ...base,
    id: 'parent',
    actions: { delete: true },
    delivery: { ...delivery, step: 'needs_you', tasks: familyTasks },
  };
  const childView = {
    ...base,
    id: 'child-2',
    phase: 'task',
    parent: { run: 'parent', slot: 'S-2' },
    actions: { restart: true, delete: true, done: true, reopen: true },
    pending_approval: { ticket: 't-9', request: { argv: ['make', 'test'], cwd: '/p' } },
  };
  const requested = [];
  const posted = [];
  globalThis.fetch = async (url, options) => {
    if (options?.body) posted.push([url, JSON.parse(options.body)]);
    else requested.push(url);
    const id = new URL(url, 'http://local').searchParams.get('id');
    const value = options?.body ? { id: 'child-2' } : id === 'parent' ? parentView : childView;
    return { ok: true, json: async () => value };
  };
  state.selected = 'child-2';
  state.focus = '';
  state.last = '';
  await app.refreshRun();
  assert.equal(state.selected, 'parent');
  assert.equal(state.focus, 'child-2');
  assert.equal(globalThis.location.hash, 'parent/child-2');
  assert.deepEqual(requested, ['/api/run?id=child-2', '/api/run?id=parent', '/api/run?id=child-2']);
  const familyButtons = all(nodes.chat).filter((n) => n.tagName === 'button');
  const deletes = familyButtons.filter((n) => n.textContent === 'Delete from history');
  assert.deepEqual(
    deletes.map((n) => n.hidden),
    [false, true],
  );
  assert.ok(familyButtons.some((n) => n.textContent === 'Restart reviewed task' && !n.hidden));
  for (const label of ['Mark as done', 'Move back from Done']) {
    assert.ok(familyButtons.filter((n) => n.textContent === label).every((n) => n.hidden));
  }
  assert.ok(all(nodes.chat).some((n) => n.textContent?.includes('"make"')));
  all(nodes.chat).find((n) => n.className === 'approval-alternative').blur = () => {};
  await familyButtons.find((n) => n.textContent === 'Allow').onclick();
  assert.deepEqual(posted[0], [
    '/api/decision',
    { id: 'child-2', ticket: 't-9', decision: 'allow', alternative: '' },
  ]);
  // Without a choice, the run that waits for you is shown in the card.
  state.focus = '';
  state.last = '';
  requested.length = 0;
  state.selected = 'parent';
  await app.refreshRun();
  assert.deepEqual(requested, ['/api/run?id=parent', '/api/run?id=child-2']);
  assert.equal(state.focus, '');
  app.render({ ...base, id: 'phase-run', phase: 'validation', actions: { restart: true } });
  assert.ok(all(nodes.chat).some((n) => n.textContent === 'Restart this phase' && !n.hidden));
  state.runs = [{ id: 'parent', title: 'Split work', members: ['child-2'], group: 'running' }];
  nodes.filter.value = 'child-2';
  app.menu();
  assert.ok(all(nodes.runs).some((n) => n.textContent === 'Split work'));
  nodes.filter.value = '';
  state.runs = [];
  app.render({
    ...base,
    id: 'outside-run',
    phase: 'task',
    outside_changes: { files: ['admin/site.yml', 'admin/.idea/workspace.xml'], git: true },
  });
  const outside = all(nodes.chat)
    .filter((n) => n.tagName === 'li')
    .map((n) => n.textContent);
  assert.ok(all(nodes.chat).some((n) => n.textContent === 'Changed outside this task'));
  assert.ok(outside.includes('admin/site.yml'));
  assert.ok(outside.includes('Git state (commits, branch or index) also changed.'));
  console.log('Task and phase runs open inside the parent card with their own decisions.');

  const toolToggle = all(nodes.chat).find((node) => node.type === 'checkbox');
  assert.equal(toolToggle, undefined);

  // Polling must not detach selected nodes or a drag's initial anchor.
  const beforeSelection = nodes.chat.children[0];
  globalThis.document.getSelection = () => ({ isCollapsed: false });
  app.render({ id: 'deferred' });
  assert.equal(nodes.chat.children[0], beforeSelection);
  const beforeMonitor = nodes.monitor.children[0];
  monitorModule.renderMonitor({ stages: [] });
  assert.equal(nodes.monitor.children[0], beforeMonitor);
  globalThis.document.getSelection = () => ({ isCollapsed: true });
  state.pointerSelecting = true;
  app.render({ id: 'dragging' });
  assert.equal(nodes.chat.children[0], beforeSelection);
  state.pointerSelecting = false;
  app.render({
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
  app.render({
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

  const taskView = {
    id: 'task-preview',
    status: 'RUNNING',
    actions: {},
    task: { text: '```taskrail-task\n{"task_spec": {}}\n```\n## Workflow rules\nKeep scope.' },
    draft: {
      goal: '<script>literal goal</script>',
      criteria: 'Existing checks pass.',
      constraints: 'Keep compatibility.',
      verification: 'Run the scenario in staging.',
      current_behavior: 'Original error log',
      entry_points: 'project/src/main.py',
    },
    roots: { project: '/workspace/project' },
    requirements: [{ id: 'R1', text: '<img src=x onerror=alert(1)>' }],
    stages: [],
    diff: { text: '' },
    report: { text: '' },
  };
  app.render(taskView);
  const taskPanel = all(nodes.chat).find((node) => node.className === 'task-overview');
  const folds = taskPanel.children.filter((node) => node.tagName === 'details');
  assert.deepEqual(
    folds.map((node) => node.querySelector('summary').children[0].textContent),
    ['Original task', 'Requirement IDs'],
  );
  assert.ok(
    all(taskPanel)
      .filter((node) => node.tagName === 'details')
      .every((node) => !node.open),
  );
  const originalBody = folds[0].children[1];
  assert.deepEqual(
    originalBody.children
      .filter((node) => node.className === 'task-field')
      .map((node) => node.children[0].textContent),
    ['Goal', 'Acceptance criteria', 'Constraints', 'Deferred runtime checks'],
  );
  assert.equal(all(taskPanel).filter((node) => node.textContent === taskView.draft.goal).length, 1);
  assert.equal(
    all(taskPanel).find((node) => node.textContent === taskView.draft.goal).tagName,
    'div',
  );
  const context = all(taskPanel).find((node) => node.csKey === 'task-context:task-preview');
  assert.ok(all(context).some((node) => node.textContent === 'Original error log'));
  assert.ok(all(context).some((node) => node.textContent === 'project/src/main.py'));
  const source = all(taskPanel).find((node) => node.csKey === 'task-source:task-preview');
  assert.equal(source.querySelector('pre').textContent, taskView.task.text);
  assert.equal(
    all(folds[1]).find((node) => node.textContent === taskView.requirements[0].text).tagName,
    'div',
  );
  folds[0].open = true;
  folds[1].open = true;
  context.open = true;
  app.render({
    ...taskView,
    requirements: [...taskView.requirements, { id: 'R2', text: 'New criterion' }],
  });
  for (const key of ['task', 'task-requirements', 'task-context'])
    assert.equal(all(nodes.chat).find((node) => node.csKey === key + ':task-preview').open, true);
  app.render({ ...taskView, id: 'another-task' });
  assert.ok(
    all(nodes.chat)
      .filter((node) => node.csKey?.startsWith('task'))
      .every((node) => !node.open),
  );
  app.render({
    ...taskView,
    id: 'legacy-task',
    draft: null,
    requirements: [],
    task: { text: 'Legacy task text', truncated: true },
  });
  assert.ok(
    all(nodes.chat).some(
      (node) => node.textContent === 'Only the end of the source file is shown.',
    ),
  );
  assert.equal(
    all(nodes.chat).find((node) => node.tagName === 'pre').textContent,
    'Legacy task text',
  );
  assert.ok(!all(nodes.chat).some((node) => node.textContent === 'Requirement IDs'));
  console.log(
    'Task preview: structured text, collapsed IDs, historical context, source fallback and polling passed.',
  );

  const sshCard = stages.executionCard({
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
      node.textContent.includes('sudo -k /usr/local/bin/taskrail-executor-approve ticket-123'),
    ),
  );
  assert.ok(
    all(sshCard).some(
      (node) => node.tagName === 'pre' && node.textContent === '<script>literal</script>',
    ),
  );
  assert.equal(all(sshCard).filter((node) => node.tagName === 'button').length, 0);
  console.log('SSH request display is text-only and cannot approve actions.');

  assert.equal(dom.durationLabel(2637.3), '43 min 57 s');
  assert.equal(dom.durationLabel(578.6), '9 min 38 s');
  assert.equal(dom.durationLabel(3600), '1 h 0 min 0 s');
  assert.equal(dom.durationLabel(59.9), '59 s');
  assert.equal(dom.durationLabel(NaN), 'Unavailable');

  assert.equal(
    stages.stageClockLabel(
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
    stages.stageClockLabel(
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
    stages.stageClockLabel({
      role: 'planner',
      status: 'RESULT_VALID',
      elapsed_seconds: 305,
      budget: { timeout: 3600 },
    }),
    'planner · 5 min 5 s / 1 h',
  );
  assert.doesNotMatch(script, /Remaining launches:|Attempt time limit:/);

  const decisionCard = app.approvalCard({
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
  const decisions = [];
  const savedFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    if (options?.body) decisions.push(JSON.parse(options.body));
    return { ok: true, json: async () => ({ token: 'token' }) };
  };
  nodes.connection = new Node('div');
  state.composing = true;
  all(decisionCard).find((n) => n.type === 'checkbox').checked = true;
  all(decisionCard).find((n) => n.className === 'approval-alternative').blur = () => {};
  await all(decisionCard)
    .find((n) => n.textContent === 'Allow')
    .onclick();
  state.composing = false;
  globalThis.fetch = savedFetch;
  assert.equal(nodes.connection.textContent, '');
  assert.equal(decisions[0].allow_all, true);
  assert.equal(decisions[0].decision, 'allow');
  const installCard = app.approvalCard({
    ticket: 'install-ticket',
    request: { argv: ['missing-tool'], notice: 'missing-tool is not installed' },
  });
  assert.ok(
    all(installCard).some(
      (n) => n.className === 'approval-notice' && n.textContent === 'missing-tool is not installed',
    ),
  );
  const waitingStage = {
    ...stage,
    status: 'WAITING_APPROVAL',
    elapsed_seconds: 50,
    paused_seconds: 7200,
    budget: { timeout: 3600 },
  };
  assert.equal(
    stages.stageClockLabel(waitingStage, Date.now()),
    'reviewer · 50 s / 1 h · Waiting for approval',
  );
  assert.equal(
    stages.stageClockLabel(waitingStage, Date.now() + 86400000),
    stages.stageClockLabel(waitingStage, Date.now()),
  );
  assert.ok(!script.includes('High cumulative token usage'));
  console.log('Approval controls and paused stage timer passed.');

  const analytics = await load('analytics');
  nodes.chat = new Node('div');
  for (const name of ['composer', 'followup-panel', 'monitor']) nodes[name] = new Node('div');
  globalThis.fetch = async () => ({
    ok: true,
    json: async () => ({
      runs: {
        count: 2,
        succeeded: 1,
        success_rate: 0.5,
        statuses: { TIMEOUT: 1 },
        elapsed_seconds: 3,
        tokens: 9,
        continuations: 0,
      },
      models: {
        'p/m': {
          attempts: 2,
          failed: 1,
          format_repairs: 1,
          recoveries: 0,
          tokens: 9,
          elapsed_seconds: 3,
        },
      },
      stages: {},
    }),
  });
  await analytics.showAnalytics();
  assert.ok(all(nodes.chat).some((n) => n.textContent === '50%'));
  assert.ok(all(nodes.chat).some((n) => n.textContent === 'Timed out: 1'));
  assert.ok(all(nodes.chat).some((n) => n.textContent === 'p/m'));
  console.log('Analytics view passed.');
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
