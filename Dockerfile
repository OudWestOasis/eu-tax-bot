# Railway container voor de EU Tax bot (één altijd-aan worker).
FROM python:3.13-slim

# UTC zodat de scheduler-cron in UTC draait (zoals de oude GitHub-crons).
ENV TZ=UTC \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persistente state leeft op het volume dat in Railway op /data wordt gemount.
RUN mkdir -p /data

CMD ["python", "worker.py"]
