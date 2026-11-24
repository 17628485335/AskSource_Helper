"""Pydantic 数据模型（请求 / 响应）"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    """注册请求"""

    username: str = Field(min_length=3, max_length=64, description="用户名")
    email: EmailStr = Field(description="邮箱")
    password: str = Field(min_length=6, max_length=128, description="密码")


class UserLogin(BaseModel):
    """登录请求：account 可填用户名或邮箱"""

    account: str = Field(description="用户名或邮箱")
    password: str = Field(description="密码")


class UserOut(BaseModel):
    """用户信息响应"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    is_active: bool
    created_at: datetime


class Token(BaseModel):
    """登录成功后返回的访问令牌"""

    access_token: str
    token_type: str = "bearer"
