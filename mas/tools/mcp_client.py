'''
这里实现MCP客户端的功能，用于向Executor提供MCP Client的相关功能:

- 实现通过MCP Client获取可用工具列表中的全部工具描述，并组装成提示词
    1 根据传入的工具名称的列表，获取全部对应MCP工具的server config
    2 根据server config通过mcp client获取工具的详细描述
    3 将返回结果组装成提示词

- 实现通过MCP Client获取单个工具的详细描述与调用格式，并组装成提示词
    1 根据传入的工具名称，获取对应MCP工具的server config
    2 根据server config通过mcp client获取工具的详细说明和调用格式
    3 将返回结果组装成提示词

- 实现通过MCP Client传入指定工具及参数，调用MCP工具并返回调用结果
    1 根据传入的工具名称，获取对应MCP工具的server config，并连接其服务器
    2 根据传入参数，调用MCP工具并获取返回结果

说明:
1. MCP Client 连接多个 MCP Server，每个 MCP Server 可以有多个 MCP Tool。
MCP Client
    ├── connects to ──> MCP Server 1
    │                      ├── MCP Tool A
    │                      └── MCP Tool B
    └── connects to ──> MCP Server 2
                           ├── MCP Tool C
                           └── MCP Tool D


2. MCP 连接管理
第一级：MCPClient.server_config
    存放了MAS中所有支持的MCP Server的启动配置
第二级：AgentState.tools
    存放了Agent可调用的外部工具（MCP服务）的权限。第二级可用MCP服务是第一级的子集。
第三级：MCPClient.server_sessions
    存放了活跃的MCP Server连接实例，key为MCP Server名称，value为requests.Session实例。
    server_sessions会动态连接第二级权限包含的MCP Server，并保证MAS中所有Agent的工具权限所涉及到的MCP Server都处于活跃连接状态。
第四级：MCPClient.tool_descriptions
    存放了MCP Server中可用工具的详细描述，key为工具名称，value为工具描述。
    tool_descriptions会从第三级中活跃session连接中调用工具名称，描述和使用方式并记录。
    在Agent获取全部工具和技能提示词时，tool_descriptions相应支持；在Agent执行具体工具Step/组装工具Step提示词时，tool_descriptions也会提供具体工具的描述和调用格式信息。

3. MCP Client实例应当是全局唯一的，MAS中所有Agent都共享同一个MCP Client实例。
    应当在MAS启动时创建MCPClient实例，并传入给Executor，使得Executor可以通过MCPClient实例获取MCP Server连接和工具描述? TODO
'''
import os
import yaml
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union
import requests

from contextlib import AsyncExitStack

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client

class MCPClient:
    def __init__(self):
        """
        初始化 MCP 客户端
        我们需要三套数据结构来管理 MCP 服务器和工具：
        1. `server_config`: 存储 MCP 服务器的启动配置
        2. `server_sessions`: 存储连接的 MCP 服务器实例
        3. `tool_descriptions`: 存储 MCP 工具的详细描述
        """
        self.exit_stack = AsyncExitStack()  # 管理异步上下文连接

        # 初始化一个服务器启动配置字典，用于存储连接的 MCP 服务器启动配置
        self.server_config = self._get_server_config()  # 储存一一对应的服务器名称和启动配置 Dict[str,Dict[str, Any]]
        # 初始化一个储存服务器连接字典，用于存储连接的 MCP 服务器实例
        self.server_sessions = {}  # 存储连接实例：server_name -> requests.Session()
        # 初始化一个储存工具描述的字典，用于存储 MCP 工具的详细描述
        self.tool_descriptions = {}


    # 获取全部MCP服务启动配置，并记录在self.server_config中
    def _get_server_config(self):
        """
        从当前目录中读取所有以 "mcp_config.yaml" 结尾的文件。
        将其中的 name 作为服务器名称，config 作为服务器启动配置，添加到 server_config。

        这里的server_config中保存的启动配置类似：
        {"mcpServers": {
            "playwright": {
              "command": "npx",
              "args": ["@playwright/mcp@latest"]
            }
        }}
        """
        server_config = {}
        current_dir = os.path.dirname(os.path.abspath(__file__))
        for filename in os.listdir(current_dir):
            if filename.endswith("mcp_config.yaml"):
                file_path = os.path.join(current_dir, filename)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        config_data = yaml.safe_load(f)

                    name = config_data.get("name")
                    config = config_data.get("config")

                    if name and isinstance(config, dict):
                        server_config[name] = config
                    else:
                        print(f"[MCPClient] 配置文件 {filename} 缺少 'name' 或 'config' 字段，或格式不正确。")
                except Exception as e:
                    print(f"[MCPClient] 无法加载配置文件 {filename}: {e}")
        return server_config

    # 连接指定MCP服务器，并记录到 server_sessions 中
    async def connect_to_server(self, server_list: List[str]):
        """
        根据 server_list 中的服务器名称，通过其在 server_config 中的配置连接到对应的 MCP 服务器。
        连接到指定 MCP 服务器，并将连接的服务器实例记录到 server_sessions 中。

        尝试连接时兼容本地/远程两种方式：
        - 如果配置中有 "command" 字段，则认为是本地执行的 MCP 服务器，使用 stdio_client 连接。
        - 如果配置中有 "baseurl" 字段，则认为是远程的 MCP 服务器，使用 sse_client 连接。
        """
        for server_name in server_list:
            config = self.server_config.get(server_name)
            if not config:
                print(f"[MCPClient] 未找到服务器 '{server_name}' 的启动配置，跳过。")
                continue

            mcp_servers = config.get("mcpServer", {})
            for instance_name, value in mcp_servers.items():
                session = None

                try:
                    # 如果为command字段则说明是本地执行的MCP服务器
                    if "command" in value:
                        command = value["command"]
                        args = value["args"]
                        env = value.get("env", None)

                        # print(f"[MCPClient] 正在连接本地 MCP 服务器 '{server_name}'，命令：{command} {args}")
                        server_params = StdioServerParameters(
                            command=command,
                            args=args,
                            env=env  # 可以根据需要传入环境变量
                        )
                        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
                        stdio, write = stdio_transport
                        session = await self.exit_stack.enter_async_context(ClientSession(stdio, write))

                    # 如果为baseurl字段则说明是远程的MCP服务器，使用SSE连接
                    elif "baseurl" in value:
                        server_url = value["baseurl"]

                        # print(f"[MCPClient] 正在连接远程 MCP 服务器 '{server_name}'")
                        sse_transport = await self.exit_stack.enter_async_context(sse_client(server_url))
                        write,read = sse_transport
                        session = await self.exit_stack.enter_async_context(ClientSession(read, write))

                    # 如果成功连接到服务器，则记录到 server_sessions 中
                    if session:
                        await session.initialize()  # 初始化会话
                        self.server_sessions[server_name] = session
                        print(f"[MCPClient] 成功连接到 MCP 服务器 '{server_name}' 实例 '{instance_name}'")

                except Exception as e:
                    print(f"[MCPClient] 连接 MCP 服务器 '{server_name}'（实例：{instance_name}）失败: {e}")

    # 获取指定工具的详细描述
    async def get_tool_description(self, server_name: str):
        """
        尝试从tool_descriptions中获取对应工具名称的详细描述。

        - 优先从本地缓存 tool_descriptions 获取。
        - 否则通过已连接的MCP Server获取。
            如果tool_descriptions中没有该工具的描述，则从server_sessions对应活跃的MCP Server连接中调用工具描述信息。
        - 如果没有连接过服务器，则尝试自动连接再请求描述。
            如果server_sessions中没有对应的MCP Server连接，则从server_config中获取对应的MCP Server配置并连接。

        TODO:在ExecutorBase中调用get_tool_description后组装提示词未实现
        """
        # 1. tool_descriptions 缓存优先
        if server_name in self.tool_descriptions:
            return self.tool_descriptions[server_name]

        # 2. 从 server_sessions 中遍历已连接的 MCP Server
        for server_name, session in self.server_sessions.items():
            try:
                result = await session.list_tools()  # 异步调用服务器获取工具列表
                if hasattr(result, "tools") and result.tools:
                    # print("[DEBUG][MCPClient]\n📋 Available tools:")
                    for i, tool in enumerate(result.tools, 1):
                        if tool.description:
                            # 将工具描述存入 tool_descriptions 缓存
                            self.tool_descriptions[server_name][tool.name] = {
                                "description": tool.description,
                                "usage": tool.usage  # TODO: MCP tool_list会返回使用方式字段吗？怎么获取
                            }
                    return self.tool_descriptions[server_name]
                else:
                    print(f"[MCPClient] MCP Server {server_name} 没有可用工具。")
                    return {}

            except Exception as e:
                print(f"[MCPClient] 获取工具描述失败（MCP服务 {server_name}）: {e}")
                return {}

        # 3. 如果没有连接过服务器，则尝试自动连接
        if server_name not in self.server_sessions:
            # 尝试连接到指定的 MCP Server
            await self.connect_to_server([server_name])

            # 再次尝试获取工具描述
            if server_name in self.server_sessions:
                return await self.get_tool_description(server_name)

    # TODO：传入参数调用工具























if __name__ == "__main__":




