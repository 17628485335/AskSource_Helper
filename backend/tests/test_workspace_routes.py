"""工作区接口装配测试：路由注册与鉴权门槛（不依赖 MySQL）"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_workspace_routes_registered():
    paths = set(app.openapi()["paths"].keys())
    assert "/workspaces" in paths
    assert "/workspaces/{workspace_id}" in paths


def test_workspaces_require_token():
    # 未带凭证应返回 401，而不是走到数据库
    resp = client.get("/workspaces")
    assert resp.status_code == 401
