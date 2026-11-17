export default {
  branches: ['stable', { name: 'master', prerelease: 'alpha', channel: 'alpha' }],
  plugins: [
    ['@semantic-release/commit-analyzer', { preset: 'conventionalcommits' }],
    ['@semantic-release/release-notes-generator', { preset: 'conventionalcommits' }],
    ['@semantic-release/exec', {
      prepareCmd: 'bash .github/release/prepare.sh <%= nextRelease.version %>',
      successCmd: 'bash .github/release/promote-alpha.sh <%= nextRelease.gitTag %>',
    }],
    ['@semantic-release/git', {
      assets: [
        '.codex-plugin/plugin.json',
        '.github/packaging/directory/plugin.json',
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
