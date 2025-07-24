## State

### 1. 总览

该目录下实现MAS架构中核心的四种状态其三（ `AgentState` 在 `AgentBase` 中定义）。

```python
mas/agent/state
task_state.py		# 任务状态
stage_state.py		# 阶段状态
step_state.py		# 步骤状态
sync_state.py		# 状态同步器
```



- `mas/agent/state/task_state.py` ：实现 `TaskState` 类，用于定义MAS架构中任务的构成
- `mas/agent/state/stage_state.py` ：实现 `StageState` 类，用于定义MAS架构中任务下阶段的构成
- `mas/agent/state/step_state.py` ：实现 `StepState` 类，用于定义MAS架构中Agent执行的一个个Step的构成
- `mas/agent/state/sync_state.py` ：实现 `SyncState` 类，用于Agent在执行中将Agent意图的操作行为实施在具体 `TaskState` 和 `StageState` 中

 

### 2. Task State

> 详情见文档[Multi-Agent-System实现细节](https://github.com/motern88/Allen/blob/main/docs/Multi-Agent-System实现细节.md)中第**2.1**节。

MAS架构是一个以任务为驱动的架构，其中最大的具体目标的执行单位就是任务。任务概念以 `TaskState` 的形式出现在MAS中。所有Agent的活动与执行均依赖于某个 `TaskState` 所提供的任务空间。

> TaskState提供Agent的活动空间的具体表现有：
>
> - Agent之间的通讯/消息传递均只能在TaskState中转发。
> - 所有的Agent通讯记录均记录在TaskState中。
> - 所有Agent的活动与执行均依赖于TaskState下的具体StageS，可以说如果Agent不属于任何一个Task时，它无法产生任何活动行为。

一个任务下允许被规划处多个阶段，所有阶段按顺序执行。同一时刻只允许其中的一个阶段处于被执行状态。



### 3. Stage State

> 详情见文档[Multi-Agent-System实现细节](https://github.com/motern88/Allen/blob/main/docs/Multi-Agent-System实现细节.md)中第**2.2**节。

一个任务的管理Agent有能力为任务Task规划出一个个阶段State，这些阶段会以 `StageState` 的形式存放在 `TaskState` 中。其中包含：

- 阶段的详细意图和目标
- 阶段下每个涉及到的Agent的具体目标
- 阶段完成情况



### 4. Step State

> 详情见文档[Multi-Agent-System实现细节](https://github.com/motern88/Allen/blob/main/docs/Multi-Agent-System实现细节.md)中第**2.4**节。

Agent 在执行任务的过程中，会顺序执行多个自主规划的步骤Step（MAS中最小执行单元）。这些步骤可能包含思考、规划、决策，或是调用工具完成具体的操作。

这些步骤Step以 `StepState` 的形式出现并存放在 `AgentState.agent_step` 中，每个步骤都拥有相同的构造。

> `AgentState.agent_step` 类用于管理 `StepState` 列表，支持步骤的添加、查询、更新和移除操作。未执行的步骤会存放在 `todo_list` 中，按顺序执行。

StepState 本身只记录该步骤的目标。实施情况等信息，真正执行产生行为是通过执行器 Executor 。执行器根据 StepState 中的具体内容产生具体的执行行为。



### 5. Sync State

> 详情见文档[Multi-Agent-System实现细节](https://github.com/motern88/Allen/blob/main/docs/Multi-Agent-System实现细节.md)中第**2.5**节。

在MAS中，`SyncState`专门负责同步`StageState`与`TaskState`这些不属于某一Agent的状态。

Agent自身的 `AgentState` 与 `StepState` 在执行器执行过程中就更新完毕。执行器返回的 `executor_output` 用于指导 `sync_state` 的状态同步工作。