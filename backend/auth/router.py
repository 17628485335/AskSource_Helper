"""认证路由：注册 / 登录 / 刷新 / 登出 / 当前用户（异步）

bcrypt 为 CPU 密集操作，通过 run_in_threadpool 卸载到线程池，避免阻塞事件循环。
登录/刷新会下发 HttpOnly 的 refresh_token Cookie（路径 /auth），支持服务端吊销。
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from . import models, schemas
from .config import get_settings
from .database import get_db
from .deps import get_current_user
from .security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/auth"


def _cookie_secure(request: Request) -> bool:
    """根据请求协议判断 Cookie 的 Secure 标志；开发 http 下必须为 False 否则不下发"""
    forwarded = request.headers.get("x-forwarded-proto", "")
    proto = forwarded.split(",")[0].strip() or request.url.scheme
    return proto == "https"


async def _issue_tokens(
    db: AsyncSession, response: Response, user: models.User, request: Request
) -> schemas.Token:
    """签发 access + refresh：refresh 哈希入库并以 HttpOnly Cookie 下发，返回 access"""
    settings = get_settings()
    refresh_days = settings.refresh_token_expire_days
    refresh_raw = generate_refresh_token()
    db.add(
        models.RefreshToken(
            token_hash=hash_token(refresh_raw),
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=refresh_days),
        )
    )
    await db.commit()

    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_raw,
        max_age=refresh_days * 24 * 3600,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request),
    )
    return schemas.Token(
        access_token=create_access_token(user.id),
        expires_in=settings.access_token_expire_minutes * 60,
    )


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
    # 首个注册用户自动成为管理员：/chat 只读管理员维护的全局模型配置，
    # 全新部署（users 表为空）若没人能进「设置 - 模型」，服务就彻底不可用。
    # 已有任何用户时一律普通用户，提管理员靠改库（is_admin=1）。
    is_first = (
        await db.scalar(select(func.count()).select_from(models.User))
    ) == 0
    user = models.User(
        username=payload.username,
        email=payload.email,
        hashed_password=hashed,
        is_admin=is_first,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=schemas.Token, summary="登录获取令牌")
async def login(
    payload: schemas.UserLogin,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """account 支持用户名或邮箱；成功返回 JWT access_token，并下发 refresh Cookie"""
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
    return await _issue_tokens(db, response, user, request)


@router.post("/refresh", response_model=schemas.Token, summary="刷新令牌续期")
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """用 HttpOnly Cookie 中的 refresh 换新 access，并轮换（吊销旧 refresh）"""
    raw = request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少刷新令牌"
        )
    record = await db.scalar(
        select(models.RefreshToken).where(
            models.RefreshToken.token_hash == hash_token(raw)
        )
    )
    now = datetime.now(timezone.utc)
    if (
        record is None
        or record.revoked
        or record.expires_at.replace(tzinfo=timezone.utc) < now
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="刷新令牌无效或已过期"
        )
    user = await db.get(models.User, record.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已被禁用"
        )
    # 轮换：旧记录作废后签发新令牌
    record.revoked = True
    await db.commit()
    return await _issue_tokens(db, response, user, request)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="登出吊销刷新令牌")
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """吊销当前 refresh 记录并清除 Cookie；幂等，无有效令牌也返回成功"""
    raw = request.cookies.get(REFRESH_COOKIE_NAME)
    if raw:
        record = await db.scalar(
            select(models.RefreshToken).where(
                models.RefreshToken.token_hash == hash_token(raw)
            )
        )
        if record is not None and not record.revoked:
            record.revoked = True
            await db.commit()
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)
    return None


@router.get("/me", response_model=schemas.UserOut, summary="获取当前登录用户")
async def me(current_user: models.User = Depends(get_current_user)):
    return current_user


@router.patch("/me", response_model=schemas.UserOut, summary="修改昵称或头像")
async def update_me(
    payload: schemas.UpdateProfileRequest,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """只改提交了的字段；头像存前端压缩后的 data URL，空串表示清除"""
    if payload.nickname is not None:
        current_user.nickname = payload.nickname
    if payload.avatar is not None:
        current_user.avatar = payload.avatar
    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.post("/password", summary="修改密码")
async def change_password(
    payload: schemas.ChangePasswordRequest,
    response: Response,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """校验旧密码后更新哈希，并吊销该用户所有 refresh，迫使其重新登录"""
    ok = await run_in_threadpool(
        verify_password, payload.old_password, current_user.hashed_password
    )
    if not ok:
        # 用 400 而非 401：401 会让前端以为 token 过期、自动刷新重试
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="当前密码不正确"
        )
    current_user.hashed_password = await run_in_threadpool(
        hash_password, payload.new_password
    )
    await db.execute(
        update(models.RefreshToken)
        .where(models.RefreshToken.user_id == current_user.id)
        .values(revoked=True)
    )
    await db.commit()
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)
    return {"message": "密码已修改，请重新登录"}
