class Config(object):
	"""
	Configuration base, for all environments.
	"""
	DEBUG = False
	SQLALCHEMY_DATABASE_URI = 'sqlite:///./../app.db'
	SECRET_KEY = "\x15['\xfc\xa6\x0fo^\xda\x83\xfe\x83Zz\xd1\xa8?Cs\xf4\xf3]\xf8\x94"
	CSRF_ENABLED = True
	SQLALCHEMY_TRACK_MODIFICATIONS = False


class ProductionConfig(Config):
	SQLALCHEMY_DATABASE_URI = 'postgres://user@localhost/foo'

class DevelopmentConfig(Config):
	DEBUG = True



