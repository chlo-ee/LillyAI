import json

import requests

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
                tool_descriptions.append(tool.get_tooling())

        con = ContextManager.get_db_connection(self.context_db)
        messages = ContextManager.get_message_list(con)

        if prompt is not None:
            message = {
                'role': 'user',
                'content': f'{prompt}\n\n{content}'
            }
        else:
            message = {
                'role': 'user',
                'content': content
            }
        ContextManager.save_message_to_db(con, message)
        messages.append(message)
        reply_received = False

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
            print(json.dumps(payload))
            print(response.json())
            reply = response.json()['message']
            reply['content'] = reply['content'].lstrip().rstrip()
            messages.append(reply)
            ContextManager.save_message_to_db(con, reply)

            if 'tool_calls' in reply and len(reply['tool_calls']) > 0:
                for call in reply['tool_calls']:
                    function = call['function']
                    for tool in tools:
                        if tool.tool_function == function['name']:
                            tool_result = tool.run_tool(function['arguments'])
                            message = {
                                'role': 'tool',
                                'content': tool_result
                            }
                            messages.append(message)
                            ContextManager.save_message_to_db(con, message)
            reply_received = len(reply['content']) > 0

        con.commit()
        con.close()
        return reply["content"], prompt
