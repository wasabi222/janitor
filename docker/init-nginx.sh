#!/bin/bash

set -e

cd /opt/janitor

if [ "$INIT_DB" == true ]; then
    echo "Initialising the database..."
    flask db init
    flask db migrate
    flask db upgrade
fi

/usr/bin/supervisord

if [ "$START_NGINX" == true ]; then
    /usr/sbin/nginx -g "daemon off;"
fi
