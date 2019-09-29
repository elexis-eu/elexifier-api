#!/bin/bash

DIR="/var/www/elexifier-api/migrations"
if [ ! -d "$DIR" ]; then
  echo "Initializing database, migrating and creating user"
  python /var/www/elexifier-api/manage.py db init &&
  python /var/www/elexifier-api/manage.py db migrate && 
  python /var/www/elexifier-api/manage.py db upgrade
else
  echo "Migration folder exists, checking if database migrations are needed"
  output=$(python /var/www/elexifier-api/manage.py db migrate 2>&1)
  if  [[ ! $output == *"No changes in schema detected." ]] ; then
  	echo "Upgrading database"
  	python /var/www/elexifier-api/manage.py db upgrade
  else
  	echo "No database upgrade required"
  fi
fi

echo "Starting the gunicorn server"
gunicorn -b 0.0.0.0:8080 wsgi:app

