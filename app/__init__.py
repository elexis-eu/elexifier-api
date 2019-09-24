# -*- encoding: utf-8 -*-
"""
Python Aplication Template
Licence: GPLv3
"""

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS


app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

#run the following command to change environment.
#export FLASK_ENV={production|development}


if app.config['ENV'] == 'production' :
	
	import sentry_sdk
	from sentry_sdk.integrations.flask import FlaskIntegration
	from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
	from sentry_sdk.integrations.celery import CeleryIntegration

	sentry_sdk.init(
	    dsn="https://f64acc6a844543e3bde419789edbb54f@sentry.io/1724070",
	    integrations=[FlaskIntegration(), SqlalchemyIntegration(), CeleryIntegration()]
	)

	app.config.from_object('app.configuration.ProductionConfig')

elif app.config['ENV'] == 'development':
	app.config.from_object('app.configuration.DevelopmentConfig')

else:
	app.config.from_object('configuration.TestingConfig')


db = SQLAlchemy(app) #flask-sqlalchemy
from app import views, models
