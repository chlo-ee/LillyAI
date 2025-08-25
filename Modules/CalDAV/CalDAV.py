import datetime

from caldav.davclient import get_davclient
from datetime import date, timedelta

config = {}
tool_function = 'get_calendar_events'

def get_events(url, username, password, begin, end):
    with get_davclient(username=username, password=password,url=url) as client:
        calendar = client.calendar(url=url)

        events = calendar.search(
            event=True,
            start=begin,
            end=end,
            expand=True)
    return events

def is_date(dt) -> bool:
    return type(dt) is date or dt.hour == dt.minute == dt.second == dt.microsecond == 0

def get_caldav_summary(begin, end):
    summary = ''
    for calendar in config['calendars']:
        events = get_events(calendar['url'], calendar['username'], calendar['password'], begin, end)
        if len(events) > 0:
            summary += f'====================\n{calendar['topic']}:\n'
            for event in events:
                dtstart = event.component['dtstart'].dt
                dtend = event.component['dtend'].dt
                delta = dtend - dtstart

                # If the event is for the whole day and ONLY for today, skip adding Begin and End timestamps
                if is_date(dtstart) and is_date(dtend) and delta.days == 1:
                    summary += f'    Summary: {event.component['summary']}\n    Date: {dtstart.isoformat()}\n\n'
                else:
                    summary += f'    Summary: {event.component['summary']}\n    Begin: {dtstart.isoformat()}\n    End: {dtend.isoformat()}\n\n'
    return summary

async def get_data():
    summary = get_caldav_summary(date.today(), date.today() + timedelta(days=1))
    print(summary)
    return summary

def get_tooling():
    tool = {
        "type": "function",
        "function": {
            "name": tool_function,
            "description": "Get events from all the user's calendars for a given timespan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date_begin": {
                        "type": "string",
                        "description": "ISO formatted date - Begin date of the timespan to search"
                    },
                    "date_end": {
                        "type": "string",
                        "description": "ISO formatted date - End date of the timespan to search"
                    }
                },
                "required": ["date_begin", "date_end"]
            }
        }
    }

    return tool

def run_tool(parameters):
    begin_date = date.fromisoformat(parameters['date_begin'])
    end_date = date.fromisoformat(parameters['date_end'])
    summary = get_caldav_summary(begin_date, end_date)
    return "No events in the given timespan" if len(summary) == 0 else summary