import { badge, detail, durationLabel, el, list, names, timeLabel, timeNode } from './dom.js';
import { preserveSelection, state } from './state.js';

export function messageCard(message) {
  const node = el('div', undefined, 'message');
  const header = el('div', undefined, 'message-header');
  header.append(timeNode(message.timestamp));
  node.append(header, el('div', message.text, 'text'));
  return node;
}
// Requirement ID -> its request label (R1, R2, ...) and full text.
function requirementNames(requirements) {
  return new Map(
    (requirements || []).map((entry, index) => [
      entry.id,
      { label: 'R' + (index + 1), text: entry.text },
    ]),
  );
}
function requirementLine(id, named) {
  const entry = named.get(id);
  return entry ? entry.label + ': ' + entry.text : id;
}
export function renderPlan(parent, steps, requirements) {
  if (!steps?.length) return;
  const named = requirementNames(requirements);
  parent.append(el('h3', 'Plan'));
  for (const step of steps) {
    const box = el('div', undefined, 'message');
    box.append(el('strong', step.id + ' · ' + step.action));
    list(box, 'Files', step.files);
    list(
      box,
      'Criteria',
      step.criteria?.map((id) => requirementLine(id, named)),
    );
    list(box, 'Dependencies', step.depends_on);
    list(box, 'Checks', step.checks);
    list(box, 'Required checks', step.required_checks);
    list(box, 'Not ToDo', step.not_todo);
    parent.append(box);
  }
}
const outcomeLabel = (outcome) =>
  outcome.charAt(0).toUpperCase() + outcome.slice(1).replaceAll('_', ' ');
// Collapsed: each requirement's label, outcome and full text; a routine assessment adds nothing.
export function renderCoverage(parent, entries, requirements) {
  if (!entries?.length) return;
  const named = requirementNames(requirements);
  const counts = {};
  for (const entry of entries) counts[entry.outcome] = (counts[entry.outcome] || 0) + 1;
  const tally = Object.entries(counts)
    .map(([outcome, count]) => count + ' ' + outcomeLabel(outcome).toLowerCase())
    .join(', ');
  const fold = el('details', undefined, 'coverage');
  fold.append(el('summary', 'Requirement coverage · ' + tally));
  for (const entry of entries) {
    const box = el('div', undefined, 'message');
    const name = named.get(entry.id);
    box.append(el('strong', (name?.label || entry.id) + ' · ' + outcomeLabel(entry.outcome)));
    if (name) box.append(el('p', name.text, 'text'));
    if (entry.explanation && !entry.explanation.startsWith('Agent assessment:'))
      box.append(el('p', entry.explanation, 'text muted'));
    if (entry.evidence_ids?.length)
      box.append(el('small', 'Evidence: ' + entry.evidence_ids.join(', ')));
    fold.append(box);
  }
  parent.append(fold);
}
export function stageProvenance(parent, stage) {
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
export function stageClockLabel(stage, now = Date.now()) {
  const limit = stage.budget?.timeout;
  const running = stage.status === 'RUNNING';
  const started = new Date(stage.started_at).getTime();
  const elapsed =
    running && Number.isFinite(started)
      ? Math.max(0, (now - started) / 1000 - (stage.paused_seconds || 0))
      : stage.elapsed_seconds;
  let label = stage.role || 'System';
  if (Number.isFinite(elapsed)) label += ' · ' + durationLabel(elapsed);
  if (Number.isFinite(limit)) label += ' / ' + durationLabel(limit).replace(' h 0 min 0 s', ' h');
  if (stage.status === 'WAITING_APPROVAL') label += ' · Waiting for approval';
  return label;
}
// Rough size of the text a session received: about four characters per token.
const CHARACTERS_PER_TOKEN = 4;
// The session's context against its model's window: the input the provider reported for
// the latest step plus what arrived since, or, without reports, the request and every
// text and tool call. '≈' marks an estimate; a finished stage shows its peak.
export function contextUse(stage) {
  const budget = stage.context_budget || {};
  const telemetry = stage.telemetry || {};
  const running = stage.status === 'RUNNING';
  const reported = running ? telemetry.last_input : telemetry.peak_input;
  if (Number.isFinite(reported)) {
    const pending = running ? telemetry.unreported_characters || 0 : 0;
    return { tokens: reported + pending / CHARACTERS_PER_TOKEN, estimated: pending > 0 };
  }
  if (!Number.isFinite(telemetry.observed_characters) || !Number.isFinite(budget.request_bytes))
    return null;
  const sent = budget.request_bytes + (budget.role_bytes || 0) + telemetry.observed_characters;
  return { tokens: sent / CHARACTERS_PER_TOKEN + (budget.framing_tokens || 0), estimated: true };
}
export function stageContextLabel(stage) {
  const capacity = stage.context_budget?.input_capacity_tokens;
  const use = contextUse(stage);
  if (!Number.isFinite(capacity) || capacity <= 0 || !use) return '';
  const tokens = Math.round(use.tokens);
  const about = use.estimated ? '≈' : '';
  const prefix = stage.status === 'RUNNING' ? 'Context ' : 'Peak context ';
  return (
    prefix +
    about +
    Math.round((100 * tokens) / capacity) +
    '% · ' +
    about +
    tokens.toLocaleString('en-GB') +
    ' of ' +
    capacity.toLocaleString('en-GB') +
    ' tokens'
  );
}
export function tickStageTimers() {
  if (preserveSelection()) return;
  for (const node of document.querySelectorAll('.stage-clock'))
    node.textContent = stageClockLabel(node.csStage, Date.now() + state.serverClockOffset);
}
// Identical warnings collapse into one line with their count and the files they name.
export function warningLines(warnings) {
  const groups = new Map();
  for (const w of warnings || []) {
    const text =
      w.resolution ||
      (w.input?.filePath || '') + ': ' + w.error + ' → subsequent full read confirmed';
    const group = groups.get(text) || { count: 0, files: [] };
    const file = w.resolution && w.input?.filePath;
    if (file && !group.files.includes(file)) group.files.push(file);
    group.count += 1;
    groups.set(text, group);
  }
  return [...groups].map(
    ([text, group]) =>
      (group.count > 1 ? group.count + ' × ' : '') +
      text +
      (group.files.length ? ' Files: ' + group.files.join(', ') : ''),
  );
}

export function stageCard(stage, requirements = []) {
  const card = el('section', undefined, stage.status === 'RUNNING' ? 'running' : '');
  const heading = el('div', undefined, 'stage-header');
  const meta = el('div', undefined, 'stage-meta muted');
  const timer = el(
    'span',
    stageClockLabel(stage, Date.now() + state.serverClockOffset),
    'stage-clock',
  );
  timer.csStage = stage;
  meta.append(timer);
  const contextUse = stageContextLabel(stage);
  if (contextUse) meta.append(el('span', contextUse, 'stage-context'));
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
    renderPlan(card, result.steps, requirements);
    renderCoverage(card, result.coverage, requirements);
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
  list(card, 'Warnings', warningLines(stage.warnings));
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
    const log = el('details', undefined, 'activity-log');
    const summary = el('summary', 'Activity log · ' + stage.directory);
    const close = el('button', 'Close log', 'activity-log-close');
    close.type = 'button';
    close.onclick = (event) => {
      event.preventDefault();
      event.stopPropagation();
      log.open = false;
      summary.scrollIntoView?.({ block: 'nearest' });
      summary.focus?.();
    };
    summary.append(close);
    log.append(summary);
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

export function executionCard(job) {
  const card = el('section', undefined, 'card');
  const build = job.request?.jenkins;
  card.append(el('h3', (build ? 'Jenkins build · ' : 'SSH action · ') + job.status));
  const reason = (job.action || job.request?.action || build)?.reason;
  card.append(el('p', reason || 'Submitting request'));
  if (job.id) {
    card.append(el('p', 'Ticket: ' + job.id, 'muted'));
    if (job.status === 'PENDING_APPROVAL') {
      card.append(
        el('p', 'Review and approve in your terminal. The UI cannot grant server access.'),
      );
      card.append(el('pre', 'sudo -k /usr/local/bin/taskrail-executor-approve ' + job.id));
    }
  }
  if (build) {
    card.append(el('p', 'Jenkins job: ' + build.server + ' / ' + build.job));
    card.append(el('pre', JSON.stringify(build.parameters, null, 2)));
  }
  const action = build ? null : job.action || job.request?.action;
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
