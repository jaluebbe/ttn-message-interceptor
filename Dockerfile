FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt

RUN touch /app/lorawan_gateway_messages.db
RUN touch /app/ttn_device_sessions.db

COPY message_processor.py /app/message_processor.py
COPY message_database.py /app/message_database.py
COPY device_database.py /app/device_database.py
COPY message_handler.py /app/message_handler.py

RUN useradd --create-home appuser
USER appuser

CMD ["python", "message_handler.py"]
