'''
Agent被分配执行或协作执行一个任务时，任务会由管理Agent拆分成具体阶段Stage。
阶段内容包含 所属任务ID与参与阶段的 Agent ID，阶段的意图与每个Agent需要完成的阶段目标，阶段与Agent的状态等。
'''

import uuid
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union, Callable
from mas.utils.monitor import StateMonitor

@StateMonitor.track  # 注册状态监控器
class StageState:
    '''
    由Agent生成的任务阶段，包含需要共同完成这个阶段目标的Agent。

    属性:
        task_id (str): 任务ID，用于标识一个任务的唯一ID
        stage_id (str): 阶段ID，用于标识一个阶段的唯一ID

        stage_intention (str): 阶段的意图, 由创建Agent填写(仅作参考并不需要匹配特定格式)。例如：'Extract contract information and archive it...'
        agent_allocation (Dict[<agent_id>, <agent_stage_goal>]):
            阶段中Agent的分配情况，key为Agent ID，value为Agent在这个阶段职责的详细说明

        execution_state (str): 阶段的执行状态
            "init" 初始化（阶段状态已创建）
            "running" 执行中
            "finished" 已完成
            "failed" 失败（阶段执行异常终止）

        every_agent_state (Dict[<agent_id>, <agent_state>]): 涉及到的每个Agent在这个阶段的状态
            "idle" 空闲
            "working" 工作中
            "finished" 已完成
            "failed" 失败（agent没能完成阶段目标）
            这里的状态是指Agent在这个阶段的状态，不是全局状态

        completion_summary (Dict[<agent_id>, <completion_summary>]): 阶段中每个Agent的完成情况

    其他:
        on_stage_complete (Optional[Callable]): 阶段完成时的回调函数，用于向task_state提交阶段完成情况
    '''

    def __init__(
        self,
        task_id: str,
        stage_intention: str,
        agent_allocation: Dict[str, str],
        execution_state: str = "init",
        # 回调函数参数 用于阶段完成时的传递至task_state的回调函数
        on_stage_complete: Optional[Callable] = None  # 在TaskState中添加StageState时会自动注册这个回调函数，不需要我们手动传入
    ):
        # 阶段基本信息
        self.task_id = task_id
        self.stage_id = str(uuid.uuid4())

        # 阶段意图与目标
        self.stage_intention = stage_intention
        self.agent_allocation = agent_allocation

        # 执行状态
        self.execution_state = execution_state  # 阶段整体状态 'init', 'running', 'finished', 'failed'
        self.every_agent_state = {agent_id: "idle" for agent_id in agent_allocation}  # 每个Agent的状态 'idle'

        # 完成情况
        self.completion_summary = {}  # Dict[<agent_id>, <completion_summary>] 阶段中每个Agent的完成情况总结

        # 阶段完成时的回调函数
        self.on_stage_complete = on_stage_complete

    def update_agent_state(self, agent_id: str, state: str):
        '''
        更新阶段中某个Agent的状态
        '''
        self.every_agent_state[agent_id] = state

    def update_agent_completion(self, agent_id: str, completion_summary: str):
        '''
        更新阶段中某个Agent的完成情况

        更新完成情况时会触发检查，如果发现此时所有Agent都已经提交了完成情况，则触发向管理Agent提交阶段完成情况的逻辑。
        '''
        self.completion_summary[agent_id] = completion_summary

        # 检查是否所有Agent都完成了,只要提交completion_summary就认为Agent已经结束了阶段目标
        all_agents = set(self.agent_allocation.keys())
        reported_completion = set(self.completion_summary.keys())

        if all_agents == reported_completion:
            # 触发向管理Agent提交阶段完成情况的逻辑
            if self.on_stage_complete:
                # 回调通知task_state
                self.on_stage_complete(self.stage_id, self.completion_summary, self.agent_allocation)







