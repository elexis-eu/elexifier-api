# -*- encoding: utf-8 -*-
"""
Python Aplication Template
Licence: GPLv3
"""

import dotenv
import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from celery import Celery


app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Read environment file
if os.path.exists('.env'):
	print('Environment file .env found.')
	dotenv.load_dotenv(dotenv_path='./.env', verbose=True, override=True)
else:
	print('Environment file not found!')
	dotenv.load_dotenv(dotenv_path='./.example.env', verbose=True, override=True)

# Load config based on environment
if os.environ['ENV'] == 'production':
	app.config.from_object('app.configuration.ProductionConfig')

elif os.environ['ENV'] == 'staging':
	app.config.from_object('app.configuration.StagingConfig')

elif os.environ['ENV'] == 'development':
	app.config.from_object('app.configuration.DevelopmentConfig')

# Init db and celery
db = SQLAlchemy(app)
celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)

# Import views
from app.user import views, models
from app.dataset import views, models
from app.transformation import views, models
from app.modules.pdf2lex_ml.ml_module import *
from app.modules.lexonomy import *
from app.modules.support import *
from app.modules.clarin import *
