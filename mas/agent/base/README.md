## 基础类

```python
mas/agent/base
├──agent_base.py  # agent基础类
├──executor_base.py  # 执行器基础类(为skills与tools定义统一的方法)
├──llm_base.py  # LLM基础调用类
├──router.py  # 根据每个step信息调用不同具体executor的路由
└──base_prompt.yaml  # mas系统提示词 
```



### 1. agent_base  【开发中】



#### 1.1 agent_state

`agent_state` 是 `Agent` 的核心状态管理数据结构，它记录了 `Agent` 的所有关键信息，包括标识、角色、任务状态、记忆、工具等。所有 `Agent` 共享相同的类和方法，但因 `agent_state` 的不同而具备独特性。

| key               | 类型           | 说明                                                         |
| ----------------- | -------------- | ------------------------------------------------------------ |
| agent_id          | str            | Agent的唯一标识符                                            |
| name              | str            | Agent的名称                                                  |
| role              | str            | Agent的角色                                                  |
| profile           | str            | Agent的角色简介                                              |
| working_state     | str            | Agent的当前工作状态；<br />Unassigned 未分配任务, idle 空闲, working 工作中, awaiting 等待执行反馈中 |
| llm_config        | Dict[str, Any] | 从配置文件中获取 LLM 配置                                    |
| working_memory    | Dict[str, Any] | Agent工作记忆 {<task_id>: {<stage_id>: [<step_id>,...],...},...} 记录Agent还未完成的属于自己的任务 |
| persistent_memory | str            | 由Agent自主追加的永久记忆，不会因为任务、阶段、步骤的结束而被清空；<br />（md格式纯文本，里面只能用三级标题 ### 及以下！不允许出现一二级标题！） |
| agent_step        | AgentStep实例  | AgentStep,用于管理Agent的执行步骤列表；<br />（一般情况下步骤中只包含当前任务当前阶段的步骤，在下一个阶段时，上一个阶段的step_state会被同步到stage_state中，不会在列表中留存） |
| tools             | List[str]      | Agent可用的技能                                              |
| skills            | List[str]      | Agent可用的工具                                              |
|                   |                |                                                              |
|                   |                |                                                              |



#### 1.2 Agent执行逻辑：action

不断从待执行列表 `agent_step.todo_list` 中获取 `step_id` 并执行 `step_action()` 。

`agent_step.todo_list` 是一个 `queue.Queue()` 共享队列，用于存放待执行的 `step_id`。对 `todo_list.get(step_id)` 到的每个 `step` 执行 `step_action()`



`step_action()` 执行单个step_state的具体Action：

- 根据Step的executor执行具体的Action，由路由器分发执行器

  ```python
  executor = self.router.get_executor(type=step_type, executor=step_executor)
  ```

- 运行路由器返回的执行器

  ```python
  with self.agent_state_lock:  # 防止任务线程与执行线程同时修改agent_state，优先保证执行线程的修改
      executor_output = executor.execute(step_id=step_id, agent_state=self.agent_state) 
  ```

- 更新Step的执行状态

  ```python
  self.sync_state(executor_output, self.agent_state)
  ```





#### 1.3 Agent的任务逻辑：

【开发中】







### 2. executor_base

定义`Executor`基础类，所有的skills与tools都继承自`executor`基类，具备基础类的通用实现方法

- 注册表与注册器

在 `Executor` 基类中维护注册表 `_registry: Dict[tuple[str, str], type]` ，并通过类型和名称注册子类。

所有技能和工具类使用添加装饰器的方式注册，例如：

```python
@Executor.register("skill", "planning")
```

- execute具体执行方法

子类实现 `execute(self, step_id: str, agent_state: Dict[str, Any])` 的具体执行方法。

在 `executor.execute()` 中，来自 `agent_base` 的 `self.agent_state` 传入。Agent的具体执行能够修改自身 `agent_state` ,从而自主决策自身工作逻辑与工作状态。

需要注意的是，为了防止 `agent_base` 中的执行线程和任务分配线程同时修改 `agent_state`，在execute具体执行过程中 `agent_base` 会施加线程锁，优先保证执行线程对 `agent_state` 的修改。



### 3. llm_base

该脚本实现两个类：

`LLMContext`：一个LLM上下文类，用于维护对话历史

`LLMClient`：一个LLM基础调用类，来封装API请求逻辑

使用方法：

```python
# 获取LLM配置
config = LLMConfig.from_yaml("mas/role_config/qwq32b.yaml")
# 创建 LLM 客户端
llm_client = LLMClient(config)
# 创建一个上限15轮的对话上下文
chat_context = LLMContext(context_size=15)

# 追加自定义历史记录
chat_context.add_message("user", "你好")
chat_context.add_message("assistant", "你好！我是 AI 助手")

# 调用 LLM
response = llm_client.call(
    "请介绍一下自己", context=chat_context
)

# 清空对话历史
chat_context.clear()
```

### 4. router

根据 `step_state.type` 和 `step_state.executor` 两个字段信息访问`Executor` 的注册表，并返回实例化后的执行器类。

### 5. base_prompt.yaml

记录MAS系统的系统提示词，包含两个字段：

```yaml
system_prompt:   # Muti-Agent System的基础设定与介绍
persistent_memory_prompt:  # Agent自己维护和持有的永久记忆的管理方式说明
```

