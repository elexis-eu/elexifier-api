FROM python:3.6

RUN apt-get update && \
      apt-get -y install g++ gcc libxslt-dev apt-utils libffi-dev python3-dev virtualenv autoconf automake g++ make


COPY ./ /var/www/elexifier-api

WORKDIR /var/www/elexifier-api/

RUN pip install -r /var/www/elexifier-api/requirements.txt


RUN python /var/www/elexifier-api/manage.py db init
RUN python /var/www/elexifier-api/manage.py db migrate
RUN python /var/www/elexifier-api/manage.py db upgrade
RUN python /var/www/elexifier-api/create_server_user.py

CMD ["gunicorn", "-b", "0.0.0.0:8080", "wsgi:app"]
