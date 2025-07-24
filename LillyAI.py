import asyncio
import importlib
import sys
from enum import Enum

import Logging
import json

import PromptTools
from Logging import Severity
from Router import Router
from Scheduler import Scheduler


class ExitCodes(Enum):
    INVALID_ROUTES = 2

LOGGING_NAME = "Lilly"
modules = {}
routers = []
scheduler = Scheduler()

def configure_module(module, configuration):
    for configuration_item, configuration_value in configuration.items():
        Logging.log(f'Configuring {configuration_item}', severity=Severity.DEBUG)
        module.config[configuration_item] = configuration_value


def import_module(module_name):
    mod = importlib.import_module(f'Modules.{module_name}')
    return mod


def load_modules(module_names, module_configs):
    for module_name in module_names:
        Logging.log(f'Initializing {module_name}')
        module = import_module(module_name)
        modules[module_name] = module
        configure_module(module, module_configs[module_name])


def init_routes(routes):
    Logging.log('Adding routers...')
    for route in routes:
        inputs = route['inputs']
        processors = route['processors']
        outputs = route['outputs']
        prompt = route['prompt'] if 'prompt' in route else None
        name = route['name']

        input_modules = []
        processor_modules = []
        output_modules = []

        for input_name in inputs:
            input_modules.append(modules[input_name])

        for processor_description in processors:
            tools = []
            if 'tools' in processor_description:
                for tool_description in processor_description['tools']:
                    tool = {
                        'module': modules[tool_description['module']]
                    }
                    if 'context_decay' in tool_description:
                        tool['context_decay'] = tool_description['context_decay']
                    tools.append(tool)

            processor_modules.append(
                {
                    "module": modules[processor_description["module"]],
                    "tools": tools
                })

        for output_name in outputs:
            output_modules.append(modules[output_name])

        router = Router(inputs=input_modules, processors=processor_modules, outputs=output_modules, prompt=prompt, name=name)
        if not router.verify():
            sys.exit(ExitCodes.INVALID_ROUTES.value)
        routers.append(router)

        if 'schedule_seconds' in route:
            scheduler.schedule(router, route['schedule_seconds'])


async def init():
    Logging.log('Lilly AI stack is booting.')
    with open('config.json', 'r') as config_fp:
        config = json.load(config_fp)
    Logging.severity_limit = Severity[config['log_level']]
    PromptTools.ai_name = config['assistant_name']
    PromptTools.user_name = config['user_name']
    PromptTools.language = config['language']
    PromptTools.personality = config['personality']
    load_modules(config['modules'], config['module_configs'])
    init_routes(config['routes'])
    await scheduler.start()

if __name__ == '__main__':
    asyncio.run(init())