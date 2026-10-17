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
    document.activeElement?.className === 'approval-alternative' ||
    Boolean(document.getSelection?.()?.isCollapsed === false)
  );
}
