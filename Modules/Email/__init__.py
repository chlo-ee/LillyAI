import email

import imapclient
from bs4 import BeautifulSoup

config = {}

async def get_data():
    with imapclient.IMAPClient(config['imap_host']) as client:
        client.login(config['imap_user'], config['imap_password'])
        client.select_folder('INBOX')
        messages = client.search(['UNSEEN'])
        if not messages:
            return []
        raw_messages = client.fetch(messages[:1], ['RFC822'])
        for msgid, data in raw_messages.items():
            msg = email.message_from_bytes(data[b'RFC822'])
            body = ""
            backup_body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == 'text/plain':
                        body += part.get_payload(decode=True).decode(errors='ignore')
                    elif part.get_content_type() == 'text/html':
                        soup = BeautifulSoup(part.get_payload(decode=True).decode(errors='ignore'),
                                             features="html.parser")

                        # kill all script and style elements
                        for script in soup(["script", "style"]):
                            script.extract()  # rip it out

                        # get text
                        backup_body += soup.get_text()
            else:
                if msg.get_content_type() == 'text/html':
                    soup = BeautifulSoup(msg.get_payload(decode=True).decode(errors='ignore'),
                                         features="html.parser")

                    # kill all script and style elements
                    for script in soup(["script", "style"]):
                        script.extract()  # rip it out

                    # get text
                    backup_body += soup.get_text()
                else:
                    body = msg.get_payload(decode=True).decode(errors='ignore')

            body = body.strip()
            if len(body) == 0:
                body = backup_body.strip()

            return f'''Subject: {msg.get('Subject', '')}
From: {msg.get('From', '')}
Body: {body}
'''
        return None

if __name__ == "__main__":
    print('This module is part of LillyAI and can not be run individually.')