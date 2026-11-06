import { loadApiProvider } from 'promptfoo';

export default class NativeExecutorAdapter {
  constructor(options) { this.config = options.config; this.load = options.loadApiProvider ?? loadApiProvider; }
  id() { return `model-fit-corpus:${this.config.mode}`; }
  async invoke(id, options, prompt, context) {
    let provider; let response;
    try { provider = await this.load(id, options); response = await provider.callApi(prompt, context); }
    catch (error) { response = { ...response, error: error.message }; }
    finally {
      try { await provider?.cleanup?.(); }
      catch (error) { response = { ...response, error: error.message }; }
    }
    return response;
  }
  async callApi(prompt, context) {
    const options = { env: this.config.python_env, options: { config: this.config } };
    const prepared = await this.invoke(`file://${this.config.python_provider}:prepare`, options, prompt, context);
    if (prepared.error) return prepared;
    const plan = JSON.parse(prepared.output);
    const execution = await this.invoke('openai:codex-app-server', plan.provider, prompt, context);
    return this.invoke(`file://${this.config.python_provider}:finalize`, options, JSON.stringify({ prepared: plan, execution }), context);
  }
}
