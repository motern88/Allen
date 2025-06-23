'''
MAS系统接收到一个具体任务时，会实例化一个TaskState对象用于管理这个任务的状态。
一个任务会被拆分为多个阶段（多个子目标），即TaskState内会包含多个StageState以记录每个阶段的信息
'''
import uuid
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union
from mas.agent.state.stage_state import StageState
from mas.agent.base.message import Message
import queue
from mas.utils.monitor import StateMonitor

@StateMonitor.track  # 注册状态监控器
class TaskState:
    '''
    表示一个完整任务的状态，由多个阶段（StageState）组成。

    属性:
        task_id (str): 任务ID，用于标识一个任务的唯一ID
        task_name (str): 一个任务简介的名称，向人类使用者提供基本的信息区分
        task_intention (str): 任务意图, 较为详细的任务目标说明
        task_manager (str): 任务管理者Agent ID，负责管理这个任务的Agent ID

        task_group (list[str]): 任务群组，包含所有参与这个任务的Agent ID
        shared_message_pool (List[Dict]): 任务群组共享消息池（可选结构：包含agent_id, role, content等）
        communication_queue (queue.Queue): 用于存放任务群组的通讯消息队列，Agent之间相互发送的待转发的消息会被存放于此

        stage_list (List[StageState]): 当前任务下所有阶段的列表（顺序执行不同阶段）
        execution_state (str): 当前任务的执行状态，"init"、"running"、"finished"、"failed"
        task_summary (str): 任务完成后的总结，由SyncState或调度器最终生成

    说明:
        共享消息池是各个Agent完成自己step后同步的简略信息，且共享消息池的信息所有Agent可主动访问，但是不会一有新消息就增量通知Agent。Agent可以不感知共享消息池的变化。
        通讯消息队列是Agent之间相互发送的待转发的消息，里面存放的是Agent主动发起的通讯请求，里面必然包含需要其他Agent及时回复/处理的消息。
    '''

    def __init__(
        self,
        task_name: str,
        task_intention: str,
        task_manager: str,
        task_group: None,
    ):
        # 任务基本信息
        self.task_id = str(uuid.uuid4())
        self.task_name = task_name
        self.task_intention = task_intention
        self.task_manager = task_manager
        # 任务群组与共享消息池
        self.task_group = task_group  # list[str] 所有参与这个任务的Agent ID
        self.shared_message_pool: List[Dict[str, str]] = []  # 示例结构：[{"agent_id": "A1", "role": "assistant", "stage_id": "stage001" "content": "xxx"}]
        self.communication_queue = queue.Queue()  # 用于存放任务群组的通讯消息队列，Agent之间相互发送的待转发的消息会被存放于此，待MAS系统的消息处理模块定期扫描task_state的消息处理队列，执行消息传递任务。
        # 任务执行信息
        self.stage_list: List[StageState] = []  # 当前任务下所有阶段的列表（顺序执行不同阶段）
        self.execution_state = "init"  # 当前任务的执行状态，"init"、"running"、"finished"、"failed"
        self.task_summary = ""

    def get_stage(self, stage_id: str):
        '''
        获取指定阶段的状态
        '''
        for stage in self.stage_list:
            if stage.stage_id == stage_id:
                return stage
        return None

    # 添加任务阶段
    def add_stage(self, stage_state: StageState):
        assert stage_state.task_id == self.task_id, "Stage task_id 不一致"
        # 绑定回调函数到当前任务实例，这里给StageState绑定的回调函数是用于传递阶段完成信息到TaskState的。
        stage_state.on_stage_complete = self._handle_stage_completion
        # 添加任务阶段
        self.stage_list.append(stage_state)

    # 插入任务阶段
    def add_next_stage(self, stage_state: StageState):
        '''
        从后向前查找第一个 execution_state 为 "running"、"finished" 或 "failed" 的阶段，
        并在其后插入新的 StageState。如果都找不到，则追加到末尾。
        '''
        assert stage_state.task_id == self.task_id, "Stage task_id 不一致"
        # 绑定回调函数到当前任务实例，这里给StageState绑定的回调函数是用于传递阶段完成信息到TaskState的。
        stage_state.on_stage_complete = self._handle_stage_completion
        # 插入任务阶段为下一个待执行的阶段
        insert_index = None
        for i in reversed(range(len(self.stage_list))):
            state = getattr(self.stage_list[i], "execution_state", None)
            if state in ("running", "finished", "failed"):
                insert_index = i + 1
                break
        if insert_index is None:
            self.stage_list.append(stage_state)  # 如果没有找到合适的插入位置，则追加到末尾
        else:
            self.stage_list.insert(insert_index, stage_state)  # 在找到的位置插入新的阶段

    # 处理阶段完成时的回调函数
    def _handle_stage_completion(self, stage_id: str, completion_data: Dict[str, str], agent_allocation: Dict[str, str]):
        '''
        StageState触发阶段完成时的回调函数，在TaskState中整理信息通知管理Agent。
        以消息发送的方式通知管理Agent，将构造好的消息放入communication_queue消息队列中。
        '''
        print(f"[TaskState] 阶段 {stage_id} 已完成，向管理Agent {self.task_manager} 通知完成情况")

        # 构造阶段完成的通知消息
        message: Message = {
            "task_id": self.task_id,
            "sender_id": "[TaskState系统通知]",
            "receiver": self.task_manager,
            "message": f"[TaskState] 已侦测到阶段 {stage_id} 下所有Agent均已提交完成总结。\n"
                       f"**阶段中各个Agent被分配阶段目标**: {agent_allocation} \n"
                       f"**阶段中各个Agent提交的完成总结**: {completion_data} \n"
                       f"**现在你作为管理Agent需要对该阶段完成情况进行判断**:\n"
                       f"- 如果阶段完成情况满足预期，则使用task_manager技能的finish_stage结束该任务阶段\n"
                       f"- 如果阶段完成情况不满足预期，则使用task_manager技能的retry_stage重试该任务阶段\n",
            "stage_relative": stage_id,
            "need_reply": False,
            "waiting": None,
            "return_waiting_id": None
        }

        # 将构造好的消息放入任务的通信队列中
        self.communication_queue.put(message)

    # 获取当前需要执行/正在执行的阶段
    def get_current_or_next_stage(self) -> Optional[StageState]:
        """
        获取当前正在执行的阶段，如果没有正在执行的，则返回下一个未开始的阶段。
        用于任务调度推进。

        返回:
            当前或下一个应执行的 StageState；若全部阶段均已完成或失败，则返回 None
        """
        if len(self.stage_list) == 0:
            print("任务不存在阶段，无法获取当前阶段")
            return None

        # 1. 如果第一个阶段处于 'init' 状态，则返回第一个阶段
        if self.stage_list[0].execution_state == "init":
            return self.stage_list[0]

        # 2. 优先查找正在执行的阶段
        for stage in self.stage_list:
            if stage.execution_state == "running":
                return stage

        print("没有正在执行的阶段，查找下一个未开始的阶段")
        # 3. 查找下一个未开始的阶段
        # 找到最后一个 'finished' 或 'failed' 的阶段索引
        last_completed_index = -1
        for i, stage in enumerate(self.stage_list):
            if stage.execution_state in ("finished", "failed"):
                last_completed_index = i

        # 如果下一个阶段存在且尚未开始，则返回
        next_index = last_completed_index + 1
        if next_index < len(self.stage_list):
            next_stage = self.stage_list[next_index]
            if next_stage.execution_state == "init":
                return next_stage

        return None  # 所有阶段均已执行完毕

    def update_task_execution_state(self, state: str):
        '''
        更新任务的执行状态
        '''
        self.execution_state = state

    def add_shared_message(self, agent_id: str, role: str, stage_id: str, content: str):
        '''
        向共享消息池添加一条信息
        '''
        self.shared_message_pool.append({
            "agent_id": agent_id,
            "role": role,
            "stage_id": stage_id,
            "content": content
        })

    def get_shared_context(self, limit: int = 10) -> List[Dict[str, str]]:
        '''
        获取最近的共享消息，用于构建Agent的上下文
        '''
        return self.shared_message_pool[-limit:]
