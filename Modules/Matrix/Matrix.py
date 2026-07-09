import asyncio

import markdown
from nio import AsyncClient, LoginResponse, MatrixRoom, RoomMessageText

import Logging
from Logging import Severity

config = {}
client = None
message_queue = []

# Every nio call gets a hard deadline: an idle connection dropped by a NAT or
# reverse proxy otherwise leaves sync() awaiting forever - silently freezing
# the whole (synchronous) event loop with nothing for the scheduler to catch.
NETWORK_TIMEOUT_SECONDS = 60

async def message_callback(room: MatrixRoom, event: RoomMessageText) -> None:
    if event.sender == config['matrix_user']:
        return
    Logging.log(f'{room.display_name} {room.user_name(event.sender)} | {event.body}', severity=Severity.DEBUG)
    if room.room_id == config['matrix_dm_room_id']:
        message_queue.append(event.body)

async def _drop_client():
    """Forget the client so the next call starts with a fresh login."""
    global client
    old = client
    client = None
    if old is not None:
        try:
            await asyncio.wait_for(old.close(), timeout=10)
        except Exception:
            pass

async def login():
    global client
    client = AsyncClient(config['matrix_homeserver'], config['matrix_user'])
    login = await client.login(config['matrix_password'])

    if not isinstance(login, LoginResponse):
        Logging.log("Login failed", severity=Logging.Severity.ERROR)
        raise RuntimeError(f'Matrix login failed: {login}')

    await client.sync()
    client.add_event_callback(message_callback, RoomMessageText)

async def output(text):
    try:
        if client is None:
            await asyncio.wait_for(login(), timeout=NETWORK_TIMEOUT_SECONDS)
        await asyncio.wait_for(client.room_send(
            room_id=config['matrix_dm_room_id'],
            message_type="m.room.message",
            content={"msgtype": "m.text",
                     "body": text,
                     "format": "org.matrix.custom.html",
                     "formatted_body": markdown.markdown(text)}
        ), timeout=NETWORK_TIMEOUT_SECONDS)
    except Exception:
        await _drop_client()
        raise

async def get_data():
    try:
        if client is None:
            await asyncio.wait_for(login(), timeout=NETWORK_TIMEOUT_SECONDS)
        await asyncio.wait_for(client.sync(), timeout=NETWORK_TIMEOUT_SECONDS)
    except Exception:
        await _drop_client()
        raise

    if len(message_queue) > 0:
        message = message_queue.pop(0)
        return message
    return None
