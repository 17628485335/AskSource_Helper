"""当前日期时间工具：让模型在需要“现在几点/今天哪天”时自行取值。

不依赖外部服务；默认按项目统一使用的 Asia/Shanghai 返回，同时给 UTC 和 Unix 时间戳。
"""

from datetime import datetime, timezone as dt_timezone
from typing import Any, ClassVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from app.graph.tools import ToolCategory, register_tool

_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


class CurrentDatetimeArgs(BaseModel):
    timezone: str = Field(
        default="Asia/Shanghai",
        description="IANA 时区名，例如 Asia/Shanghai、UTC、America/New_York；默认 Asia/Shanghai",
    )


@register_tool(
    category=ToolCategory.CORE,
    icon="clock",
    label="当前时间",
    example='current_datetime(timezone="Asia/Shanghai")',
)
class CurrentDatetimeTool(BaseTool):
    name: str = "current_datetime"
    description: str = (
        "获取当前的日期、时间和星期。需要判断“今天/现在”、做时间计算或确认时区时调用；"
        "不传参数时按北京时间（Asia/Shanghai）返回，同时给出 UTC 和 Unix 时间戳。"
    )
    args_schema: ClassVar[Any] = CurrentDatetimeArgs

    @classmethod
    def available(cls) -> bool:
        return True

    def _format(self, timezone_name: str) -> str:
        try:
            tz = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(
                f"未知时区 {timezone_name!r}，请传 IANA 时区名，例如 Asia/Shanghai 或 UTC"
            ) from exc

        now = datetime.now(tz)
        utc_now = now.astimezone(dt_timezone.utc)
        weekday = _WEEKDAYS[now.weekday()]
        label = "北京时间" if timezone_name == "Asia/Shanghai" else timezone_name
        return (
            f"当前时间（{label}）：{now:%Y-%m-%d %H:%M:%S} {weekday}\n"
            f"ISO 8601：{now.isoformat(timespec='seconds')}\n"
            f"UTC：{utc_now:%Y-%m-%d %H:%M:%S}\n"
            f"Unix 时间戳（秒）：{int(now.timestamp())}"
        )

    def _run(self, timezone: str = "Asia/Shanghai") -> str:
        return self._format(timezone)

    async def _arun(self, timezone: str = "Asia/Shanghai") -> str:
        return self._format(timezone)
