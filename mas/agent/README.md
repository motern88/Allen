## Agent

### 1. 总览

```python
mas/agent
├──base						# 实现Agent相关的基础方法
|   ├──agent_base.py
|   ├──base_prompt.yaml
|   ├──executor_base.py
|   ├──llm_base.py
|   └──router.py
├──configs					# 定义LLM配置类
|   └──llm_config.py
└──state					# 定义三种状态与实现状态同步器
    ├──task_state.py
    ├──stage_state.py
    ├──step_state.py
    └──sync_state.py
agent.py  					# LLM-Agent,继承自AgentBase类
human_agent.py				# 人类操作端HumanAgent,继承自AgentBase类
```



- `mas/agent/base`：其中实现单Agent逻辑相关的基础方法

  实现了Agent最核心的Action逻辑，同时实现了基础Executor和路由Router

- `mas/agent/configs`：其中定义LLM-Agent中使用的LLM配置类

- `mas/agent/state`：其中定义了三种状态类，和跨状态的状态同步器



- `mas/agent/agent.py`：这里实现LLM-Agent，继承自 `mas/agent/base/agent_base.py` 的AgentBase类，但当前的LLM-Agent并不会使用到该类，当前LLM-Agent直接从AgentBase实例化。**因此当前该脚本的实现并没有实际被使用**。

- `mas/agent/human_agent.py`：这里实现HumanAgent类，继承自 `mas/agent/base/agent_base.py` 的AgentBase类。HumanAgent类实现了人类操作端所需的额外的方法。



### 2. Human Agent

> 详情见文档[Multi-Agent-System实现细节](https://github.com/motern88/Allen/blob/main/docs/Multi-Agent-System实现细节.md)中第**7**节。

我们在 `mas/agent/human_agent.py` 实现了人类操作端 HumanAgent ，继承AgentBase类，拥有和 LLM-Agent 相同的构造与接口。唯一的区别是人类操作端是由人类驱动而非LLM驱动。

与LLM-Agent有大致以下区别：

- 步骤记录：

  LLM-Agent中先有一个个Step，Agent再按顺序执行这一个个Step；Human-Agent中则是人类操作端先产生具体行为，再通过补充Step来记录实施的操作。

- `receive_message()`方法：

  Human-Agent的receive_message方法被覆写，其中收到来自其他Agent的消息均会额外添加到 `agent_state["conversation_pool"]["conversation_privates"]` 的单独私聊对话中；而LLM-Agent不会在自己的 `AgentState` 中存储会话信息。
