FROM ubuntu:18.04

RUN apt-get update && \
      apt-get -y install g++ gcc libxslt-dev apt-utils libffi-dev python3-dev virtualenv autoconf automake g++ make nginx supervisor



COPY ./ /var/www/elexifier-api


RUN virtualenv -p /usr/bin/python3 /var/www/elexifier-api/venv
RUN /var/www/elexifier-api/venv/bin/pip install -r /var/www/elexifier-api/requirements.txt

RUN /var/www/elexifier-api/venv/bin/python /var/www/elexifier-api/manage.py db init
RUN /var/www/elexifier-api/venv/bin/python /var/www/elexifier-api/manage.py db migrate
RUN /var/www/elexifier-api/venv/bin/python /var/www/elexifier-api/manage.py db upgrade
RUN /var/www/elexifier-api/venv/bin/python /var/www/elexifier-api/create_server_user.py

RUN ./elexifier-supervisor.conf /etc/supervisor/conf.d/elexifier-supervisor.conf

RUN supervisorctl reread
RUN service supervisor restart

RUN ls /etc/nginx/

COPY ./nginx.conf /etc/nginx/nginx.conf
COPY ./elexifier-api.nginx /etc/nginx/conf.d/virtual.conf


Run nginx -t

RUN /etc/init.d/nginx start


EXPOSE 80




