import os

"""
Configuration base, for all environments.
If there is no .env file in root directory,
api will load with default configuration DEVELOPMENT.
In case of STAGING or PRODUCTION environment,
manage api configuration via .env file.
"""
class Config(object):
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = 'sqlite:///./../app.db'
    SECRET_KEY = "\x15['\xfc\xa6\x0fo^\xda\x83\xfe\x83Zz\xd1\xa8?Cs\xf4\xf3]\xf8\x94"
    CSRF_ENABLED = True
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    CELERY_BROKER_URL = 'redis://localhost:6379/0'
    CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'


class DevelopmentConfig(Config):
    DEBUG = True
    ENV = 'development'


class ProductionConfig(Config):
    ENV = os.environ['ENV']
    SQLALCHEMY_DATABASE_URI = 'postgresql+psycopg2://{user}:{passwd}@{host}/{db}'.format(
        user=os.environ['SQLALCHEMY_USER'],
        passwd=os.environ['SQLALCHEMY_PASSWD'],
        host=os.environ['SQLALCHEMY_HOST'],
        port=os.environ['SQLALCHEMY_PORT'],
        db=os.environ['SQLALCHEMY_DB'])



