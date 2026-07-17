"""Input module that reports on currently tracked parcels without touching
the ParcelTracking database's schema - it just reads the table that
ParcelTracking owns and maintains (migrations, polling, updates all live
there). Mirrors the Email/EmailStatus split: ParcelTracking does the work,
ParcelStatus is the read-only summary used by the morning briefing.
"""

import os
import sqlite3
import time

config = {}


async def get_data():
    parcel_database = config['parcel_database']
    if not os.path.isfile(parcel_database):
        return None

    connection = sqlite3.connect(parcel_database)
    cursor = connection.cursor()
    cursor.execute('SELECT carrier, tracking_number, description, last_status, last_status_time '
                   'FROM parcels WHERE active=1 ORDER BY created')
    rows = cursor.fetchall()
    cursor.close()
    connection.close()

    if not rows:
        return None

    now = int(time.time())
    lines = ['Parcels currently being tracked:']
    for carrier, tracking_number, description, last_status, last_status_time in rows:
        if last_status and last_status_time:
            status_time = time.strftime('%Y-%m-%d %H:%M', time.localtime(last_status_time))
            lines.append(f'- {carrier} {tracking_number} ({description}): {last_status} '
                        f'(status from {status_time})')
        else:
            lines.append(f'- {carrier} {tracking_number} ({description}): no status yet')

    return '\n'.join(lines)
