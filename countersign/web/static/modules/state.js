// Mutable UI state shared by the dashboard modules.
export const state = {
  pointerSelecting: false,
  actionPending: false,
  selected: '',
  runs: [],
  last: '',
  composing: false,
  sessionToken: null,
  currentRun: null,
  serverClockOffset: 0,
  composerContext: {},
  resumeNote: '',
};

try {
  state.selected = decodeURIComponent(location.hash.slice(1));
} catch {
  state.selected = '';
}

// Keep DOM nodes stable throughout a drag and while copied text remains selected.
export function preserveSelection() {
  return (
    state.pointerSelecting ||
    ['approval-alternative', 'resume-note'].includes(document.activeElement?.className) ||
    Boolean(document.getSelection?.()?.isCollapsed === false)
  );
}
