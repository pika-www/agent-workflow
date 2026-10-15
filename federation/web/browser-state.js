// Browser storage contains only an opaque client ID; content lives in the API.
export async function openServerState(kind, storageName, legacyKey) {
  const clone = value => JSON.parse(JSON.stringify(value));
  let clientId;
  if (kind === 'chat') {
    try { clientId = localStorage.getItem('weiming.browser-client.v1'); } catch { /* Private browser. */ }
    if (!/^[a-f0-9]{32}$/.test(clientId || '')) {
      clientId = crypto.randomUUID().replaceAll('-', '');
      try { localStorage.setItem('weiming.browser-client.v1', clientId); } catch { /* Content still stays on the server. */ }
    }
  }
  const endpoint = '/api/browser-state/' + (kind === 'journal' ? 'journal' : 'chat-' + clientId);
  async function request(body) {
    const response = await fetch(endpoint, body === undefined ? { cache: 'no-store' } : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    if (!response.ok) {
      let data; try { data = await response.json(); } catch { /* Unknown response stays uncertain. */ }
      const error = new Error(data?.code === 'release_draining'
        ? '正在安全发布，新消息尚未受理。草稿仍在当前页面，请保留页面，发布完成后重新发送。'
        : '服务器暂时无法保存草稿或手记，请保留当前页面后重试。');
      error.code = data?.code; error.accepted = data?.accepted; error.status = response.status; throw error;
    }
    return response.json();
  }
  let legacy = null, storage;
  try { storage = window[storageName]; const raw = storage.getItem(legacyKey); if (raw) legacy = JSON.parse(raw); } catch { /* Keep unreadable originals. */ }
  let loaded = await request();
  if (legacy && typeof legacy === 'object' && !Array.isArray(legacy)) {
    loaded = await request({ value: legacy, migrate: true });
    if (loaded.saved) { try { storage.removeItem(legacyKey); } catch { /* The server copy is already safe. */ } }
  }
  let previous = clone(loaded.value), queue = Promise.resolve();
  return {
    value: clone(loaded.value),
    save(value) {
      const snapshot = clone(value);
      const pending = queue.catch(() => {}).then(async () => {
        let result;
        // Only draft persistence is retried, never the chat submission. Keep
        // writes ordered while the sealed API restarts; no content goes into
        // browser storage. A prolonged outage still surfaces a bounded error.
        for (let attempt = 0; ; attempt++) {
          try { result = await request({ before: previous, value: snapshot }); break; }
          catch (error) {
            const transient = error.code === 'release_draining' || error.name === 'TypeError'
              || [502, 503, 504].includes(error.status);
            if (!transient || attempt >= 29) throw error;
            await new Promise(resolve => setTimeout(resolve, 1000));
          }
        }
        if (!result.saved) throw new Error('服务器未确认保存，请保留当前页面。');
        previous = snapshot;
        return result;
      });
      queue = pending;
      return pending;
    },
  };
}
