import asyncio

import Logging
from Logging import Severity


class Router:
    def __init__(self, inputs: list, processors: list, outputs: list, prompt: str|None, name: str):
        self.inputs = inputs
        self.processors = processors
        self.outputs = outputs
        self.prompt = prompt
        self.name = name

    def verify(self):
        is_valid = True

        if len(self.inputs) == 0:
            Logging.log(f'Route {self.name} is missing input modules and can therefore never work.', severity=Severity.FATAL)
            is_valid = False

        for input_module in self.inputs:
            if not hasattr(input_module, 'get_data'):
                Logging.log(f'Route {self.name}: Module {input_module.MODULE_NAME} can not be used as input module.', severity=Severity.FATAL)
                is_valid = False

        for processor in self.processors:
            processor_module = processor['module']
            processor_tools = processor['tools']
            if not hasattr(processor_module, 'process_data'):
                Logging.log(f'Route {self.name}: Module {processor_module.MODULE_NAME} can not be used as processor module.', severity=Severity.FATAL)
                is_valid = False
            for tool in processor_tools:
                tool_module = tool['module']
                if not hasattr(tool_module, 'get_tooling') or not hasattr(tool_module, 'run_tool') or not hasattr(tool_module, 'tool_function'):
                    Logging.log(
                        f'Route {self.name} -> {processor_module.MODULE_NAME}: Module {tool_module.MODULE_NAME} can not be used as tool module.', severity=Severity.FATAL)
                    is_valid = False

        for output_module in self.outputs:
            if not hasattr(output_module, 'output'):
                Logging.log(f'Route {self.name}: Module {output_module.MODULE_NAME} can not be used as output module.', severity=Severity.FATAL)
                is_valid = False
        return is_valid


    async def get_input(self):
        for input_module in self.inputs:
            input_data = await input_module.get_data()
            if input_data:
                return input_data
        return None

    def process_data(self, data):
        for processor in self.processors:
            processor_module = processor['module']
            tools = processor['tools']
            data, prompt = processor_module.process_data(data, self.prompt, tools)
        return data

    async def output_data(self, data):
        coroutines = []
        for output_module in self.outputs:
            coroutines.append(output_module.output(data))
        for coroutine in coroutines:
            await coroutine

    async def run(self):
        Logging.log(f'Running router "{self.name}"')
        input_data = await self.get_input()
        if not input_data:
            return

        processed_data = self.process_data(input_data)
        if not processed_data:
            return

        await self.output_data(processed_data)