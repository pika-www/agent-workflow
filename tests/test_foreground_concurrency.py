import asyncio
import threading
import time
import base64
from fastapi.testclient import TestClient
from federation.app import create_app
from federation.foreground import ForegroundGate


def test_writer_excludes_readers_and_cancelled_waiter_releases_queue():
    async def scenario():
        gate = ForegroundGate(2)
        async with gate.slot():
            acquired = asyncio.Event()
            async def writer():
                async with gate:
                    acquired.set()
            task = asyncio.create_task(writer())
            await asyncio.sleep(0)
            assert not acquired.is_set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            async with gate.slot():
                assert gate.readers == 2
        async with gate:
            assert gate.locked() and gate.writer and not gate.readers
        assert not gate.locked()
    asyncio.run(scenario())


def test_short_conversation_completes_while_other_room_is_running(tmp_path):
    entered = threading.Event()
    release = threading.Event()
    calls = []
    async def runner(turn, store):
        calls.append(turn['room_id'])
        if len(calls) == 1:
            entered.set()
            while not release.is_set():
                await asyncio.sleep(.01)
        turn['answer'] = '这条对话已完成'
    app = create_app(base=tmp_path/'data', runner=runner)
    with TestClient(app) as client:
        one = client.post('/api/chat/primary', json={}).json()
        first = client.post(f"/api/chat/rooms/{one['id']}/messages", json={'content':'你好'}).json()['job']['id']
        assert entered.wait(3)
        two = client.post('/api/chat/rooms', json={'mode':'orchestrated','participants':['central']}).json()
        two['purpose']='primary'; app.state.chat.save_room(two)
        second = client.post(f"/api/chat/rooms/{two['id']}/messages", json={'content':'hello'}).json()['job']['id']
        for _ in range(200):
            job=client.get('/api/jobs/'+second).json()
            if job['status']=='completed': break
            time.sleep(.01)
        assert job['status']=='completed', job
        assert client.get('/api/jobs/'+first).json()['status']=='running'
        assert client.post(f"/api/chat/rooms/{one['id']}/messages", json={'content':'再问一遍'}).status_code==409
        payload={'filename':'scope.txt','data_base64':base64.b64encode(b'isolated fixture').decode()}
        assert client.post(f"/api/chat/rooms/{one['id']}/files",json=payload).status_code==409
        uploaded=client.post(f"/api/chat/rooms/{two['id']}/files",json=payload)
        assert uploaded.status_code==200,uploaded.text
        assert client.get(f"/api/chat/rooms/{one['id']}/files/"+uploaded.json()['id']).status_code==404
        assert len(calls)==2
        release.set()


def test_cancel_one_running_room_does_not_cancel_other(tmp_path):
    entered = threading.Event()
    release = threading.Event()
    calls=[]
    async def runner(turn, store):
        calls.append(turn['room_id'])
        if len(calls)==2:entered.set()
        while not release.is_set():await asyncio.sleep(.01)
        turn['answer']='已完成'
    app=create_app(base=tmp_path/'data',runner=runner)
    with TestClient(app) as client:
        rooms=[];jobs=[]
        for _ in range(2):
            room=client.post('/api/chat/rooms',json={'mode':'orchestrated','participants':['central']}).json()
            room['purpose']='primary';app.state.chat.save_room(room);rooms.append(room)
            jobs.append(client.post(f"/api/chat/rooms/{room['id']}/messages",json={'content':'你好'}).json()['job']['id'])
        assert entered.wait(3)
        stopped=client.post(f"/api/chat/rooms/{rooms[1]['id']}/jobs/{jobs[1]}/stop",json={})
        assert stopped.status_code==200
        assert client.get('/api/jobs/'+jobs[1]).json()['status']=='cancelled'
        assert client.get('/api/jobs/'+jobs[0]).json()['status']=='running'
        release.set()
