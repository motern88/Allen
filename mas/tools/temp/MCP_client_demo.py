'''
该文件用于注释和理解MCP的使用方式
'''



#################### 客户端 ####################

import asyncio
from typing import Optional
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from anthropic import Anthropic
from dotenv import load_dotenv

# 从 .env 文件加载环境变量（例如 API 密钥、配置等）
load_dotenv()  # 从 .env 文件加载环境变量

class MCPClient:
    def __init__(self):
        # 初始化一个 aiohttp 的 HTTP 会话（初始设为 None，稍后在需要时创建）
        self.session: Optional[ClientSession] = None
        # 创建一个异步的上下文管理器堆栈（可用于统一管理多个异步资源）
        self.exit_stack = AsyncExitStack()
        # 初始化 Anthropic 客户端（可能用于调用 Claude 等模型服务）
        self.anthropic = Anthropic()
    # methods will go here

    async def connect_to_server(self, server_script_path: str):
        """
        连接到一个 MCP 服务器

        参数:
            server_script_path: 服务器脚本的路径（支持 .py 或 .js 文件）
        """
        # 判断路径是否为 Python 脚本（以 .py 结尾）
        is_python = server_script_path.endswith('.py')
        # 判断路径是否为 JavaScript 脚本（以 .js 结尾）
        is_js = server_script_path.endswith('.js')

        # 如果既不是 .py 也不是 .js，抛出异常
        if not (is_python or is_js):
            raise ValueError("服务器脚本必须是 .py 或 .js 文件")

        # 根据脚本类型设置启动命令：Python 脚本用 python，JS 脚本用 node
        command = "python" if is_python else "node"
        # 创建 StdioServerParameters 对象，指定执行命令和参数
        server_params = StdioServerParameters(
            command=command,                 # 启动命令（如 "python" 或 "node"）
            args=[server_script_path],       # 脚本路径作为参数
            env=None                         # 可选环境变量（此处未指定）
        )

        # 使用 stdio_client 启动并连接到服务器，通过 exit_stack 管理上下文
        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self.stdio, self.write = stdio_transport  # 解包 stdio 通信接口：读取流（self.stdio）和写入函数（self.write）
        # 使用 stdio 接口创建一个 MCP 客户端会话
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))

        # 初始化会话（发送初始化请求，完成握手）
        await self.session.initialize()

        # 向服务器请求可用的工具列表
        response = await self.session.list_tools()
        # 获取工具对象列表
        tools = response.tools
        print("\n已连接服务器，可用工具:", [tool.name for tool in tools])


    async def process_query(self, query: str) -> str:
        """使用 Claude 和可用工具处理用户查询"""
        # 构造初始对话消息，包含用户的输入
        messages = [
            {
                "role": "user",
                "content": query
            }
        ]

        # 获取 MCP 服务器上注册的工具列表
        response = await self.session.list_tools()
        # 将工具信息提取为 Claude API 所需的格式
        available_tools = [{
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.inputSchema
        } for tool in response.tools]

        # 首次调用 Claude 模型，传入用户消息和工具列表
        response = self.anthropic.messages.create(
            model="claude-3-5-sonnet-20241022",  # 指定 Claude 使用的模型
            max_tokens=1000,                     # 响应最大 token 数
            messages=messages,                   # 当前对话历史
            tools=available_tools                # 提供给 Claude 使用的工具信息c
        )

        # 用于收集最终返回文本的列表
        final_text = []
        # 用于保存 Claude 的 assistant 响应内容（包括 text 和 tool_use）
        assistant_message_content = []
        # 遍历 Claude 返回的内容块（可能包含文本或工具调用）
        for content in response.content:
            # 如果是文本内容，添加到最终输出和 assistant 内容中
            if content.type == 'text':
                final_text.append(content.text)
                assistant_message_content.append(content)

            elif content.type == 'tool_use':
                # 如果 Claude 要求调用工具，则获取工具名和参数
                tool_name = content.name
                tool_args = content.input

                # 实际调用对应的工具
                result = await self.session.call_tool(tool_name, tool_args)
                # 在输出中加入提示信息
                final_text.append(f"[Calling tool {tool_name} with args {tool_args}]")

                # 将 tool_use 加入 assistant 的消息记录
                assistant_message_content.append(content)
                # 将 assistant 的工具调用信息加入 messages（用于下一轮 Claude 回答）
                messages.append({
                    "role": "assistant",
                    "content": assistant_message_content
                })

                # 将工具返回的结果作为用户的响应继续传给 Claude（类型为 tool_result）
                messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": content.id,     # 工具调用对应的唯一 ID
                            "content": result.content      # 工具执行结果
                        }
                    ]
                })

                # 再次调用 Claude 获取后续回复（考虑了工具返回值后的上下文）
                response = self.anthropic.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=1000,
                    messages=messages,
                    tools=available_tools
                )
                # 将后续 Claude 回复的文本加入最终输出
                final_text.append(response.content[0].text)

        return "\n".join(final_text)

    async def chat_loop(self):
        """运行交互式聊天循环"""
        print("\nMCP 客户端已启动！")
        print("请输入你的问题，输入 'quit' 可退出。")

        while True:
            try:
                query = input("\nQuery: ").strip()
                # 如果用户输入 'quit'，则退出循环
                if query.lower() == 'quit':
                    break
                # 如果用户输入为空，则提示重新输入
                response = await self.process_query(query)
                print("\n" + response)
            # 捕获并打印处理过程中的异常，避免程序崩溃
            except Exception as e:
                print(f"\nError: {str(e)}")

    async def cleanup(self):
        """清理资源"""
        await self.exit_stack.aclose()  # 关闭 exit_stack，自动释放会话、连接等资源

async def main():
    # 如果命令行参数数量不足（应至少包含脚本路径参数），输出使用提示并退出
    if len(sys.argv) < 2:
        print("Usage: python client.py <path_to_server_script>")
        sys.exit(1)

    # 创建 MCPClient 实例
    client = MCPClient()
    try:
        # 连接到 MCP 服务器（传入命令行指定的服务器脚本路径）
        await client.connect_to_server(sys.argv[1])
        # 启动交互式聊天循环
        await client.chat_loop()
    finally:
        # 无论是否出错，最后都执行资源清理
        await client.cleanup()

if __name__ == "__main__":
    import sys
    asyncio.run(main())  # 使用 asyncio 运行异步主函数 main()