## Utils

### 1. 总览

我们在 `mas/utils` 实现一些MAS中不属于Agent内部所需的其他组件。

```python
mas/utils
async_loop.py			# 实现异步线程循环和MCP Client Wapper
message.py				# 定义MAS中的消息结构
message_dispatcher.py	# 消息分发器
monitor.py				# 状态监控器
```



- `mas/utils/async_loop.py` ：实现在MAS中支持异步调用MCPClient的功能

  实现了 `AsyncLoopThread` 和 `MCPClientWrapper` 两个类

  

- `mas/utils/message.py` ：定义了MAS中跨Agent的消息传递格式

- `mas/utils/message_dispatcher.py` ：实现了一个用于在MAS中分发消息的对象

  

- `mas/utils/monitor.py` ：实现了对四种状态的监控器

  其中的 `StateMonitor` 类会以装饰器的形式获取到 TaskState、StageState、AgentState、StepState 等状态类



#### 1.1 Async Loop

该类主要实现在MAS（Multi-Agent System）架构中支持异步调用 MCPClient 的功能。

- `AsyncLoopThread` 一个异步事件循环线程，用于MAS架构中支持每个Agent独立对MCPClient进行异步并行调用。
- `MCPClientWrapper` 一个MCPClient的同步包装器，用于在MAS架构中提供异步调用支持。



> 我们的MAS架构：
>
> - MAS 主线程：负责初始化系统、创建 Agent、启动 Agent 的线程。
>
> - 每个 Agent：有自己的 threading.Thread，在 action() 循环中同步执行任务（顺序处理 Steps）。
>
> - Agent 与 Agent之间的执行是并行的，因为它们在不同线程中运行。
>
> - Agent 内部 Action 循环是同步的，不使用 async/await，所以每个 Agent 在执行 MCPClient 调用时会阻塞当前线程，直到 MCPClient 返回结果。
>
> 所以可以这样描述：
>
> - MAS 架构：多线程并行 + 每个线程内部同步逻辑
>
> - MCPClient：异步 API，但我们希望在 Agent 内能并发执行多个工具调用（而不是一个个阻塞）。



因此 `async_loop` 脚本用于支持实现以下方案：

保持 MAS 和 Agent 的同步代码不改，提供 同步包装器，内部用 `asyncio.run_coroutine_threadsafe` 提交到全局事件循环线程，这样：

- Agent 调 MCPClient → 不会卡死整个系统（只阻塞该 Agent 线程）。

- 多个 Agent 调 MCPClient → 并发执行（因为 MCPClient 运行在事件循环线程，异步调度）。

- 即使一个 Agent 想在一个 Step 中发起多个 MCP 调用并发执行，也可以通过 `asyncio.gather` 在 MCPClient 事件循环里实现。



#### 1.2 Message

> Message实现详情见文档[Multi-Agent-System实现细节](https://github.com/motern88/Allen/blob/main/docs/Multi-Agent-System实现细节.md)中**8.3**节



#### 1.3 Message Dispatcher

> 消息分发器实现详情见文档[Multi-Agent-System实现细节](https://github.com/motern88/Allen/blob/main/docs/Multi-Agent-System实现细节.md)中**8.4**节



#### 1.4 Monitor

> 状态监控器实现详情见文档[Multi-Agent-System实现细节](https://github.com/motern88/Allen/blob/main/docs/Multi-Agent-System实现细节.md)中**8.5**节

我们在此实现了一个 `StateMonitor` 状态监控器类。本MAS架构的核心就是从任务到步骤的四种状态，因此只要监控到状态基本就能监控到整个MAS的全部动向。

我们的 `StateMonitor` 实现了一个装饰器方法，只需要在 TaskState、StageState、AgentState、StepState 实现上加上这个装饰器，`StateMonitor` 即可获取其内容。

然而，面对前端展示，我们依然需要对直接获取到的状态信息做序列化操作。我们会将不可序列化的字段换成特殊可表示形式，其中：

- `task_state.communication_queue` ：

  将 `queue.Queue` 以 `obj.qsize()` 的形式展示其元素数量

- `agent_step.todo_list` ：

  将 `deque()` 转化成列表 `[self._safe_serialize(item) for item in obj]`

