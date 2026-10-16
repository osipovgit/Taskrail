import js from '@eslint/js';
import globals from 'globals';

export default [
  { ignores: ['build/**', 'node_modules/**'] },
  js.configs.recommended,
  {
    files: ['countersign/web/static/*.js'],
    languageOptions: { sourceType: 'script', globals: globals.browser },
  },
  { files: ['tests/*.cjs'], languageOptions: { sourceType: 'commonjs', globals: globals.node } },
  { rules: { eqeqeq: ['error', 'always'], 'no-var': 'error', 'prefer-const': 'error' } },
];
