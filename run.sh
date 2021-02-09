#!/bin/bash
python manage.py collectstatic --noinput
python manage.py migrate --noinput
crontab crontab.txt
gunicorn -b 0.0.0.0:8080 snex2.wsgi
