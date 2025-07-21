user_name = ''
ai_name = ''
language = ''
personality = ''

def build_base_prompt():
    prompt = f'''{personality}
!!! ALWAYS REPLY IN {language.upper()} !!!

Your name: {ai_name}
User's name: {user_name}
    '''
    return prompt