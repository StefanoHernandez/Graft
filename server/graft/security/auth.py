"""Authentication: JWT bearer login, and an owner-only guard for the admin API.

There is deliberately no registration router. Accounts are created by the
operator with `python -m graft.cli create-admin`, so a reachable Graft instance
cannot be handed an account by whoever finds it.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, status
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users.authentication import AuthenticationBackend, BearerTransport, JWTStrategy
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..models import User

TOKEN_LIFETIME_SECONDS = 3600

bearer_transport = BearerTransport(tokenUrl="auth/jwt/login")


def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(
        secret=get_settings().jwt_secret, lifetime_seconds=TOKEN_LIFETIME_SECONDS
    )


auth_backend = AuthenticationBackend(
    name="jwt", transport=bearer_transport, get_strategy=get_jwt_strategy
)


async def get_user_db(
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> AsyncIterator[SQLAlchemyUserDatabase]:
    yield SQLAlchemyUserDatabase(session, User)


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    @property
    def reset_password_token_secret(self) -> str:
        return get_settings().jwt_secret

    @property
    def verification_token_secret(self) -> str:
        return get_settings().jwt_secret


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase = Depends(get_user_db),  # noqa: B008
) -> AsyncIterator[UserManager]:
    yield UserManager(user_db)


fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

# active=True already rejects a deactivated account with 401.
current_active_user = fastapi_users.current_user(active=True)


async def current_owner(user: User = Depends(current_active_user)) -> User:  # noqa: B008
    """Every admin route needs an active owner in this release.

    Editor and viewer exist in the schema but are refused here until the RBAC
    milestone actually enforces a matrix; granting them access early would mean
    shipping an unenforced permission.
    """
    if user.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail={"code": "owner_required"}
        )
    return user
