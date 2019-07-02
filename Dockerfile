FROM python:3.6-slim-stretch

COPY ./ /opt/janitor/

COPY ./docker/init.sh /var/run/init.sh
COPY ./docker/nginx.conf /etc/nginx/sites-enabled/janitor
COPY ./docker/supervisor.conf /etc/supervisor/conf.d/janitor.conf

RUN apt-get update \
 && apt-get install -y nginx ca-certificates supervisor gcc libmariadbclient-dev libpq-dev \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* \
 && pip --no-cache install gunicorn \
 && pip --no-cache install -r /opt/janitor/requirements.txt \
 && rm /etc/nginx/sites-enabled/default

EXPOSE 80

ENTRYPOINT /var/run/init.sh
