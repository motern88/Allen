## 状态类



### 1. 任务状态 `task_state`

每一个任务会有自己的一个任务群组。任务群组由多个Agent组成。每个任务初始化时会维护一个 `task_state` 。`task_state` 记录任务所包含的全部信息

| 属性                | 类型             | 说明                                                        |
| ------------------- | ---------------- | ----------------------------------------------------------- |
| task_id             | str              | 用于标识一个任务的唯一ID                                    |
| task_intention      | str              | 任务意图, 较为详细的任务目标说明                            |
| task_manager        | str              | 任务管理者Agent ID，负责管理这个任务的Agent ID              |
| task_group          | list[str]        | 任务群组，包含所有参与这个任务的Agent ID                    |
| shared_message_pool | List[Dict]       | 任务群组共享消息池                                          |
| stage_list          | List[StageState] | 当前任务下所有阶段的列表（顺序执行不同阶段）                |
| execution_state     | str              | 当前任务的执行状态，"init"、"running"、"finished"、"failed" |
| task_summary        | str              | 任务完成后的总结，由SyncState或调度器最终生成               |

`task_state`存储包含多个`stage_state`的列表。任务状态类负责管理`stage_state`列表，管理`shared_message_pool`共享消息池。



### 2. 阶段状态 `stage_state`

由任务群组的管理者制定和调整当前任务流程需要经过的多个任务阶段，并为每个任务阶段分配相应的Agent去执行。一个任务阶段可能由多个Agent协作执行。

每个阶段维护一个 `stage_state`

| 属性               | 类型           | 说明                                                         |
| ------------------ | -------------- | ------------------------------------------------------------ |
| task_id            | str            | 用于标识一个任务的唯一ID                                     |
| stage_id           | str            | 用于标识一个阶段的唯一ID                                     |
| stage_intention    | str            | 阶段的意图, 由创建Agent填写                                  |
| agent_allocation   | Dict[str, str] | 阶段中Agent的分配情况，key为Agent ID，value为Agent在这个阶段职责的详细说明 |
| execution_state    | str            | 阶段的执行状态 init  ， running， finished， failed          |
| every_agent_state  | Dict[str, str] | Dict[<agent_id>, <agent_state>]，Agent在这个阶段的状态，不是全局状态：idle，working，finished，failed |
| completion_summary | Dict[str, str] | Dict[<agent_id>, <completion_summary>]，阶段中每个Agent的完成情况 |



### 3. 步骤状态 `step_state`

Agent 在执行任务的过程中，会将任务拆解为多个步骤（Step），并逐步执行。这些步骤可能包含思考、规划、决策，或是调用工具完成具体的操作。每个步骤都会维护一个 `StepState`，用于记录其执行状态。

`AgentStep` 类用于管理 `StepState` 列表，支持步骤的添加、查询、更新和移除操作。未执行的步骤会存放在 `todo_list` 中，按顺序执行。

#### StepState

`StepState` 代表 Agent 生成的最小执行单位，可能是 LLM 的文本回复（思考/反思/规划/决策）或一次工具调用。

| 属性                | 类型 | 说明                                                         |
| ------------------- | ---- | ------------------------------------------------------------ |
| task_id             | str  | 任务 ID                                                      |
| stage_id            | str  | 阶段 ID                                                      |
| agent_id            | str  | Agent ID                                                     |
| step_id             | str  | 步骤 ID（自动生成）                                          |
| step_intention      | str  | 步骤的意图（例如：'ask a question', 'use tool to check'）    |
| type                | str  | 步骤类型（'skill' 或 'tool'）                                |
| executor            | str  | 执行该步骤的对象（技能名称或工具名称）                       |
| execution_state     | str  | 执行状态（'init', 'pending', 'running', 'finished', 'failed'） |
| text_content        | str  | 文本内容（描述技能调用的具体目标）                           |
| instruction_content | dict | 指令内容（工具调用的具体指令）                               |
| execute_result      | dict | 用来记录LLM输出解析或工具返回的结果，主要作用是向reflection反思模块提供每个步骤的执行信息 |



#### AgentStep类

`AgentStep` 用于管理 Agent 的执行步骤列表，提供步骤的增删改查功能。

| 属性      | 类型            | 说明                             |
| --------- | --------------- | -------------------------------- |
| agent_id  | str             | 关联的 Agent ID                  |
| todo_list | queue.Queue     | 存放待执行步骤的 step_id         |
| step_list | List[StepState] | 记录所有步骤（包含已完成的步骤） |

核心方法：

`add_step(step: StepState)`: 添加新步骤到 `step_list`，如果未执行过，则加入 `todo_list`。

`get_step(step_id=None, stage_id=None, task_id=None) -> List[StepState]`: 查询特定步骤。

`update_step_status(step_id: str, new_state: str)`: 更新步骤的执行状态。





### 4. 状态同步器 `sync_state`

在MAS中，`sync_state`专门负责同步`stage_state`与`task_state`这些不属于某一Agent的状态，而Agent自身的`agent_state`与`step_state`在`executor`执行过程中就更新完毕。`executor`执行返回的`executor_output`用于指导`sync_state`工作。

在一个MAS系统中只实例化一个`sync_state`，这个`sync_state`会在Agent实例化时传递给多个Agent，不同Agent均操作同一个状态同步器。



SyncState类用于管理任务状态和阶段状态的同步。所有任务将被注册进 all_tasks 字典中（task_id -> TaskState）：`all_tasks(Dict[str, TaskState])` : 所有任务的状态信息，键为task_id。

同时该类实现一个 `sync_state(executor_output: Dict[str, any])` 方法解析并更新task/stage状态