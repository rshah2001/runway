FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# never run the API as root inside the container
RUN useradd --create-home runway
USER runway

EXPOSE 8000
# ROOT_PATH=/api when served behind Caddy, so /api/docs and the OpenAPI schema resolve correctly
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --root-path \"${ROOT_PATH:-}\""]
