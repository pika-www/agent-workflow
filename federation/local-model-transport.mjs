/** CPU model timeouts apply only to this project's loopback Ollama endpoint. */
import {createRequire} from 'node:module';
const require = createRequire(new URL('../openwiki-tools/package.json', import.meta.url));
const agents = new Map();

export function localStructuredInit(target, init) {
  if (target.origin !== 'http://127.0.0.1:11436' || target.pathname !== '/v1/chat/completions'
      || typeof init?.body !== 'string') return init;
  let payload;
  try { payload=JSON.parse(init.body); } catch { return init; }
  if (!/^qwen3(?:\.\d+)?:/i.test(payload.model || '') || !payload.response_format
      || payload.reasoning_effort !== undefined || payload.reasoning !== undefined) return init;
  // Structured routing and text delivery use the same local model. Preserve
  // explicit reasoning settings and all cloud/non-structured requests.
  return {...init,body:JSON.stringify({...payload,reasoning_effort:'none'})};
}

export function localModelOptions(baseURL, configuration, env=process.env) {
  if (!env.WEIMING_LOCAL_MODEL_TIMEOUT_SECONDS) return {};
  let url;
  try { url = new URL(baseURL); } catch { return {}; }
  if (url.origin !== 'http://127.0.0.1:11436' || !/^\/v1\/?$/.test(url.pathname)
      || url.username || url.password || url.search || url.hash) return {};
  const seconds = Number(env.WEIMING_LOCAL_MODEL_TIMEOUT_SECONDS);
  if (!Number.isInteger(seconds) || seconds < 60 || seconds > 3600) throw new Error('Invalid local model timeout');
  const timeout = seconds * 1000;
  const {Agent,fetch} = require('undici');
  if (!agents.has(timeout)) agents.set(timeout, new Agent({headersTimeout:timeout,bodyTimeout:timeout,connect:{timeout:10000}}));
  const dispatcher = agents.get(timeout);
  return {timeout, configuration:{...configuration,fetch(input,init) {
    const target = new URL(typeof input === 'string' || input instanceof URL ? input : input.url);
    if (target.origin !== url.origin || !target.pathname.startsWith('/v1/')) throw new Error('Local model transport target mismatch');
    // Preserve the SDK/user AbortSignal; never extend an explicitly cancelled request.
    return fetch(input,{...localStructuredInit(target,init),dispatcher,redirect:'error'});
  }}};
}
