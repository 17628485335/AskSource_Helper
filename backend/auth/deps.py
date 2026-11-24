"""FastAPI 依赖：从请求中解析当前登录用户（异步）"""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_db
from .models import User
from .security import decode_access_token

# tokenUrl 指向本模块的登录接口，供 OpenAPI / Swagger "Authorize" 使用
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """解析 Bearer 令牌并返回对应活跃用户，否则 401"""
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效或过期的凭证",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        raise credentials_exc

    user_id = payload.get("sub")
    if user_id is None:
        raise credentials_exc

    user = await db.get(User, int(user_id))
    if user is None or not user.is_active:
        raise credentials_exc
    return user


async def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """在登录基础上要求管理员，否则 403。

    模型密钥现在全库只有一份生效配置（任何一次保存都影响所有用户的对话），
    所以写接口必须收紧到管理员；依赖里直接读 user.is_admin，不按请求查库。
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以配置模型密钥",
        )
    return current_user
