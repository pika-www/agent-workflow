import asyncio
import threading
import time
from fastapi.testclient import TestClient
from federation.app import create_app
from federation.scheduling import ForegroundQueue, ModelSlots


def test_full_general_lanes_leave_social_lane_and_preserve_fifo():
    async def scenario():
        jobs = {key: {'simple_chat':key.startswith('s')} for key in ['g1','g2','g3','s1','s2']}
        queue = ForegroundQueue(jobs)
        for key in jobs: queue.put_nowait(key)
        assert await queue.get() == 'g1'
        assert await queue.get() == 'g2'
        assert await queue.get() == 's1'
        waiting = asyncio.create_task(queue.get()); await asyncio.sleep(0)
        assert not waiting.done()
        queue.task_done('g1')
        assert await waiting == 'g3'
        queue.task_done('s1')
        assert await queue.get() == 's2'
    asyncio.run(scenario())


def test_bounded_dialogue_can_use_reserved_lane_but_attachments_cannot():
    async def scenario():
        queue = ForegroundQueue({'bounded':{'short_dialogue':True},
                                 'file':{'short_dialogue':True,'files':[{'id':'fixture'}]},
                                 'learning':{'short_dialogue':True,'learning':True}})
        assert queue.lane('bounded') == 'social'
        assert queue.lane('file') == queue.lane('learning') == 'general'
    asyncio.run(scenario())


def test_model_priority_is_bounded_and_does_not_preempt_running_calls():
    async def scenario():
        slots = ModelSlots(1, max_burst=2)
        order = []
        async def work(name, social):
            async with slots.slot(social=social):
                order.append(name); await asyncio.sleep(0)
        async with slots.slot():
            tasks = [asyncio.create_task(work(name, social)) for name, social in
                     [('general',False),('s1',True),('s2',True),('s3',True)]]
            await asyncio.sleep(0)
            assert order == [] and slots.running == 1
        await asyncio.gather(*tasks)
        assert order == ['s1','s2','general','s3']
        assert slots.running == 0
    asyncio.run(scenario())


def test_aged_waiter_and_cancellation_do_not_leak_model_permits():
    async def scenario():
        slots = ModelSlots(1, age_seconds=0)
        order = []
        async def work(name, social):
            async with slots.slot(social=social): order.append(name)
        async with slots.slot():
            cancel = asyncio.create_task(work('cancelled', True))
            first = asyncio.create_task(work('old', False))
            second = asyncio.create_task(work('social', True))
            await asyncio.sleep(0); cancel.cancel()
            await asyncio.gather(cancel, return_exceptions=True)
        await asyncio.gather(first, second)
        assert order == ['old','social'] and slots.running == 0 and slots.waiters == []
    asyncio.run(scenario())


def test_real_http_short_turn_while_two_general_roots_stay_active(tmp_path):
    release = threading.Event()
    entered = []
    async def runner(turn, store):
        if '耗时' in turn.get('current_question',''):
            entered.append(turn['id'])
            while not release.is_set(): await asyncio.sleep(.01)
        turn['answer'] = '本轮真实队列、受控模型'
    app = create_app(base=tmp_path, runner=runner)
    with TestClient(app) as client:
        ids=[]
        try:
            for question in ['只讨论，不使用工具。请解释第一项耗时分析。','只讨论，不使用工具。请解释第二项耗时分析。','你好','只根据这句话回答，不使用工具：标识 QD-5813。请用一句话复述。']:
                room=client.post('/api/chat/rooms',json={'mode':'orchestrated','participants':['central']}).json()
                room['purpose']='primary';app.state.chat.save_room(room)
                accepted=client.post('/api/chat/rooms/'+room['id']+'/messages',json={'content':question})
                assert accepted.status_code==200,accepted.text
                ids.append(accepted.json()['job']['id'])
            deadline=time.monotonic()+4
            while time.monotonic()<deadline:
                if all(client.get('/api/jobs/'+j).json()['status']=='completed' for j in ids[2:]): break
                time.sleep(.01)
            assert all(client.get('/api/jobs/'+j).json()['status']=='completed' for j in ids[2:])
            assert client.get('/api/jobs/'+ids[3]).json()['short_dialogue']
            assert len(entered)==2
            assert all(client.get('/api/jobs/'+j).json()['status']=='running' for j in ids[:2])
        finally: release.set()


def test_local_backend_wait_does_not_hold_shared_cloud_capacity():
    async def scenario():
        shared,local=ModelSlots(2),ModelSlots(1)
        entered,release=asyncio.Event(),asyncio.Event()
        async def long_local():
            async with local.slot():
                async with shared.slot():
                    entered.set();await release.wait()
        first=asyncio.create_task(long_local());await entered.wait()
        second=asyncio.create_task(long_local());await asyncio.sleep(0)
        assert shared.running==1 and local.running==1
        async with shared.slot(social=True):
            assert shared.running==2 and not first.done() and not second.done()
        release.set();await asyncio.gather(first,second)
        assert shared.running==0 and local.running==0
    asyncio.run(scenario())
