import os
import sqlite3
import time
from sqlite3 import Connection

import Logging

config = {}
client = None
tool_functions = ['store_memory']

MEMORY_DB_VERSION = 1

def update_db(connection: Connection, version):
    Logging.log('Database migration running. Stay calm - everything is under control. Hopefully.')
    cursor = connection.cursor()
    while version < MEMORY_DB_VERSION:
        Logging.log(f'Migrating from version {version}...', severity=Logging.Severity.DEBUG)
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'DBMigrations', f'{version}.sql'),
                  'r') as migration_file:
            cursor.executescript(migration_file.read())
        connection.commit()
        version += 1
    cursor.close()


def init_db(context_db):
    con = sqlite3.connect(context_db)
    update_db(con, 0)


def get_db_connection(context_db):
    if not os.path.isfile(context_db):
        init_db(context_db)
    con = sqlite3.connect(context_db)
    cur = con.cursor()
    res = cur.execute("SELECT value FROM system WHERE key='VERSION'")
    db_version = res.fetchone()[0]
    cur.close()
    if db_version != MEMORY_DB_VERSION:
        update_db(con, db_version)
    return con


def save_memory_to_db(connection: Connection, memory):
    cursor = connection.cursor()
    cursor.execute('INSERT INTO memories (timestamp, content) VALUES (?,?)',
                   [int(time.time()), memory])
    rowid = cursor.lastrowid
    connection.commit()
    cursor.close()
    return rowid


def get_memories_from_db(connection: Connection):
    cursor = connection.cursor()
    cursor.execute('SELECT content FROM memories')
    memories = cursor.fetchall()
    return [memory[0] for memory in memories]


def get_tooling():
    tools = [{
        "type": "function",
        "function": {
            "name": "store_memory",
            "description": "Store a core memory that you as AI assistant can always access",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory": {
                        "type": "string",
                        "description": "Short summary of the memory that you want to remember - only a few words or a single sentence"
                    }
                },
                "required": ["memory"]
            }
        }
    }]

    return tools


def run_tool(function_name, parameters):
    if function_name == 'store_memory':
        memory = parameters['memory']
        connection = get_db_connection(config['memory_database'])
        save_memory_to_db(connection, memory)

        return 'Memory has been stored.'
    return 'Tool not found.'

def get_system_prompt_content():
    connection = get_db_connection(config['memory_database'])
    memories = get_memories_from_db(connection)
    prompt = 'Core Memories:'
    for memory in memories:
        prompt += f'\n    * {memory}'
    return prompt