import asyncio

import Logging
from Logging import Severity


class Scheduler:
    def __init__(self):
        self.runtime_counter = 0
        self.schedules = []
        self.enabled = True

    async def tick(self):
        for (router, interval) in self.schedules:
            if self.runtime_counter % interval == 0:
                try:
                    await router.run()
                except Exception as exception:
                    Logging.log(f'Route {router.name} failed: {exception}', severity=Severity.ERROR)
        self.runtime_counter += 1

    def schedule(self, router, interval):
        self.schedules.append((router, interval))

    async def start(self):
        while self.enabled:
            await self.tick()
            await asyncio.sleep(1)

    def stop(self):
        self.enabled = False