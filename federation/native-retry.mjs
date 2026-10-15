/** Retry transport failures only, with one five-reconnect budget per Agent run. */
import {setTimeout as sleep} from 'node:timers/promises';
export const NATIVE_RECONNECT_LIMIT = 5;
export const reconnectDelay = attempt => Math.min(8000, 1000 * 2 ** (attempt - 1));
export const waitingReconnectDelay = attempt => Math.min(30000, 2000 * 2 ** Math.min(attempt - 1, 4));
export function transportError(code, message) {
  return Object.assign(new Error(message), {code});
}
export function retryableTransport(error, signal) {
  if (signal?.aborted || ['AbortError','APIUserAbortError'].includes(error?.name)) return false;
  const status = error?.status;
  if (typeof status === 'number') return [408,409,429].includes(status) || status >= 500 && status < 600;
  if (['APIConnectionError','APIConnectionTimeoutError'].includes(error?.name)) return true;
  return ['ECONNRESET','ECONNREFUSED','ETIMEDOUT','EAI_AGAIN','ENETUNREACH','UND_ERR_SOCKET','UND_ERR_CONNECT_TIMEOUT',
    'stream_interrupted','server_error','rate_limit_exceeded'].includes(error?.code || error?.cause?.code);
}
export async function waitForReconnect(attempt, options) {
  const delay=(options.waitForModel?waitingReconnectDelay:reconnectDelay)(attempt);
  if (options.retryWait) return options.retryWait(delay, options.signal);
  await sleep(delay, undefined, {signal: options.signal});
}
