import { badge, detail, durationLabel, el, list, names, timeLabel, timeNode } from './dom.js';
import { preserveSelection, state } from './state.js';

export function messageCard(message) {
  const node = el('div', undefined, 'message');
  const header = el('div', undefined, 'message-header');
  header.append(timeNode(message.timestamp));
  node.append(header, el('div', message.text, 'text'));
  return node;
}
export function renderPlan(parent, steps) {
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
export function renderCoverage(parent, entries) {
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
  if (Number.isFinite(limit)) {
    label += ' / ' + durationLabel(limit).replace(' h 0 min 0 s', ' h');
    if (running && Number.isFinite(elapsed))
      label +=
        ' · ' + (elapsed < limit ? durationLabel(limit - elapsed) + ' left' : 'Timeout pending');
  }
  if (stage.status === 'WAITING_APPROVAL') label += ' · Waiting for approval';
  return label;
}
export function tickStageTimers() {
  if (preserveSelection()) return;
  for (const node of document.querySelectorAll('.stage-clock'))
    node.textContent = stageClockLabel(node.csStage, Date.now() + state.serverClockOffset);
}
export function stageCard(stage) {
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
