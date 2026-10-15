import asyncio,time
from fastapi.testclient import TestClient
from federation.app import create_app

def test_completed_reply_keeps_first_and_total_after_reload(tmp_path):
    async def runner(job,store):
        await asyncio.sleep(.03)
        app.state.reply_streams.append(job['room_id'],job['parent_job_id'],'你好')
        await asyncio.sleep(.04)
        job.update(answer='你好。',response_origin='simple_chat_model',usage_collected=True,model_usage=[])
    app=create_app(base=tmp_path/'data',runner=runner)
    with TestClient(app) as client:
        room=app.state.chat.primary_room()
        result=client.post('/api/chat/rooms/'+room['id']+'/messages',json={'content':'你好'}).json()
        for _ in range(100):
            job=client.get('/api/jobs/'+result['job']['id']).json()
            if job['status']=='completed':break
            time.sleep(.02)
        assert job['status']=='completed'
        message=client.get('/api/chat/rooms/'+room['id']).json()['messages'][-1]
        timing=message['timing']
        assert timing['request_first_text_ms']>=30
        assert timing['response_completed_ms']>=timing['request_first_text_ms']+30
        assert timing['response_completed_ms']<=job['timing']['request_total_ms']
        assert app.state.chat.get_room(room['id'])['messages'][-1]['timing']==timing
