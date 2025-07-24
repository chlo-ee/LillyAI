import json
import os
import sqlite3
import time
from sqlite3 import Connection

import Logging
import PromptTools
from Logging import Severity

CONTEXT_DB_VERSION = 1

def update_db(connection: Connection, version):
    Logging.log('Database migration running. Stay calm - everything is under control. Hopefully.')
    cursor = connection.cursor()
    while version < CONTEXT_DB_VERSION:
        Logging.log(f'Migrating from version {version}...', severity=Severity.DEBUG)
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
    if db_version != CONTEXT_DB_VERSION:
        update_db(con, db_version)
    return con


def get_message_list(connection: Connection):
    cursor = connection.cursor()
    result = cursor.execute('SELECT role, content, tool_calls FROM messages')
    db_messages = result.fetchall()
    cursor.close()

    messages = [
        {
            'role': 'system',
            'content': PromptTools.build_base_prompt()
        }
    ]
    for db_message in db_messages:
        message = {
            'role': db_message[0],
            'content': db_message[1]
        }
        if len(db_message[2]) > 0:
            message['tool_calls'] = json.loads(db_message[2])
        messages.append(message)
    return messages


def save_message_to_db(connection: Connection, message):
    tool_calls = ''
    if 'tool_calls' in message:
        tool_calls = json.dumps(message['tool_calls'])
    cursor = connection.cursor()
    cursor.execute('INSERT INTO messages (timestamp, role, content, tool_calls) VALUES (?,?,?,?)',
                   [int(time.time()), message['role'], message['content'], tool_calls])
    cursor.close()