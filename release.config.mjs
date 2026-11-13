import { createRequire } from 'node:module'

const require = createRequire(new URL('./evals/model-fit/package.json', import.meta.url))
const preset = require.resolve('conventional-changelog-conventionalcommits')

export default {
  branches: ['stable', { name: 'master', prerelease: 'alpha', channel: 'alpha' }],
  plugins: [
    ['@semantic-release/commit-analyzer', { config: preset }],
    ['@semantic-release/release-notes-generator', { config: preset }],
    ['@semantic-release/exec', {
      prepareCmd: 'bash .github/release/prepare.sh <%= nextRelease.version %>',
      successCmd: 'bash .github/release/promote-alpha.sh <%= nextRelease.gitTag %>',
    }],
    ['@semantic-release/git', {
      assets: [
        '.codex-plugin/plugin.json',
        'plugin.json',
        'pyproject.toml',
        'uv.lock',
        'evals/model-fit/uv.lock',
      ],
      message: 'chore(release): <%= nextRelease.version %> [skip ci]',
    }],
    ['@semantic-release/github', {
      assets: ['dist/vector-prime.zip', 'dist/vector-prime-guidance.zip'],
      successComment: false,
      failComment: false,
      releasedLabels: false,
    }],
  ],
}
