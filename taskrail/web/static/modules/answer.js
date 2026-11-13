// Present research prose using text nodes. Model output never becomes HTML.
import { el } from './dom.js';

function inline(parent, text) {
  for (const part of text.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/u)) {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4)
      parent.append(el('strong', part.slice(2, -2)));
    else if (part.startsWith('`') && part.endsWith('`') && part.length > 2)
      parent.append(el('code', part.slice(1, -1)));
    else if (part) parent.append(el('span', part));
  }
}

export function answerContent(text) {
  const body = el('div', undefined, 'answer-text');
  let block;
  let fence = '';
  for (const line of text.split(/\r?\n/u)) {
    const marker = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/u);
    if (fence) {
      if (marker && marker[1].startsWith(fence) && !marker[2].trim()) {
        fence = '';
        block = null;
      } else block.textContent += line + '\n';
      continue;
    }
    if (marker) {
      fence = marker[1];
      block = el('pre');
      body.append(block);
      continue;
    }
    const heading = line.match(/^ {0,3}(#{1,6})\s+(.+)/u);
    const item = line.match(/^\s*([-+*]|\d+[.)])\s+(.+)/u);
    if (heading) {
      const title = el('h' + Math.min(Math.max(2 + heading[1].length, 4), 6));
      inline(title, heading[2]);
      body.append(title);
      block = null;
    } else if (item) {
      const tag = /^\d/u.test(item[1]) ? 'ol' : 'ul';
      if (block?.tagName.toLowerCase() !== tag) {
        block = el(tag);
        if (tag === 'ol') block.start = Number.parseInt(item[1], 10);
        body.append(block);
      }
      const bullet = el('li');
      inline(bullet, item[2]);
      block.append(bullet);
    } else if (line.trim()) {
      if (block?.tagName.toLowerCase() !== 'p') {
        block = el('p');
        body.append(block);
      } else block.append(el('span', '\n'));
      inline(block, line);
    } else block = null;
  }
  return body;
}

export function answerCard(text, goal) {
  const section = el('section', undefined, 'reviewed-answer');
  if (goal) section.append(el('h3', 'Question'), el('p', goal, 'text'));
  section.append(el('h3', 'Answer'), answerContent(text));
  return section;
}
