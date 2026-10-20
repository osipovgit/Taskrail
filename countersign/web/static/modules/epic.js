// Delivery of a code change: its task runs, Jenkins validation, your confirmation and
// the server checks that run only after it.
import { badge, el } from './dom.js';

const STEP_TEXT = {
  implementing: 'Implementing',
  needs_you: 'Implementation needs you',
  validating: 'Jenkins validation',
  approval: 'A check waits for root approval',
  validation_failed: 'Jenkins validation failed',
  confirm: 'Waiting for your confirmation',
  server: 'Server checks',
  server_failed: 'Server checks failed',
  done: 'Done',
};

// A finished check run means its checks ran and were reviewed; its summary has the results.
const PHASE_LABELS = {
  NO_CHANGES_REQUIRED: 'CHECK_COMPLETED',
  READY_FOR_REVIEW: 'CHECK_COMPLETED',
  skipped: 'Skipped',
};

function openButton(run, actions) {
  const open = el('button', 'Open run');
  open.type = 'button';
  open.onclick = () => actions.open(run);
  return open;
}

function taskItem(task, delivery, actions) {
  const item = el('li');
  item.append(el('strong', task.id + ' · ' + task.title));
  if (task.status) item.append(badge(task.status));
  else item.append(el('span', task.id === delivery.next ? 'Next' : 'Not started', 'badge'));
  if (task.run) item.append(openButton(task.run, actions));
  if (task.summary) item.append(el('p', task.summary, 'muted'));
  if (!task.status) {
    const pause = el('input');
    pause.type = 'checkbox';
    pause.checked = task.pause_before;
    pause.onchange = () =>
      actions.act(pause.checked ? 'epic_pause' : 'epic_unpause', { task: task.id });
    const label = el('label', undefined, 'epic-pause');
    label.append(pause, el('span', ' Pause before this task (auto-continue waits for you)'));
    item.append(label);
  }
  return item;
}

function tasksBlock(delivery, actions) {
  const block = el('div', undefined, 'delivery-part');
  block.append(el('h4', 'Tasks · ' + delivery.progress + ' done'));
  const list = el('ol', undefined, 'epic-tasks');
  for (const task of delivery.tasks) list.append(taskItem(task, delivery, actions));
  const again = delivery.tasks.some((task) => task.id === delivery.next && task.run);
  const label = delivery.next
    ? 'Start ' + delivery.next + (again ? ' again' : '')
    : 'No task ready';
  const next = el('button', label, 'primary');
  next.type = 'button';
  next.disabled = !delivery.next;
  next.title = 'Start the next task as a new run with a brief of the earlier tasks.';
  next.onclick = () => actions.act('epic_next');
  const auto = el('input');
  auto.type = 'checkbox';
  auto.checked = delivery.auto_continue;
  auto.onchange = () => actions.act(auto.checked ? 'epic_auto_on' : 'epic_auto_off');
  const autoLabel = el('label', undefined, 'epic-auto');
  autoLabel.append(
    auto,
    el('span', ' Start the next task automatically after each successful one'),
  );
  const controls = el('div', undefined, 'run-actions');
  controls.append(next, autoLabel);
  block.append(list, controls);
  return block;
}

function phaseBlock(title, checks, record, waiting, actions) {
  const block = el('div', undefined, 'delivery-part');
  block.append(el('h4', title));
  const list = el('ul');
  for (const check of checks) list.append(el('li', check));
  block.append(list);
  if (!record) {
    block.append(el('p', waiting, 'muted'));
    return block;
  }
  const line = el('p');
  line.append(badge(PHASE_LABELS[record.status] || record.status));
  if (record.run) line.append(openButton(record.run, actions));
  block.append(line);
  if (record.summary) block.append(el('p', record.summary, 'muted'));
  return block;
}

function confirmationBlock(delivery, actions) {
  const block = el('div', undefined, 'delivery-part');
  block.append(el('h4', 'Your confirmation'));
  if (delivery.confirmed) {
    block.append(el('p', 'You confirmed these changes.', 'muted'));
    return block;
  }
  const button = el('button', 'Confirm changes', 'primary');
  button.type = 'button';
  button.disabled = delivery.step !== 'confirm';
  button.onclick = () => actions.act('confirm');
  block.append(button);
  const hint = delivery.checks.server.length
    ? 'Server checks start after you confirm; each server action still needs root approval.'
    : 'Confirm once you have reviewed the changes.';
  block.append(el('p', hint, 'muted'));
  return block;
}

export function deliverySection(delivery, actions) {
  const { checks } = delivery;
  const shown =
    delivery.tasks || checks.jenkins.length || checks.server.length || delivery.step === 'confirm';
  if (!shown && !delivery.confirmed) return null;
  const section = el('section', undefined, 'delivery');
  section.append(el('h3', 'Delivery · ' + (STEP_TEXT[delivery.step] || delivery.step)));
  if (delivery.tasks) section.append(tasksBlock(delivery, actions));
  if (checks.jenkins.length) {
    const waiting = 'Starts when the code is done.';
    const record = delivery.phases.validation;
    section.append(phaseBlock('Jenkins validation', checks.jenkins, record, waiting, actions));
  }
  if (delivery.step === 'confirm' || delivery.confirmed)
    section.append(confirmationBlock(delivery, actions));
  if (checks.server.length) {
    const waiting = 'Run after you confirm the changes; each action needs root approval.';
    const record = delivery.phases.server;
    section.append(phaseBlock('Server checks', checks.server, record, waiting, actions));
  }
  return section;
}
