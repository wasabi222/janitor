FROM python:3.6-slim-stretch

COPY ./ /opt/janitor/
COPY ./docker/init.sh /var/run/init.sh

RUN apt-get update \
 && apt-get install -y gcc libmariadbclient-dev libpq-dev \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* \
 && pip --no-cache install gunicorn \
 && pip --no-cache install -r /opt/janitor/requirements.txt

EXPOSE 8000

ENTRYPOINT /var/run/init.sh
