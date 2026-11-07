import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

const clinicalFeatures = ['raw', 'documents', 'sdtm', 'adam', 'tlf']
const featureBoundaryConfigs = clinicalFeatures.map((feature) => ({
  files: [`src/features/${feature}/**/*.{ts,tsx}`],
  rules: {
    'no-restricted-imports': [
      'error',
      {
        patterns: clinicalFeatures
          .filter((candidate) => candidate !== feature)
          .map((candidate) => ({
            group: [`@/features/${candidate}`, `@/features/${candidate}/**`],
            message: 'Clinical features communicate through the generated API and shared components.',
          })),
      },
    ],
  },
}))

export default tseslint.config(
  { ignores: ['dist', 'src/api/generated', 'src/routeTree.gen.ts'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': [
        'error',
        { allowConstantExport: true },
      ],
      // Honour the leading-underscore convention for intentionally unused
      // bindings (e.g. ignored callback/mutation params in test doubles),
      // matching the `noUnusedLocals`/`noUnusedParameters` behaviour of tsc.
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
        },
      ],
    },
  },
  ...featureBoundaryConfigs,
)
