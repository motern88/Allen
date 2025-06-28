## 工具库

MAS中的工具统一使用MCP实现

```python
├──mas/tools
|   ├──mcp_local_server      # 本地部署的mcp server
|   |   └──XXX_server.py
|   ├──mcp_client.py         # MAS中全局唯一的 MCP 客户端，负责提供session连接和管理
|   ├──mcp_tool.py           # Executor的工具子类，也是tool step的具体执行器
|   ├──XXX_mcp_config.yaml   # MCP服务启动配置文件
|   ...
|   └──XXX_mcp_config.yaml
```

