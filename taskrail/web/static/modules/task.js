import { el } from './dom.js';

function fold(title, key, hint) {
  const node = el('details', undefined, 'task-fold');
  node.csKey = key;
  const summary = el('summary', undefined, 'task-fold-summary');
  summary.append(el('span', title, 'task-fold-title'));
  if (hint) summary.append(el('span', hint, 'task-fold-hint'));
  node.append(summary);
  return node;
}

function field(parent, title, value) {
  if (!value) return;
  const block = el('div', undefined, 'task-field');
  block.append(el('h4', title), el('div', value, 'text'));
  parent.append(block);
}

function originalTask(data) {
  const draft = data.draft;
  const original = fold('Original task', `task:${data.id}`, 'As submitted');
  const body = el('div', undefined, 'task-fold-body');
  if (draft?.goal) {
    field(body, 'Goal', draft.goal);
    field(body, 'Acceptance criteria', draft.criteria);
    field(body, 'Constraints', draft.constraints);
    field(body, 'Deferred runtime checks', draft.verification);
    if (draft.current_behavior || draft.entry_points) {
      const context = fold('Initial context', `task-context:${data.id}`);
      const contents = el('div', undefined, 'task-fold-body');
      contents.append(
        el('p', 'Provided at submission; may no longer describe the project.', 'muted'),
      );
      field(contents, 'Starting behavior and logs', draft.current_behavior);
      field(contents, 'Suggested starting files', draft.entry_points);
      context.append(contents);
      body.append(context);
    }
  }
  if (data.task?.text) {
    const source = fold('Source file', `task-source:${data.id}`, 'Original text');
    const contents = el('div', undefined, 'task-fold-body');
    if (data.task.truncated)
      contents.append(el('p', 'Only the end of the source file is shown.', 'muted'));
    contents.append(el('pre', data.task.text));
    source.append(contents);
    if (draft?.goal) body.append(source);
    else {
      body.append(el('p', 'A structured task preview is unavailable for this run.', 'muted'));
      body.append(contents);
    }
  }
  original.append(body);
  return original;
}

export function taskSection(data) {
  const task = el('section', undefined, 'task-overview');
  task.append(el('h3', 'Task'), originalTask(data));
  const requirements = data.requirements || [];
  if (requirements.length) {
    const ids = fold(
      'Requirement IDs',
      `task-requirements:${data.id}`,
      String(requirements.length),
    );
    const items = el('ul', undefined, 'task-requirements');
    for (const entry of requirements) {
      const item = el('li', undefined, 'task-requirement');
      item.append(el('span', entry.id, 'task-requirement-id'), el('div', entry.text, 'text'));
      items.append(item);
    }
    ids.append(items);
    task.append(ids);
  }
  const roots = Object.entries(data.roots || {});
  if (roots.length) {
    const directories = el('dl', undefined, 'task-roots');
    for (const [alias, path] of roots) {
      const row = el('div', undefined, 'task-root');
      row.append(el('dt', alias), el('dd', path));
      directories.append(row);
    }
    task.append(el('h4', 'Project directories', 'task-roots-title'), directories);
  }
  return task;
}
