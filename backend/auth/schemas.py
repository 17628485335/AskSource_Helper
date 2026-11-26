"""Pydantic 数据模型（请求 / 响应）"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


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
    nickname: str = ""
    avatar: str = ""
    is_active: bool
    is_admin: bool = False
    created_at: datetime


class UpdateProfileRequest(BaseModel):
    """修改资料：只提交要改的字段，未提交字段保持不变"""

    nickname: str | None = Field(default=None, max_length=64, description="昵称")
    avatar: str | None = Field(default=None, description="头像 data URL，空串表示清除")

    @field_validator("nickname")
    @classmethod
    def nickname_not_blank(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("昵称不能为空")
        return v

    @field_validator("avatar")
    @classmethod
    def avatar_shape(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return v
        # 头像以 data URL 存库：前端先把图片压到小尺寸再提交，这里卡住明显异常的输入
        if len(v) > 2 * 1024 * 1024:
            raise ValueError("头像过大")
        prefix, sep, _ = v.partition(";base64,")
        if not sep or not prefix.startswith("data:image/"):
            raise ValueError("头像必须是图片的 data URL")
        if prefix[len("data:image/") :] not in {"png", "jpeg", "jpg", "gif", "webp"}:
            raise ValueError("头像仅支持 png / jpg / gif / webp 格式")
        return v


class ChangePasswordRequest(BaseModel):
    """修改密码：旧密码用于校验身份，新密码走与注册一致的强度限制"""

    old_password: str = Field(description="当前密码")
    new_password: str = Field(min_length=6, max_length=128, description="新密码")


class Token(BaseModel):
    """登录/刷新成功后返回的访问令牌"""

    access_token: str
    token_type: str = "bearer"
    expires_in: int | None = None  # access token 剩余秒数，供前端预刷新，旧客户端可忽略
