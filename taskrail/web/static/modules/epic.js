// Delivery of a code change in one card: its tasks and phases as a graph, the selected
// node's run below it, and the controls for the next task and your confirmation.
import { el } from './dom.js';
import { graphLayout, graphView, nodePanel } from './graph.js';

const STEP_TEXT = {
  implementing: 'Implementing',
  needs_you: 'Implementation needs you',
  integrating: 'Integration review',
  integration_failed: 'Integration review needs you',
  correcting: 'Correcting integration findings',
  corrected: 'Correction finished; integration review pending',
  correction_failed: 'Integration correction needs you',
  validating: 'Jenkins validation',
  approval: 'A check waits for root approval',
  validation_failed: 'Jenkins validation failed',
  confirm: 'Waiting for your confirmation',
  review: 'Ready for your review',
  server: 'Server checks',
  server_failed: 'Server checks failed',
  done: 'Done',
};

function taskControls(delivery, actions) {
  const controls = el('div', undefined, 'run-actions');
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
    el('span', ' Continue tasks and bounded integration corrections automatically'),
  );
  controls.append(next, autoLabel);
  if (delivery.correction_available) {
    const correct = el('button', 'Correct integration findings', 'primary');
    correct.type = 'button';
    correct.onclick = () => actions.act('integration_correct');
    controls.append(correct);
  }
  if (['integration_failed', 'corrected', 'confirm'].includes(delivery.step)) {
    const repeat = el('button', 'Repeat integration review');
    repeat.type = 'button';
    repeat.onclick = () => actions.act('integration_review');
    controls.append(repeat);
  }
  if (delivery.corrections?.length)
    controls.append(
      el('span', 'Corrections remaining: ' + delivery.corrections_remaining, 'muted'),
    );
  return controls;
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

// actions: act(action, extra), pick(focus), focus, child (the selected run's view) and
// embed(view), which renders that run inside this card.
export function deliverySection(delivery, actions) {
  const { checks } = delivery;
  const shown =
    delivery.tasks || checks.jenkins.length || checks.server.length || delivery.step === 'confirm';
  if (!shown && !delivery.confirmed) return null;
  const section = el('section', undefined, 'delivery');
  section.append(el('h3', 'Delivery · ' + (STEP_TEXT[delivery.step] || delivery.step)));
  if (delivery.launch_error) section.append(el('p', delivery.launch_error));
  if (delivery.tasks) section.append(el('p', 'Tasks · ' + delivery.progress + ' done', 'muted'));
  const layout = graphLayout(delivery);
  if (layout.nodes.length) section.append(graphView(layout, actions.focus, actions.pick));
  if (delivery.tasks) section.append(taskControls(delivery, actions));
  if (delivery.step === 'confirm' || delivery.confirmed)
    section.append(confirmationBlock(delivery, actions));
  if (layout.nodes.length) section.append(nodePanel(layout, delivery, actions));
  return section;
}
