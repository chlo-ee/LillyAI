import asyncio
import os
import socket
from datetime import datetime

import Logging
from Logging import Severity


def sd_notify(state: str):
    """Best-effort systemd notification (Type=notify readiness + watchdog).

    No-op outside systemd (NOTIFY_SOCKET unset), so development runs are
    unaffected.
    """
    addr = os.environ.get('NOTIFY_SOCKET')
    if not addr:
        return
    if addr.startswith('@'):
        addr = '\0' + addr[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(addr)
            sock.sendall(state.encode())
    except OSError:
        pass


class Scheduler:
    def __init__(self):
        self.runtime_counter = 0
        self.schedules = []
        self.enabled = True
        self.last_tick_minute = datetime.now().time().minute

    async def tick(self):
        # Feed the systemd watchdog: if the (synchronous) event loop ever
        # hangs, the pings stop, systemd SIGABRTs the process (faulthandler
        # then dumps the stack of the exact hang site to the journal) and
        # restarts it.
        sd_notify('WATCHDOG=1')
        now = datetime.now().time()
        for (router, interval, time_of_day) in self.schedules:
            if ((interval is not None and self.runtime_counter % interval == 0) or   # interval scheduling
                    (time_of_day is not None and self.last_tick_minute != now.minute # daily scheduling
                     and now.hour == time_of_day.hour
                     and now.minute == time_of_day.minute)):
                try:
                    await router.run()
                except Exception as exception:
                    Logging.log(f'Route {router.name} failed: {exception}', severity=Severity.ERROR)
        self.last_tick_minute = now.minute
        self.runtime_counter += 1

    def schedule(self, router, interval=None, time_of_day=None):
        self.schedules.append((router, interval, time_of_day))

    async def start(self):
        sd_notify('READY=1')
        while self.enabled:
            await self.tick()
            await asyncio.sleep(1)

    def stop(self):
        self.enabled = False
