from app.services.connectors.database_connector import _build_connection_url


def test_build_connection_url_accepts_user_key():
    url = _build_connection_url(
        {
            "dialect": "postgresql",
            "host": "db",
            "port": 5432,
            "database": "opsradar",
            "user": "connector_user",
            "password": "secret",
        }
    )

    assert url == "postgresql://connector_user:secret@db:5432/opsradar"


def test_build_connection_url_accepts_legacy_username_key():
    url = _build_connection_url(
        {
            "dialect": "postgresql",
            "host": "db",
            "port": 5432,
            "database": "opsradar",
            "username": "connector_user",
            "password": "secret",
        }
    )

    assert url == "postgresql://connector_user:secret@db:5432/opsradar"
