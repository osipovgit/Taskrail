// Tasks of a split goal: status of each task run, the next task and auto-continue.
import { badge, el } from './dom.js';

function taskItem(task, epic, actions) {
  const item = el('li');
  item.append(el('strong', task.id + ' · ' + task.title));
  if (task.status) item.append(badge(task.status));
  else item.append(el('span', task.id === epic.next ? 'Next' : 'Not started', 'badge'));
  if (task.run) {
    const open = el('button', 'Open run');
    open.type = 'button';
    open.onclick = () => actions.open(task.run);
    item.append(open);
  }
  if (task.summary) item.append(el('p', task.summary, 'muted'));
  return item;
}

export function epicSection(epic, actions) {
  const section = el('section', undefined, 'epic');
  section.append(el('h3', 'Tasks · ' + epic.progress + ' done'));
  const list = el('ol', undefined, 'epic-tasks');
  for (const task of epic.tasks) list.append(taskItem(task, epic, actions));
  const next = el('button', epic.next ? 'Start ' + epic.next : 'No task ready', 'primary');
  next.type = 'button';
  next.disabled = !epic.next;
  next.title = 'Start the next task as a new run with a brief of the earlier tasks.';
  next.onclick = () => actions.act('epic_next');
  const auto = el('input');
  auto.type = 'checkbox';
  auto.checked = epic.auto_continue;
  auto.onchange = () => actions.act(auto.checked ? 'epic_auto_on' : 'epic_auto_off');
  const label = el('label', undefined, 'epic-auto');
  label.append(auto, el('span', ' Start the next task automatically after each successful one'));
  const controls = el('div', undefined, 'run-actions');
  controls.append(next, label);
  section.append(list, controls);
  return section;
}
