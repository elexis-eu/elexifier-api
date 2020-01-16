FROM python:3.6

RUN apt-get update && \
      apt-get -y install g++ gcc libxslt-dev apt-utils libffi-dev python3-dev virtualenv autoconf automake g++ make


ADD . /var/www/elexifier-api

WORKDIR /var/www/elexifier-api/

RUN pip install -r /var/www/elexifier-api/requirements.txt
