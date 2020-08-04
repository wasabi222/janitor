'''
all available providers
'''
from abc import ABCMeta, abstractmethod, abstractproperty
import requests
import json
import icalendar
import base64
from flask import current_app
import pandas as pd
import bs4
import re
import datetime
import pytz
import dateutil.parser as parser
import time
from prometheus_client import Counter, Gauge
import quopri

from app.models import Maintenance, Circuit, MaintCircuit, MaintUpdate
from app.models import Provider as Pro # don't conflict with the class below
from app import db, registry

from app.jobs.started import FUNCS as started_funcs
from app.jobs.ended import FUNCS as ended_funcs

NEW_PARENT_MAINT = Counter('janitor_maintenances_total',
              'total number of master maintenances, which many contain many CIDs',
              labelnames=['provider',
                          ],
              registry=registry
              )

NEW_CID_MAINT = Counter('janitor_cid_maintenances_total',
              'total number of maintenances on a circuit for each window',
              labelnames=['cid',
                          ],
              registry=registry
              )


IN_PROGRESS = Gauge('janitor_maintenances_inprogress',
                    'maintenances marked as started and have not ended',
                    labelnames=['provider',
                                ],
              multiprocess_mode='livesum',
              registry=registry
                    )

class ParsingError(Exception):
    '''
    Raised when unable to parse the maintenance notification.
    '''

    pass


class Provider(metaclass=ABCMeta):
    '''
    this is a provider that DOES NOT implement the MAINTNOTE standard and
    needs to have a custom class defined to parse their messages
    '''
    def __init__(self):
        self.name = 'Provider'

    @abstractproperty
    def identified_by():
        '''
        this is how you know that a maintenance email is from this provider.
        For instance, a sender is maints@example.com.
        they should all end with UNSEEN so the mail client only looks at
        unseen messages. A full list of search critera is here:
        https://gist.github.com/martinrusev/6121028
        '''
        pass


    @abstractmethod
    def process(self, email):
        '''
        this method is sent an email object that is able to be parsed and
        processed. It should return True if the message was processed correctly
        and False if it wasn't. "process" means correctly inserting or updating
        the maintenance in the db.
        '''
        pass


class StandardProvider(Provider):
    '''
    this class of provider follows the MAINTNOTE standard as defined
    here: https://github.com/jda/maintnote-std/blob/master/standard.md
    '''
    def __init__(self):
        super().__init__()


    def add_and_commit(self, row):
        db.session.add(row)
        db.session.commit()

    @property
    def identified_by(self):
        pass

    
    def add_circuit(self, cid):
        '''
        add a circuit to the db if it doesn't already exist
        '''
        current_app.logger.info(f'adding {self.name} circuit {cid} to db')

        circuit = Circuit()
        circuit.provider_cid = cid
        provider = Pro.query.filter_by(name=self.name,
                                   type=self.type).first()
        circuit.provider_id = provider.id
        self.add_and_commit(circuit)

        current_app.logger.info(f'{cid} added successfully to db')


    def add_new_maint(self, email, cal):
        '''
        add a new maintenance to the db
        email: email.email object
        cal: icalendar object
        '''
        maint = Maintenance()
        maint.provider_maintenance_id = cal['X-MAINTNOTE-MAINTENANCE-ID'] \
                                        .strip()

        current_app.logger.info(f'adding {maint.provider_maintenance_id} to db')

        maint.start = cal['DTSTART'].dt.time()
        maint.end = cal['DTEND'].dt.time()
        maint.timezone = cal['DTSTART'].dt.tzname()
        # not all ics attachments have descriptions
        if cal.get('DESCRIPTION'):
            maint.reason = cal['DESCRIPTION'].strip()
        received = email['Received'].splitlines()[-1].strip()
        maint.received_dt = parser.parse(received)

        self.add_and_commit(maint)

        current_app.logger.info(f'added {maint.provider_maintenance_id} successfully')

        NEW_PARENT_MAINT.labels(provider=self.name).inc()

        cids = []

        if type(cal['X-MAINTNOTE-OBJECT-ID']) == list:
            # more than one circuit is affected
            for cid in cal['X-MAINTNOTE-OBJECT-ID']:
                cids.append(cid)

        else:
            # this is only for one circuit
            cids.append(cal['X-MAINTNOTE-OBJECT-ID'])

        for cid in cids:
            if not Circuit.query.filter_by(provider_cid=cid).first():
                self.add_circuit(cid)

            circuit_row = Circuit.query.filter_by(provider_cid=cid).first()
            maint_row = Maintenance.query.filter_by(
                provider_maintenance_id=maint.provider_maintenance_id,
                rescheduled=0).first()
            mc = MaintCircuit(impact=cal['X-MAINTNOTE-IMPACT'].strip(),
                 date=cal['DTSTART'].dt.date())
            circuit_row.maintenances.append(mc)
            mc.maint_id = maint_row.id
            db.session.commit()
            NEW_CID_MAINT.labels(cid=cid).inc()

        return True


    def add_cancelled_maint(self, email, cal):
        '''
        add a maintenance cancellation to the maintenance row
        email: email.email object
        cal: icalendar object
        '''

        current_app.logger.info(f'cancelling maintenance from email {email["Subject"]}')

        maint = Maintenance.query.filter_by(
            provider_maintenance_id=cal['X-MAINTNOTE-MAINTENANCE-ID'],
            rescheduled=0).first()

        if not maint:
            return False

        maint.cancelled = 1

        self.add_and_commit(maint)

        current_app.logger.info(f'maintenance {maint.provider_maintenance_id} cancelled successfully')

        return True

    def add_start_maint(self, email, cal):
        '''
        change the maintenance started column from 0 to 1.
        not all providers send an email when a maintenance starts.
        email: email.email object
        cal: icalendar object
        '''

        current_app.logger.info(f'attempting to mark start maintenance')

        maint = Maintenance.query.filter_by(
            provider_maintenance_id=cal['X-MAINTNOTE-MAINTENANCE-ID'],
            rescheduled=0).first()

        if not maint:
            return False

        if maint.started:
            return True

        maint.started = 1

        self.add_and_commit(maint)

        IN_PROGRESS.labels(provider=self.name).inc()

        current_app.logger.info(f'maintenance {maint.provider_maintenance_id} started successfully')

        for func in started_funcs:
            func(email=email, maintenance=maint)

        return True


    def add_end_maint(self, email, cal):
        '''
        change the maintenance ended column from 0 to 1
        email: email.email object
        cal: icalendar object
        '''

        current_app.logger.info(f'attempting to mark end maintenance')

        maint = Maintenance.query.filter_by(
            provider_maintenance_id=cal['X-MAINTNOTE-MAINTENANCE-ID'],
            rescheduled=0).first()
        
        if not maint:
            return False

        maint.ended = 1

        IN_PROGRESS.labels(provider=self.name).dec()

        self.add_and_commit(maint)

        current_app.logger.info(f'maintenance {maint.provider_maintenance_id} ended successfully')

        for func in ended_funcs:
            func(email=email, maintenance=maint)

        return True


    def update(self, email, cal):

        current_app.logger.info(f'attempting to update maintenance')

        maint = Maintenance.query.filter_by(
            provider_maintenance_id=cal['X-MAINTNOTE-MAINTENANCE-ID'],
            rescheduled=0).first()

        if not maint:
            return False

        u = MaintUpdate(maintenance_id=maint.id, comment=cal['DESCRIPTION'],
            updated=datetime.datetime.now())

        self.add_and_commit(u)

        current_app.logger.info(f'maintenance {maint.provider_maintenance_id} updated successfully')

        return True

    
    def process(self, email):

        current_app.logger.info(f'attempting to process email {email["Subject"]}')

        msg = None
        info = None
        result = False
        for part in email.walk():
            if part.get_content_type().startswith('multipart'):
                for subpart in part.get_payload():
                    if subpart.get_content_type() == 'text/calendar':
                        try:
                            # some payloads are base64 encoded...
                            msg = base64.b64decode(subpart.get_payload())
                            msg = icalendar.Calendar.from_ical(msg)
                        except ValueError:
                            # ... and some aren't
                            msg = subpart.get_payload()
                            msg = icalendar.Calendar.from_ical(msg)
                        break
        
        if not msg:
            return False

        for event in msg.subcomponents:
            if event.name == 'VEVENT':
                info = event

        if not info:
            return False

        if not info.get('X-MAINTNOTE-STATUS'):
            if info.get('SUMMARY'):
                if 'completed' in info.get('SUMMARY'):
                    result = self.add_end_maint(email, info)
            else:
                return False


        elif info['X-MAINTNOTE-STATUS'].lower() in ['confirmed', 'tentative']:
            result = self.add_new_maint(email, info)

        elif info['X-MAINTNOTE-STATUS'].lower() == 'cancelled':
            result = self.add_cancelled_maint(email, info)

        elif info['X-MAINTNOTE-STATUS'].lower() == 'in-process':
            result = self.add_start_maint(email, info)

        elif info['X-MAINTNOTE-STATUS'].lower() == 'completed':
            result = self.add_end_maint(email, info)

        elif info['SEQUENCE'] > 0:
            result = self.update(email, info)


        current_app.logger.info(f'process result: {result}')

        return result



class NTT(StandardProvider):
    '''
    Notes: NTT starts their sequence numbers at 0
    '''
    def __init__(self):
        super().__init__()
        self.name = 'ntt'
        self.type = 'transit'
        self.email_esc = 'noc@us.ntt.net'
        if not Pro.query.filter_by(name=self.name, type=self.type).first():
            p = Pro(name=self.name, type=self.type, email_esc=self.email_esc)
            self.add_and_commit(p)

    @property
    def identified_by(self):
        #return b'(FROM "NTT Communications" UNSEEN)'
        return b'(SUBJECT NTT UNSEEN)'


class PacketFabric(StandardProvider):
    def __init__(self):
        super().__init__()
        self.name = 'packetfabric'
        self.type = 'transit'
        self.email_esc = 'support@packetfabric.com'
        if not Pro.query.filter_by(name=self.name, type=self.type).first():
            p = Pro(name=self.name, type=self.type, email_esc=self.email_esc)
            self.add_and_commit(p)

    @property
    def identified_by(self):
        return b'(FROM "support@packetfabric.com" UNSEEN)'


class EUNetworks(StandardProvider):
    def __init__(self):
        super().__init__()
        self.name = 'eunetworks'
        self.type = 'transit'
        self.email_esc = 'noc@eunetworks.com'
        if not Pro.query.filter_by(name=self.name, type=self.type).first():
            p = Pro(name=self.name, type=self.type, email_esc=self.email_esc)
            self.add_and_commit(p)

    @property
    def identified_by(self):
        return b'(SUBJECT "eunetworks" UNSEEN)'


class Zayo(Provider):
    '''
    zayo seems to use salesforce and mostly uses templates 
    '''
    def __init__(self):
        super().__init__()
        self.name = 'zayo'
        self.type = 'transit'
        self.email_esc = 'mr@zayo.com'
        if not Pro.query.filter_by(name=self.name, type=self.type).first():
            p = Pro(name=self.name, type=self.type, email_esc=self.email_esc)
            self.add_and_commit(p)

    @property
    def identified_by(self):
        return b'(FROM "MR Zayo" UNSEEN)'


    def clean_line(self, line):
        '''
        there are nasty chars mid-line that need to be stripped out
        '''
        line = line.strip()
        return line.replace('\r', '').replace('=', '').replace('\n', '')


    def format_circuit_table(self, table):
        ptable = pd.read_html(str(table))
        assert len(ptable) == 1
        ptable = ptable[0]
        # columns:
        # ['Circuit Id', 'Expected Impact',
        # 'A Location CLLI', 'Z Location CLLI',
        # 'Legacy Circuit Id']
        return ptable


    def add_and_commit(self, row):
        db.session.add(row)
        db.session.commit()


    
    def get_maintenance(self, soup):
        '''
        for pulling the id out and returning the maintenance row
        '''
        maint_id = None
        for line in soup.find_all('b'):
            if type(line) == bs4.element.Tag:
                if line.text.lower().strip().startswith('maintenance ticket'):
                    maint_id = self.clean_line(line.next_sibling)
                    break

        if maint_id:
            maint_id = Maintenance.query.filter_by(
            provider_maintenance_id=maint_id, rescheduled=0).first()

        return maint_id


    def add_start_maint(self, soup, email):

        current_app.logger.info(f'attempting to mark start maintenance')

        maint = self.get_maintenance(soup)

        if not maint:
            return False

        if maint.started:
            return True

        maint.started = 1

        IN_PROGRESS.labels(provider=self.name).inc()

        self.add_and_commit(maint)

        current_app.logger.info(f'maintenance {maint.provider_maintenance_id} started successfully')

        for func in started_funcs:
            func(email=email, maintenance=maint)


        return True

    
    def add_end_maint(self, soup, email):

        current_app.logger.info(f'attempting to mark end maintenance')

        maint = self.get_maintenance(soup)

        if not maint:
            return False

        if email['Subject'].lower().startswith('completed maintenance'):
            maint.ended = 1

            self.add_and_commit(maint)

            current_app.logger.info(f'maintenance {maint.provider_maintenance_id} ended successfully')

        else:
            IN_PROGRESS.labels(provider=self.name).dec()
            
            current_app.logger.info(f'maintenance {maint.provider_maintenance_id} decremented in prometheus but not ended')

        for func in ended_funcs:
            func(email=email, maintenance=maint)



        return True


    def add_cancelled_maint(self, soup, email):

        current_app.logger.info(f'attempting to mark cancelled maintenance')

        maint = self.get_maintenance(soup)

        if not maint:
            return False

        maint.cancelled = 1

        self.add_and_commit(maint)

        current_app.logger.info(f'maintenance {maint.provider_maintenance_id} cancelled successfully')

        return True


    def add_reschedule_maint(self, soup, email):
        '''
        zayo sends reschedule emails so we're able to identified_by
        a new maintenance that references an old one
        '''

        current_app.logger.info(f'attempting to mark maintenance rescheduled')
        
        old_maint = self.get_maintenance(soup)

        if not old_maint:
            self.add_new_maint(soup, email)
            return True

        old_maint.rescheduled = 1
        self.add_and_commit(old_maint)

        current_app.logger.info(f'maintenance {old_maint.provider_maintenance_id} marked rescheduled successfully')

        time.sleep(5)

        self.add_new_maint(soup, email)

        new_maint = Maintenance.query.filter_by(
            provider_maintenance_id=old_maint.provider_maintenance_id,
            rescheduled=0).first()

        old_maint.rescheduled_id = new_maint.id

        self.add_and_commit(old_maint)

        current_app.logger.info(f'maintenance {old_maint.provider_maintenance_id} rescheduled is now id {new_maint.id}')


        return True

    def add_new_maint(self, soup, email):
        '''
        zayo bolds the relevant fields so we use bs4 to search for those
        and then get the next sibling
        '''

        current_app.logger.info(f'attempting to add new maint from email {email["Subject"]}')
        
        table = soup.find('table')
        if not table:
            subject = email['Subject']
            return False
        maint = Maintenance()

        dates = []

        for line in soup.find_all('b'):
            if type(line) == bs4.element.Tag:
                if line.text.lower().strip().endswith('activity date:'):
                    dt = parser.parse(self.clean_line(line.next_sibling))
                    t = datetime.date(dt.year, dt.month, dt.day)
                    dates.append(t)
                if line.text.lower().strip().startswith('maintenance ticket'):
                    maint.provider_maintenance_id = self.clean_line(
                                                      line.next_sibling)
                # elif 'urgency' in line.text.lower():
                #    row_insert['urgency'] = self.clean_line(line.next_sibling)

                elif 'location of maintenance' in line.text.lower():
                    maint.location = self.clean_line(
                                             line.next_sibling)

                elif 'maintenance window' in line.text.lower():
                    window = line.next_sibling.strip().split('-')
                    window = [time.strip() for time in window]
                    start = window.pop(0)
                    start = parser.parse(start)
                    maint.start = datetime.time(start.hour, start.minute)
                    window = window[0].split()
                    end = window.pop(0)
                    end = parser.parse(end)
                    maint.end = datetime.time(end.hour, end.minute)

                    if len(window) == 1:
                        if current_app.config['TZ_PREFIX']:
                            # zayo will send timezones such as "Eastern"
                            # instead of "US/Eastern" so the tzinfo
                            # may not be able to be parsed without a prefix
                            tz = window.pop()
                            pfx = current_app.config['TZ_PREFIX']
                            if tz != 'GMT':
                                maint.timezone = pfx + tz
                            else:
                                maint.timezone = tz
                        else:
                            maint.timezone = window.pop()
                    else:
                        # failsafe
                        maint.timezone = ' '.join(window)

                elif 'reason for maintenance' in line.text.lower():
                    maint.reason = self.clean_line(line.next_sibling)

        received = email['Received'].splitlines()[-1].strip()
        maint.received_dt = parser.parse(received)

        self.add_and_commit(maint)

        current_app.logger.info(f'maintenance {maint.provider_maintenance_id} added successfully')

        NEW_PARENT_MAINT.labels(provider=self.name).inc()

        cid_table = self.format_circuit_table(table)
        for row in cid_table.values:
            if not Circuit.query.filter_by(provider_cid=row[0]).first():

                current_app.logger.info(f'adding circuit {row[0]}')

                circuit = Circuit()
                circuit.provider_cid = row[0]
                if str(row[2]) == 'nan':
                    circuit.a_side = None
                else:
                    circuit.a_side = row[2]
                if str(row[3]) == 'nan':
                    circuit.z_side = None
                else:
                    circuit.z_side = row[3]
                this = Pro.query.filter_by(name=self.name,
                                           type=self.type).first()
                circuit.provider_id = this.id
                self.add_and_commit(circuit)

                current_app.logger.info(f'circuit {row[0]} added successfully')

            circuit_row = Circuit.query.filter_by(provider_cid=row[0]).first()
            maint_row = Maintenance.query.filter_by(
                provider_maintenance_id=maint.provider_maintenance_id, rescheduled=0).first()
            for date in dates:

                current_app.logger.info(f'adding maint_circuit row for {maint_row.provider_maintenance_id}')

                mc = MaintCircuit(impact=row[1], date=date)
                circuit_row.maintenances.append(mc)
                mc.maint_id = maint_row.id
                db.session.commit()

                current_app.logger.info(f'maint_circuit row for {maint_row.provider_maintenance_id} added successfully')

                NEW_CID_MAINT.labels(cid=circuit_row.provider_cid).inc()

        return True


    def update(self, soup, email):
        current_app.logger.info(f'attempting to update a zayo ticket')
        match = re.search('TTN-\d+', email['Subject'])
        if not match:

            current_app.logger.info(f'could not find an RE match - skipping')

            return

        ticket = match.group()
        maint = Maintenance.query.filter_by(provider_maintenance_id=ticket,
         rescheduled=0).all()

        if maint:
            assert len(maint) == 1, 'More than one maint returned!'
            maint = maint[0]

            u = MaintUpdate(maintenance_id=maint.id, comment=self.clean_line(soup.text),
            updated=datetime.datetime.now())

            self.add_and_commit(u)

            current_app.logger.info(f'maintenance updated')

            return True


        return False

    def process(self, email):

        current_app.logger.info(f'attempting to process email {email["Subject"]}')

        msg = None
        result = False

        for part in email.walk():
            if part.get_content_type() == 'text/html':
                msg = part
                break

        if not msg:
            return False

        soup = bs4.BeautifulSoup(msg.get_payload(), features="lxml")

        if (email['Subject'].startswith('***') and
            'maintenance notification' in self.clean_line(email['Subject'].lower())):
            result = self.add_new_maint(soup, email)

        elif email['Subject'].lower().startswith('reschedule notification'):
            result = self.add_reschedule_maint(soup, email)

        elif email['Subject'].lower().startswith('start maintenance notification'):
            result = self.add_start_maint(soup, email)

        elif email['Subject'].lower().startswith('completed maintenance notification') or \
        email['Subject'].lower().startswith('end of window'):
            result = self.add_end_maint(soup, email)

        elif email['Subject'].lower().startswith('cancelled notification'):
            result = self.add_cancelled_maint(soup, email)

        elif 'TTN-' in email['Subject'] and 'exten' in email['Subject'].lower():
            result = self.update(soup, email)
        elif 'TTN-' in email['Subject'] and 'maintenance notification' in email['Subject'].lower():
            result = self.update(soup, email)

        current_app.logger.info(f'result: {result}')

        return result


class GTT(Provider):
    '''
    GTT
    '''
    def __init__(self):
        super().__init__()
        self.name = 'gtt'
        self.type = 'transit'
        self.email_esc = 'inoc@gtt.net'
        if not Pro.query.filter_by(name=self.name, type=self.type).first():
            p = Pro(name=self.name, type=self.type, email_esc=self.email_esc)
            self.add_and_commit(p)

    @property
    def identified_by(self):
        return b'(FROM "netopsadmin@gtt.net" UNSEEN)'

    def add_and_commit(self, row):
        db.session.add(row)
        db.session.commit()

    def get_maint_id(self, email):
        maint_re = re.search(r'#\((\d+)', email['Subject'])
        if not maint_re:
            return False

        maint_id = maint_re.groups()[0]

        return maint_id


    def add_new_maint(self, soup, email):
        maint_id = self.get_maint_id(email)
        if not maint_id:
            return False

        maint = Maintenance()
        maint.provider_maintenance_id = maint_id
        received = email['Received'].splitlines()[-1].strip()
        maint.received_dt = parser.parse(received)
        start_re = re.search(r'Start: (.*)(\r|\n)', soup.text)
        end_re = re.search(r'End: (.*)(\r|\n)', soup.text)
        location_re = re.search(r'Location: (.*)(\r|\n)', soup.text)
        reason_re = re.search(r'Reason: (.*)(\r|\n)', soup.text)
        impact_re = re.search(r'Impact: (.*)(\r|\n)', soup.text)
        impact = impact_re.groups()[0]
        start_dt = parser.parse(start_re.groups()[0])
        end_dt = parser.parse(end_re.groups()[0])
        maint.start = start_dt.time()
        maint.end = end_dt.time()
        maint.timezone = start_dt.tzname()
        maint.location = location_re.groups()[0]
        maint.reason = reason_re.groups()[0]
        if not all((start_re, end_re, location_re, reason_re, impact_re)):
            raise ParsingError(
                'Unable to parse the maintenance notification from GTT: {}'.format(
                    soup.text
                )
            )

        self.add_and_commit(maint)

        NEW_PARENT_MAINT.labels(provider=self.name).inc()

        # sometimes maint emails contain the same cid several times
        cids = set()
        a_side = set()

        for line in soup.text.splitlines():
            if 'gtt service' in line.lower():
                cid = re.search(r'GTT Service = (.+);', line)
                if cid:
                    cids.add(cid.groups()[0])
            elif line.lower().startswith('site address'):
                loc = re.search(r'= (.*)', line)
                if loc:
                    a_side.add(loc.groups()[0])
            # there is sometimes two location lines with
            # = ostensibly being the circuit location
            elif line.lower().startswith('location ='):
                loc = re.search(r'= (.*)', line)
                if loc:
                    a_side.add(loc.groups()[0])

        if len(cids) == len(a_side):
            for cid, a_side in zip(cids, a_side):
                if not Circuit.query.filter_by(provider_cid=cid).first():
                    circuit = Circuit()
                    circuit.provider_cid = cid
                    circuit.a_side = a_side
                    this = Pro.query.filter_by(name=self.name,
                                                type=self.type).first()
                    circuit.provider_id = this.id
                    self.add_and_commit(circuit)

                circuit_row = Circuit.query.filter_by(provider_cid=cid).first()
                maint_row = Maintenance.query.filter_by(
                provider_maintenance_id=maint.provider_maintenance_id, rescheduled=0).first()
                
                mc = MaintCircuit(impact=impact, date=start_dt.date())
                circuit_row.maintenances.append(mc)
                mc.maint_id = maint_row.id
                db.session.commit()
                NEW_CID_MAINT.labels(cid=cid).inc()

        return True



    def add_end_maint(self, soup, email):
        maint_id = self.get_maint_id(email)
        if not maint_id:
            return False

        maint = Maintenance.query.filter_by(
            provider_maintenance_id=maint_id, rescheduled=0).first()
        if not maint:
            return False

        maint.ended = 1

        self.add_and_commit(maint)

        for func in ended_funcs:
            func(email=email, maintenance=maint)

        return True

    def add_cancelled_maint(self, soup, email):
        maint_id = self.get_maint_id(email)
        if not maint_id:
            return False

        maint = Maintenance.query.filter_by(
            provider_maintenance_id=maint_id, rescheduled=0).first()
        if not maint:
            return False

        maint.cancelled = 1

        self.add_and_commit(maint)

        return True


    def update(self, soup, email):
        maint_id = self.get_maint_id(email)
        if not maint_id:
            return False

        maint = Maintenance.query.filter_by(
            provider_maintenance_id=maint_id, rescheduled=0).first()

        if not maint:
            return False

        update_text = soup.text

        if not update_text:
            for payload in email.get_payload():
                update_text = payload.get_payload() 

        u = MaintUpdate(maintenance_id=maint.id, comment=soup.text,
            updated=datetime.datetime.now())

        self.add_and_commit(u)


        return True


    def process(self, email):
        msg = None
        result = False
        for part in email.walk():
            if part.get_content_type() == 'text/html':
                msg = part.get_payload()
                
                if 'GTT' in msg:
                    # this does not need to be decoded
                    break
                else:
                    # this needs to be decoded
                    msg = base64.b64decode(msg).decode()
                    break

        if not msg:
            return False

        soup = bs4.BeautifulSoup(quopri.decodestring(msg), features="lxml")

        if 'work announcement' in email['Subject'].lower():
            result = self.add_new_maint(soup, email)

        elif 'work conclusion' in email['Subject'].lower():
            result = self.add_end_maint(soup, email)
            
        elif 'work cancellation' in email['Subject'].lower():
            result = self.add_cancelled_maint(soup, email)

        elif 'gtt tt#' in email['Subject'].lower():
            result = self.update(soup, email)

        return result


class Hibernia(GTT):
    '''
    same provider, different email
    '''

    @property
    def identified_by(self):
        return b'(FROM "changemanagement@gtt.net" UNSEEN)'


class Telia(Provider):
    '''
    Telia
    '''
    def __init__(self):
        super().__init__()
        self.name = 'telia'
        self.type = 'transit'
        self.email_esc = 'carrier-csc@teliasonera.com'
        if not Pro.query.filter_by(name=self.name, type=self.type).first():
            p = Pro(name=self.name, type=self.type, email_esc=self.email_esc)
            self.add_and_commit(p)

    @property
    def identified_by(self):
        return b'(FROM ncm UNSEEN)'

    def get_maintenance(self, msg):
        '''
        for pulling the id out and returning the maintenance row
        '''
        maint_id = re.search('.*(PWIC\S+).*', msg)

        if maint_id and maint_id.groups():
            maint_id = Maintenance.query.filter_by(
            provider_maintenance_id=maint_id.groups()[0], rescheduled=0).first()
        elif maint_id and not maint_id_groups():
            raise Exception(f'maint_id: {maint_id} but no groups')
        elif not maint_id:
            raise Exception(f'no maint id. msg: {msg}')

        return maint_id

    def add_and_commit(self, row):
        db.session.add(row)
        db.session.commit()

    def add_new_maint(self, msg, email):
        maint = Maintenance()
        provider_id = re.search('(?<=pw reference number: )\S+', msg.lower())
        maint.provider_maintenance_id = provider_id.group()
        start_time = re.search('(?<=start date and time: ).+', msg.lower())
        end_time = re.search('(?<=end date and time: ).+', msg.lower())
        start_dt = datetime.datetime.strptime(
            start_time.group().rstrip(), '%Y-%b-%d %H:%M %Z'
        )
        start_dt = start_dt.replace(tzinfo=pytz.utc)
        end_dt = datetime.datetime.strptime(
            end_time.group().rstrip(), '%Y-%b-%d %H:%M %Z'
        )
        end_dt = end_dt.replace(tzinfo=pytz.utc)
        maint.start = start_dt.time()
        maint.end = end_dt.time()
        maint.timezone = start_dt.tzname()
        reason = re.search('(?<=action and reason: ).+', msg.lower())
        maint.reason = reason.group()
        received = email['Received'].splitlines()[-1].strip()
        maint.received_dt = parser.parse(received)
        location = re.search('(?<=location of work: ).+', msg.lower())
        maint.location = location.group().rstrip()
        cids = re.findall('service id: (.*)\r', msg.lower())
        impact = re.findall('impact: (.*)\r', msg.lower())

        if not all((provider_id, start_time, end_time, reason, location, cids, impact)):
            raise ParsingError(
                'Unable to parse the maintenance notification from Telia: {}'.format(
                    msg
                )
            )

        self.add_and_commit(maint)

        NEW_PARENT_MAINT.labels(provider=self.name).inc()

        all_circuits = list(zip(cids, impact))

        for cid, impact in all_circuits:
            if not Circuit.query.filter_by(provider_cid=cid).first():
                c = Circuit()
                c.provider_cid = cid
                this = Pro.query.filter_by(name=self.name,
                                           type=self.type).first()
                c.provider_id = this.id
                self.add_and_commit(c)

            circuit_row = Circuit.query.filter_by(provider_cid=cid).first()
            maint_row = Maintenance.query.filter_by(
                provider_maintenance_id=maint.provider_maintenance_id, rescheduled=0).first()
            
            mc = MaintCircuit(impact=impact, date=start_dt.date())
            circuit_row.maintenances.append(mc)
            mc.maint_id = maint_row.id
            db.session.commit()
            NEW_CID_MAINT.labels(cid=cid).inc()

        return True

    def add_cancelled_maint(self, msg, email):
        maint = self.get_maintenance(msg)

        if not maint:
            return False

        maint.cancelled = 1

        self.add_and_commit(maint)

        return True

    def add_start_maint(self, msg, email):
        maint = self.get_maintenance(msg)

        if not maint:
            return False

        if maint.started:
            return True

        maint.started = 1

        self.add_and_commit(maint)

        IN_PROGRESS.labels(provider=self.name).inc()

        for func in started_funcs:
            func(email=email, maintenance=maint)

        return True

    def add_end_maint(self, msg, email):
        maint = self.get_maintenance(msg)

        if not maint:
            return False

        maint.ended = 1

        self.add_and_commit(maint)

        IN_PROGRESS.labels(provider=self.name).dec()

        for func in ended_funcs:
            func(email=email, maintenance=maint)

        return True

    def add_rescheduled_maint(self, msg, email):
        old_maint = self.get_maintenance(msg)

        if not old_maint:
            self.add_new_maint(soup, email)
            return True

        old_maint.rescheduled = 1
        self.add_and_commit(old_maint)

        time.sleep(5)

        self.add_new_maint(msg, email)

        new_maint = Maintenance.query.filter_by(
            provider_maintenance_id=old_maint.provider_maintenance_id,
            rescheduled=0).first()

        old_maint.rescheduled_id = new_maint.id

        self.add_and_commit(old_maint)

        return True


    def process(self, email):
        msg = None
        result = False
        b64 = False

        for part in email.walk():
            if part.get_content_type() == 'text/plain':
                msg = part.get_payload()
                if 'telia' in msg.lower():
                    # this does not need to be decoded
                    break
                else:
                    # this needs to be decoded
                    msg = base64.b64decode(msg).decode()
                    break

        if not msg:
            return False


        if email['Subject'].lower().startswith(
            'planned work'
        ) or email['Subject'].lower().startswith('urgent!'):
            result = self.add_new_maint(msg, email)

        elif email['Subject'].lower().startswith('cancellation of'):
            result = self.add_cancelled_maint(msg, email)

        elif email['Subject'].lower().startswith('reminder for planned'):
            # we don't care about reminders, mark as processed
            result = True

        elif 'is about to start' in email['Subject'].lower():
            result = self.add_start_maint(msg, email)

        elif 'has been completed' in email['Subject']:
            result = self.add_end_maint(msg, email)

        elif email['Subject'].lower().startswith('update for'):
            result = self.add_rescheduled_maint(msg, email)


        return result


class Telstra(Provider):
    '''
    Telstra
    '''
    def __init__(self):
        super().__init__()
        self.name = 'telstra'
        self.type = 'transit'
        self.email_esc = 'gpen@team.telstra.com'
        if not Pro.query.filter_by(name=self.name, type=self.type).first():
            p = Pro(name=self.name, type=self.type, email_esc=self.email_esc)
            self.add_and_commit(p)

    @property
    def identified_by(self):
        return b'(FROM "gpen@team.telstra.com" UNSEEN)'


    def clean_line(self, line):
        '''
        there are nasty chars mid-line that need to be stripped out
        '''
        line = line.strip('0A')
        line = line.strip()

        return line.replace('\r', '').replace('=', '').replace('\n', '')


    def get_maintenance(self, soup, email):
        '''
        for pulling the id out and returning the maintenance row
        '''
        maint_id = email['Subject'].split()[-1]

        maint = Maintenance.query.filter_by(
            provider_maintenance_id=maint_id, rescheduled=0).first()

        return maint


    def add_and_commit(self, row):
        db.session.add(row)
        db.session.commit()


    def add_start_maint(self, soup, email):
        maint = self.get_maintenance(soup, email)

        if not maint:
            return False

        if maint.started:
            return True

        maint.started = 1

        self.add_and_commit(maint)

        IN_PROGRESS.labels(provider=self.name).inc()

        for func in started_funcs:
            func(email=email, maintenance=maint)


        return True


    def add_end_maint(self, soup, email):
        maint = self.get_maintenance(soup, email)

        if not maint:
            return False

        if email['Subject'].lower().startswith('completed maintenance'):
            maint.ended = 1

            self.add_and_commit(maint)

            IN_PROGRESS.labels(provider=self.name).dec()

        for func in ended_funcs:
            func(email=email, maintenance=maint)


        return True


    def add_cancelled_maint(self, soup, email):
        maint = self.get_maintenance(soup, email)

        if not maint:
            return False

        maint.cancelled = 1

        self.add_and_commit(maint)

        return True


    def check_maintenance(self, maint_id):
        maint = Maintenance.query.filter_by(
            provider_maintenance_id=maint_id, rescheduled=0).first()

        return maint


    def add_new_maint(self, soup, email):
        '''
        create a new telstra maintenance
        '''
        maint = Maintenance()
        maint.provider_maintenance_id = email['Subject'].split()[-1]
        maint.location = 'n/a' # telstra doesn't give this info :(
        maint.reason = ''

        received = email['Received'].splitlines()[-1].strip()
        maint.received_dt = parser.parse(received)

        headers = soup.findAll('th')
        impact = None
        cid = None
        date = None

        for column in headers:
            if 'expected impact' in self.clean_line(column.text.lower()):
                impact = self.clean_line(column.next_sibling.next_sibling.text)

            elif 'service(s) impacted' in self.clean_line(column.text.lower()):
                try:
                   tmp = self.clean_line(column.next_sibling.next_sibling.text)
                except:
                    tmp = self.clean_line(column.next_sibling.text)
                if '<' in tmp and '>' in tmp:
                    cid_soup = bs4.BeautifulSoup(tmp)
                    cid = cid_soup.text
                else:
                    cid = tmp
            
            elif 'maintenance window' in self.clean_line(column.text.lower()):
                date = self.clean_line(column.next_sibling.next_sibling.text)

        if not all((impact, cid, date)):
            raise ParsingError(f'unable to parse telstra impact: {impact}, cid: {cid}, date: {date} subject: {email["Subject"]}')

        fullstart, fullend = date.split(' to ')

        datestart, timestart = fullstart.split()
        dateend, timeend = fullend.split()

        startdate = parser.parse(datestart).date()

        timematch = re.compile(r'^\d+:\d+(?=[:00])?')

        starttime = timematch.search(timestart).group()
        endtime = timematch.search(timeend).group()

        start = parser.parse(starttime).time()
        end = parser.parse(endtime).time()

        maint.start = start
        maint.end = end

        tzmatch = re.compile(r'\((\w+)\)')

        tz = tzmatch.search(timestart).groups()[0]
        maint.timezone = tz

        # grab maintenance details. This is not pretty
        details = []
        for i in soup.find_all('tr'):
            if 'maintenance details' in i.text.lower():
                det = i
                details = det.findNextSiblings('tr')
                break

        for line in details:
            if 'service(s) impacted' in line.text.lower():
                break
            maint.reason += clean_line(line.text)
            maint.reason += ' '


        self.add_and_commit(maint)

        NEW_PARENT_MAINT.labels(provider=self.name).inc()

        # add the circuit if it doesn't exist

        circuit = Circuit.query.filter_by(provider_cid=cid).first()

        if not circuit:
            circuit = Circuit()
            circuit.provider_cid = cid
            circuit.a_side = ''
            circuit.z_side = ''

            this = Pro.query.filter_by(name=self.name,
                                           type=self.type).first()
            circuit.provider_id = this.id
            self.add_and_commit(circuit)

        # add the maint_circuit row

        maint_row = Maintenance.query.filter_by(
                provider_maintenance_id=maint.provider_maintenance_id, rescheduled=0).first()

        mc = MaintCircuit(impact=impact, date=startdate)
        circuit.maintenances.append(mc)
        mc.maint_id = maint_row.id
        db.session.commit()

        NEW_CID_MAINT.labels(cid=circuit.provider_cid).inc()

        return True



    def process(self, email):
        msg = None
        result = False

        for part in email.walk():
            if part.get_content_type() == 'text/html':
                msg = part
                break

        if not msg:
            return False

        soup = bs4.BeautifulSoup(self.clean_line(msg.get_payload()), features="lxml")



        if 'maintenance' in email['Subject'].lower():
            maint_id = email['Subject'].split()[-1]
            maintenance_exists = self.check_maintenance(maint_id)

            if not maintenance_exists:
                self.add_new_maint(soup, email)

                result = self.add_new_maint(soup, email)

            elif 'reminder' in email['Subject'].lower():
                result = self.add_start_maint(soup, email)

            elif 'completed successfully' in email['Subject'].lower():
                result = self.add_end_maint(soup, email)

            elif ('did not proceed' in email['Subject'].lower() or 
                  'reschedule' in email['Subject'].lower()):
                result = self.add_cancelled_maint(soup, email)


        return result


class Cogent(Provider):
    '''
    Cogent
    '''
    def __init__(self):
        super().__init__()
        self.name = 'cogent'
        self.type = 'transit'
        self.email_esc = 'Cogent-NoReply@cogentco.com'
        if not Pro.query.filter_by(name=self.name, type=self.type).first():
            p = Pro(name=self.name, type=self.type, email_esc=self.email_esc)
            self.add_and_commit(p)

    @property
    def identified_by(self):
        return b'(FROM "Cogent-NoReply@cogentco.com" UNSEEN)'

    def add_and_commit(self, row):
        row.provider_name = self.name
        db.session.add(row)
        db.session.commit()

    def get_maint_id(self, email):
        # match all 3 possible date strings so we can for sure
        # match the ticket # in the second grouping
        maint_re = re.search(
            r'(\w+ \d+, \d+|\d+\/\d+\/\d+|\S+-\S+-\S+) (\S+-\S+) ((Emergency|Planned|Cancellation Planned) Network Maintenance|Maintenance Completed)',
            email['Subject']
        )
        if not maint_re:
            current_app.logger.info(f'Cogent failed subject: {email["Subject"]}')
            return False

        maint_id = maint_re.groups()[1]
        current_app.logger.info(f'Cogent maint_id: {maint_id}')

        return maint_id

    def get_maint_date(self, line):
        """Takes in a line containing a date in one of the many
        formats that Cogent sends them in..
        Returns a date object and TZ "name" where TZ "name" may be useless
        """
        tz_info = None
        re_date = None
        parsed = None
        one_re = re.search(r'^(\d+|\d+:\d+) (\S+) ?(.* *) (\w+ \d+, \d+)', line)
        two_re = re.search(r'^(\d+:\d+) (.*) (\d+-\w+-\d+)', line)
        three_re = re.search(r'^(\d+:\d+ \w+) (.*) (\d+/\d+/\d+)$', line)
        if one_re:
            g_one = one_re.groups()
            if g_one[1].lower() not in ['am', 'pm']:
                tz_info = g_one[1]
                re_date = ' '.join([g_one[0], g_one[-1]])
            else:
                tz_info = g_one[2]
                re_date = ' '.join([g_one[0], g_one[1], g_one[-1]])
        elif two_re:
            g_two = two_re.groups()
            tz_info = g_two[1]
            re_date = ' '.join([g_two[0], g_two[-1]])
        elif three_re:
            g_three = three_re.groups()
            tz_info = g_three[1]
            re_date = ' '.join([g_three[0], g_three[-1]])

        # if we have re_date, it should be parsable, hopefully
        if re_date is not None:
            try:
                parsed = parser.parse(re_date)
            except Exception as e:
                pass

        return (parsed, tz_info)

    def add_new_maint(self, soup, email):
        """Adds a new regular 'Planned Maintenance' to the db
        Returns true on success
        Also note, it adds circuits and location as required
        """
        maint_id = self.get_maint_id(email)
        if not maint_id:
            return False

        # We want to check to see if we have a duplicate before proceeding
        # Not sure why but I have duplicate emails so just in case of a re-send
        maint_row = Maintenance.query.filter_by(
            provider_maintenance_id=maint_id
        ).first()
        if maint_row:
            current_app.logger.info(f'Cogent maint_id: {maint_id} already exists, skipping.')
            return True

        # so we must be new...
        maint = Maintenance()
        maint.provider_maintenance_id = maint_id
        received = email['Received'].splitlines()[-1].strip()
        subject = email['Subject']
        maint.received_dt = parser.parse(received)
        current_app.logger.info(f'Cogent starting')
        # start regex searches
        start_line_re = re.search(r'Start time: (.*)(\r|\n)', soup.text)
        end_line_re = re.search(r'End time: (.*)(\r|\n)', soup.text)
        circuit_ids_re = re.search(r'Order ID\(s\) impacted: (.*)(\r|\n)', soup.text)
        location_re = re.search(
            r'.*(Planned|Emergency) Network Maintenance - (.*) \d+.*',
            subject
        )
        # just gets the first sentence of description
        impact_re = re.search(r'Expected Outage\/Downtime: (.*)(\r|\n)', soup.text)

        if not all((start_line_re, end_line_re, location_re, circuit_ids_re, impact_re)):
            current_app.logger.info(f'Cogent Failed for {subject}')
            raise ParsingError(
                'Unable to parse the maintenance notification from EquinixBR: {}'.format(
                    soup.text
                )
            )
        current_app.logger.info(f'Cogent got all oure REs at least')
        # parsed all the lines, keep going...
        # regex groups pulled out
        start_dt, start_tz_name = self.get_maint_date(start_line_re.groups()[0])
        end_dt, end_tz_name = self.get_maint_date(end_line_re.groups()[0])

        impact = impact_re.groups()[0]
        maint.location = location_re.groups()[1]
        maint.reason = soup.text.splitlines()[0]
        # timing
        maint.start = start_dt.time()
        maint.end = end_dt.time()
        maint.timezone = start_tz_name

        current_app.logger.info(f'Cogent start TZ: {start_tz_name}')
        self.add_and_commit(maint)

        NEW_PARENT_MAINT.labels(provider=self.name).inc()

        # get the circuit IDs
        cids = set()
        a_side = set()
        for cid in circuit_ids_re.groups()[0].split(','):
            cid = cid.strip()
            cids.add(cid)
            a_side.add(maint.location)

        current_app.logger.info(f'Cogent cids: {cids}, a_sides: {a_side}')
        if len(cids) == len(a_side):
            for cid, a_side in zip(cids, a_side):
                if not Circuit.query.filter_by(provider_cid=cid).first():
                    circuit = Circuit()
                    circuit.provider_cid = cid
                    circuit.a_side = a_side
                    this = Pro.query.filter_by(
                        name=self.name,
                        type=self.type
                    ).first()
                    circuit.provider_id = this.id
                    self.add_and_commit(circuit)

                circuit_row = Circuit.query.filter_by(provider_cid=cid).first()
                maint_row = Maintenance.query.filter_by(
                    provider_maintenance_id=maint.provider_maintenance_id,
                    rescheduled=0
                ).first()

                mc = MaintCircuit(impact=impact, date=start_dt.date())
                circuit_row.maintenances.append(mc)
                mc.maint_id = maint_row.id
                db.session.commit()
                NEW_CID_MAINT.labels(cid=cid).inc()

        # sync with adm4
        sync_notices_na(email, maint.provider_maintenance_id, 'scheduled')

        return True

    def add_end_maint(self, soup, email):
        maint_id = self.get_maint_id(email)
        if not maint_id:
            return False

        maint = Maintenance.query.filter_by(
            provider_maintenance_id=maint_id, rescheduled=0).first()
        if not maint:
            return False

        maint.ended = 1

        self.add_and_commit(maint)

        return True

    def add_cancelled_maint(self, soup, email):
        maint_id = self.get_maint_id(email)
        if not maint_id:
            return False

        maint = Maintenance.query.filter_by(
            provider_maintenance_id=maint_id, rescheduled=0).first()
        if not maint:
            return False

        maint.cancelled = 1

        self.add_and_commit(maint)

        return True

    def process(self, email):
        msg = None
        result = False
        current_app.logger.info(f'Cogent Subject: {email["Subject"]}')
        for part in email.walk():
            if part.get_content_type() in ['text/html', 'text/plain']:
                msg = part.get_payload()

                if 'Cogent' in msg:
                    # this does not need to be decoded
                    break
                else:
                    # this needs to be decoded
                    msg = base64.b64decode(msg).decode()
                    break

        if not msg:
            current_app.logger.info(f'Cogent NO MSG')
            return False

        soup = bs4.BeautifulSoup(quopri.decodestring(msg), features="lxml")

        if 'Maintenance Completed' in email['Subject']:
            result = self.add_end_maint(soup, email)

        elif 'Cancellation Planned Network Maintenance' in email['Subject']:
            # cancellations prepend the word so have to filter first
            result = self.add_cancelled_maint(soup, email)

        elif 'Planned Network Maintenance' in email['Subject']:
            # NOTE cancellations are above here so we don't trigger on new
            result = self.add_new_maint(soup, email)

        elif 'Emergency Network Maintenance' in email['Subject']:
            # similar to regular one but an emergency
            result = self.add_new_maint(soup, email)


        return result
