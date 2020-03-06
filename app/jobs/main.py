'''
emails are processed from this module
maintenances are marked started and ended from this module
'''

from flask import current_app, jsonify

from app import db, scheduler
from app.models import Provider, Maintenance, MaintCircuit
from app.MailClient import Gmail as mc
from app.Providers import Zayo, NTT, PacketFabric, EUNetworks, GTT, GTTalt, Telia, Telstra, IN_PROGRESS

from api.v1.maintenances import starting_soon, ending_soon
from app.jobs.started import FUNCS as start_funcs
from app.jobs.ended import FUNCS as end_funcs

import email
from datetime import datetime, timedelta
import pytz

PROVIDERS = [Zayo, NTT, PacketFabric, EUNetworks, GTT, GTTalt, Telia, Telstra]


def mark_started():
    '''
    a job to mark upcoming maintenances that are starting soon
    as started.
    '''
    with scheduler.app.app_context():
        upcoming_maints = starting_soon()

        for maint in upcoming_maints:
            m = Maintenance.query.get(maint['id'])
            m.started = 1

            mc = MaintCircuit.query.get(maint['circuits'][0]['id'])

            scheduler.app.logger.info(f'trying to mark {m.provider_maintenance_id} started via the api')

            db.session.add(m)
            db.session.commit()

            scheduler.app.logger.info(f'{m.provider_maintenance_id} marked started via the api')

            IN_PROGRESS.labels(provider=m.provider.name).inc()

            for func in start_funcs:
                func(email=None, maintenance=m)


def mark_ended():
    '''
    a job to mark upcoming maintenances that are ending soon
    as ended. it checks to make sure the last maintenance window
    hasn't passed before marking it ended, and that there are no
    updates saying it has been extended
    '''
    now = datetime.now(tz=pytz.utc)

    with scheduler.app.app_context():
        upcoming_maints = ending_soon()

        for maint in upcoming_maints:
            m = Maintenance.query.get(maint['id'])

            mc = MaintCircuit.query.get(maint['circuits'][0]['id'])

            # we need to loop through each maintcircuit to verify
            # this is the last day for this maintenance

            for maintcircuit in m.circuits:
                if now.date() < maintcircuit.date:
                    scheduler.app.logger.info(f'{m.provider_maintenance_id} is continuing at a later date. Not marking ended.')
                    return

            # next we make sure the maintenance hasn't been extended

            for update in m.updates.all():
                if 'extended' in update.comment or 'extension' in update.comment:
                    # this means that a maint complete email must be sent
                    # in order for this maint to be marked as ended
                    return

            scheduler.app.logger.info(f'trying to mark {m.provider_maintenance_id} ended via the api')

            m.ended = 1

            db.session.add(m)
            db.session.commit()

            scheduler.app.logger.info(f'{m.provider_maintenance_id} marked ended via the api')

            IN_PROGRESS.labels(provider=m.provider.name).dec()

            for func in end_funcs:
                func(email=None, maintenance=m)

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


