from datetime import datetime
from time import sleep


class Scheduler:
    def __init__(self):
        self.runtime_counter = 0
        self.schedules = []
        self.enabled = True
        self.last_tick_minute = datetime.now().time().minute

    async def tick(self):
        promises = []
        now = datetime.now().time()
        for (router, interval, time_of_day) in self.schedules:
            if ((interval is not None and self.runtime_counter % interval == 0) or   # interval scheduling
                    (time_of_day is not None and self.last_tick_minute != now.minute # daily scheduling
                     and now.hour == time_of_day.hour
                     and now.minute == time_of_day.minute)):
                promises.append(router.run())
        self.last_tick_minute = now.minute
        self.runtime_counter += 1
        for promise in promises:
            await promise

    def schedule(self, router, interval=None, time_of_day=None):
        self.schedules.append((router, interval, time_of_day))

    async def start(self):
        while self.enabled:
            await self.tick()
            sleep(1)

    def stop(self):
        self.enabled = False