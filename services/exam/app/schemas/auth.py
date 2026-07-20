import uuid

from pydantic import BaseModel, EmailStr, Field

from app.models.examiner import Role


class RegisterRequest(BaseModel):
    org_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class RegisterResponse(BaseModel):
    examiner_id: uuid.UUID
    org_id: uuid.UUID
    email: EmailStr
    role: Role
    totp_secret: str
    totp_provisioning_uri: str


class TOTPVerifyRequest(BaseModel):
    email: EmailStr
    password: str
    code: str = Field(min_length=6, max_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    totp_code: str = Field(min_length=6, max_length=8)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str
