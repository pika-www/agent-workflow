import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
import threading
import time
import pytest
from fastapi.testclient import TestClient
from federation.app import create_app
from federation.release_fence import ReleaseFence, ReleaseDraining
from deploy.server.atomic_release import ReleaseSession


def wait(check):
    until = time.monotonic() + 5
    while time.monotonic() < until:
        value = check()
        if value: return value
        time.sleep(.01)
    raise AssertionError('Timed out')


def room(client, app):
    result = client.post('/api/chat/rooms', json={'mode':'orchestrated','participants':['central']}).json()
    result['purpose'] = 'primary'; app.state.chat.save_room(result)
    return result['id']


def test_fence_locks_survive_new_instances_and_fail_closed(tmp_path):
    fence = ReleaseFence(tmp_path)
    with fence.activity():
        fence.write('release-a', 'draining')
        assert not ReleaseFence(tmp_path).idle()
        with pytest.raises(ReleaseDraining):
            with fence.activity(): pass
        with fence.activity(admitted=True): pass
    assert fence.idle()
    assert ReleaseFence(tmp_path).closed()
    with pytest.raises(ValueError): fence.write('release-b', 'open')
    # A commit lock excludes admitted work too, and has no timeout lease.
    fd = fence.lock('activity', exclusive=True)
    with pytest.raises(ReleaseDraining):
        with fence.activity(admitted=True): pass
    os.close(fd)
    fence.path.write_text('{broken')
    assert fence.closed()


def test_inflight_routing_and_queued_jobs_finish_before_seal(tmp_path):
    running, release = threading.Event(), threading.Event()
    async def runner(turn, store):
        running.set()
        while not release.is_set(): await asyncio.sleep(.01)
        turn['answer'] = '保存每条已受理的任务'
    app = create_app(base=tmp_path, runner=runner)
    with TestClient(app) as client:
        rooms = [room(client, app) for _ in range(3)]
        ids = [client.post(f'/api/chat/rooms/{r}/messages', json={'content':'你好'}).json()['job']['id'] for r in rooms]
        assert running.wait(2)
        session = ReleaseSession(tmp_path, 'test-release')
        session.status = lambda: client.get('/api/release/status').json()
        session.begin()
        try:
            assert not session.status()['ready']
            rejected = client.post(f'/api/chat/rooms/{rooms[0]}/messages', json={'content':'必须保持未受理'})
            assert rejected.status_code == 503 and rejected.json()['accepted'] is False
            assert rejected.headers['retry-after'] == '5'
            # Every mutation route, including upload/settings/resume, is fenced.
            for path in ['/api/video-generation/jobs','/api/autonomy/settings', f'/api/chat/rooms/{rooms[0]}/jobs/{ids[0]}/resume']:
                assert client.post(path, json={}).status_code == 503
            release.set()
            wait(lambda: all(client.get('/api/jobs/'+j).json()['status']=='completed' for j in ids))
            session.seal(timeout=2)
            assert app.state.release_fence.state()['phase'] == 'sealed'
            for r in rooms:
                messages = client.get('/api/chat/rooms/'+r).json()['messages']
                assert any(m.get('content')=='保存每条已受理的任务' for m in messages)
                assert not any(m.get('content')=='必须保持未受理' for m in messages)
            session.reopen()
            assert client.post('/api/chat/rooms', json={'mode':'orchestrated','participants':['central']}).status_code == 200
        finally:
            release.set(); session.close()


def test_admission_lock_covers_handler_before_job_creation(tmp_path):
    entered, release = threading.Event(), threading.Event()
    app = create_app(base=tmp_path)
    @app.post('/controlled-slow-write')
    async def slow_write():
        entered.set()
        while not release.is_set(): await asyncio.sleep(.01)
        return {'persisted': True}
    with TestClient(app) as client, ThreadPoolExecutor(1) as executor:
        future = executor.submit(client.post, '/controlled-slow-write', json={})
        assert entered.wait(2)
        app.state.release_fence.write('boundary', 'draining')
        status = client.get('/api/release/status').json()
        assert status['active_jobs'] == [] and status['activities'] == 1 and not status['ready']
        release.set()
        assert future.result().json()['persisted']
        assert client.get('/api/release/status').json()['ready']


def test_release_restart_stays_closed_without_changing_history(tmp_path):
    app = create_app(base=tmp_path)
    with TestClient(app) as client:
        rid = room(client, app)
        before = client.get('/api/chat/rooms/'+rid).json()['messages']
        app.state.release_fence.write('restart', 'sealed')
    restored = create_app(base=tmp_path)
    with TestClient(restored) as client:
        assert client.get('/api/release/status').json()['phase'] == 'sealed'
        assert client.post('/api/chat/primary', json={}).status_code == 503
        assert client.get('/api/chat/rooms/'+rid).json()['messages'] == before
        restored.state.release_fence.write('restart', 'open')
        assert client.post('/api/chat/primary', json={}).status_code == 200


def test_background_drain_finishes_current_and_blocks_next(tmp_path):
    fence = ReleaseFence(tmp_path)
    with fence.background() as admitted:
        assert admitted
        fence.write('background', 'draining')
        assert not fence.idle()
    with fence.background() as admitted: assert not admitted
    assert fence.idle()


def test_hotspot_background_refresh_holds_activity_until_complete(tmp_path):
    app = create_app(base=tmp_path)
    entered, finish = threading.Event(), threading.Event()
    async def refresh():
        entered.set()
        while not finish.is_set(): await asyncio.sleep(.01)
    app.state.hotspots.refresh = refresh
    with TestClient(app) as client:
        try:
            assert client.get('/api/hotspots').status_code == 200
            assert entered.wait(2)
            app.state.release_fence.write('hotspot', 'draining')
            assert not client.get('/api/release/status').json()['ready']
            finish.set()
            wait(lambda: client.get('/api/release/status').json()['ready'])
        finally: finish.set()


def test_conflicting_owner_cannot_reopen_or_steal(tmp_path):
    one, two = ReleaseSession(tmp_path, 'one'), ReleaseSession(tmp_path, 'two')
    one.begin()
    try:
        with pytest.raises(BlockingIOError): two.begin()
    finally: one.close()
    with pytest.raises(ValueError): two.begin()
    assert one.fence.closed()
    one.begin(); one.reopen()


def test_autonomy_loop_finishes_current_round_and_wakes_after_reopen(tmp_path):
    async def scenario():
        from federation.autonomy import Autonomy
        from federation.core import FederationStore
        store = FederationStore(base=tmp_path); store.init()
        fence = ReleaseFence(tmp_path)
        manager = Autonomy(store, lambda: True, None)
        manager.release_fence = fence
        manager.due = lambda: {'id':'central'}
        entered, finish = asyncio.Event(), asyncio.Event()
        rounds = []
        async def learn(agent):
            manager.active = 'controlled-round'
            rounds.append(agent['id']); entered.set()
            await finish.wait()
            manager.active = None
        manager.learn = learn
        manager.start()
        try:
            await asyncio.wait_for(entered.wait(), 2)
            fence.write('autonomy', 'draining')
            assert not fence.idle()
            finish.set(); await asyncio.sleep(.05)
            assert rounds == ['central'] and fence.idle()
            manager.wake.set(); await asyncio.sleep(.05)
            assert rounds == ['central']
            fence.write('autonomy', 'open')
            manager.wake.set(); await asyncio.sleep(.05)
            assert len(rounds) == 2
        finally: await manager.close()
    asyncio.run(scenario())


def test_draft_writes_drain_but_are_excluded_by_seal(tmp_path):
    app=create_app(base=tmp_path)
    path='/api/browser-state/chat-'+'d'*32
    payload={'before':{},'value':{'drafts':[['fixture','保留本轮草稿']]}}
    with TestClient(app) as client:
        fence=app.state.release_fence
        fence.write('draft-test','draining')
        assert client.post(path,json=payload).json()['saved']
        assert client.post('/api/chat/primary',json={}).status_code==503
        fd=fence.lock('activity',exclusive=True)
        try:
            assert client.post(path,json=payload).status_code==503
            fence.write('draft-test','sealed')
        finally:os.close(fd)
        assert client.post(path,json=payload).status_code==503


def staged_release(tmp_path):
    import hashlib
    project=tmp_path/'project';release=tmp_path/'release'
    target=project/'federation/example.py';target.parent.mkdir(parents=True);target.write_text('old = True\n')
    staged=release/'staged/federation/example.py';staged.parent.mkdir(parents=True);staged.write_text('new = True\n')
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    (release/'manifest.json').write_text(json.dumps({'federation/example.py':{'before':sha(target),'after':sha(staged)}}))
    return project,release,target


def test_restart_failure_leaves_fence_closed_and_original_source_backed_up(tmp_path,monkeypatch):
    from deploy.server import atomic_release,state_receipt
    project,release,target=staged_release(tmp_path)
    state={'rooms':{},'settings':{},'pending':{},'agent_ids':[]}
    monkeypatch.setattr(state_receipt,'receipt',lambda url:state)
    def status(self):
        return {**self.fence.state(),'protocol':1,'pid':123,'ready':True,'active_jobs':[],
                'active_run':None,'video_dispatches':0,'activities':0,'background_summary':False}
    monkeypatch.setattr(ReleaseSession,'status',status)
    def fail(*args,**kwargs):raise RuntimeError('controlled restart failure')
    monkeypatch.setattr(atomic_release.subprocess,'run',fail)
    with pytest.raises(RuntimeError,match='controlled restart failure'):atomic_release.activate(project,release)
    assert ReleaseFence(project/'openwiki-federation').state()['phase']=='sealed'
    assert target.read_text()=='new = True\n'
    assert (release/'source-backup/federation/example.py').read_text()=='old = True\n'


def test_drain_timeout_reopens_without_touching_source(tmp_path,monkeypatch):
    from deploy.server import atomic_release
    project,release,target=staged_release(tmp_path)
    def timeout(*args,**kwargs):raise TimeoutError('controlled drain timeout')
    monkeypatch.setattr(ReleaseSession,'seal',timeout)
    with pytest.raises(TimeoutError):atomic_release.activate(project,release)
    assert not ReleaseFence(project/'openwiki-federation').closed()
    assert target.read_text()=='old = True\n'
    assert not (release/'source-backup').exists()
