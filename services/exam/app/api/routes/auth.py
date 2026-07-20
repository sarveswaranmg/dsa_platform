from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    TOTPVerifyRequest,
)
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

DB = Annotated[AsyncSession, Depends(get_db)]


@router.post("/register", response_model=RegisterResponse, status_code=201)
async def register(body: RegisterRequest, session: DB) -> RegisterResponse:
    return await auth_service.register(
        session, org_name=body.org_name, email=body.email, password=body.password
    )


@router.post("/totp/verify", status_code=204)
async def verify_totp_enrollment(body: TOTPVerifyRequest, session: DB) -> None:
    await auth_service.verify_totp_enrollment(
        session, email=body.email, password=body.password, code=body.code
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, session: DB) -> TokenResponse:
    return await auth_service.login(
        session, email=body.email, password=body.password, totp_code=body.totp_code
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, session: DB) -> TokenResponse:
    return await auth_service.refresh(session, refresh_token=body.refresh_token)


@router.post("/logout", status_code=204)
async def logout(body: LogoutRequest, session: DB) -> None:
    await auth_service.logout(session, refresh_token=body.refresh_token)
