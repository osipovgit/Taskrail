// Mutable UI state shared by the dashboard modules.
export const state = {
  pointerSelecting: false,
  actionPending: false,
  selected: '',
  // A task or phase run shown inside the selected parent's card, or a planned node key.
  focus: '',
  turn: '',
  runs: [],
  doneOpen: false,
  last: '',
  composing: false,
  sessionToken: null,
  currentRun: null,
  serverClockOffset: 0,
  composerContext: {},
  resumeNote: '',
};

// An earlier turn can carry its own task or phase focus: #discussion/focus/turn.
export function parseHash(hash) {
  try {
    const [selected = '', focus = '', turn = ''] = hash.slice(1).split('/').map(decodeURIComponent);
    return { selected, focus, turn };
  } catch {
    return { selected: '', focus: '', turn: '' };
  }
}

Object.assign(state, parseHash(location.hash));

// Keep DOM nodes stable throughout a drag and while copied text remains selected.
export function preserveSelection() {
  return (
    state.pointerSelecting ||
    ['approval-alternative', 'resume-note'].includes(document.activeElement?.className) ||
    Boolean(document.getSelection?.()?.isCollapsed === false)
  );
}
