from Modules.Ollama.Ollama import Ollama

config = {}
ollama_instance = None

def process_data(text, prompt, tools):
    global ollama_instance
    if ollama_instance is None:
        ollama_instance = Ollama(config['ollama_endpoint'], config['ollama_model'], config['context_database'])
    return ollama_instance.chat(content=text, prompt=prompt, tools=tools)

if __name__ == "__main__":
    print('This module is part of LillyAI and can not be run individually.')