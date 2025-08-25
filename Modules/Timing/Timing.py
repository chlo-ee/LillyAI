import datetime
import os
import sqlite3
import time
from sqlite3 import Connection

import Logging

config = {}
client = None
tool_functions = ['schedule_event']

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


def save_event_to_db(connection: Connection, target_time, action):
    cursor = connection.cursor()
    cursor.execute('INSERT INTO events (time, action) VALUES (?,?)',
                   [int(target_time.timestamp()), action])
    rowid = cursor.lastrowid
    connection.commit()
    cursor.close()
    return rowid


def delete_event_from_db(connection: Connection, rowid):
    cursor = connection.cursor()
    cursor.execute('DELETE FROM events WHERE _rowid_=?',
                   [rowid])
    rowid = cursor.lastrowid
    connection.commit()
    cursor.close()
    return rowid


def get_events_from_db(connection: Connection):
    cursor = connection.cursor()
    cursor.execute('SELECT _rowid_, time, action FROM events')
    events = cursor.fetchall()
    return [(event[1], event[2], event[0]) for event in events]


def get_tooling():
    tools = [{
        "type": "function",
        "function": {
            "name": "schedule_event",
            "description": "Schedule an event. YOU (the assistant) will be reminded of the action at the provided datetime.",
            "parameters": {
                "type": "object",
                "properties": {
                    "datetime": {
                        "type": "string",
                        "description": "ISO formatted datetime when the action will be sent to the LLM"
                    },
                    "action": {
                        "type": "string",
                        "description": "The string that YOU (the assistant) will be reminded of at the given time"
                    }
                },
                "required": ["datetime", "action"]
            }
        }
    }]

    return tools


def run_tool(function_name, parameters):
    if function_name == 'schedule_event':
        time = datetime.datetime.fromisoformat(parameters['datetime'])
        action = parameters['action']
        connection = get_db_connection(config['timing_database'])
        save_event_to_db(connection, time, action)
        return 'Action has been scheduled.'
    return 'Tool not found.'


def get_system_prompt_content():
    now = datetime.datetime.now().astimezone()
    prompt = f'Current date and time: {now.isoformat(timespec='seconds')}'
    return prompt

async def get_data():
    connection = get_db_connection(config['timing_database'])
    result = ''
    events = get_events_from_db(connection)
    for event in events:
        if time.time() - event[0] >= 0:
            delete_event_from_db(connection, event[2])
            result = event[1]
            break
    return result