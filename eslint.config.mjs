import js from '@eslint/js';
import globals from 'globals';

export default [
  { ignores: ['build/**', 'node_modules/**'] },
  js.configs.recommended,
  {
    files: ['taskrail/web/static/theme.js'],
    languageOptions: { sourceType: 'script', globals: globals.browser },
  },
  {
    files: ['taskrail/web/static/dashboard.js', 'taskrail/web/static/modules/*.js'],
    languageOptions: { sourceType: 'module', globals: globals.browser },
  },
  { files: ['tests/*.cjs'], languageOptions: { sourceType: 'commonjs', globals: globals.node } },
  { rules: { eqeqeq: ['error', 'always'], 'no-var': 'error', 'prefer-const': 'error' } },
];
