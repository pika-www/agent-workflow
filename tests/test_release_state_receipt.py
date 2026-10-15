import io
import json
import pytest
from deploy.server import state_receipt, guarded_agent_release


@pytest.mark.parametrize('visible', [True, False])
def test_ordinary_chat_blocks_release_even_if_federation_excludes_it(monkeypatch, tmp_path, visible):
    payloads={
        '/api/federation':{'instance':'temporary','model':'configured','branches':[],'jobs':[]},
        '/api/workspace':{'jobs':[{'id':'chat-running','status':'running'}] if visible else [],'running':1,'queued':0},
        '/api/autonomy':{'agents':[],'active_run':None,'budget':{},'settings':{}},
        '/api/chat/rooms':{'rooms':[]},
    }
    class FakeHTTP:
        def open(self,url,timeout):
            return io.BytesIO(json.dumps(payloads[url.replace('http://127.0.0.1:18732','')]).encode())
    monkeypatch.setattr(state_receipt,'build_opener',lambda *args:FakeHTTP())
    receipt=state_receipt.receipt('http://127.0.0.1:18732')
    assert receipt['active_jobs'] and receipt['foreground_running']==1
    # No file creation, pause request or restart may happen when chat is active.
    with pytest.raises(ValueError,match='Foreground jobs still active'):
        guarded_agent_release.checkpoint(tmp_path/'project',tmp_path/'release')
    assert not (tmp_path/'release').exists()
