#!/bin/bash
python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py runcadencestrategies
crontab crontab.txt
gunicorn -b 0.0.0.0:8080 snex2.wsgi
