"""内置工具包：一个工具一个文件，导入这个包即完成注册

约定：工具文件按功能命名（web_search.py / read_url.py），不带 _tool 后缀；
注册表本身在 app/graph/tools.py —— 那是「图怎么绑工具」的基础设施，不是工具。

新增工具记得在下面补一行 import。漏掉的症状是「工具默默消失了」，
因为注册表空着也不会报错，模型只是少一个能力。
"""

from . import current_datetime  # noqa: F401  导入即执行 @register_tool
from . import read_url  # noqa: F401  导入即执行 @register_tool
from . import web_search  # noqa: F401 导入即执行 @register_tool

__all__ = ["current_datetime", "read_url", "web_search"]
