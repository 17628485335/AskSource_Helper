"""认证路由：注册 / 登录 / 当前用户（异步）

bcrypt 为 CPU 密集操作，通过 run_in_threadpool 卸载到线程池，避免阻塞事件循环。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import models, schemas
from .database import get_db
from .deps import get_current_user
from .security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=schemas.UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="注册新用户",
)
async def register(payload: schemas.UserCreate, db: AsyncSession = Depends(get_db)):
    """用户名或邮箱唯一，重复返回 409"""
    exists = await db.scalar(
        select(models.User).where(
            (models.User.username == payload.username)
            | (models.User.email == payload.email)
        )
    )
    if exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名或邮箱已被注册",
        )

    hashed = await run_in_threadpool(hash_password, payload.password)
    user = models.User(
        username=payload.username,
        email=payload.email,
        hashed_password=hashed,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=schemas.Token, summary="登录获取令牌")
async def login(payload: schemas.UserLogin, db: AsyncSession = Depends(get_db)):
    """account 支持用户名或邮箱；成功返回 JWT access_token"""
    user = await db.scalar(
        select(models.User).where(
            (models.User.username == payload.account)
            | (models.User.email == payload.account)
        )
    )
    password_ok = (
        user is not None
        and await run_in_threadpool(verify_password, payload.password, user.hashed_password)
    )
    if not user or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="账号或密码错误",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用",
        )
    return schemas.Token(access_token=create_access_token(user.id))


@router.get("/me", response_model=schemas.UserOut, summary="获取当前登录用户")
async def me(current_user: models.User = Depends(get_current_user)):
    return current_user
