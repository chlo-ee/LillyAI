"""Workaround for an upstream imapclient bug (present in 3.0.1): the TLS
connect path DROPS the configured timeout.

imapclient.tls.IMAP4_TLS.__init__ stores the timeout in self._timeout but
calls imaplib.IMAP4.__init__(host, port) WITHOUT it - imaplib then invokes
open()/_create_socket() with timeout=None, so the TCP connect and (worse)
the TLS handshake run on a fully blocking socket. IMAPClient applies its
read timeout only AFTER the connection exists. Result: a black-holed TLS
handshake (flaky server or NAT) blocks forever, no matter what timeout was
passed to IMAPClient. Observed live: lillyai frozen in ssl.do_handshake with
timeout=30 configured.

Importing this module patches IMAP4_TLS._create_socket to fall back to the
stored self._timeout when imaplib hands it None. Safe to import repeatedly.
"""

import socket

import imapclient.tls


def _create_socket_with_timeout(self, timeout):
    if timeout is None:
        timeout = self._timeout
    sock = socket.create_connection((self.host, self.port), timeout=timeout)
    return imapclient.tls.wrap_socket(sock, self.ssl_context, self.host)


imapclient.tls.IMAP4_TLS._create_socket = _create_socket_with_timeout
