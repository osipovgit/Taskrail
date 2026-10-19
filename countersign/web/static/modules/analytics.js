// Totals across all runs, shown in place of a run.
import { get } from './app.js';
import { durationLabel, el, showError, statuses } from './dom.js';
import { state } from './state.js';

const COLUMNS = [
  ['attempts', 'Attempts'],
  ['failed', 'Failed'],
  ['format_repairs', 'Format repairs'],
  ['recoveries', 'Recoveries'],
  ['tokens', 'Tokens'],
  ['elapsed_seconds', 'Seconds'],
];

function table(title, groups) {
  const section = el('section');
  section.append(el('h3', title));
  const grid = el('table', undefined, 'analytics');
  const head = el('tr');
  head.append(el('th', 'Name'), ...COLUMNS.map(([, label]) => el('th', label)));
  grid.append(head);
  for (const [name, totals] of Object.entries(groups)) {
    const row = el('tr');
    row.append(el('td', name), ...COLUMNS.map(([key]) => el('td', String(totals[key] ?? 0))));
    grid.append(row);
  }
  section.append(grid);
  return section;
}

function stat(value, label) {
  const tile = el('div', undefined, 'stat');
  tile.append(el('strong', String(value)), el('span', label));
  return tile;
}

function overview(runs) {
  const section = el('section');
  section.append(el('h3', 'Runs'));
  const rate = runs.success_rate === null ? 'n/a' : Math.round(runs.success_rate * 100) + '%';
  const tiles = el('div', undefined, 'stats');
  tiles.append(
    stat(runs.count, 'runs'),
    stat(rate, 'ready or no changes'),
    stat(durationLabel(runs.elapsed_seconds), 'recorded model time'),
    stat(runs.tokens.toLocaleString('en-GB'), 'reported tokens'),
    stat(runs.continuations, 'continuations'),
  );
  section.append(tiles);
  const counts = Object.entries(runs.statuses).map(
    ([status, count]) => `${statuses[status] || status}: ${count}`,
  );
  section.append(el('p', counts.join(' · '), 'muted'));
  return section;
}

export async function showAnalytics() {
  try {
    const data = await get('/api/analytics');
    state.selected = '';
    state.composing = false;
    location.hash = '';
    document.getElementById('composer').hidden = true;
    document.getElementById('followup-panel').hidden = true;
    document
      .getElementById('monitor')
      .replaceChildren(
        el('h2', 'Monitoring'),
        el('p', 'Select a task to see live usage.', 'muted'),
      );
    const chat = document.getElementById('chat');
    chat.hidden = false;
    chat.replaceChildren(
      el('h2', 'Analytics'),
      overview(data.runs),
      table('By model', data.models),
      table('By stage', data.stages),
    );
  } catch (error) {
    showError(error);
  }
}
