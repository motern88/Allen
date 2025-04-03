## 状态类



### 1. 任务状态 `task_state`

每一个任务会有自己的一个任务群组。任务群组由多个Agent组成。每个任务初始化时会维护一个 `task_state` 。`task_state` 记录任务所包含的全部信息



### 2. 阶段状态 `stage_state`

由任务群组的管理者制定和调整当前任务流程需要经过的多个任务阶段，并为每个任务阶段分配相应的Agent去执行。一个任务阶段可能由多个Agent协作执行。

每个阶段维护一个 `stage_state`



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
| execute_result      | dict | 执行结果                                                     |



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