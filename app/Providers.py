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

from app.models import Maintenance, Circuit, MaintCircuit, MaintUpdate
from app.models import Provider as Pro  # don't conflict with the class below
from app import db

from app.jobs.started import FUNCS as started_funcs
from app.jobs.ended import FUNCS as ended_funcs


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
        circuit = Circuit()
        circuit.provider_cid = cid
        provider = Pro.query.filter_by(name=self.name, type=self.type).first()
        circuit.provider_id = provider.id
        self.add_and_commit(circuit)

    def add_new_maint(self, email, cal):
        '''
        add a new maintenance to the db
        email: email.email object
        cal: icalendar object
        '''
        maint = Maintenance()
        maint.provider_maintenance_id = cal['X-MAINTNOTE-MAINTENANCE-ID'].strip()
        maint.start = cal['DTSTART'].dt.time()
        maint.end = cal['DTEND'].dt.time()
        maint.timezone = cal['DTSTART'].dt.tzname()
        # not all ics attachments have descriptions
        if cal.get('DESCRIPTION'):
            maint.reason = cal['DESCRIPTION'].strip()
        received = email['Received'].splitlines()[-1].strip()
        maint.received_dt = parser.parse(received)

        self.add_and_commit(maint)

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
                provider_maintenance_id=maint.provider_maintenance_id, rescheduled=0
            ).first()
            mc = MaintCircuit(
                impact=cal['X-MAINTNOTE-IMPACT'].strip(), date=cal['DTSTART'].dt.date()
            )
            circuit_row.maintenances.append(mc)
            mc.maint_id = maint_row.id
            db.session.commit()

        return True

    def add_cancelled_maint(self, email, cal):
        '''
        add a maintenance cancellation to the maintenance row
        email: email.email object
        cal: icalendar object
        '''
        maint = Maintenance.query.filter_by(
            provider_maintenance_id=cal['X-MAINTNOTE-MAINTENANCE-ID'], rescheduled=0
        ).first()

        if not maint:
            return False

        maint.cancelled = 1

        self.add_and_commit(maint)

        return True

    def add_start_maint(self, email, cal):
        '''
        change the maintenance started column from 0 to 1.
        not all providers send an email when a maintenance starts.
        email: email.email object
        cal: icalendar object
        '''
        maint = Maintenance.query.filter_by(
            provider_maintenance_id=cal['X-MAINTNOTE-MAINTENANCE-ID'], rescheduled=0
        ).first()

        if not maint:
            return False

        maint.started = 1

        self.add_and_commit(maint)

        for func in started_funcs:
            func(email=email, maintenance=maint)

        return True

    def add_end_maint(self, email, cal):
        '''
        change the maintenance ended column from 0 to 1
        email: email.email object
        cal: icalendar object
        '''
        maint = Maintenance.query.filter_by(
            provider_maintenance_id=cal['X-MAINTNOTE-MAINTENANCE-ID'], rescheduled=0
        ).first()

        if not maint:
            return False

        maint.ended = 1

        self.add_and_commit(maint)

        for func in ended_funcs:
            func(email=email, maintenance=maint)

        return True

    def update(self, email, cal):
        maint = Maintenance.query.filter_by(
            provider_maintenance_id=cal['X-MAINTNOTE-MAINTENANCE-ID'], rescheduled=0
        ).first()

        if not maint:
            return False

        u = MaintUpdate(
            maintenance_id=maint.id,
            comment=cal['DESCRIPTION'],
            updated=datetime.datetime.now(),
        )

        self.add_and_commit(u)

        return True

    def process(self, email):
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

        if 'X-MAINTNOTE-STATUS' not in info:
            return False

        if info['X-MAINTNOTE-STATUS'].lower() in ['confirmed', 'tentative']:
            result = self.add_new_maint(email, info)

        elif info['X-MAINTNOTE-STATUS'].lower() == 'cancelled':
            result = self.add_cancelled_maint(email, info)

        elif info['X-MAINTNOTE-STATUS'].lower() == 'in-process':
            result = self.add_start_maint(email, info)

        elif info['X-MAINTNOTE-STATUS'].lower() == 'completed':
            result = self.add_end_maint(email, info)

        elif info['SEQUENCE'] > 0:
            result = self.update(email, info)

        return result


class NTT(StandardProvider):
    '''
    Notes: NTT starts their sequence numbers at 0
    '''

    def __init__(self):
        super().__init__()
        self.name = 'ntt'
        self.type = 'transit'
        self.email_esc = 'fillmein'
        if not Pro.query.filter_by(name=self.name, type=self.type).first():
            p = Pro(name=self.name, type=self.type, email_esc=self.email_esc)
            self.add_and_commit(p)

    @property
    def identified_by(self):
        return b'(FROM "NTT Communications" UNSEEN)'


class PacketFabric(StandardProvider):
    def __init__(self):
        super().__init__()
        self.name = 'packetfabric'
        self.type = 'transit'
        self.email_esc = 'fillmein'
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
        self.email_esc = 'fillmein'
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
        self.email_esc = 'fillmein'
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
                provider_maintenance_id=maint_id, rescheduled=0
            ).first()

        return maint_id

    def add_start_maint(self, soup, email):
        maint = self.get_maintenance(soup)

        if not maint:
            return False

        maint.started = 1

        self.add_and_commit(maint)

        for func in started_funcs:
            func(email=email, maintenance=maint)

        return True

    def add_end_maint(self, soup, email):
        maint = self.get_maintenance(soup)

        if not maint:
            return False

        if email['Subject'].lower().startswith('completed maintenance'):
            maint.ended = 1

            self.add_and_commit(maint)

        for func in ended_funcs:
            func(email=email, maintenance=maint)

        return True

    def add_cancelled_maint(self, soup, email):
        maint = self.get_maintenance(soup)

        if not maint:
            return False

        maint.cancelled = 1

        self.add_and_commit(maint)

        return True

    def add_reschedule_maint(self, soup, email):
        '''
        zayo sends reschedule emails so we're able to identified_by
        a new maintenance that references an old one
        '''
        old_maint = self.get_maintenance(soup)

        if not old_maint:
            self.add_new_maint(soup, email)
            return True

        old_maint.rescheduled = 1
        self.add_and_commit(old_maint)

        time.sleep(5)

        self.add_new_maint(soup, email)

        new_maint = Maintenance.query.filter_by(
            provider_maintenance_id=old_maint.provider_maintenance_id, rescheduled=0
        ).first()

        old_maint.rescheduled_id = new_maint.id

        self.add_and_commit(old_maint)

        return True

    def add_new_maint(self, soup, email):
        '''
        zayo bolds the relevant fields so we use bs4 to search for those
        and then get the next sibling
        '''
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
                    maint.provider_maintenance_id = self.clean_line(line.next_sibling)
                # elif 'urgency' in line.text.lower():
                #    row_insert['urgency'] = self.clean_line(line.next_sibling)

                elif 'location of maintenance' in line.text.lower():
                    maint.location = self.clean_line(line.next_sibling)

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
                            pfx = current_app.config['TZ_PREFIX']
                            maint.timezone = pfx + window.pop()
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

        cid_table = self.format_circuit_table(table)
        for row in cid_table.values:
            if not Circuit.query.filter_by(provider_cid=row[0]).first():
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
                this = Pro.query.filter_by(name=self.name, type=self.type).first()
                circuit.provider_id = this.id
                self.add_and_commit(circuit)

            circuit_row = Circuit.query.filter_by(provider_cid=row[0]).first()
            maint_row = Maintenance.query.filter_by(
                provider_maintenance_id=maint.provider_maintenance_id, rescheduled=0
            ).first()
            for date in dates:
                mc = MaintCircuit(impact=row[1], date=date)
                circuit_row.maintenances.append(mc)
                mc.maint_id = maint_row.id
                db.session.commit()

        return True

    def update(self, soup, email):
        match = re.search('TTN-\d+', email['Subject'])
        if not match:
            return

        ticket = match.group()
        maint = Maintenance.query.filter_by(
            provider_maintenance_id=ticket, rescheduled=0
        ).all()

        if maint:
            assert len(maint) == 1, 'More than one maint returned!'
            maint = maint[0]

            u = MaintUpdate(
                maintenance_id=maint.id,
                comment=soup.text,
                updated=datetime.datetime.now(),
            )

            self.add_and_commit(u)

            return True

        return False

    def process(self, email):
        msg = None
        result = False

        for part in email.walk():
            if part.get_content_type() == 'text/html':
                msg = part
                break

        if not msg:
            return False

        soup = bs4.BeautifulSoup(msg.get_payload(), features="lxml")

        if email['Subject'].startswith(
            '***'
        ) and 'maintenance notification' in self.clean_line(email['Subject'].lower()):
            result = self.add_new_maint(soup, email)

        elif email['Subject'].lower().startswith('reschedule notification'):
            result = self.add_reschedule_maint(soup, email)

        elif email['Subject'].lower().startswith('start maintenance notification'):
            result = self.add_start_maint(soup, email)

        elif email['Subject'].lower().startswith(
            'completed maintenance notification'
        ) or email['Subject'].lower().startswith('end of window'):
            result = self.add_end_maint(soup, email)

        elif email['Subject'].lower().startswith('cancelled notification'):
            result = self.add_cancelled_maint(soup, email)

        elif (
            'TTN-' in email['Subject']
            and 'maintenance notification' in email['Subject'].lower()
        ):
            result = self.update(soup, email)

        return result


class GTT(Provider):
    '''
    GTT
    '''

    def __init__(self):
        super().__init__()
        self.name = 'gtt'
        self.type = 'transit'
        self.email_esc = 'fillmein'
        if not Pro.query.filter_by(name=self.name, type=self.type).first():
            p = Pro(name=self.name, type=self.type, email_esc=self.email_esc)
            self.add_and_commit(p)

    @property
    def identified_by(self):
        return b'(FROM "ChangeManagement@gtt.net" UNSEEN)'

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
        start_re = re.search(r'Start: (.*)\r', soup.text)
        end_re = re.search(r'End: (.*)\r', soup.text)
        location_re = re.search(r'Location: (.*)\r', soup.text)
        reason_re = re.search(r'Reason: (.*)(\r|\n)', soup.text)
        impact_re = re.search(r'Impact: (.*)\r', soup.text)
        impact = impact_re.groups()[0]
        start_dt = parser.parse(start_re.groups()[0])
        end_dt = parser.parse(end_re.groups()[0])
        maint.start = start_dt.time()
        maint.end = end_dt.time()
        maint.timezone = start_dt.tzname()
        maint.location = location_re.groups()[0]
        maint.reason = reason_re.groups()[0]

        self.add_and_commit(maint)

        # sometimes maint emails contain the same cid several times
        cids = set()
        a_side = set()

        for line in soup.text.splitlines():
            if 'gtt service' in line.lower():
                cid = re.search(r'= (.+);', line)
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
                    this = Pro.query.filter_by(name=self.name, type=self.type).first()
                    circuit.provider_id = this.id
                    self.add_and_commit(circuit)

                circuit_row = Circuit.query.filter_by(provider_cid=cid).first()
                maint_row = Maintenance.query.filter_by(
                    provider_maintenance_id=maint.provider_maintenance_id, rescheduled=0
                ).first()

                mc = MaintCircuit(impact=impact, date=start_dt.date())
                circuit_row.maintenances.append(mc)
                mc.maint_id = maint_row.id
                db.session.commit()

        return True

    def add_end_maint(self, soup, email):
        maint_id = self.get_maint_id(email)
        if not maint_id:
            return False

        maint = Maintenance.query.filter_by(
            provider_maintenance_id=maint_id, rescheduled=0
        ).first()
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
            provider_maintenance_id=maint_id, rescheduled=0
        ).first()
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
            provider_maintenance_id=maint_id, rescheduled=0
        ).first()

        if not maint:
            return False

        update_text = soup.text

        if not update_text:
            for payload in email.get_payload():
                update_text = payload.get_payload()

        u = MaintUpdate(
            maintenance_id=maint.id, comment=soup.text, updated=datetime.datetime.now()
        )

        self.add_and_commit(u)

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

        soup = bs4.BeautifulSoup(msg.get_payload(), features="lxml")

        if 'work announcement' in email['Subject'].lower():
            result = self.add_new_maint(soup, email)

        elif 'work conclusion' in email['Subject'].lower():
            result = self.add_end_maint(soup, email)

        elif 'work cancellation' in email['Subject'].lower():
            result = self.add_cancelled_maint(soup, email)

        elif 'gtt tt#' in email['Subject'].lower():
            result = self.update(soup, email)

        return result


class Telia(Provider):
    '''
    Telia
    '''

    def __init__(self):
        super().__init__()
        self.name = 'telia'
        self.type = 'transit'
        self.email_esc = 'fillmein'
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
        maint_id = re.search('(?<=reference number: )\S+', msg.lower())

        if maint_id and maint_id.group():
            maint_id = Maintenance.query.filter_by(
                provider_maintenance_id=maint_id.group(), rescheduled=0
            ).first()

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

        self.add_and_commit(maint)

        cids = re.findall('service id: (.*)\r', msg.lower())
        impact = re.findall('impact: (.*)\r', msg.lower())

        all_circuits = list(zip(cids, impact))

        for cid, impact in all_circuits:
            if not Circuit.query.filter_by(provider_cid=cid).first():
                c = Circuit()
                c.provider_cid = cid
                this = Pro.query.filter_by(name=self.name, type=self.type).first()
                c.provider_id = this.id
                self.add_and_commit(c)

            circuit_row = Circuit.query.filter_by(provider_cid=cid).first()
            maint_row = Maintenance.query.filter_by(
                provider_maintenance_id=maint.provider_maintenance_id, rescheduled=0
            ).first()

            mc = MaintCircuit(impact=impact, date=start_dt.date())
            circuit_row.maintenances.append(mc)
            mc.maint_id = maint_row.id
            db.session.commit()

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

        maint.started = 1

        self.add_and_commit(maint)

        for func in started_funcs:
            func(email=email, maintenance=maint)

        return True

    def add_end_maint(self, msg, email):
        maint = self.get_maintenance(msg)

        if not maint:
            return False

        maint.ended = 1

        self.add_and_commit(maint)

        for func in ended_funcs:
            func(email=email, maintenance=maint)

        return True

    def add_rescheduled_maint(self, msg, email):
        old_maint = self.get_maintenance(msg)

        if not old_maint:
            return False

        old_maint.rescheduled = 1
        self.add_and_commit(old_maint)

        time.sleep(5)

        self.add_new_maint(msg, email)

        new_maint = Maintenance.query.filter_by(
            provider_maintenance_id=old_maint.provider_maintenance_id, rescheduled=0
        ).first()

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

        if email['Subject'].lower().startswith('planned work') or email[
            'Subject'
        ].lower().startswith('urgent!'):
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
            result = self.add_reschedule_maint(msg, email)

        return result
