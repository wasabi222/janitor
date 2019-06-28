import pytest
import imaplib
from app import MailClient


def test_gmail(client):
    """
    GIVEN a Flask application
    WHEN a session is opened
    THEN check that the object is an imap instance
    """
    c = client.application.config
    mc = MailClient.Gmail(c['MAIL_SERVER'], c['MAIL_USERNAME'],
                          c['MAIL_PASSWORD'])

    imap = mc.open_session()
    assert isinstance(imap, imaplib.IMAP4_SSL)
    mc.close_session()

    # context manager test
    mc = MailClient.Gmail(c['MAIL_SERVER'], c['MAIL_USERNAME'],
                          c['MAIL_PASSWORD'])
    print(mc)
    with mc:
        pass

        mc.verify_mailboxes()
