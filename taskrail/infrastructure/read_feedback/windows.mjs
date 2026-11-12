// Examine at most three recent windows against the reads still in the model's context.
// The third determines whether the model already received advice for this streak.
const header =
  /^(?:<path>([^\n]+)<\/path>\r?\n<type>file<\/type>\r?\n<content>(?:\r?\n)?|Read file ([^\n]+), lines \d+-\d+\r?\n)/;
const clipped = /\.\.\. \(line truncated to \d+ chars\)$/;

function windowText(output, match) {
  const rows = new Map();
  let partial = false;
  for (const line of output.slice(match[0].length).split('\n')) {
    const row = /^(\d+)(?:: ?|\| )(.*)$/.exec(line);
    if (!row) break;
    if (clipped.test(row[2])) partial = true;
    else rows.set(row[1], row[2]);
  }
  return { rows, partial };
}

function compare(target, previous) {
  for (const [number, text] of previous.rows) {
    if (!target.rows.has(number)) continue;
    if (target.rows.get(number) !== text) {
      target.fresh = true;
      return;
    }
    target.rows.delete(number);
  }
}

export function loop(calls) {
  const targets = [];
  const seen = new Set();
  let collecting = true;
  for (const { id, tool, output } of calls) {
    if (id && seen.has(id)) continue;
    seen.add(id);
    const match = tool === 'read' && typeof output === 'string' && header.exec(output);
    if (!match) {
      if (targets.length < 2 || !['user', 'read', 'grep', 'glob'].includes(tool)) break;
      collecting = false;
      continue;
    }
    const path = match[1] ?? match[2];
    const pending = targets.filter((t) => !t.fresh && t.path === path && t.rows.size);
    if (!collecting && !pending.length) continue;
    const read = windowText(output, match);
    for (const target of pending) compare(target, read);
    if (collecting) {
      if (read.partial || !read.rows.size) collecting = false;
      else targets.push({ path, rows: read.rows, fresh: false });
      if (!collecting && targets.length < 2) break;
      collecting = collecting && targets.length < 3;
    }
    if (targets.slice(0, 2).some((t) => t.fresh)) return false;
    if (!collecting && targets.every((t) => t.fresh || !t.rows.size)) break;
  }
  const repeated = (t) => t && !t.fresh && !t.rows.size;
  return Boolean(repeated(targets[0]) && repeated(targets[1]) && !repeated(targets[2]));
}
