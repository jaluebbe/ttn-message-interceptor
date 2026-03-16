FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt

COPY message_processor.py /app/message_processor.py
COPY message_database.py /app/message_database.py
COPY device_database.py /app/device_database.py
COPY message_handler.py /app/message_handler.py
COPY reprocess_messages.py /app/reprocess_messages.py
COPY ttn_storage_fetcher.py /app/ttn_storage_fetcher.py
COPY request_ttn_devices.py /app/request_ttn_devices.py

CMD ["python", "message_handler.py"]
