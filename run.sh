#!/bin/bash
python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py runcadencestrategies
service cron start
gunicorn -b 0.0.0.0:8080 snex2.wsgi
