import os
from dotenv import load_dotenv
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))


class Config(object):
    PROJECT_ROOT = os.environ.get('PROJECT_ROOT') or os.getcwd()
    SECRET_KEY = os.environ.get('SECRET_KEY')
    MAX_CONTENT_LENGTH =  int(os.environ.get('MAX_CONTENT_LENGTH')) if os.environ.get('MAX_CONTENT_LENGTH') else \
        32 * 1024 * 1024
    LOGFILE = os.environ.get('LOGFILE') or '/var/log/janitor.log'
    LOG_LEVEL = os.environ.get('LOG_LEVEL') or 'INFO'
    CHECK_INTERVAL = os.environ.get('CHECK_INTERVAL') or 600
    POSTS_PER_PAGE = os.environ.get('POSTS_PER_PAGE') or 20
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'app.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SCHEDULER_JOBSTORES = {
        'default': SQLAlchemyJobStore(url=SQLALCHEMY_DATABASE_URI)
    }
    SCHEDULER_API_ENABLED = True
    SCHEDULER_TIMEZONE = 'UTC'
    TZ_PREFIX = os.environ.get('TZ_PREFIX')
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAILBOX = os.environ.get('MAILBOX') or 'INBOX'
    SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')
    SLACK_CHANNEL = os.environ.get('SLACK_CHANNEL')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_CLIENT = os.environ.get('MAIL_CLIENT')
    PROMETHEUS_DIR = os.environ.get('prometheus_multiproc_dir') or os.environ.get('PROMETHEUS_DIR')
    # Uploads
    UPLOADS_DEFAULT_DEST = os.environ.get('UPLOADS_DEFAULT_DEST') or PROJECT_ROOT + '/app/static/circuits/'
    UPLOADED_DOCUMENTS_DEST = os.environ.get('UPLOADED_DOCUMENTS_DEST') or PROJECT_ROOT + '/app/static/circuits/'
    UPLOADED_DOCUMENTS_ALLOW = ('pdf', 'zip', 'gzip', 'tar', 'bz')
    JANITOR_URL = os.environ.get('JANITOR_URL')


