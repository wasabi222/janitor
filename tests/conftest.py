import pytest
from datetime import datetime
from app import db, create_app
from config import Config
from app.jobs.main import PROVIDERS
from app.models import Provider, Circuit, Maintenance, MaintCircuit
import os
import tempfile

@pytest.fixture(scope='module')
def api():
    return '/api/v1'

class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite://'
    WTF_CSRF_ENABLED = False
    SCHEDULER_JOBSTORES = None


@pytest.fixture(scope='module')
def client():
    a = create_app(TestConfig)
    a.apscheduler.scheduler.shutdown()
    db_fd, a.config['DATABASE_FILE'] = tempfile.mkstemp()
    client = a.test_client()
    a.before_first_request_funcs = []

    with a.app_context():

        db.create_all()
        for provider in PROVIDERS:
             p = provider()
        circuit = Circuit(provider_cid='xxx', a_side='a', z_side='z', provider_id=1)
        db.session.add(circuit)
        db.session.commit()
        now = datetime.now()
        maint = Maintenance(provider_maintenance_id='pmaintid', start=now.time(),
                            end=now.time(), timezone='US/Eastern',
                            received_dt=now)
        mc = MaintCircuit(impact='yuge', date=now.date())
        circuit.maintenances.append(mc)
        mc.maint_id = maint.id

        db.session.add(maint)
        db.session.commit()

    yield client

    with a.app_context():
        db.drop_all()
    os.close(db_fd)
    os.unlink(a.config['DATABASE_FILE'])

