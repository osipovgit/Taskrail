'use strict';

(() => {
  const key = 'taskrail-theme';
  const button = document.getElementById('theme-toggle');
  const system = window.matchMedia('(prefers-color-scheme: dark)');
  let saved = null;
  try {
    saved = localStorage.getItem(key);
  } catch {
    /* Storage may be disabled. */
  }
  let explicit = saved === 'dark' || saved === 'light';
  let current = explicit ? saved : system.matches ? 'dark' : 'light';

  function apply(theme) {
    current = theme;
    document.documentElement.dataset.theme = theme;
    button.textContent = theme === 'dark' ? 'Light theme' : 'Dark theme';
    button.setAttribute('aria-pressed', String(theme === 'dark'));
    button.setAttribute('aria-label', 'Dark theme');
  }
  apply(current);
  button.onclick = () => {
    explicit = true;
    apply(current === 'dark' ? 'light' : 'dark');
    try {
      localStorage.setItem(key, current);
    } catch {
      /* Keep selection for this page. */
    }
  };
  if (system.addEventListener) {
    system.addEventListener('change', (event) => {
      if (!explicit) apply(event.matches ? 'dark' : 'light');
    });
  }
})();
