'''
该类主要实现一个异步事件循环线程，用于MAS架构中支持每个Agent独立对MCPClient进行异步并行调用。

其中整个MAS架构背景：
    - MAS 主线程：负责初始化系统、创建 Agent、启动 Agent 的线程。
    - 每个 Agent：有自己的 threading.Thread，在 action() 循环中同步执行任务（顺序处理 Steps）。
    - Agent 与 Agent之间的执行是并行的，因为它们在不同线程中运行。
    - Agent 内部 Action 循环是同步的，不使用 async/await，所以每个 Agent 在执行 MCPClient 调用时会阻塞当前线程，直到 MCPClient 返回结果。
所以可以这样描述：
    - MAS 架构：多线程并行 + 每个线程内部同步逻辑
    - MCPClient：异步 API，但你希望在 Agent 内能并发执行多个工具调用（而不是一个个阻塞）。

我们想要目标：
    - MAS 保持不变（多线程并行），不要大改 Agent 的同步逻辑。
    - MCPClient 的调用不要阻塞 Agent 线程太久，且可以在同一个 Agent 内部并行多个 MCP 操作（比如多个工具调用并发）。
    - 允许多个 Agent 共享同一个 MCPClient 事件循环。

因此，该脚本用于支持实现以下方案：
    保持 MAS 和 Agent 的同步代码不改，提供 同步包装器，内部用 asyncio.run_coroutine_threadsafe 提交到全局事件循环线程，这样：
    - Agent 调 MCPClient → 不会卡死整个系统（只阻塞该 Agent 线程）。
    - 多个 Agent 调 MCPClient → 并发执行（因为 MCPClient 运行在事件循环线程，异步调度）。
    - 即使一个 Agent 想在一个 Step 中发起多个 MCP 调用并发执行，也可以通过 asyncio.gather 在 MCPClient 事件循环里实现。
'''

import asyncio
import threading


class AsyncLoopThread:
    '''
    异步事件循环线程，用于在多线程环境中运行异步任务。
    该类主要向MultiAgentSystem提供异步环境。
    '''
    def __init__(self):
        self.loop = None
        self.thread = None

    def start(self):
        if self.loop is not None:
            return
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run_coroutine(self, coro):
        if self.loop is None:
            raise RuntimeError("Async loop not started")
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def stop(self):
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join()

class MCPClientWrapper:
    '''
    MCPClient的同步包装器，用于在MAS架构中提供异步调用支持。
    用于将MCPClient的调用提交到 异步事件循环线程 AsyncLoopThread 中，
    '''
    def __init__(self, mcp_client, async_loop):
        self.mcp_client = mcp_client
        self.async_loop = async_loop

    def use_capability_sync(self, **kwargs):
        '''
        传入参数使用server提供的能力
        （提交协程，并等待结果）
        '''
        future = self.async_loop.run_coroutine(self.mcp_client.use_capability(**kwargs))
        return future.result()

    def use_capability_async(self, **kwargs):
        '''
        传入参数使用server提供的能力
        （提交协程，不等待结果）
        返回一个 concurrent.futures.Future，Agent 可以稍后 future.result(timeout=...)
        '''
        return self.async_loop.run_coroutine(self.mcp_client.use_capability(**kwargs))

    def get_capabilities_list_description(self, mcp_server_name):
        '''
        并行获取 MCP 服务的 prompts/resources/tools 描述。
        获取MCP服务的能力列表描述：
        1. 获取MCPClient.server_descriptions中对应的mcp_server_name的能力范围。
        2. 调用MCPClient.get_server_descriptions方法获取具体的能力列表。
            分别获取prompts、resources和tools的描述（根据Sever是否支持该能力），
        '''
        # 1. 获取MCPClient.server_descriptions中对应的mcp_server_name的能力范围
        server_capabilities = self.mcp_client.server_descriptions.get(mcp_server_name, {})
        # print(f"[MCPClientWrapper] Server '{mcp_server_name}' capabilities: {server_capabilities}")
        # {'capabilities': {'prompts': True, 'resources': True, 'tools': True}}
        if not server_capabilities:
            return None

        # 2. 定义 调用MCPClient.get_server_descriptions方法获取具体的能力列表 的异步任务集合
        async def fetch_all():
            tasks = []
            capabilities = server_capabilities.get("capabilities", {})
            if capabilities.get("prompts"):  # 如果prompts为True，则获取所有prompts的描述
                tasks.append(asyncio.create_task(
                    self.mcp_client.get_server_descriptions(mcp_server_name, "prompts")
                ))
            if capabilities.get("resources"):  # 如果resources为True，则获取所有resources的描述
                tasks.append(asyncio.create_task(
                    self.mcp_client.get_server_descriptions(mcp_server_name, "resources")
                ))
            if capabilities.get("tools"):  # 如果tools为True，则获取所有tools的描述
                tasks.append(asyncio.create_task(
                    self.mcp_client.get_server_descriptions(mcp_server_name, "tools")
                ))

            return await asyncio.gather(*tasks)

        # 3. 提交到全局事件循环并同步等待
        future = self.async_loop.run_coroutine(fetch_all())
        results = future.result()
        # print(f"[MCPClientWrapper] 获取服务 '{mcp_server_name}' 的能力列表: {results}")

        # 4.组装结果
        capabilities_list_description = {}
        keys = ["prompts", "resources", "tools"]
        idx = 0
        for key in keys:
            if server_capabilities.get(key):
                # 如果该能力类型为True，则将对应的结果添加到能力列表描述中
                capabilities_list_description[key] = results[idx]
                idx += 1

        return capabilities_list_description if capabilities_list_description else None