import assert from 'node:assert/strict';
import test from 'node:test';
import v1 from '../taskrail/infrastructure/read_feedback/v1.mjs';
import v2 from '../taskrail/infrastructure/read_feedback/server.js';
import prompts from '../taskrail/core/prompt-texts.json' with { type: 'json' };

const hint = prompts['reading.loop'];
const read = (path, start = 1, rows = ['one', 'two']) => ({ path, start, rows });
const a = read('/project/A');
const b = read('/project/B');

function format(call, version) {
  const body = call.rows.map((s, i) => i + call.start + ': ' + s).join('\n');
  if (version === 1)
    return (
      '<path>' + call.path + '</path>\n<type>file</type>\n<content>\n' + body + '\n\n</content>'
    );
  return (
    'Read file ' +
    call.path +
    ', lines ' +
    call.start +
    '-' +
    (call.start + call.rows.length - 1) +
    '\n' +
    body
  );
}

async function received(version, sequence) {
  const calls = sequence.map((call, i) => ({
    id: call.id ?? String(i),
    tool: call.tool ?? 'read',
    output: call.path ? format(call, version) : '',
    status: call.status ?? 'completed',
  }));
  if (version === 1) {
    const hook = (await v1())['experimental.chat.messages.transform'];
    const messages = calls.map(({ id, tool, output, status }) => ({
      info: { role: 'assistant' },
      parts: [{ type: 'tool', callID: id, tool, state: { status, output } }],
    }));
    const originals = messages.map((m) => m.parts[0]);
    await hook({}, { messages });
    await hook({}, { messages });
    assert.ok(messages.at(-1).parts[0].state.output.split(hint).length <= 2);
    assert.deepEqual(
      originals.map((p) => p.state.output),
      calls.map((c) => c.output),
    );
    return messages.at(-1).parts[0].state.output.endsWith(hint);
  }
  let context;
  await v2.setup({
    session: {
      hook: (name, handler) => {
        assert.equal(name, 'context');
        context = handler;
      },
    },
  });
  const event = {
    system: [],
    messages: calls.map(({ id, tool, output, status }) => ({
      role: 'tool',
      content: [
        {
          type: 'tool-result',
          name: tool,
          id,
          result: { type: status === 'error' ? 'error' : 'text', value: output },
        },
      ],
    })),
  };
  await context(event);
  await context(event);
  assert.ok(event.system.length <= 1);
  return event.system.some((p) => p.text === hint);
}

for (const version of [1, 2]) {
  test(
    'opencode ' + version + ' delivers one hint for A → B → A → B, including overlapping ranges',
    async () => {
      const sequence = [a, b, read(a.path, 2, ['two']), read(b.path, 1, ['one'])];
      assert.equal(await received(version, sequence.slice(0, 3)), false);
      assert.equal(await received(version, sequence), true);
      assert.equal(await received(version, [a, b, a, b]), true);
      // A later wider read may reuse lines delivered by separate earlier windows.
      assert.equal(
        await received(version, [read(a.path, 1, ['one']), read(a.path, 2, ['two']), b, a, b]),
        true,
      );
      assert.equal(await received(version, [...sequence, a]), false);
      assert.equal(await received(version, [a, b]), false); // Fresh reviewer session.
    },
  );
  test(
    'opencode ' + version + ' respects content, distinct calls and incomplete observations',
    async () => {
      for (const tail of [
        read(b.path, 2, ['two', 'new']),
        read(b.path, 2, ['changed']),
        read(b.path, 1, ['one... (line truncated to 2000 chars)']),
        { ...b, status: 'error' },
        { ...b, id: '1' },
      ])
        assert.equal(await received(version, [a, b, a, tail]), false);
      assert.equal(await received(version, [a, b, { tool: 'edit' }, a, b]), false);
      const clipped = read(a.path, 1, ['one... (line truncated to 2000 chars)']);
      assert.equal(await received(version, [clipped, b, a, b]), false);
      assert.equal(await received(version, [a, b, a, b, { tool: 'grep' }]), false);
      assert.equal(await received(version, [a, b, a, b, read('/new'), a, b]), true);
    },
  );
}
