
class Config(object):
	"""
	Configuration base, for all environments.
	"""
	DEBUG = False
	SQLALCHEMY_DATABASE_URI = 'sqlite:///./../app.db'
	SECRET_KEY = "\x15['\xfc\xa6\x0fo^\xda\x83\xfe\x83Zz\xd1\xa8?Cs\xf4\xf3]\xf8\x94"
	CSRF_ENABLED = True
	SQLALCHEMY_TRACK_MODIFICATIONS = False
	CELERY_BROKER_URL = 'redis://localhost:6379/0'
	CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'
	ENV = 'production'


class ProductionConfig(Config):
	SQLALCHEMY_DATABASE_URI = 'postgresql+psycopg2://{user}:{passwd}@{host}/{db}'.format(
        user='elexifier',
        passwd='elexifierpass',
        host='db',
        port='5431',
        db='postgresdb')

class DevelopmentConfig(Config):
	DEBUG = True
	ENV = 'development'



