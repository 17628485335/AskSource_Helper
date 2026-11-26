"""应用入口测试：FastAPI 装配与健康检查（不依赖 MySQL）"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_endpoint():
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_auth_routes_registered():
    paths = set(app.openapi()["paths"].keys())
    assert "/auth/register" in paths
    assert "/auth/login" in paths
    assert "/auth/me" in paths


def test_me_requires_token():
    # 未带凭证应返回 401
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_profile_and_password_routes_registered_and_protected():
    paths = set(app.openapi()["paths"].keys())
    assert "/auth/password" in paths
    # 新增的两个写接口同样必须带 token
    assert client.patch("/auth/me", json={"nickname": "新昵称"}).status_code == 401
    assert (
        client.post(
            "/auth/password", json={"old_password": "old", "new_password": "123456"}
        ).status_code
        == 401
    )
