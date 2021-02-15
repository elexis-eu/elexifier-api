import os
"""
Some configuration is loaded from .env file in project root directory.
- Database
- Secrets
"""


class Config(object):
    APP_DIR = os.path.abspath(os.path.dirname(__file__))  # This directory
    APP_ROOT = os.path.abspath(os.path.join(APP_DIR, os.pardir))
    APP_MEDIA = os.path.os.path.join(APP_DIR, 'media')
    URL = os.environ['URL']
    LEXONOMY_URL = os.environ['LEXONOMY_URL']

    # Database
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = 'postgresql+psycopg2://{user}:{passwd}@{host}/{db}'.format(
        user=os.environ['SQLALCHEMY_USER'],
        passwd=os.environ['SQLALCHEMY_PASSWD'],
        host=os.environ['SQLALCHEMY_HOST'],
        port=os.environ['SQLALCHEMY_PORT'],
        db=os.environ['SQLALCHEMY_DB'])

    # Worker
    CELERY_BROKER_URL = 'redis://redis:6379/0'
    CELERY_RESULT_BACKEND = 'redis://redis:6379/0'

    # Secrets
    SECRET_KEY = os.environ['SECRET_KEY']
    LEXONOMY_AUTH_KEY = os.environ['LEXONOMY_AUTH_KEY']


class DevelopmentConfig(Config):
    ENV = 'development'
    DEBUG = True


class StagingConfig(Config):
    ENV = 'staging'
    DEBUG = True
    SENTRY_DNS = 'https://2c2addccf9dc4ba8adee2452bae1782d@sentry.io/1768384'


class ProductionConfig(Config):
    ENV = 'production'
    DEBUG = False
    SENTRY_DNS = 'https://f64acc6a844543e3bde419789edbb54f@sentry.io/1724070'
