FROM tiangolo/uwsgi-nginx-flask:python3.6-alpine3.7
RUN apk --update add bash nano

RUN adduser -D -u 1000 docker
COPY ./ /home/docker/elexifier-api

RUN apk add --update --no-cache g++ gcc libxslt-dev libffi-dev
RUN apk add python3-dev py3-virtualenv autoconf automake g++ make build-base linux-headers pcre-dev openrc --no-cache

RUN /usr/bin/python3.6

COPY ./elexifier-api.service /etc/systemd/system/elexifier-api.service
COPY ./elexifier-api.nginx /etc/nginx/sites-available/elexifier-api
RUN ln -s /etc/nginx/sites-available/myproject /etc/nginx/sites-enabled



RUN pip install -r /home/docker/elexifier-api/requirements.txt

RUN rc-service elexifier-api start
RUN rc-status

RUN rc-service nginx restart



