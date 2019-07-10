import logging
from logging.handlers import RotatingFileHandler
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_moment import Moment
from pytz import utc
from flask_apscheduler import APScheduler
from flask_marshmallow import Marshmallow
from flask_migrate import Migrate
from flask_bootstrap import Bootstrap
from config import Config
from flask_uploads import UploadSet, DOCUMENTS, configure_uploads
import connexion

db = SQLAlchemy()
moment = Moment()
migrate = Migrate()
bootstrap = Bootstrap()
ma = Marshmallow()
documents = UploadSet('documents', DOCUMENTS)
scheduler = APScheduler()


def process_startup():
    process()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    JOBS = [
        {
            'id': 'run_loop',
            'func': process_startup,
            'trigger': 'interval',
            'replace_existing': True,
            'seconds': int(app.config['CHECK_INTERVAL']),
        }
    ]
    app.config['JOBS'] = JOBS

    db.init_app(app)
    moment.init_app(app)
    migrate.init_app(app, db)
    bootstrap.init_app(app)
    ma.init_app(app)
    scheduler.init_app(app)
    scheduler.start()

    from app.errors import bp as errors_bp

    app.register_blueprint(errors_bp)

    from app.main import bp as main_bp

    app.register_blueprint(main_bp)

    configure_uploads(app, documents)

    connexion_register_blueprint(app, 'api/v1/swagger/main.yaml')

    log_level = {
        'debug': logging.DEBUG,
        'info': logging.INFO,
        'warning': logging.WARNING,
        'error': logging.ERROR,
        'critical': logging.CRITICAL,
    }

    if not app.debug and not app.testing:
        file_handler = RotatingFileHandler(
            app.config['LOGFILE'], maxBytes=20480, backupCount=10
        )
        file_handler.setFormatter(
            logging.Formatter(
                '%(asctime)s %(levelname)s: %(message)s ' '[in %(pathname)s:%(lineno)d]'
            )
        )
        file_handler.setLevel(log_level[app.config['LOG_LEVEL']])
        app.logger.addHandler(file_handler)

        app.logger.setLevel(log_level[app.config['LOG_LEVEL']])
        app.logger.info('janitor app started')

    return app


def connexion_register_blueprint(app, swagger_file, **kwargs):
    options = {"swagger_ui": True}
    con = connexion.FlaskApp(
        "api/v1",
        app.instance_path,  # /v1/swagger
        specification_dir='api/v1/swagger',
        options=options,
    )
    specification = 'main.yaml'
    api = super(connexion.FlaskApp, con).add_api(specification, **kwargs)
    app.register_blueprint(api.blueprint)
    return api


from app import models
from app.jobs.main import process
