"""Fixtures compartidas para pruebas de integración y e2e contra el stack levantado (compose o kind).

Variables:
  GRAPHQL_URL       (default http://127.0.0.1:8080/graphql)
  AWS_ENDPOINT_URL  (default http://127.0.0.1:4566 -> Floci)
  AEGIS_ENV         (default dev)
  ADMIN_TOKEN       (default local-admin-token)
"""

from __future__ import annotations

import os
import time

import boto3
import httpx
import pytest

GRAPHQL_URL = os.getenv("GRAPHQL_URL", "http://127.0.0.1:8080/graphql")
ENV = os.getenv("AEGIS_ENV", "dev")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "local-admin-token")
AWS_ENDPOINT = os.getenv("AWS_ENDPOINT_URL", "http://127.0.0.1:4566")

os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")


class GraphQL:
    def __init__(self, url: str):
        self.http = httpx.Client(timeout=30)
        self.url = url

    def __call__(self, query: str, variables: dict | None = None, admin: bool = False) -> dict:
        headers = {"X-Admin-Token": ADMIN_TOKEN, "X-Actor": "pytest"} if admin else {}
        response = self.http.post(
            self.url, json={"query": query, "variables": variables or {}}, headers=headers
        )
        response.raise_for_status()
        body = response.json()
        if body.get("errors"):
            raise AssertionError(f"GraphQL errors: {body['errors']}")
        return body["data"]


@pytest.fixture(scope="session")
def gql() -> GraphQL:
    client = GraphQL(GRAPHQL_URL)
    deadline = time.time() + 60
    while True:
        try:
            client("{ environment { name } }")
            return client
        except Exception:  # noqa: BLE001
            if time.time() > deadline:
                raise
            time.sleep(2)


@pytest.fixture(scope="session")
def dynamo():
    return boto3.client("dynamodb", region_name="us-east-1", endpoint_url=AWS_ENDPOINT)


@pytest.fixture(scope="session")
def logs():
    return boto3.client("logs", region_name="us-east-1", endpoint_url=AWS_ENDPOINT)


@pytest.fixture(scope="session")
def env() -> str:
    return ENV


def table(logical: str) -> str:
    return f"aegisvolt-{logical}-{ENV}"
