# Contexto de build: services/   (docker build -f graphql-gateway/Dockerfile services)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv
COPY common /srv/common
COPY graphql-gateway/requirements.txt /srv/requirements.txt
RUN pip install /srv/common -r /srv/requirements.txt

COPY graphql-gateway/app /srv/app

RUN useradd --uid 10001 --create-home aegis
USER 10001

ARG APP_VERSION=local
ENV APP_VERSION=${APP_VERSION}
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--ws", "websockets"]
