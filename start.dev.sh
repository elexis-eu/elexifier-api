#!/bin/bash

service redis-server start
celery -A app.views:celery worker --loglevel=info &
python run.py
