- 任务状态 `task_state`

  每一个任务会有自己的一个任务群组。任务群组由多个Agent组成。每个任务初始化时会维护一个 `task_state` 。`task_state` 记录任务所包含的全部信息



- 阶段状态 `stage_state`

  由任务群组的管理者制定和调整当前任务流程需要经过的多个任务阶段，并为每个任务阶段分配相应的Agent去执行。一个任务阶段可能由多个Agent协作执行。

  每个阶段维护一个 `stage_state`



- 步骤状态 `step_state`

  Agent被分配执行或协作执行一个阶段时，Agent会为自己规划数个执行步骤以完成目标。步骤是最小执行单位，每个步骤的执行会维护一个 `step_state` 。

  `step_state` 是Agent感知与观察的渠道之一，Agent通过 `step_state` 来获得执行操作的反馈。