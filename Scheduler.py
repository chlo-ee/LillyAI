from time import sleep


class Scheduler:
    def __init__(self):
        self.runtime_counter = 0
        self.schedules = []
        self.enabled = True

    async def tick(self):
        for (router, interval) in self.schedules:
            if self.runtime_counter % interval == 0:
                await router.run()
        self.runtime_counter += 1

    def schedule(self, router, interval):
        self.schedules.append((router, interval))

    async def start(self):
        while self.enabled:
            await self.tick()
            sleep(1)

    def stop(self):
        self.enabled = False