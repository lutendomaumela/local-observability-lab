FROM python:3.12.11-slim-bookworm

WORKDIR /receiver
COPY receiver.py .

EXPOSE 8080
CMD ["python", "-u", "receiver.py"]
