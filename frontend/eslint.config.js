import js from '@eslint/js';
import globals from 'globals';

export default [
  js.configs.recommended,
  {
    files: ['public/js/**/*.js'],
    languageOptions: { globals: globals.browser },
  },
  {
    files: ['tests/**/*.js', '*.config.js'],
    languageOptions: { globals: globals.node },
  },
  {
    rules: {
      'no-unused-vars': 'error',
      eqeqeq: 'error',
      'prefer-const': 'error',
    },
  },
];
