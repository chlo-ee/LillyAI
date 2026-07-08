"""
Messenger is a tool module that files "compose requests" into the Matrix drafts room for
LillyVoice to pick up: it writes the actual message draft in the user's voice, and the user
must approve it with a 👍 reaction there before anything is sent to the contact. This module
requires a Matrix access token for Lilly's own account.
"""

import time
import urllib.parse

import requests

COMPOSE_META_KEY = "ee.chlo.lilly.compose"

config = {}
tool_functions = ['compose_message']


def get_tooling():
    tools = [{
        "type": "function",
        "function": {
            "name": "compose_message",
            "description": "Have a message drafted and sent to one of the user's contacts (e.g. via "
                            "WhatsApp/Signal/Telegram). This only files a DRAFT in the user's drafts room - "
                            "the user must approve it with a 👍 reaction before it is actually sent. Use it "
                            "when the user asks you to send, write or tell something to a person.",
            "parameters": {
                "type": "object",
                "properties": {
                    "contact": {
                        "type": "string",
                        "description": "Name of the person or chat the message is for, as the user said it"
                    },
                    "message": {
                        "type": "string",
                        "description": "What the message should convey, in the user's language - the intent, "
                                        "not necessarily the final wording"
                    }
                },
                "required": ["contact", "message"]
            }
        }
    }]

    return tools


def run_tool(tool_name, parameters):
    if tool_name != 'compose_message':
        return "Tool not found."

    try:
        contact = parameters['contact'].strip()
        message = parameters['message'].strip()
        if not contact or not message:
            return "Compose request failed: contact and message must not be empty."

        txn_id = f"lilly-compose-{int(time.time() * 1000)}"
        room_id = urllib.parse.quote(config['drafts_room_id'])
        response = requests.put(
            f"{config['matrix_homeserver']}/_matrix/client/v3/rooms/{room_id}/send/m.room.message/{txn_id}",
            headers={"Authorization": f"Bearer {config['matrix_token']}"},
            json={
                "msgtype": "m.text",
                "body": f"📨 Compose request for '{contact}': {message}",
                COMPOSE_META_KEY: {"contact": contact, "instruction": message}
            },
            timeout=15
        )
        response.raise_for_status()
    except Exception as error:
        return f"Compose request failed: {error}"

    return (f"Draft requested. A draft of the message to {contact} will appear in the user's drafts room "
            f"shortly - the user has to approve it with a 👍 reaction there before it is sent. Tell the user "
            f"that.")
