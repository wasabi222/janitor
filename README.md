janitor
=======

Janitor is a flask application for parsing provider maintenance notification emails and taking actions based on those emails. It's written to be easily extensible to your environment.


# Overview
Janitor connects to an email server on a user-specified interval and checks for any maintenance emails from a list of providers and adds them to the database. It can then be configured to take an action based on the type of email: new, update, cancel, reschedule, started, and ended. For instance, you can post updates to slack on maintenance start/end emails, add events to your calendar for new emails, remove events from your calendar for cancelled emails, etc. By default, start/end messages post to slack. You can perform custom actions on maintenance start/end emails by adding functions to `app/jobs/started.py` and `app/jobs/ended.py`.

# Demo
![demo](docs/demo.gif)

# Requirements
A gmail account with an [app password](https://support.google.com/accounts/answer/185833) is required to parse messages.

# Quickstart

```
git clone https://github.com/wasabi222/janitor.git
cd janitor/docker-compose
[edit janitor.env to provide correct values to MAIL_SERVER, MAIL_USERNAME, and MAIL_PASSWORD]
docker-compose up
```

# Components

## Mail Clients
A mail client is configured with an email address, password, and port so that it can be connected to for email retrieval. Currently only gmail is supported.

## Providers
Currently supported providers include:
 - NTT * 
 - PacketFabric * 
 - EUNetworks * 
 - GTT
 - Zayo


The * Providers follow the [maint note](https://github.com/jda/maintnote-std/blob/master/standard.md) standard.

# Configuration Options

### PROJECT_ROOT
The root folder of the janitor app. default: current working directory

### SECRET_KEY
Your application's secret key. This is required.

### MAX_CONTENT_LENGTH
Maximum size for circuit contract file uploads. default: 32 Mib

### LOGFILE
Location of the file that logs are written to. default: /var/log/janitor.log

### CHECK_INTERVAL
How frequently the mail server is checked for new messages. default: 10 minutes

### POSTS_PER_PAGE
The number of maintenances/circuits/providers to display on a single page. default: 20

### DATABASE_URL
The location of the database. all databases supported by sqlalchemy are supported. default: current working directory + app.db

### TZ_PREFIX
For correctly modifying timezones. Some providers send maintenances with a timezone of "Eastern" instead of "US/Eastern" which breaks python datetime. You could set the TZ_PREFIX value to "US/" to fix this issue. default: None

### MAIL_USERNAME
Username for your mail server. This is required

### MAIL_PASSWORD
Password for your mail server. This is required

### MAIL_SERVER
imap address of your mail server

### MAILBOX
The name of the mailbox to process messages from. default: INBOX

### MAIL_CLIENT
The mail client you wish to use. currently only gmail is supported. This is required.

### SLACK_WEBHOOK_URL
If you wish to send messages to slack, you can define this. default: None

### SLACK_CHANNEL
The channel to post slack messages to. default: None

### PROMETHEUS_DIR
The directory to store multiprocess prometheus metrics. default: /tmp/janitor_prometheus 


# database schema

![db schema](docs/schema.png)

# Setup
Below walks through installation on ubuntu

First, clone this repository into `/opt`:
```
cd /opt && git clone https://github.com/wasabi222/janitor.git
```

Next, work within the `janitor` directory:
```
cd janitor
```

## Database
You can choose any database you'd like. The examples below cover mariadb and postgres.

## mariadb
1. install mariadb
```
apt install mariadb-server
```
2. install mariadb dependencies
```
apt install libmariadbclient-dev
pip3 install mysqlclient
```
3. create the database
```
mariadb
MariaDB [(none)]> create database janitor CHARACTER SET utf8;
MariaDB [(none)]> CREATE USER 'janitor'@'localhost' IDENTIFIED BY 'mypass';
MariaDB [(none)]> GRANT ALL PRIVILEGES ON janitor.* TO 'janitor'@'localhost';
MariaDB [(none)]> quit

```

## postgres
1. install postgres
```
apt install postgresql
```
2. install postgres dependencies
```
pip3 install psycopg2
```
3. create the database
```
sudo -u postgres -i
psql
CREATE DATABASE janitor ENCODING 'UTF8';
CREATE USER janitor WITH PASSWORD mypass;
GRANT ALL PRIVILEGES ON DATABASE janitor to janitor;
```

## requirements
janitor requires python3.6

1. clone this repository into your desired installation directory
2. create your virtual environment and activate it
```
python3 -m venv venv
source venv/bin/activate
```
3. install the requirements
```
pip3 install -r requirements.txt
```
4. create a `.env` configuration files with the necessary variables. For example (note the different DATABASE_URL names based on the DB you're using):
```
PROJECT_ROOT='/opt/janitor'
# mariadb:
DATABASE_URL='mysql://janitor:mypass@localhost/janitor?charset=utf8'
# postgres:
DATABASE_URL='postgresql+psycopg2://janitor:mypass@127.0.0.1:5432/janitor'
CHECK_INTERVAL=300
SLACK_WEBHOOK_URL='https://hooks.slack.com/abc123'
SLACK_CHANNEL='#mychannel'
MAIL_USERNAME='user@example.com'
MAIL_PASSWORD='mypassword'
MAIL_SERVER='imap.example.com'
MAIL_CLIENT='Gmail'
SECRET_KEY='mysecretkey'
```
5. create the db schema:
```
flask db init
flask db migrate
flask db upgrade
```
6. You may wish to choose the providers you have in your network at this point, rather than selecting them all. You can do so by editing `app/jobs/main.py` and removing the ones you don't want in the `PROVIDERS` list
7. From the providers you selected, you can define the email and type info under each provider's class in `app/Providers.py` types are one of: `transit`, `backbone`, `transport`, `peering`, and `facility`.
8. at this point you can test connectivity to your server. First run the server:
```
flask run -h 0.0.0.0
```
and then open a browser to your IP to see if you can connect. 


## Web/uwsgi Server
It's not recommended to expose the flask app directly to the internet. Below we'll use nginx and gunicorn with supervisord for setup. It's also recommended to use https, though the the steps below only cover http

1. install the packages
```
apt install nginx supervisor
pip3 install gunicorn
```
2. create /etc/supervisor/conf.d/janitor.conf with the following contents:
```
[program:janitor]
command=/opt/janitor/venv/bin/gunicorn -b localhost:8000 -c /opt/janitor/gunicorn_config.py -w 4 janitor:app
directory=/opt/janitor
user=root
autostart=true
autorestart=true
stopasgroup=true
killasgroup=true
```
3. create /etc/nginx/sites-enabled/janitor with the following contents:
```
server {
    # listen on port 80 (http)
    listen 80;
    server_name _;
    access_log /var/log/janitor_access.log;
    error_log /var/log/janitor_error.log;
    location / {
        # forward application requests to the gunicorn server
        proxy_pass http://localhost:8000;
        proxy_redirect off;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location /static {
        # handle static files directly, without forwarding to the application
        alias /opt/janitor/app/static;
        expires 30d;
    }
}
```
4. restart nginx and supervisor
```
supervisorctl reload janitor
systemctl restart nginx
```

janitor only checks for unread messages in your inbox. You may want to mark a few messages as unread to see if messages are being parsed at this point by navigating to your janitor server's IP, and either waiting until the next email check runs (it will tell you when this will be), or by using the "process emails" button to process immediately. Once the connection is successful you can stop the server with Ctrl-C

# API
The API has a UI and can be reached via the `/api/v1/ui/` endpoint for testing. 

## Endpoints
All API endpoints need to be prefaced with `/api/v1`, for example, `/api/v1/circuits`

### /circuits
#### GET
Get all circuits
eg:
`curl -X GET --header 'Accept: application/json' 'https://192.0.2.1/api/v1/circuits'`

#### POST
Create a new circuit by posting json.
eg:
```
curl -X POST --header 'Content-Type: application/json' --header 'Accept: application/json' -d '{ \ 
   "a_side": "string", \ 
   "id": 0, \ 
   "provider_cid": "string", \ 
   "provider_id": 0, \ 
   "z_side": "string" \ 
 }' 'http://127.0.0.1:5000/api/v1/circuits'
```

### /circuits/{circuit_id}
#### GET
Get a single circuit by the ID
eg:
`curl -X GET --header 'Accept: application/json' 'http://127.0.0.1:5000/api/v1/circuits/1'`

#### PUT
Update a circuit by posting json
eg:
```
curl -X PUT --header 'Content-Type: application/json' --header 'Accept: application/json' -d '{ \ 
   "a_side": "string", \ 
   "provider_id": 1 \ 
 }' 'http://127.0.0.1:5000/api/v1/circuits/5'
```

### /maintenances
#### GET
Get all maintenances
eg:
`curl -X GET --header 'Accept: application/json' 'http://127.0.0.1:5000/api/v1/maintenances'`

### /maintenances/{maintenance_id}
#### GET
Get a maintenance by id
eg:
`curl -X GET --header 'Accept: application/json' 'http://127.0.0.1:5000/api/v1/maintenances/1'`

### /providers
#### GET
Get all providers
eg:
`curl -X GET --header 'Accept: application/json' 'http://127.0.0.1:5000/api/v1/providers'`

### /providers/{provider_id}
#### GET
Get a provider by id
eg:
`curl -X GET --header 'Accept: application/json' 'http://127.0.0.1:5000/api/v1/providers/1'`
