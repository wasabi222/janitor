FROM python:3.7.6-slim-stretch as builder

RUN apt-get update && apt-get install -y build-essential libpq-dev libmariadbclient-dev curl

ADD ./ /opt/janitor/

COPY ./docker/init.sh /tmp/init.sh

COPY ./docker/requirements.txt /tmp/requirements.txt

RUN pip3 install --upgrade setuptools

RUN pip3 install -r /tmp/requirements.txt && pip3 --no-cache install gunicorn && pip3 --no-cache install psycopg2

EXPOSE 8000

WORKDIR /opt/janitor

ENTRYPOINT ["sh", "/tmp/init.sh"]

CMD ["uwsgi", "--http", ":8000", "--mount", "/myapplication=janitor:app", "--enable-threads", "--processes", "5"]
