import asyncio

from nio import AsyncClient, LoginResponse, MatrixRoom, RoomMessageText

config = {}
client = None
logged_in = False
message_queue = []

async def message_callback(room: MatrixRoom, event: RoomMessageText) -> None:
    if event.sender == config['matrix_user']:
        return
    print(
        f"Message received in room {room.display_name}\n"
        f"{room.user_name(event.sender)} | {event.body}"
    )
    if room.room_id == config['matrix_dm_room_id']:
        message_queue.append(event.body)

async def login():
    global client
    client = AsyncClient(config['matrix_homeserver'], config['matrix_user'])
    login = await client.login(config['matrix_password'])

    if not isinstance(login, LoginResponse):
        print("Login failed:", login)
        return

    await client.sync()
    client.add_event_callback(message_callback, RoomMessageText)

async def output(text):
    if client is None:
        await login()
    await client.room_send(
        room_id=config['matrix_dm_room_id'],
        message_type="m.room.message",
        content={"msgtype": "m.text", "body": f"{text}"}
    )

async def get_data():
    if client is None:
        await login()

    await client.sync()
    if len(message_queue) > 0:
        message = message_queue.pop(0)
        return message
    return None

if __name__ == "__main__":
    print('This module is part of LillyAI and can not be run individually.')