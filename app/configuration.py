import os

"""
Configuration base, for all environments.
If there is no .env file in root directory,
api will load with default configuration DEVELOPMENT.
In case of STAGING or PRODUCTION environment,
manage api configuration via .env file.
"""
class Config(object):
    DEBUG = os.environ['DEBUG']
    SECRET_KEY = os.environ['SECRET_KEY']
    # CSRF_ENABLED - remove in the future
    # CSRF_ENABLED = os.environ['CSRF_ENABLED']
    SQLALCHEMY_TRACK_MODIFICATIONS = os.environ['SQLALCHEMY_TRACK_MODIFICATIONS']
    CELERY_BROKER_URL = os.environ['CELERY_BROKER_URL']
    CELERY_RESULT_BACKEND = os.environ['CELERY_RESULT_BACKEND']
    LEXONOMY_AUTH_KEY = os.environ['LEXONOMY_AUTH_KEY']
    SQLALCHEMY_DATABASE_URI = 'postgresql+psycopg2://{user}:{passwd}@{host}/{db}'.format(
        user=os.environ['SQLALCHEMY_USER'],
        passwd=os.environ['SQLALCHEMY_PASSWD'],
        host=os.environ['SQLALCHEMY_HOST'],
        port=os.environ['SQLALCHEMY_PORT'],
        db=os.environ['SQLALCHEMY_DB'])


class DevelopmentConfig(Config):
    ENV = 'development'


class ProductionConfig(Config):
    ENV = os.environ['ENV']
    SQLALCHEMY_DATABASE_URI = 'postgresql+psycopg2://{user}:{passwd}@{host}/{db}'.format(
        user=os.environ['SQLALCHEMY_USER'],
        passwd=os.environ['SQLALCHEMY_PASSWD'],
        host=os.environ['SQLALCHEMY_HOST'],
        port=os.environ['SQLALCHEMY_PORT'],
        db=os.environ['SQLALCHEMY_DB'])



