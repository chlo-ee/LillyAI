"""
WebSearch is a tool module that queries a SearXNG metasearch instance over its JSON API,
letting the LLM look up current information from the live web. It requires a reachable
SearXNG instance with the JSON output format enabled (`format=json` in SearXNG's settings).
"""

import requests

config = {}
tool_functions = ['search_web']


def get_tooling():
    tools = [{
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the live web via a metasearch engine. Use this for current events, "
                            "facts you are unsure about, and anything the user asks you to look up.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query, as you would type it into a search engine"
                    }
                },
                "required": ["query"]
            }
        }
    }]

    return tools


def run_tool(tool_name, parameters):
    if tool_name != 'search_web':
        return "Tool not found."

    try:
        query = parameters['query']
        response = requests.get(
            f"{config['searxng_endpoint']}/search",
            params={"q": query, "format": "json"},
            timeout=15
        )
        response.raise_for_status()
        data = response.json()
    except Exception as error:
        return f"Web search failed: {error}"

    max_results = config.get('max_results', 5)

    reply = ''
    answers = data.get('answers')
    if answers:
        first_answer = answers[0]
        if isinstance(first_answer, dict):
            first_answer = first_answer.get('answer', '')
        else:
            first_answer = str(first_answer)
        reply += f"Answer: {first_answer}\n\n"

    results = data.get('results')
    if results:
        for i, result in enumerate(results[:max_results], start=1):
            title = result.get('title', '')
            url = result.get('url', '')
            content = result.get('content', '')
            if len(content) > 300:
                content = content[:300] + '...'
            reply += f"{i}. {title}\n{url}\n{content}\n\n"

    if not reply:
        return "No results found."

    return reply.strip()
