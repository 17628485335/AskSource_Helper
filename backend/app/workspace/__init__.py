"""工作区模块：workspaces 表 + /workspaces 接口

工作区是会话的分组容器（类似 ChatGPT 的 Project）：
- 每个用户可建多个工作区，chat_sessions 通过 workspace_id 归属；
- 删除工作区不删会话，只把会话的 workspace_id 置回 NULL（未归属）。
"""
