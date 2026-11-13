import { loop } from './windows.mjs';
import prompts from '../../core/prompt-texts.json' with { type: 'json' };

function* calls(messages) {
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (message.role === 'user') yield { tool: 'user' };
    for (let j = message.content.length - 1; j >= 0; j--) {
      const part = message.content[j];
      if (part.type === 'tool-result') {
        yield {
          id: part.id,
          tool: part.name,
          output: part.result.type === 'text' && part.result.value,
        };
      }
    }
  }
}

export default {
  id: 'taskrail.read-feedback',
  async setup(ctx) {
    await ctx.session.hook('context', (event) => {
      if (event.system.some((part) => part.text === prompts['reading.loop'])) return;
      if (loop(calls(event.messages)))
        event.system.push({ type: 'text', text: prompts['reading.loop'] });
    });
  },
};
