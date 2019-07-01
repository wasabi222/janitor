'''
emails are processed from this module
'''

from flask import current_app, jsonify

from app import db, scheduler
from app.models import Provider
from app.MailClient import Gmail as mc
from app.Providers import Zayo, NTT, PacketFabric, EUNetworks, GTT

import email


PROVIDERS = [Zayo, NTT, PacketFabric, EUNetworks, GTT]


def get_client():
    server = current_app.config['MAIL_SERVER']
    username = current_app.config['MAIL_USERNAME']
    passwd = current_app.config['MAIL_PASSWORD']
    client = mc(server, username, passwd)
    return client


def process_provider(client, mail, provider):
    '''
    retreive messages from the provider's "identified_by"
    and process each one. 
    '''
    typ, messages = mail.search(None, provider.identified_by)
    length = len(messages[0].split())
    if typ != 'OK':
        raise Exception(f'error retrieving messages for {provider.name}')

    msg_ids = messages[0].split()

    for msg_id in msg_ids:
        typ, data = mail.fetch(msg_id, "(RFC822)")
        em = email.message_from_bytes(data[0][1])

        subject = em['Subject']
        result = provider.process(em)

        if result:
            client.mark_processed(msg_id)
        else:
            subject = em['Subject']
            failed = True
            client.mark_failed(msg_id)


def failed_messages():
    '''
    get all of the failed messages subjects to be displayed
    by the front end
    '''
    client = get_client()
    mail = client.open_session()
    client.verify_mailboxes()
    mail.select('failures')
    typ, messages = mail.search(None, '(ALL)')
    msg_ids = messages[0].split()
    subjects = []
    for msg_id in msg_ids:
        typ, data = mail.fetch(msg_id, "(RFC822)")
        em = email.message_from_bytes(data[0][1])

        subjects.append(em['Subject'])
    return jsonify(subjects)


def process():
    '''
    called on startup and run every CHECK_INTERVAL seconds
    '''
    with scheduler.app.app_context():
        client = get_client()
        mail = client.open_session()
        mail.select(current_app.config['MAILBOX'])
        for provider in PROVIDERS:
            p = provider()
            process_provider(client, mail, p)

        client.close_session()
