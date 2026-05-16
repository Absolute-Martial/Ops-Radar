"""Tests for first-user bootstrap behavior.

A fresh self-hosted OpsRadar instance needs a safe way to create the
first operator account without manual SQL. The registration endpoint
therefore promotes only the first registered user to the global admin
role; every later self-registered account stays at analyst level.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete

from app.models import User, UserRole


@pytest.mark.asyncio
async def test_first_registered_user_becomes_instance_admin(client, db_session):
    """The first registration on an empty database is the bootstrap admin."""

    await db_session.execute(delete(User))
    await db_session.commit()

    email = f"bootstrap-{uuid.uuid4().hex[:8]}@example.com"
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "Str0ng!Bootstrap2026",
            "full_name": "Bootstrap Operator",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == email
    assert body["role"] == UserRole.admin.value


@pytest.mark.asyncio
async def test_later_registered_users_start_as_analysts(client, db_session):
    """Only the first registration is promoted; later accounts are analysts."""

    await db_session.execute(delete(User))
    await db_session.commit()

    first_email = f"first-{uuid.uuid4().hex[:8]}@example.com"
    second_email = f"second-{uuid.uuid4().hex[:8]}@example.com"

    first = await client.post(
        "/api/v1/auth/register",
        json={
            "email": first_email,
            "password": "Str0ng!First2026",
            "full_name": "First Operator",
        },
    )
    assert first.status_code == 201, first.text
    assert first.json()["role"] == UserRole.admin.value

    second = await client.post(
        "/api/v1/auth/register",
        json={
            "email": second_email,
            "password": "Str0ng!Second2026",
            "full_name": "Second User",
        },
    )
    assert second.status_code == 201, second.text
    assert second.json()["role"] == UserRole.analyst.value
