import datetime
import uuid

from caldav.davclient import get_davclient
from datetime import date, timedelta

config = {}
tool_functions = ['get_calendar_events', 'add_calendar_event']

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
    calendar_names = []
    for calendar in config["calendars"]:
        calendar_names.append(calendar["topic"])

    tools = [{
        "type": "function",
        "function": {
            "name": "get_calendar_events",
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
    }, {
        "type": "function",
        "function": {
            "name": "add_calendar_event",
            "description": "Add an event to a calendar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "datetime_begin": {
                        "type": "string",
                        "description": "ISO formatted datetime - Begin of the event"
                    },
                    "datetime_end": {
                        "type": "string",
                        "description": "ISO formatted datetime - End of the event"
                    },
                    "summary": {
                        "type": "string",
                        "description": "Short summary of the event"
                    },
                    "calendar": {
                        "type": "string",
                        "description": "The calendar to save the event in",
                        "enum": calendar_names
                    }
                },
                "required": ["datetime_begin", "datetime_end", "summary", "calendar"]
            }
        }
    }]

    return tools

def create_event(begin, end, summary, calendar):
    calendar_config = None
    for c in config["calendars"]:
        if c["topic"] == calendar:
            calendar_config = c
            break
    if calendar_config is None:
        return 'Invalid calendar selected'

    with get_davclient(username=calendar_config['username'], password=calendar_config['password'], url=calendar_config['url']) as client:
        cal = client.calendar(url=calendar_config['url'])
        cal.save_event(
            dtstart=begin,
            dtend=end,
            uid=str(uuid.uuid4()),
            summary=summary)

    return 'Event saved.'

def run_tool(tool_name, parameters):
    if tool_name == 'get_calendar_events':
        try:
            begin_date = date.fromisoformat(parameters['date_begin'])
        except ValueError:
            try:
                begin_date = datetime.datetime.fromisoformat(parameters['date_begin'])
            except:
                return "Invalid date_begin parameter: Not A date in ISO format."
        try:
            end_date = date.fromisoformat(parameters['date_end'])
        except ValueError:
            try:
                end_date = datetime.datetime.fromisoformat(parameters['date_end'])
            except:
                return "Invalid date_end parameter: Not A date in ISO format."
        summary = get_caldav_summary(begin_date, end_date)
        return "No events in the given timespan" if len(summary) == 0 else summary
    elif tool_name == 'add_calendar_event':
        begin_datetime = datetime.datetime.fromisoformat(parameters['datetime_begin'])
        end_datetime = datetime.datetime.fromisoformat(parameters['datetime_end'])
        summary = parameters['summary']
        calendar = parameters['calendar']
        create_event(begin_datetime, end_datetime, summary, calendar)
        return "Event created."

    return "Tool not found."