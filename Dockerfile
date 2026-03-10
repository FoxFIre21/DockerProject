FROM python:3.11-slim

WORKDIR /app

COPY server.py .
COPY static ./static

EXPOSE 9510

CMD ["python", "server.py"]
