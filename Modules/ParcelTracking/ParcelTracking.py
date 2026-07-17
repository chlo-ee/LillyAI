import os
import re
import sqlite3
import time
from sqlite3 import Connection

import Logging
from Modules.ParcelTracking import Detection
from Modules.ParcelTracking import Carriers

config = {}
tool_functions = ['track_parcel', 'update_parcel_status', 'get_parcel_status']

VALID_CARRIERS = ('DHL', 'DPD', 'Amazon')

PARCEL_DB_VERSION = 1

def update_db(connection: Connection, version):
    Logging.log('Database migration running. Stay calm - everything is under control. Hopefully.')
    cursor = connection.cursor()
    while version < PARCEL_DB_VERSION:
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
    if db_version != PARCEL_DB_VERSION:
        update_db(con, db_version)
    return con


def get_parcel(connection: Connection, tracking_number):
    cursor = connection.cursor()
    cursor.execute('SELECT tracking_number, carrier, description, created, last_status, last_status_time, '
                   'last_polled, active FROM parcels WHERE tracking_number=?', [tracking_number])
    row = cursor.fetchone()
    cursor.close()
    return row


def insert_parcel(connection: Connection, tracking_number, carrier, description, created):
    cursor = connection.cursor()
    cursor.execute('INSERT INTO parcels (tracking_number, carrier, description, created, last_status, '
                   'last_status_time, last_polled, active) VALUES (?,?,?,?,?,?,?,?)',
                   [tracking_number, carrier, description, created, None, None, None, 1])
    connection.commit()
    cursor.close()


def update_description(connection: Connection, tracking_number, description):
    cursor = connection.cursor()
    cursor.execute('UPDATE parcels SET description=? WHERE tracking_number=?', [description, tracking_number])
    connection.commit()
    cursor.close()


def set_status(connection: Connection, tracking_number, status, timestamp, delivered=False):
    cursor = connection.cursor()
    if delivered:
        cursor.execute('UPDATE parcels SET last_status=?, last_status_time=?, active=0 WHERE tracking_number=?',
                       [status, timestamp, tracking_number])
    else:
        cursor.execute('UPDATE parcels SET last_status=?, last_status_time=? WHERE tracking_number=?',
                       [status, timestamp, tracking_number])
    connection.commit()
    cursor.close()


def set_last_polled(connection: Connection, tracking_number, timestamp):
    cursor = connection.cursor()
    cursor.execute('UPDATE parcels SET last_polled=? WHERE tracking_number=?', [timestamp, tracking_number])
    connection.commit()
    cursor.close()


def deactivate(connection: Connection, tracking_number):
    cursor = connection.cursor()
    cursor.execute('UPDATE parcels SET active=0 WHERE tracking_number=?', [tracking_number])
    connection.commit()
    cursor.close()


def get_active_parcels(connection: Connection):
    cursor = connection.cursor()
    cursor.execute('SELECT carrier, tracking_number, description, last_status FROM parcels '
                   'WHERE active=1 ORDER BY created')
    rows = cursor.fetchall()
    cursor.close()
    return rows


def get_parcels_for_status(connection: Connection, finished_cutoff):
    cursor = connection.cursor()
    cursor.execute('SELECT carrier, tracking_number, description, last_status, last_status_time, active '
                   'FROM parcels WHERE active=1 OR (active=0 AND last_status_time>=?) ORDER BY created',
                   [finished_cutoff])
    rows = cursor.fetchall()
    cursor.close()
    return rows


def get_pollable_due(connection: Connection, poll_cutoff):
    cursor = connection.cursor()
    placeholders = ','.join('?' for _ in Carriers.POLLABLE_CARRIERS)
    cursor.execute(f'SELECT tracking_number, carrier, description, last_status FROM parcels '
                   f'WHERE active=1 AND carrier IN ({placeholders}) AND (last_polled IS NULL OR last_polled<?)',
                   [*Carriers.POLLABLE_CARRIERS, poll_cutoff])
    rows = cursor.fetchall()
    cursor.close()
    return rows


def get_stale_active(connection: Connection, created_cutoff):
    cursor = connection.cursor()
    cursor.execute('SELECT tracking_number, carrier, description FROM parcels WHERE active=1 AND created<?',
                   [created_cutoff])
    rows = cursor.fetchall()
    cursor.close()
    return rows


def _normalize_carrier(carrier):
    if not carrier:
        return None
    for valid in VALID_CARRIERS:
        if valid.lower() == carrier.strip().lower():
            return valid
    return None


def _clean_tracking_number(tracking_number):
    return re.sub(r'\s+', '', tracking_number or '')


def _format_age(timestamp, now):
    delta = now - timestamp
    if delta < 60:
        return 'just now'
    minutes = delta // 60
    if minutes < 60:
        return f'{minutes} minute(s) ago'
    hours = delta // 3600
    if hours < 24:
        return f'{hours} hour(s) ago'
    days = delta // 86400
    return f'{days} day(s) ago'


def _track_parcel(parameters):
    carrier = _normalize_carrier(parameters.get('carrier'))
    if carrier is None:
        return f"Unknown carrier '{parameters.get('carrier')}'. Valid carriers are: {', '.join(VALID_CARRIERS)}."

    tracking_number = _clean_tracking_number(parameters.get('tracking_number'))
    description = parameters.get('description', '')

    if not Detection.validate(carrier, tracking_number):
        return (f"'{tracking_number}' does not look like a valid {carrier} tracking number - please "
                f"double check the email and try again.")

    connection = get_db_connection(config['parcel_database'])
    existing = get_parcel(connection, tracking_number)
    if existing is not None:
        update_description(connection, tracking_number, description)
        last_status = existing[4] or 'no status yet'
        return f"'{tracking_number}' ({carrier}) is already being tracked. Last known status: {last_status}."

    now = int(time.time())
    insert_parcel(connection, tracking_number, carrier, description, now)

    if carrier not in Carriers.POLLABLE_CARRIERS:
        return (f"Now tracking {carrier} parcel {tracking_number} ({description}). Amazon offers no live "
                f"tracking - status will be updated from Amazon's follow-up emails.")

    try:
        result = Carriers.poll(carrier, tracking_number, config)
        status = result['status']
        set_status(connection, tracking_number, status, now, delivered=result.get('delivered'))
        return f"Now tracking {carrier} parcel {tracking_number} ({description}). Current status: {status}."
    except Carriers.CarrierError:
        return (f"Now tracking {carrier} parcel {tracking_number} ({description}). No status available "
                f"from the carrier yet.")


def _update_parcel_status(parameters):
    tracking_number = _clean_tracking_number(parameters.get('tracking_number'))
    status = parameters.get('status')
    delivered = parameters.get('delivered')

    connection = get_db_connection(config['parcel_database'])
    existing = get_parcel(connection, tracking_number)
    if existing is None:
        return f"No parcel with tracking number '{tracking_number}' is currently tracked - register it with track_parcel first."

    now = int(time.time())
    set_status(connection, tracking_number, status, now, delivered=delivered)
    if delivered:
        return f"Updated '{tracking_number}': {status} (marked as delivered, tracking finished)."
    return f"Updated '{tracking_number}': {status}."


def _get_parcel_status():
    connection = get_db_connection(config['parcel_database'])
    now = int(time.time())
    cutoff = now - 7 * 24 * 60 * 60
    rows = get_parcels_for_status(connection, cutoff)
    if not rows:
        return 'No parcels are currently being tracked.'

    lines = []
    for carrier, tracking_number, description, last_status, last_status_time, active in rows:
        status_text = last_status if last_status else 'no status yet'
        label = '' if active else ' (delivered/finished)'
        if last_status_time:
            age = _format_age(last_status_time, now)
            lines.append(f'- {carrier} {tracking_number} ({description}): {status_text}{label} - {age}')
        else:
            lines.append(f'- {carrier} {tracking_number} ({description}): {status_text}{label}')
    return '\n'.join(lines)


def get_tooling():
    tools = [{
        "type": "function",
        "function": {
            "name": "track_parcel",
            "description": "Register a parcel/shipment for automatic tracking.",
            "parameters": {
                "type": "object",
                "properties": {
                    "carrier": {
                        "type": "string",
                        "enum": ["DHL", "DPD", "Amazon"],
                        "description": "The carrier shipping the parcel"
                    },
                    "tracking_number": {
                        "type": "string",
                        "description": "The exact tracking number"
                    },
                    "description": {
                        "type": "string",
                        "description": "What the parcel is / who it's from"
                    }
                },
                "required": ["carrier", "tracking_number", "description"]
            }
        }
    }, {
        "type": "function",
        "function": {
            "name": "update_parcel_status",
            "description": "Update the status of an already tracked parcel from information found in an "
                           "email. Mainly used for Amazon, which cannot be polled.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tracking_number": {
                        "type": "string",
                        "description": "The tracking number of the parcel to update"
                    },
                    "status": {
                        "type": "string",
                        "description": "The new status, e.g. 'out for delivery' or 'delivered'"
                    },
                    "delivered": {
                        "type": "boolean",
                        "description": "Whether the parcel has been delivered"
                    }
                },
                "required": ["tracking_number", "status"]
            }
        }
    }, {
        "type": "function",
        "function": {
            "name": "get_parcel_status",
            "description": "Get the current status of all tracked parcels.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }]

    return tools


def run_tool(function_name, parameters):
    if function_name == 'track_parcel':
        return _track_parcel(parameters)
    if function_name == 'update_parcel_status':
        return _update_parcel_status(parameters)
    if function_name == 'get_parcel_status':
        return _get_parcel_status()
    return 'Tool not found.'


def get_system_prompt_content():
    connection = get_db_connection(config['parcel_database'])
    prompt = ('You can track parcels with the track_parcel tool. When an email contains shipment tracking '
              "numbers (often flagged by a '[System hint: ...]' line), register genuine shipments to the "
              'user with track_parcel (carrier, exact tracking number, short description) - ignore return '
              'labels and pure marketing. If an Amazon email is a status update about an already-registered '
              'order, call update_parcel_status instead.\n'
              'Currently tracked parcels:')
    active_parcels = get_active_parcels(connection)
    if not active_parcels:
        prompt += ' none'
        return prompt
    for carrier, tracking_number, description, last_status in active_parcels:
        status_text = last_status if last_status else 'no status yet'
        prompt += f'\n    * {carrier} {tracking_number} ({description}): {status_text}'
    return prompt


async def get_data():
    poll_minutes = config.get('poll_minutes', 30)
    connection = get_db_connection(config['parcel_database'])
    now = int(time.time())
    lines = []

    poll_cutoff = now - poll_minutes * 60
    for tracking_number, carrier, description, last_status in get_pollable_due(connection, poll_cutoff):
        # last_polled is set before the call so a permanently broken endpoint
        # isn't hammered every tick even when every poll raises.
        set_last_polled(connection, tracking_number, now)
        try:
            result = Carriers.poll(carrier, tracking_number, config)
        except Carriers.CarrierError as exception:
            Logging.log(f'Polling {carrier} parcel {tracking_number} failed: {exception}',
                       severity=Logging.Severity.DEBUG)
            continue

        status = result['status']
        delivered = result.get('delivered')
        if status != last_status:
            set_status(connection, tracking_number, status, now, delivered=delivered)
            line = f'{carrier} parcel {tracking_number} ({description}): {status}'
            if delivered:
                line += ' — delivered, tracking finished.'
            lines.append(line)

    stale_cutoff = now - 45 * 24 * 60 * 60
    for tracking_number, carrier, description in get_stale_active(connection, stale_cutoff):
        deactivate(connection, tracking_number)
        lines.append(f'{carrier} parcel {tracking_number} ({description}): tracking stopped after 45 days '
                    f'without delivery.')

    return '\n'.join(lines) if lines else None
