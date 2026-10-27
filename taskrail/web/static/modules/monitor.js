import { detail, durationLabel, el } from './dom.js';
import { preserveSelection } from './state.js';

export function renderMonitor(data) {
  if (preserveSelection()) return;
  const panel = document.getElementById('monitor');
  const expanded = new Set(
    [...panel.querySelectorAll('details')].filter((node) => node.open).map((node) => node.csKey),
  );
  const panelScroll = panel.scrollTop;
  panel.replaceChildren(el('h2', 'Monitoring'));
  const rows = data.stages.filter((s) => s.telemetry && s.mode !== 'builtin');
  const sums = { input: 0, output: 0, reasoning: 0, cache_read: 0, cache_write: 0, total: 0 };
  let calls = 0,
    errors = 0,
    repeats = 0,
    reported = 0,
    steps = 0;
  for (const row of rows) {
    const t = row.telemetry;
    for (const key of Object.keys(sums)) sums[key] += t.tokens[key] || 0;
    calls += t.tool_calls;
    errors += t.tool_errors;
    repeats += t.repeated_reads;
    reported += t.usage_steps;
    steps += t.model_steps;
  }
  const fmt = (value) =>
    typeof value === 'number'
      ? value.toLocaleString('en-GB', { maximumFractionDigits: 1 })
      : 'Unavailable';
  const metric = (label, value) => {
    const line = el('div', undefined, 'metric');
    line.append(el('span', label), el('strong', value));
    panel.append(line);
  };
  const end =
    data.finished_at ||
    (data.status === 'RUNNING' ? data.server_time : data.stages.at(-1)?.finished_at);
  const wall =
    data.started_at && end ? Math.max(0, (new Date(end) - new Date(data.started_at)) / 1000) : null;
  metric('Wall time (incl. pauses)', wall === null ? 'Unavailable' : durationLabel(wall));
  const active = data.stages.reduce(
    (total, s) =>
      total +
      (typeof s.elapsed_seconds === 'number'
        ? s.elapsed_seconds
        : s.status === 'RUNNING' && s.started_at
          ? Math.max(0, (new Date(data.server_time) - new Date(s.started_at)) / 1000)
          : 0),
    0,
  );
  metric('Stage execution time', durationLabel(active));
  metric('Observed tokens', reported ? fmt(sums.total) : 'Not reported yet');
  for (const [key, label] of [
    ['input', 'Input (reported)'],
    ['output', 'Output (reported)'],
    ['cache_read', 'Cache read'],
    ['cache_write', 'Cache write'],
    ['reasoning', 'Reasoning (reported)'],
  ])
    metric(label, reported ? fmt(sums[key]) : 'Unavailable');
  metric('Model steps / usage records', fmt(steps) + ' / ' + fmt(reported));
  metric('Tool calls / errors', fmt(calls) + ' / ' + fmt(errors));
  metric('Repeated identical reads', fmt(repeats));
  const retries = rows.filter((r, i) => rows.slice(0, i).some((p) => p.stage === r.stage));
  metric('Repeat stage attempts', fmt(retries.length));
  metric(
    'Tokens in repeat attempts',
    fmt(retries.reduce((n, r) => n + r.telemetry.tokens.total, 0)),
  );
  const failed = rows.filter((r) => /ERROR|BLOCKED|FAIL|INVALID|TIMEOUT/.test(r.status));
  metric(
    'Tokens in failed attempts',
    fmt(failed.reduce((n, r) => n + r.telemetry.tokens.total, 0)),
  );
  const limit = data.monitoring?.max_observed_tokens || 0;
  metric('Observed-token limit', limit ? fmt(limit) : 'Not set');
  if (repeats > 2)
    panel.append(
      el(
        'p',
        'Repeated reads detected. Narrow the task entry points or inspect whether research is revisiting the same evidence.',
        'hint',
      ),
    );
  panel.append(
    el(
      'p',
      'Usage updates on reported step completions. In-flight or interrupted usage may be missing. Cumulative tokens are not context size. Cache/reasoning categories may overlap provider totals.',
      'hint',
    ),
  );
  panel.append(el('h3', 'By stage'));
  for (const row of rows) {
    const t = row.telemetry,
      box = el('div', undefined, 'metric-stage');
    box.append(
      el('strong', row.directory),
      el(
        'p',
        (t.usage_steps ? fmt(t.tokens.total) : 'Unreported') +
          ' tokens · ' +
          fmt(t.tool_calls) +
          ' tools',
        'muted',
      ),
    );
    box.append(
      el(
        'small',
        'Input ' +
          fmt(t.tokens.input) +
          ' · output ' +
          fmt(t.tokens.output) +
          ' · cache ' +
          fmt(t.tokens.cache_read),
      ),
    );
    const bar = el('div', undefined, 'token-bar');
    bar.style.width = (sums.total ? (100 * t.tokens.total) / sums.total : 0) + '%';
    box.append(bar);
    const more = detail(
      box,
      'More metrics',
      JSON.stringify(
        {
          model: row.model,
          tokens: t.tokens,
          last_reported_input: t.last_input,
          peak_reported_input: t.peak_input,
          reported_cost_unverified: t.reported_cost,
          usage_coverage: t.usage_coverage,
        },
        null,
        2,
      ),
    );
    more.csKey = row.directory;
    more.open = expanded.has(row.directory);
    panel.append(box);
  }
  panel.scrollTop = panelScroll;
}
