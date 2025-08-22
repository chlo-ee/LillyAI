user_name = ''
ai_name = ''
language = ''
personality = ''

def build_base_prompt(system_prompt_additions=None):
    prompt = f'''{personality}
!!! ALWAYS REPLY IN {language.upper()} !!!

Your name: {ai_name}
User's name: {user_name}
'''

    if system_prompt_additions:
        for addition_module in system_prompt_additions:
            prompt += f'\n\n{addition_module.get_system_prompt_content()}\n'
    return prompt