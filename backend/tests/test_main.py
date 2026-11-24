"""入口模块的单元测试"""

from app.main import main


def test_main_runs(capsys):
    main()
    captured = capsys.readouterr()
    assert "Backend 服务已启动" in captured.out
