"""Isolated browser fixture; never connects to a real video provider."""
import asyncio
import json
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI

from federation.core import FederationStore
from federation.video_api import install


temporary = tempfile.TemporaryDirectory(prefix='weiming-video-ui-')
store = FederationStore(base=Path(temporary.name))
calls = []


@asynccontextmanager
async def lifespan(app):
    app.state.video_submission.recover()
    yield
    await app.state.video_submission.close()
    temporary.cleanup()


app = FastAPI(lifespan=lifespan)
service = install(app, store, Path(__file__).resolve().parents[1] / 'federation/web')


async def provider(request):
    await asyncio.sleep(.3)
    calls.append({'path': request.url.path, 'content_type': request.headers.get('content-type'),
                  'parameters': json.loads(request.content) if request.headers.get('content-type', '').startswith('application/json') else 'multipart'})
    return httpx.Response(202, json={'promptId': 'controlled-ui-task-' + str(len(calls)), 'queueNumber': 0, 'duration': 10, 'seed': 42})


service.client_factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(provider))


@app.get('/fixture-calls')
async def fixture_calls():
    return {'calls': calls, 'fixture_only': True}


if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=18761, log_level='warning')
