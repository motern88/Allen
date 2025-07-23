## Tools

### 1. 总览

MAS中的工具统一使用MCP实现

```python
mas/tools
├──mcp_local_server      		# 本地部署的mcp server文件夹
|   └──XXX_server.py
└──mcp_server_config			# MCP服务启动配置文件夹
    └──XXX_mcp_config.json
mcp_client.py         			# MAS中全局唯一的 MCP Client，负责提供session连接和管理
mcp_tool.py           			# Executor的工具子类，也是tool step的具体执行器
mcp_base_prompt.yaml  			# MCP使用的基础提示词
```

