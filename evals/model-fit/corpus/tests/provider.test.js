import test from 'node:test';
import assert from 'node:assert/strict';
import Adapter from '../provider.js';

const config = { mode: 'stock-control', python_provider: '/fixture/provider.py', python_env: { CODEX_HOME: '/isolated', OPENAI_API_KEY: '' } };

test('official providers receive unchanged context and cleanup for preparation, execution and finalization', async () => {
  const context = { vars: { original: true } }; const calls = []; const cleanups = [];
  const adapter = new Adapter({ config, loadApiProvider: async (id, options) => ({
    callApi: async (prompt, received) => {
      calls.push({ id, options, prompt, context: received });
      if (id.endsWith(':prepare')) return { output: JSON.stringify({ provider: { options: { config: { model: 'selected' } } } }) };
      if (id === 'openai:codex-app-server') return { output: 'answer', raw: 'retained' };
      return { output: 'final answer', metadata: { retained: true } };
    }, cleanup: async () => { cleanups.push(id); },
  }) });
  const result = await adapter.callApi('original task', context);
  assert.equal(result.output, 'final answer');
  assert.deepEqual(calls.map(x => x.id), ['file:///fixture/provider.py:prepare', 'openai:codex-app-server', 'file:///fixture/provider.py:finalize']);
  assert.ok(calls.every(x => x.context === context));
  assert.equal(calls[0].options.env.CODEX_HOME, '/isolated');
  assert.equal(JSON.parse(calls[2].prompt).execution.raw, 'retained');
  assert.deepEqual(cleanups, calls.map(x => x.id));
});

test('a preparation failure is returned unchanged without invoking an executor', async () => {
  let count = 0; const failure = { error: 'not eligible', metadata: { retained: true } };
  const adapter = new Adapter({ config, loadApiProvider: async () => { count++; return { callApi: async () => failure }; } });
  assert.equal(await adapter.callApi('task', {}), failure);
  assert.equal(count, 1);
});

test('native executor and cleanup errors reach Python finalization with retained data', async () => {
  let final;
  const adapter = new Adapter({ config, loadApiProvider: async id => ({
    callApi: async prompt => {
      if (id.endsWith(':prepare')) return { output: '{"provider":{}}' };
      if (id === 'openai:codex-app-server') return { output: 'partial', raw: 'retained' };
      final = JSON.parse(prompt); return { error: final.execution.error, raw: final.execution.raw };
    }, cleanup: async () => { if (id === 'openai:codex-app-server') throw new Error('cleanup failed'); },
  }) });
  const result = await adapter.callApi('task', {});
  assert.equal(result.error, 'cleanup failed');
  assert.equal(result.raw, 'retained');
});
