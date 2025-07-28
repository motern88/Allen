'''
这里实现MCP客户端的功能，用于向Executor提供MCP Client的相关功能:
    1. `connect_to_server`: 连接指定的 MCP 服务器
    2. `get_server_description`: 获取服务器支持的指定能力的详细描述，例如tools/resources/prompts
    3. `use_capability`: 执行指定能力并返回结果

说明:
1. MCP Client 连接多个 MCP Server，每个 MCP Server 可以有多个 MCP Tool。
    MCP Client
        ├ connects to ─> MCP Server 1
        │                ├── MCP Tool A
        │                └── MCP Tool B
        └ connects to ─> MCP Server 2
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

    第四级：MCPClient.server_descriptions
        存放了MCP Server中可用工具的详细描述，key为工具名称，value为工具描述。
        server_descriptions 会从第三级中活跃session连接中调用工具名称，描述和使用方式并记录。
        在Agent获取全部工具和技能提示词时，server_descriptions 提供相应支持；在Agent执行具体工具Step/组装工具Step提示词时，server_descriptions 也会提供具体工具的描述和调用格式信息。

3. MCP Client实例应当是全局唯一的，MAS中所有Agent都共享同一个MCP Client实例。
    在MAS启动时创建MCPClient实例，并传入给Executor.execute，使得Executor.execute可以通过MCPClient实例获取MCP Server连接和工具描述
'''
import os
import json
import yaml
import logging
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union
import requests
import asyncio

from contextlib import AsyncExitStack

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client

# 配置日志级别，忽略 MCP 通知验证的 WARNING 消息，但保留 ERROR 级别的消息
logging.getLogger().setLevel(logging.ERROR)

class MCPClient:
    def __init__(self):
        """
        初始化 MCP 客户端
        我们需要三套数据结构来管理 MCP 服务器和工具：
        1. `server_config`: 存储 MCP 服务器的启动配置
        2. `server_sessions`: 存储连接的 MCP 服务器实例。
            这里尽管每个session都已经注册到AsyncExitStack中了，但是我们仍然额外地显式管理一份会话在server_sessions中
            {
                "<SERVER_NAME>": <ClientSession>,  # 连接的 MCP 服务器会话实例
            }
        3. `server_descriptions`: 存储 MCP 服务的详细描述，包括工具描述
            {
                "<SERVER_NAME>": {
                    "capabilities":{
                        "prompts": bool,                                          # 是否支持提示词
                        "resources": bool,                                        # 是否支持资源
                        "tools": bool,                                            # 是否支持工具
                    },
                    "tools": {                                                    # 如果支持工具，则存储工具描述
                        "<TOOL_NAME>": {                                          # 工具名称
                            "description": "<TOOL_DESCRIPTION>",
                            "tittle": "<TOOL_TITLE>",                             # 工具标题
                            "input_schema": {
                                "type": "object",                                 # 工具输入参数类型
                                "properties": {
                                    "<PROPERTY_NAME>": {                          # 工具输入参数名称
                                        "type": "<PROPERTY_TYPE>",                # 工具输入参数类型
                                        "description": "<PROPERTY_DESCRIPTION>",  # 工具输入参数描述
                                    },
                                    ...                                           # 其他输入参数
                                }
                            },
                            "output_schema": <OUTPUT_SCHEMA>,                     # 工具输出参数的JSON Schema说明（可能类似input_schema），官方文档没有要求该字段，但是在一些实现中确实存在该字段
                            "required": ["<PROPERTY_NAME>", ...]                  # 工具输入参数是否必需
                        },
                        ...                                                       # 其他工具
                    },
                    "resources": {                                                # 如果支持资源，则存储资源描述
                        "<RESOURCE_NAME>": {                                      # 资源名称
                            "description": "<RESOURCE_DESCRIPTION>",              # 资源描述
                            "title": "<RESOURCE_TITLE>",                          # 资源标题
                            "uri": "<RESOURCE_URI>",                              # 资源URI
                            "mimeType": "<RESOURCE_MIME_TYPE>",                   # 资源MIME类型
                        },
                        ...                                                       # 其他资源
                    },
                    "prompts": {                                                  # 如果支持提示词，则存储提示词描述
                        "<PROMPT_NAME>": {                                        # 提示词名称
                            "description": "<PROMPT_DESCRIPTION>",                # 提示词描述
                            "title": "<PROMPT_TITLE>",                            # 提示词标题
                            "arguments": {                                        # 提示词参数
                                "<ARGUMENT_NAME>": {                              # 提示词参数名称
                                    "description": "<ARGUMENT_DESCRIPTION>",      # 提示词参数描述
                                    "required": bool,                             # 提示词参数是否必需
                                },
                                ...                                               # 提示词参数其他属性
                            }
                        },
                        ...                                                       # 其他提示词
                    },
                }
            }

        同时我们实现几个MCP基础方法：
        1. `connect_to_server`: 连接指定的 MCP 服务器
        2. `get_server_description`: 获取服务器支持的指定能力的详细描述，例如tools/resources/prompts
        3. `use_capability`: 执行指定能力并返回结果
        """
        self.exit_stack = AsyncExitStack()  # 管理异步上下文连接

        # 初始化一个服务器启动配置字典，用于存储连接的 MCP 服务器启动配置
        self.server_config = self._get_server_config()  # 储存一一对应的服务器名称和启动配置 Dict[str,Dict[str, Any]]
        # 初始化一个储存服务器连接字典，用于存储连接的 MCP 服务器实例
        self.server_sessions = {}  # 存储连接实例：server_name -> requests.Session()
        # 初始化一个储存服务描述的字典，用于存储 MCP 服务的详细描述（包括工具详细描述）
        self.server_descriptions = {}

    # 初始化的时候自动尝试连接所有的服务器以获取服务器能力描述
    async def initialize_servers(self):
        '''
        初始化时，连接所有配置的 MCP 服务器。
        在MAS初始化时通过MultiAgentSystem._init_mcp_client调用该方法
        '''
        # 收集所有连接任务
        connect_tasks = [
            self.connect_to_server([server_name])
            for server_name in self.server_config.keys()
        ]

        # 并行执行所有任务
        results = await asyncio.gather(*connect_tasks, return_exceptions=True)

    # 结束所有已连接的MCP服务器连接
    async def close_all_server(self):
        '''
        关闭所有已连接的 MCP 服务器连接。
        '''
        # 关闭所有通过这个 exit stack 注册的异步上下文管理器。在之前的连接过程中（可能在 connect_to_server 方法中
        await self.exit_stack.aclose()
        # 清空服务器会话和描述字典
        self.server_sessions.clear()
        self.server_descriptions.clear()


    # 获取全部MCP服务启动配置，并记录在self.server_config中
    def _get_server_config(self):
        """
        从 mas/tools/mcp_server_config 中读取所有以 "mcp_config.yaml" 结尾的文件。
        其中保存的启动配置类似（在yaml文件的config字段中）：
        {
            "mcpServers": {
                "playwright": {
                    "command": "npx",
                    "args": ["@playwright/mcp@latest"]
                }
            }
        }
        将其中playwright的部分为name，整体为config，存入 server_config Dict[<name>,<config>] 字典中。
        """
        server_config = {}

        base_dir = os.path.dirname(os.path.abspath(__file__))  # 当前文件（mcp_client.py）所在目录
        config_dir = os.path.join(base_dir, "mcp_server_config")

        for filename in os.listdir(config_dir):
            if filename.endswith("mcp_config.yaml"):
                file_path = os.path.join(config_dir, filename)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        yaml_data = yaml.safe_load(f)

                    # tool_name = yaml_data.get("use_guide", "").get("tool_name", "").strip()
                    config_str = yaml_data.get("config", "").strip()
                    if not config_str:
                        continue

                    config_json = json.loads(config_str)
                    mcp_servers = config_json.get("mcpServers", {})

                    for server_name in mcp_servers.keys():
                        server_config[server_name] = config_json

                except Exception as e:
                    print(f"[MCPClient] 无法加载配置文件 {file_path}: {e}")
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

            mcp_servers = config.get("mcpServers", {})
            for instance_name, value in mcp_servers.items():
                session = None

                try:
                    # print(f"[DEBUG][MCPClient] 正在连接 MCP 服务器 '{server_name}' 实例 '{instance_name}'，配置：{value}")
                    # 如果为command字段则说明是本地执行的MCP服务器
                    if "command" in value:
                        command = value["command"]
                        args = value["args"]
                        env = value.get("env", None)

                        # print(f"[MCPClient] 正在通过命令连接 MCP 服务器 '{server_name}'，命令：{command} {args}")
                        server_params = StdioServerParameters(
                            command=command,
                            args=args,
                            env=env  # 可以根据需要传入环境变量
                        )
                        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
                        stdio, write = stdio_transport
                        session = await self.exit_stack.enter_async_context(ClientSession(stdio, write))

                    # 如果为baseurl或url字段则说明是远程的MCP服务器，使用SSE连接
                    elif "baseurl" in value or "url" in value:
                    # 优先使用baseurl，如果没有则使用url
                        server_url = value.get("baseurl") or value.get("url")

                        # print(f"[MCPClient] 正在通过url连接远程 MCP 服务器 '{server_name}'")
                        sse_transport = await self.exit_stack.enter_async_context(sse_client(server_url))
                        read, write = sse_transport
                        session = await self.exit_stack.enter_async_context(ClientSession(read, write))

                    # 如果成功连接到服务器，则记录到 server_sessions 中
                    if session:
                        initialize_result = await session.initialize()  # 初始化会话
                        # print(f"[MCPClient] 初始化会话后服务器返回结果:{initialize_result}")
                        # 将服务器返回的初始化信息记录到 server_descriptions 中
                        self.server_descriptions[server_name] = {
                            "capabilities": {
                                "prompts": False if initialize_result.capabilities.prompts is None else True,
                                "resources": False if initialize_result.capabilities.resources is None else True,
                                "tools": False if initialize_result.capabilities.tools is None else True,
                            }
                        }

                        self.server_sessions[server_name] = session
                        print(f"[MCPClient] 成功连接到 MCP 服务器 '{server_name}' 实例 '{instance_name}'")

                except Exception as e:
                    print(f"[MCPClient] 连接 MCP 服务器 '{server_name}'（实例：{instance_name}）失败: {e}")

    # 获取指定工具的详细描述
    async def get_server_descriptions(self, server_name: str, capability_type: str):
        """
        输入参数：
            server_name: 要获取描述的MCP Server名称
            capability_type: 要获取的能力类型，"tools"、"resources" 或"prompts"

        尝试从server_descriptions中获取对应能力的详细描述。
        - 优先从本地缓存 server_descriptions 获取。
        - 否则通过已连接的MCP Server获取。
            如果server_descriptions中没有该能力的描述，则从server_sessions对应活跃的MCP Server连接中调用能力描述信息。
        - 如果没有连接过服务器，则尝试自动连接再请求描述。
            如果server_sessions中没有对应的MCP Server连接，则从server_config中获取对应的MCP Server配置并连接。
        """
        # 1. server_descriptions 缓存优先
        if server_name in self.server_descriptions:
            if capability_type in self.server_descriptions[server_name]:
                return self.server_descriptions[server_name][capability_type]

        # 2. 本地缓存中没有，从 server_sessions 中找到对应已连接的 MCP Server 获取描述
        session = self.server_sessions.get(server_name, None)
        if session:
            try:
                # 如果该能力被 MCP Server 支持
                # print(f"[DEBUG]server_name:{server_name}, capability_type:{capability_type}")
                print(f"[DEBUG]server_descriptions[server_name]['capabilities'][capability_type]：",self.server_descriptions[server_name]["capabilities"][capability_type])
                capability_supported = self.server_descriptions.get(server_name, {}).get("capabilities", {}).get(capability_type, None)
                if capability_supported is True:

                    if capability_type == "tools":
                        result = await session.list_tools()  # 异步调用服务器获取工具列表
                        # print("[DEBUG][MCPClient] 工具列表返回结果:", result)
                        if hasattr(result, "tools") and result.tools:
                            for i, tool in enumerate(result.tools, 1):
                                '''
                                将工具描述存入 server_descriptions 缓存
                                获取返回的字段的文档说明 https://modelcontextprotocol.io/specification/2025-06-18/server/tools
                                
                                从result.tools列表中获取到的tool格式示例：
                                {
                                    "name": "get_weather",
                                    "title": "Weather Information Provider",
                                    "description": "Get current weather information for a location",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {
                                            "location": {
                                                "type": "string",
                                                "description": "City name or zip code"
                                            }
                                        },
                                        "required": ["location"]
                                    }
                                }
                                '''
                                self.server_descriptions[server_name].setdefault("tools", {})[tool.name] = {
                                    "description": tool.description,
                                    "title": getattr(tool, "title", None),
                                    "input_schema": getattr(tool, "inputSchema", None),
                                    "output_schema": getattr(tool, "outputSchema", None),
                                    "required": getattr(tool, "required", None),
                                }
                            return self.server_descriptions[server_name]["tools"]

                        else:
                            print(f"[MCPClient] MCP Server {server_name} 返回的工具列表为空或未定义。")
                            return None

                    elif capability_type == "resources":
                        result = await session.list_resources()  # 异步调用服务器获取资源列表
                        if hasattr(result, "resources") and result.resources:
                            for i, resource in enumerate(result.resources, 1):
                                '''
                                将资源描述存入 server_descriptions 缓存
                                获取返回的字段的文档说明 https://modelcontextprotocol.io/specification/2025-06-18/server/resources
                                
                                从result.resources列表中获取到的resource格式示例：
                                {
                                    "uri": "file:///project/src/main.rs",
                                    "name": "main.rs",
                                    "title": "Rust Software Application Main File",
                                    "description": "Primary application entry point",
                                    "mimeType": "text/x-rust"
                                }
                                '''
                                self.server_descriptions[server_name].setdefault("resources", {})[resource.name] = {
                                    "description": resource.description,
                                    "title": getattr(resource, "title", None),
                                    "uri": getattr(resource, "uri", None),
                                    "mimeType": getattr(resource, "mimeType", None),

                                }
                            return self.server_descriptions[server_name]["resources"]

                        else:
                            print(f"[MCPClient] MCP Server {server_name} 返回的资源列表为空或未定义。")
                            return None

                    elif capability_type == "prompts":
                        result = await session.list_prompts()  # 异步调用服务器获取提示词列表
                        if hasattr(result, "prompts") and result.prompts:
                            for i, prompt in enumerate(result.prompts, 1):
                                '''
                                将提示词描述存入 server_descriptions 缓存
                                获取返回的字段的文档说明 https://modelcontextprotocol.io/specification/2025-06-18/server/prompts
                                
                                从result.prompts列表中获取到的prompt格式示例：
                                {
                                    "name": "code_review",
                                    "title": "Request Code Review",
                                    "description": "Asks the LLM to analyze code quality and suggest improvements",
                                    "arguments": [
                                        {
                                            "name": "code",
                                            "description": "The code to review",
                                            "required": true
                                        }
                                    ]
                                }
                                !!! 这里要将arguments从列表形式转换成字典形式，方便后续使用 !!!
                                '''
                                # 将 prompt.arguments 列表转换为符合 schema 的字典结构
                                arguments_list = getattr(prompt, "arguments", []) or []
                                arguments_dict = {}
                                for arg in arguments_list:
                                    arg_name = getattr(arg, "name", None)
                                    if arg_name:
                                        arguments_dict[arg_name] = {
                                            "description": getattr(arg, "description", ""),
                                            "required": getattr(arg, "required", False)
                                        }
                                # 存储到 server_descriptions 中
                                self.server_descriptions[server_name].setdefault("prompts", {})[prompt.name] = {
                                    "description": prompt.description,
                                    "title": getattr(prompt, "title", None),
                                    "arguments": arguments_dict,
                                }
                            return self.server_descriptions[server_name]["prompts"]

                        else:
                            print(f"[MCPClient] MCP Server {server_name} 返回的提示词列表为空或未定义。")
                            return None
                else:
                    print(f"[MCPClient] MCP Server {server_name} 不支持能力：{capability_type}。")
                    return None

            except Exception as e:
                print(f"[MCPClient] 获取能力描述失败（MCP服务 {server_name}，能力 {capability_type}）: {e}")
                return None

        # 3. 如果没有连接过服务器，则尝试自动连接
        else:
            # 尝试连接到指定的 MCP Server
            await self.connect_to_server([server_name])
            # 再次尝试获取工具描述
            if server_name in self.server_sessions:
                return await self.get_server_descriptions(server_name, capability_type)

    # 传入参数使用server提供的能力
    async def use_capability(
        self,
        server_name: str,
        capability_type: str,
        capability_name: str,
        arguments: Dict[str, Any] | None = None
    ) -> Any:
        '''
        调用指定server的指定能力
        从server_sessions中已连接的对应服务器会话，从中调用server能力

        参数：
            server_name: MCP Server的名称
            capability_type: 能力类型，可以是 "tools"、"resources" 或 "prompts"
            capability_name: 要调用的能力的具体名称
            arguments: 调用能力时需要传入的参数，以字典形式传入
        '''
        if server_name not in self.server_sessions:
            # 如果没有连接过服务器，则尝试自动连接
            await self.connect_to_server([server_name])

        session = self.server_sessions.get(server_name)

        if not session:
            print(f"[Debug][MCPClient] 未连接到 MCP Server '{server_name}'，尝试连接也失败。")
            return None

        # 检查能力类型是否支持
        capability_supported = self.server_descriptions[server_name]["capabilities"][capability_type]
        if not capability_supported:
            print(f"[MCPClient] MCP Server '{server_name}' 不支持能力类型：{capability_type}")
            return None

        try:
            if capability_type == "tools":
                '''
                返回工具调用结果result.content：
                [
                    {
                        "type": "text",
                        "text": "Current weather in New York:\nTemperature: 72°F\nConditions: Partly cloudy"
                    }
                ],
                '''
                # 调用工具 需要传入对应的参数
                result = await session.call_tool(capability_name, arguments or {})
                print(f"\nresult:{str(result)}")
                return str(result.content)  # 返回json中"content"字段中的值,以字符串形式

            elif capability_type == "resources":
                '''
                返回资源结果result.contents：
                [
                  {
                    "uri": "test://static/resource/1",
                    "name": "Resource 1",
                    "title": "Rust Software Application Main File",
                    "mimeType": "text/x-rust",
                    "text": "Resource 1: This is a plaintext resource"
                  }
                ]
                '''
                # 查看资源 需要获取url，arguments字典中应包含arguments["url"]字段值
                result = await session.read_resource(arguments.get("uri", ""))
                print(f"\nresult:{str(result)}")
                return str(result.contents)  # 返回json中"contents"字段中的值,以字符串形式

            elif capability_type == "prompts":
                '''
                返回提示词结果result.messages：
                [
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": "Please review this Python code:\ndef hello():\n    print('world')"
                        }
                    }
                ]
                '''
                # 获取提示词，只需要传入提示词名称
                result = await session.get_prompt(capability_name)
                print(f"\nresult:{str(result.messages)}")
                return str(result.messages)  # 返回json中的值,以字符串形式

            else:
                print(f"[MCPClient] 不支持的能力类型：{capability_type}")
                return None

        except Exception as e:
            print(f"[MCPClient] 使用能力 '{capability_name}' 失败: {e}")
            return None

# 测试 MCPClient 的基本功能
async def test():
    """
    用于测试 MCPClient 的基本功能。
    连接到指定的 MCP 服务器，并获取工具描述。
    """
    # 使用with AsyncExitStack()包裹主函数，统一管理整个上下文生命周期，自动清理异步资源。
    async with AsyncExitStack() as stack:
        print("...正在测试 MCPClient 功能...\n")
        mcp_client = MCPClient()
        mcp_client.exit_stack = stack  # 替换为当前栈
        # print(f"mcp_client.server_config:\n {mcp_client.server_config}")

        await mcp_client.initialize_servers()
        # print(f"当前活跃连接：\n {mcp_client.server_sessions.keys()}\n")

        print(f"\n此时server_descriptions：\n {mcp_client.server_descriptions}")

        # 获取MCP服务的能力描述列表
        server_description = await mcp_client.get_server_descriptions(
            server_name = "milvus-sse",
            capability_type = "tools"  # 可以是 "tools"、"resources" 或 "prompts"
        )
        print("\n服务描述获取结果：\n", server_description)

        # 调用 MCP Server 的具体能力
        response = await mcp_client.use_capability(
            server_name = "milvus-sse",
            capability_type = "tools",
            capability_name = 'milvus_list_collections', # "echo",
            # arguments={"message": "Hello, MCP!"}  # 传入工具调用参数
        )
        print("\n调用 MCP Server 的能力返回结果：\n", response)



if __name__ == "__main__":
    '''
    测试 MCPClient 的基本功能命令 python -m mas.tools.mcp_client
    
    验证是否安装了npx，可用尝试在环境中执行 npx --version 命令 
    
    '''
    import asyncio
    asyncio.run(test())
    # main()



