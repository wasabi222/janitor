import os

import yaml
from dotenv import load_dotenv
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))


class Config(object):
    def __init__(self):
        self.CONFIG_FILE = os.environ.get('CONFIG_FILE')
        self._CONFIG = {}
        if self.CONFIG_FILE:
            with open(self.CONFIG_FILE) as cfg_file:
                self._CONFIG = yaml.load(cfg_file)
        # When adding a new configuration variable, make sure to add its default here.
        defaults = {
            'PROJECT_ROOT': os.getcwd(),
            'SECRET_KEY': None,
            'MAX_CONTENT_LENGTH': 32 * 1024 * 1024,
            'LOGFILE': '/var/log/janitor.log',
            'CHECK_INTERVAL': 600,
            'POSTS_PER_PAGE': 20,
            'DATABASE_URL': None,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + os.path.join(basedir, 'app.db'),
            'SQLALCHEMY_TRACK_MODIFICATIONS': True,
            'SCHEDULER_API_ENABLED': True,
            'UPLOADED_DOCUMENTS_ALLOW': ('pdf', 'zip', 'gzip', 'tar', 'bz'),
            'SCHEDULER_TIMEZONE': 'UTC',
            'TZ_PREFIX': None,
            'MAILBOX': 'INBOX',
            'MAIL_USERNAME': None,
            'MAIL_PASSWORD': None,
            'MAIL_SERVER': None,
            'MAIL_CLIENT': 'gmail',
            'JANITOR_URL': None,
            'SLACK_WEBHOOK_URL': None,
            'SLACK_CHANNEL': None,
        }
        for attr, default in defaults.items():
            value = os.environ.get(attr, self._CONFIG.get(attr, default))
            setattr(self, attr, value)
        if self.DATABASE_URL:
            self.SQLALCHEMY_DATABASE_URI = self.DATABASE_URL
        # Uploads
        self.UPLOADS_DEFAULT_DEST = self.PROJECT_ROOT + '/app/static/circuits/'
        self.UPLOADED_DOCUMENTS_DEST = self.PROJECT_ROOT + '/app/static/circuits/'
