from Modules.Ollama.OllamaInstance import OllamaInstance

config = {}
ollama_instance = None

def process_data(text, prompt, tools):
    global ollama_instance
    if ollama_instance is None:
        ollama_instance = OllamaInstance(config['ollama_endpoint'], config['ollama_model'], config['context_database'])
    return ollama_instance.chat(content=text, prompt=prompt, tools=tools)