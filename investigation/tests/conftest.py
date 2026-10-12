from __future__ import annotations

import os

import psycopg
import pytest

from traceforge_investigation.config import Settings
from traceforge_investigation.repository import IncidentRepository


@pytest.fixture(scope="session")
def incident_repository() -> IncidentRepository:
    host = os.environ.get("TEST_DATABASE_HOST")
    database_name = os.environ.get("TEST_DATABASE_NAME")
    database_user = os.environ.get("TEST_DATABASE_USER")
    database_password = os.environ.get("TEST_DATABASE_PASSWORD", "")
    if not host or not database_name or not database_user or not database_password:
        pytest.fail("isolated test database settings are required; run the PostgreSQL Compose test profile")
    # Guard before any migration or cleanup. Integration tests must never target the persistent demo database.
    if (
        host != "incident-test-postgres"
        or database_name != "traceforge_incident_test"
        or database_user != "traceforge_test"
    ):
        pytest.fail("test database settings do not identify the disposable incident database")
    settings = Settings(
        database_host=host,
        database_port=int(os.environ.get("TEST_DATABASE_PORT", "5432")),
        database_name=database_name,
        database_user=database_user,
        database_password=database_password,
    )
    repository = IncidentRepository(settings)
    repository.migrate()
    return repository


@pytest.fixture(autouse=True)
def clear_disposable_incident_test_rows(incident_repository: IncidentRepository) -> None:
    # This fixture is only reachable after the strict disposable-database guard above.
    with psycopg.connect(incident_repository._dsn) as connection:
        with connection.transaction():
            connection.execute("DELETE FROM incident_service.detection_source_state")
            connection.execute("DELETE FROM incident_service.detection_cycles")
            connection.execute("DELETE FROM incident_service.incidents")
            connection.execute("DELETE FROM incident_service.health_rule_state")
