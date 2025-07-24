import json

import requests

import Logging
from Logging import Severity
from Modules.Ollama import ContextManager


class Ollama:
    def __init__(self, endpoint, model, context_db):
        self.endpoint = endpoint
        self.model = model
        self.context_db = context_db

    def chat(self, content, prompt=None, tools=None):
        tool_descriptions = []
        if tools is not None:
            for tool in tools:
                tool_descriptions.append(tool['module'].get_tooling())

        con = ContextManager.get_db_connection(self.context_db)
        stored_messages = ContextManager.get_message_list(con)
        messages = []
        msg_idx = 0

        for stored_message in stored_messages:
            msg_idx += 1
            if not 'tool_context' in stored_message:
                messages.append(stored_message)
                continue

            dismiss_message = False
            for tool_name in stored_message['tool_context']:
                for tool in tools:
                    tool_module = tool['module']
                    if tool_name == tool_module.MODULE_NAME:
                        if 'context_decay' in tool:
                            if tool['context_decay'] < len(stored_messages) - msg_idx:
                                dismiss_message = True
            if not dismiss_message:
                messages.append(stored_message)

        if prompt is not None:
            user_message = {
                'role': 'user',
                'content': f'{prompt}\n\n{content}'
            }
        else:
            user_message = {
                'role': 'user',
                'content': content
            }
        user_message_rowid = ContextManager.save_message_to_db(con, user_message)
        messages.append(user_message)
        reply_received = False
        called_tools = []

        while not reply_received:
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "think": True
            }
            if len(tool_descriptions) > 0:
                payload['tools'] = tool_descriptions
            response = requests.post(f'{self.endpoint}/chat', json=payload)
            Logging.log(response.json(), severity=Severity.DEBUG)
            reply = response.json()['message']
            reply['content'] = reply['content'].lstrip().rstrip()

            if 'tool_calls' in reply and len(reply['tool_calls']) > 0:
                tool_replies = []
                for call in reply['tool_calls']:
                    function = call['function']
                    for tool in tools:
                        tool_module = tool['module']
                        if not tool_module.MODULE_NAME in called_tools:
                            called_tools.append(tool_module.MODULE_NAME)

                        if tool_module.tool_function == function['name']:
                            tool_result = tool_module.run_tool(function['arguments'])
                            message = {
                                'role': 'tool',
                                'content': tool_result
                            }
                            tool_replies.append(message)
                reply['tool_context'] = called_tools
                messages.append(reply)
                ContextManager.save_message_to_db(con, reply)
                user_message['tool_context'] = called_tools
                ContextManager.alter_db_message(con, user_message, user_message_rowid)
                for tool_reply in tool_replies:
                    tool_reply['tool_context'] = called_tools
                    messages.append(tool_reply)
                    ContextManager.save_message_to_db(con, tool_reply)
            else:
                reply['tool_context'] = called_tools
                messages.append(reply)
                ContextManager.save_message_to_db(con, reply)

            reply_received = len(reply['content']) > 0

        con.commit()
        con.close()
        return reply["content"], prompt
