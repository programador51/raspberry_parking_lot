FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY static ./static

ENV SERIAL_PORT=/dev/ttyACM0
ENV SERIAL_BAUD=115200
ENV HTTP_PORT=8080

EXPOSE 8080

CMD ["python", "-u", "app.py"]
