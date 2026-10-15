import asyncio
import threading
import time
from fastapi.testclient import TestClient
from federation.app import create_app


def wait(client, job_id, status):
    for _ in range(200):
        job = client.get('/api/jobs/' + job_id).json()
        if job['status'] == status:
            return job
        time.sleep(.01)
    raise AssertionError(job)


def test_stop_waiting_preserves_text_and_releases_worker(tmp_path):
    started = threading.Event()
    calls = []
    async def runner(turn, store):
        calls.append(turn['id'])
        if len(calls) == 1:
            app.state.reply_streams.append(turn['room_id'], turn['parent_job_id'], '尚未完成的正文')
            app.state.reply_streams.progress(turn['room_id'], turn['parent_job_id'], 'waiting_model', '继续等待')
            started.set()
            await asyncio.sleep(60)
        turn['answer'] = '新一轮真实测试回答'
    app = create_app(base=tmp_path/'data', runner=runner)
    with TestClient(app) as client:
        room = client.post('/api/chat/primary', json={}).json()
        url = '/api/chat/rooms/' + room['id']
        sent = client.post(url+'/messages', json={'content':'你好'}).json()
        job = sent['job']['id']
        assert started.wait(3)
        assert client.get(url).json()['can_stop_reply'] is True
        stop = client.post(url+'/jobs/'+job+'/stop', json={})
        assert stop.status_code == 200, stop.text
        assert wait(client, job, 'cancelled')['error'] is None
        saved = client.get(url).json()
        assert saved['status'] == 'idle' and saved['active_job_id'] is None
        message = saved['messages'][-1]
        assert message['status'] == 'cancelled'
        assert '尚未完成的正文' in message['content'] and '未能完成答复' not in message['content']
        assert not message.get('recoverable_job_id')
        assert client.post(url+'/jobs/'+job+'/stop', json={}).status_code == 200
        next_job = client.post(url+'/messages', json={'content':'你好'}).json()['job']['id']
        wait(client, next_job, 'completed')
        assert len(calls) == 2


def test_stop_queued_greeting_never_cancels_another_room_or_runs_it(tmp_path):
    started = threading.Event()
    release = threading.Event()
    calls = []
    async def runner(turn, store):
        calls.append(turn['room_id'])
        started.set()
        while not release.is_set():
            await asyncio.sleep(.01)
        turn['answer'] = '已完成'
    app = create_app(base=tmp_path/'data', runner=runner)
    with TestClient(app) as client:
        one = client.post('/api/chat/primary', json={}).json()
        url = '/api/chat/rooms/'+one['id']
        running = client.post(url+'/messages', json={'content':'你好'}).json()['job']['id']
        assert started.wait(3)
        # Occupy both bounded conversation slots; the third room must queue.
        other = client.post('/api/chat/rooms', json={'mode':'orchestrated','participants':['central']}).json()
        other['purpose'] = 'primary'; app.state.chat.save_room(other)
        other_job = client.post('/api/chat/rooms/'+other['id']+'/messages', json={'content':'你好'}).json()['job']['id']
        wait(client, other_job, 'running')
        two = client.post('/api/chat/rooms', json={'mode':'orchestrated','participants':['central']}).json()
        two['purpose'] = 'primary'; app.state.chat.save_room(two)
        url2 = '/api/chat/rooms/'+two['id']
        queued = client.post(url2+'/messages', json={'content':'hello'}).json()['job']['id']
        assert client.post(url2+'/jobs/'+running+'/stop', json={}).status_code == 404
        stopped = client.post(url2+'/jobs/'+queued+'/stop', json={})
        assert stopped.status_code == 200, stopped.text
        assert client.get('/api/jobs/'+running).json()['status'] == 'running'
        assert client.get('/api/jobs/'+queued).json()['status'] == 'cancelled'
        release.set(); wait(client, running, 'completed'); time.sleep(.05)
        assert calls == [one['id'], other['id']]
        assert client.get(url2).json()['status'] == 'idle'
