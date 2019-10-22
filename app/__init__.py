# -*- encoding: utf-8 -*-
"""
Python Aplication Template
Licence: GPLv3
"""

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
import dotenv, os

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# If there is no .env file in root directory, api will load with default configuration DEVELOPMENT.
if os.path.exists(".env"):
	print("Environment file .env found.")
	dotenv.load_dotenv(dotenv_path='./.env', verbose=True)
	app.config.from_object('app.configuration.ProductionConfig')

	import sentry_sdk
	from sentry_sdk.integrations.flask import FlaskIntegration
	from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
	from sentry_sdk.integrations.celery import CeleryIntegration

	if os.environ['ENV'] == "staging":
		sentry_sdk.init(
			dsn=os.environ['SENTRY_DSN_STAGING'],
			integrations=[FlaskIntegration(), SqlalchemyIntegration(), CeleryIntegration()]
		)
	else:
		sentry_sdk.init(
			dsn=os.environ['SENTRY_DSN_PRODUCTION'],
			integrations=[FlaskIntegration(), SqlalchemyIntegration(), CeleryIntegration()]
		)

else:
	print("No .env file found, using default config: Development.")

	# This is here, so that configuration.py doesn't crash.
	os.environ['ENV'] = 'development'
	os.environ['SQLALCHEMY_USER'] = ""
	os.environ['SQLALCHEMY_PASSWD'] = ""
	os.environ['SQLALCHEMY_HOST'] = ""
	os.environ['SQLALCHEMY_PORT'] = ""
	os.environ['SQLALCHEMY_DB'] = ""
	app.config.from_object('app.configuration.DevelopmentConfig')

db = SQLAlchemy(app)  # flask-sqlalchemy
from app import views, models
