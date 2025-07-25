## Base

### 1. 总览 

```python
mas/agent/base
agent_base.py  				# agent基础类
base_prompt.yaml 			# mas系统提示词
llm_base.py  				# LLM基础调用类
router.py  					# 根据每个step信息调用不同具体executor的路由
executor_base.py  			# 执行器基础类(为skills与tools定义统一的方法)
```



- `mas/agent/base/agent_base.py`：实现Agent的基础类

- `mas/agent/base/base_prompt.yaml`：存放MAS的系统提示词

- `mas/agent/base/llm_base.py`：实现LLM调用客户端

- `mas/agent/base/router.py`：实现Agent执行具体操作的路由

  路由用于根据步骤状态调用具体的执行器

- `mas/agent/base/executor_base.py`：实现基础执行器类



### 2. Agent Base

> 详情见文档[Multi-Agent-System实现细节](https://github.com/motern88/Allen/blob/main/docs/Multi-Agent-System实现细节.md)中第**6**节

我们在 `mas/agent/base/agent_base.py` 中实现了 AgentBase 基础类，该类定义了 Agent 最基础的执行逻辑。

在 AgentBase 中，Agent 会在循环中不断地执行下一个 Step （如果不存在下一个Step则不会执行）。通过顺序处理一个个步骤 AgentBase 实现 Agent 与 MAS 中环境交互的能力。

- 在 AgentBase 初始化时，维护一个属性 `AgentBase.agent_state` 用于维持自身状态。不同Agent的区别在于该 Agent 状态不同。

- 在 AgentBase 的执行方法中，获取到的每个 Step 都会首先使用 Router 调取其对应的执行器。随后执行该执行器 Executor ，并将其返回结果用于指导 SyncState 进行状态同步。

- 在 AgentBase 的任务方法中，AgentBase 支持随时处理来自 MAS 中其他 Agent 的消息，同时触发一些列的反应行为。



### 3. LLM Base

> 详情见文档[Multi-Agent-System实现细节](https://github.com/motern88/Allen/blob/main/docs/Multi-Agent-System实现细节.md)中第**8.1**节

我们在 `mas/agent/base/llm_base.py` 实现了 LLMClient 类，该类通过维护 LLMContext 管理对话上下文并与 LLM 建立联系。



### 4. Router

> 详情见文档[Multi-Agent-System实现细节](https://github.com/motern88/Allen/blob/main/docs/Multi-Agent-System实现细节.md)中第**8.2**节

我们在 `mas/agent/base/router.py` 实现路由器 Router ，该 Router 专门用于根据不同的 StepState 调用对应各自的 Executor 。



### 5. Executor Base

> 详情见文档[Multi-Agent-System实现细节](https://github.com/motern88/Allen/blob/main/docs/Multi-Agent-System实现细节.md)中第**5**节

我们在 `mas/agent/base/executor_base.py` 实现 ExecutorBase 类，所有的技能/工具 Executor 均继承 ExecutorBase 类，并共享其中的通用方法。

其中包括各种不同情况下组装提示词的方法。

