"""Input module that reports on UNREAD mail (count + senders/subjects)
without touching the messages - it uses BODY.PEEK so nothing gets marked
as read (unlike the Email module, which consumes messages for
summarising); used by the morning-briefing route.
"""

import email

import imapclient

config = {}


async def get_data():
    # timeout: a stalled IMAP server must never hang the (synchronous) event
    # loop forever - a timeout error is caught by the scheduler and retried
    # on the next tick.
    with imapclient.IMAPClient(config['imap_host'], timeout=30) as client:
        client.login(config['imap_user'], config['imap_password'])
        client.select_folder('INBOX', readonly=True)
        messages = client.search(['UNSEEN'])
        if not messages:
            return None

        response = client.fetch(messages[:10], ['BODY.PEEK[HEADER.FIELDS (SUBJECT FROM)]'])

        lines = []
        for msgid in messages[:10]:
            msg_data = response.get(msgid, {})
            header_bytes = None
            for key, value in msg_data.items():
                if b'HEADER' in key:
                    header_bytes = value
                    break
            if header_bytes is None:
                continue

            msg = email.message_from_bytes(header_bytes)
            from_ = msg.get('From', '')
            subject = msg.get('Subject', '')
            lines.append(f"- {from_}: {subject}")

        total = len(messages)
        result = [f"{total} unread email(s):"]
        result.extend(lines)
        if total > 10:
            result.append(f"... and {total - 10} more")

        return "\n".join(result)
