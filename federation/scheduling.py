"""Bounded foreground lanes and fair model permits, without cancelling work."""
import asyncio
from contextlib import asynccontextmanager
import time


class ForegroundQueue:
    """Two general roots plus one strictly classified social root.

    Model concurrency remains two. A general root cannot occupy the spare
    social lane while waiting, and FIFO within each lane prevents starvation.
    """
    def __init__(self, jobs):
        self.jobs, self.pending, self.active = jobs, [], {}
        self.wake = asyncio.Event()

    def lane(self, identifier):
        job = self.jobs[identifier]
        return ('social' if (job.get('simple_chat') or job.get('short_dialogue'))
                and not job.get('files') and not job.get('learning') else 'general')

    def empty(self): return not self.pending

    def put_nowait(self, identifier):
        self.pending.append(identifier)
        self.wake.set()

    async def get(self):
        while True:
            for i, identifier in enumerate(self.pending):
                lane = self.lane(identifier)
                # Extra social turns may use free general capacity. General
                # work never occupies the reserved social lane.
                if lane == 'social' and 'social' in self.active.values(): lane = 'general'
                if list(self.active.values()).count(lane) < (1 if lane == 'social' else 2):
                    self.pending.pop(i)
                    self.active[identifier] = lane
                    return identifier
            self.wake.clear()
            await self.wake.wait()

    def task_done(self, identifier):
        self.active.pop(identifier)
        self.wake.set()


class ModelSlots:
    """At most two calls; social priority has burst and age starvation bounds."""
    def __init__(self, capacity=2, max_burst=2, age_seconds=30):
        self.capacity, self.max_burst, self.age_seconds = capacity, max_burst, age_seconds
        self.running, self.burst, self.waiters = 0, 0, []

    def dispatch(self):
        while self.running < self.capacity and self.waiters:
            now = time.monotonic()
            index = 0
            if now - self.waiters[0][0] < self.age_seconds and self.burst < self.max_burst:
                index = next((i for i, (_, social, _) in enumerate(self.waiters) if social), 0)
            _, social, future = self.waiters.pop(index)
            if future.cancelled(): continue
            self.burst = self.burst + 1 if social else 0
            self.running += 1
            future.set_result(True)

    @asynccontextmanager
    async def slot(self, *, social=False):
        future = asyncio.get_running_loop().create_future()
        row = (time.monotonic(), social, future)
        self.waiters.append(row)
        self.dispatch()
        acquired = False
        try:
            await future
            acquired = True
            yield
        finally:
            if row in self.waiters: self.waiters.remove(row)
            elif acquired or (future.done() and not future.cancelled()): self.running -= 1
            self.dispatch()
