// Entry point: wire the page to the dashboard modules.
import {
  addRoot,
  closeComposer,
  menu,
  openComposer,
  refresh,
  refreshRun,
  showRun,
  submitFollowup,
  submitTask,
} from './modules/app.js';
import { showAnalytics } from './modules/analytics.js';
import { showError } from './modules/dom.js';
import { tickStageTimers } from './modules/stages.js';
import { state } from './modules/state.js';

document.getElementById('new-task').onclick = () => openComposer();
document.getElementById('show-analytics').onclick = showAnalytics;
document.getElementById('cancel-task').onclick = () => {
  closeComposer();
  refreshRun().catch(showError);
};
document.getElementById('add-root').onclick = () => addRoot();
document.getElementById('task-form').onsubmit = submitTask;
document.getElementById('followup-form').onsubmit = submitFollowup;
document.getElementById('filter').oninput = menu;
// Back/forward and edited addresses change only the hash; follow them to the named run.
function hashRun() {
  try {
    return decodeURIComponent(location.hash.slice(1));
  } catch {
    return '';
  }
}
window.addEventListener('hashchange', () => {
  const id = hashRun();
  if (!id || id === state.selected) return;
  closeComposer();
  showRun(id).catch(showError);
});
addRoot('project');
refresh();

// Keep DOM nodes stable throughout a drag and while copied text remains selected.
document.addEventListener('pointerdown', (event) => {
  if (event.button === 0) state.pointerSelecting = true;
});
for (const name of ['pointerup', 'pointercancel']) {
  document.addEventListener(name, () => {
    state.pointerSelecting = false;
  });
}
window.addEventListener('blur', () => {
  state.pointerSelecting = false;
});

setInterval(tickStageTimers, 1000);
