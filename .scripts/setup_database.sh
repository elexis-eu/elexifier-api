set -e

echo "Initializing the database"
python3 manage.py db init

echo "Running migrations"
python3 manage.py db migrate

echo "Upgrading the database"
python3 manage.py db upgrade
