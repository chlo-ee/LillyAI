import json

import requests

import Logging
from Logging import Severity
from Modules.OpenAICompat import ContextManager

# Safety net: if the server keeps returning empty replies without tool calls,
# give up instead of hammering it forever.
MAX_CHAT_TURNS = 8


class OpenAICompatInstance:
    def __init__(self, endpoint, model, context_db, short_term_memory_minutes):
        self.endpoint = endpoint
        self.model = model
        self.context_db = context_db
        self.short_term_memory_minutes = short_term_memory_minutes

    def chat(self, content, prompt=None, tools=None, system_prompt_additions=None):
        if tools is None:
            tools = []
        tool_descriptions = []
        for tool in tools:
            tool_descriptions.extend(tool['module'].get_tooling())

        con = ContextManager.get_db_connection(self.context_db)
        stored_messages = ContextManager.get_message_list(con, system_prompt_additions, self.short_term_memory_minutes)
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
        reply = None
        called_tools = []

        for _ in range(MAX_CHAT_TURNS):
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False
            }
            if len(tool_descriptions) > 0:
                payload['tools'] = tool_descriptions
            response = requests.post(f'{self.endpoint}/v1/chat/completions', json=payload)
            response.raise_for_status()
            Logging.log(response.json(), severity=Severity.DEBUG)
            reply = response.json()['choices'][0]['message']
            reply['content'] = (reply.get('content') or '').strip()

            if reply.get('tool_calls') and len(reply['tool_calls']) > 0:
                tool_replies = []
                for call in reply['tool_calls']:
                    function = call['function']
                    # OpenAI-compatible: arguments is a JSON string
                    arguments = function['arguments']
                    if isinstance(arguments, str):
                        arguments = json.loads(arguments)

                    tool_result = None
                    for tool in tools:
                        tool_module = tool['module']
                        if function['name'] in tool_module.tool_functions:
                            tool_result = tool_module.run_tool(function['name'], arguments)
                            if not tool_module.MODULE_NAME in called_tools:
                                called_tools.append(tool_module.MODULE_NAME)
                    if tool_result is None:
                        # Answer anyway - an unanswered tool call makes the conversation
                        # invalid for most OpenAI-compatible servers.
                        tool_result = f'Unknown tool: {function["name"]}'

                    message = {
                        'role': 'tool',
                        'tool_call_id': call.get('id', ''),
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

            if len(reply['content']) > 0:
                break
        else:
            Logging.log(f'No final reply from {self.endpoint} after {MAX_CHAT_TURNS} turns - giving up.',
                        severity=Severity.ERROR)

        con.commit()
        con.close()
        return reply['content'], prompt
