import { loop } from './windows.mjs';
import prompts from '../../core/prompt-texts.json' with { type: 'json' };

function* calls(messages) {
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (message.info.role === 'user') yield { tool: 'user' };
    for (let j = message.parts.length - 1; j >= 0; j--) {
      const part = message.parts[j];
      if (part.type !== 'tool') continue;
      const state = part.state;
      const visible = state.status === 'completed' && !state.time?.compacted;
      yield { id: part.callID, tool: part.tool, output: visible && state.output };
    }
  }
}

export default async () => ({
  'experimental.chat.messages.transform': async (_, { messages }) => {
    if (!loop(calls(messages))) return;
    // Only the outgoing model context gets the hint. Keep the stored read verbatim.
    const index = messages.findLastIndex((m) => m.parts.some((p) => p.type === 'tool'));
    const message = messages[index];
    const parts = [...message.parts];
    const at = parts.findLastIndex((p) => p.type === 'tool');
    const part = parts[at];
    if (part.state.output.endsWith(prompts['reading.loop'])) return;
    parts[at] = {
      ...part,
      state: { ...part.state, output: part.state.output + '\n\n' + prompts['reading.loop'] },
    };
    messages[index] = { ...message, parts };
  },
});
