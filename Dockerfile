FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt

COPY message_collector.py /app/message_collector.py
COPY message_database.py /app/message_database.py
COPY semtech_udp.py /app/semtech_udp.py

RUN useradd --create-home appuser
USER appuser

CMD ["python", "message_collector.py"]
