#!/bin/bash

set -e

cd /opt/janitor
flask db init
flask db migrate
flask db upgrade

/usr/bin/supervisord
/usr/sbin/nginx -g "daemon off;"
