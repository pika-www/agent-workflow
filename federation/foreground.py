"""Bounded conversation readers with exclusive knowledge mutation ownership."""
import asyncio
from contextlib import asynccontextmanager


class ForegroundGate:
    def __init__(self, capacity=2):
        self.capacity = capacity
        self.condition = asyncio.Condition()
        self.readers = 0
        self.writer = False
        self.waiting_writers = 0

    def locked(self):
        return bool(self.readers or self.writer)

    async def acquire(self):
        async with self.condition:
            self.waiting_writers += 1
            try:
                await self.condition.wait_for(lambda: not self.locked())
                self.writer = True
            finally:
                self.waiting_writers -= 1
                self.condition.notify_all()

    async def release(self):
        async with self.condition:
            self.writer = False
            self.condition.notify_all()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *args):
        await self.release()

    @asynccontextmanager
    async def slot(self, *, exclusive=False):
        if exclusive:
            async with self:
                yield
            return
        async with self.condition:
            await self.condition.wait_for(lambda: not self.writer and not self.waiting_writers
                                          and self.readers < self.capacity)
            self.readers += 1
        try:
            yield
        finally:
            async with self.condition:
                self.readers -= 1
                self.condition.notify_all()
