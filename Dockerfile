FROM python:3.7.3-slim-stretch

ENTRYPOINT ["./run.sh"]

RUN apt-get update && apt-get install -y git libpq-dev gcc gfortran libmagic-dev cron && apt-get autoclean && rm -rf /var/lib/apt/lists/*

COPY . /snex2

RUN pip install --upgrade pip && pip install numpy && pip install -r /snex2/requirements.txt && pip cache purge

WORKDIR /snex2

RUN crontab crontab.txt
