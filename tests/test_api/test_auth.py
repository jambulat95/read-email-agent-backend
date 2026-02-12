"""Tests for authentication API endpoints."""
import pytest
from httpx import AsyncClient

from app.models.user import User


class TestRegister:
    """Tests for POST /api/auth/register."""

    async def test_register_success(self, client: AsyncClient):
        response = await client.post(
            "/api/auth/register",
            json={
                "email": "new@example.com",
                "password": "NewPass123",
                "full_name": "New User",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "new@example.com"
        assert data["full_name"] == "New User"
        assert data["plan"] == "free"
        assert "id" in data

    async def test_register_duplicate_email(self, client: AsyncClient, user: User):
        response = await client.post(
            "/api/auth/register",
            json={
                "email": user.email,
                "password": "AnotherPass123",
                "full_name": "Another User",
            },
        )
        assert response.status_code == 400
        assert "already registered" in response.json()["detail"]

    async def test_register_weak_password(self, client: AsyncClient):
        response = await client.post(
            "/api/auth/register",
            json={
                "email": "weak@example.com",
                "password": "weak",
                "full_name": "Weak User",
            },
        )
        assert response.status_code == 422

    async def test_register_no_uppercase(self, client: AsyncClient):
        response = await client.post(
            "/api/auth/register",
            json={
                "email": "no_upper@example.com",
                "password": "nouppercase1",
                "full_name": "No Upper",
            },
        )
        assert response.status_code == 422

    async def test_register_invalid_email(self, client: AsyncClient):
        response = await client.post(
            "/api/auth/register",
            json={
                "email": "not-an-email",
                "password": "ValidPass123",
                "full_name": "Bad Email",
            },
        )
        assert response.status_code == 422


class TestLogin:
    """Tests for POST /api/auth/login."""

    async def test_login_success(self, client: AsyncClient, user: User):
        response = await client.post(
            "/api/auth/login",
            data={
                "username": user.email,
                "password": "TestPass123",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    async def test_login_wrong_password(self, client: AsyncClient, user: User):
        response = await client.post(
            "/api/auth/login",
            data={
                "username": user.email,
                "password": "WrongPass123",
            },
        )
        assert response.status_code == 401

    async def test_login_nonexistent_user(self, client: AsyncClient):
        response = await client.post(
            "/api/auth/login",
            data={
                "username": "nobody@example.com",
                "password": "SomePass123",
            },
        )
        assert response.status_code == 401


class TestRefreshToken:
    """Tests for POST /api/auth/refresh."""

    async def test_refresh_success(self, client: AsyncClient, user: User):
        # First login to get tokens
        login_response = await client.post(
            "/api/auth/login",
            data={"username": user.email, "password": "TestPass123"},
        )
        refresh_token = login_response.json()["refresh_token"]

        response = await client.post(
            "/api/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data

    async def test_refresh_invalid_token(self, client: AsyncClient):
        response = await client.post(
            "/api/auth/refresh",
            json={"refresh_token": "invalid.token.here"},
        )
        assert response.status_code == 401


class TestGetCurrentUser:
    """Tests for GET /api/auth/me."""

    async def test_get_me_success(
        self, client: AsyncClient, user: User, auth_headers: dict
    ):
        response = await client.get("/api/auth/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == user.email
        assert data["full_name"] == user.full_name

    async def test_get_me_no_token(self, client: AsyncClient):
        response = await client.get("/api/auth/me")
        assert response.status_code == 401

    async def test_get_me_invalid_token(self, client: AsyncClient):
        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer invalid.token"},
        )
        assert response.status_code == 401
