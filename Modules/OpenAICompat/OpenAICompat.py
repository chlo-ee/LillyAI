from Modules.OpenAICompat.OpenAICompatInstance import OpenAICompatInstance

config = {}
instance = None

def process_data(text, prompt, tools, system_prompt_additions):
    global instance
    if instance is None:
        instance = OpenAICompatInstance(config['endpoint'], config['model'], config['context_database'],
                                        config['short_term_memory_minutes'],
                                        disable_thinking=config.get('disable_thinking', False))
    return instance.chat(content=text, prompt=prompt, tools=tools, system_prompt_additions=system_prompt_additions)
