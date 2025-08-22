import datetime

from caldav.davclient import get_davclient
from datetime import date, timedelta

config = {}

def get_todays_events(url, username, password):
    with get_davclient(username=username, password=password,url=url) as client:
        calendar = client.calendar(url=url)

        events = calendar.search(
            event=True,
            start=date.today(),
            end=date.today() + timedelta(days=1) - timedelta(microseconds=1),
            expand=True)
    return events

async def get_data():
    summary = ''
    for calendar in config['calendars']:
        events = get_todays_events(calendar['url'], calendar['username'], calendar['password'])
        if len(events) > 0:
            summary += f'====================\n{calendar['topic']}:\n'
            for event in events:
                summary += f'    Summary: {event.component['summary']}\n    Begin: {event.component['dtstart'].dt.isoformat()}\n    End: {event.component['dtend'].dt.isoformat()}\n\n'
    print(summary)
    return summary
