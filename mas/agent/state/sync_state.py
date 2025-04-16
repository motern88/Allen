'''
在MAS中，sync_state状态同步器专门负责管理不属于单一Agent的状态，stage_state与task_state。
相对而言，Agent自身的局部状态，agent_state与step_state会在executor执行过程中更新。无需sync_state参与。

executor执行返回的executor_output用于指导sync_state工作

具体实现：
    SyncState作为task_state与stage_state的管理类
'''

from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union
from mas.agent.state.task_state import TaskState
from mas.agent.state.stage_state import StageState

class SyncState:
    '''
    SyncState类用于管理任务状态和阶段状态的同步。

    所有任务将被注册进 all_tasks 字典中（task_id -> TaskState）

    属性:
        all_tasks (Dict[str, TaskState]): 所有任务的状态信息，键为task_id
    '''
    def __init__(self):
        self.all_tasks: Dict[str, TaskState] = {}  # 存储系统中所有任务状态，键为 task_id，值为对应的 TaskState 实例

    def add_task(self, task_state: TaskState):
        '''
        添加任务状态到SyncState任务字典中中
        '''
        self.all_tasks[task_state.task_id] = task_state

    def get_task_state(self, task_id: str) -> Optional[TaskState]:
        '''
        获取指定任务的状态
        '''
        return self.all_tasks.get(task_id, None)

    # 实现解析executor_output并更新task/stage状态
    def sync_state(self, executor_output: Dict[str, any]):
        '''
        解析执行器返回的输出结果 executor_output ，更新任务状态与阶段状态。
        一般情况下只有 任务管理Agent 会变更任务状态与阶段状态。
        普通Agent完成自己所处阶段的任务目标后会更新stage_state.every_agent_state中自己的状态
        '''

        # 如果字典的key是"update_stage_agent_state",则更新Agent在stage中的状态
        if "update_stage_agent_state" in executor_output:
            info = executor_output["update_stage_agent_state"]
            # 获取任务状态
            task_state = self.all_tasks.get(info["task_id"])
            # 获取对应阶段状态
            stage_state = task_state.get_stage(info["stage_id"])
            # 更新阶段中agent状态
            stage_state.update_agent_state(info["agent_id"], info["state"])
            print(f"[SyncState] 已更新 stage{info["stage_id"]}"
                  f" 中 agent{info["agent_id"]} 的状态为 {info["state"]}")


        # 如果字典的key是"send_shared_message",则添加共享消息到任务共享消息池
        if "send_shared_message" in executor_output:
            info = executor_output["send_shared_message"]
            # 获取任务状态
            task_state = self.all_tasks.get(info["task_id"])
            # 将消息添加到共享消息池中
            task_state.add_shared_message(
                info["agent_id"],
                info["role"],
                info["stage_id"],
                info["content"]
            )
            print(f"[SyncState] 已更新任务{info["task_id"]}的共享消息池，"
                    f"添加了来自 agent{info["agent_id"]} 的消息")

        # 如果字典的key是"update_stage_agent_completion",则更新阶段中Agent完成情况
        if "update_stage_agent_completion" in executor_output:
            info = executor_output["update_stage_agent_completion"]
            # 获取任务状态
            task_state = self.all_tasks.get(info["task_id"])
            # 获取对应阶段状态
            stage_state = task_state.get_stage(info["stage_id"])
            # 更新阶段中agent完成情况
            stage_state.update_agent_cpmpletion(info["agent_id"], info["completion_summary"])
            print(f"[SyncState] 已更新 stage{info["stage_id"]}"
                  f"中 agent{info["agent_id"]} 的完成情况")

        # 如果字典的key是"send_message",则添加消息到任务通讯队列
        if "send_message" in executor_output:
            info = executor_output["send_message"]
            # 获取任务状态
            task_state = self.all_tasks.get(info["task_id"])
            # 将消息添加到任务的通讯队列中
            task_state.communication_queue.put(info)
            print(f"[SyncState] 已更新任务{info["task_id"]}的通讯队列，"
                  f"添加了来自 agent{info["sender"]} 的消息")


        # TODO: 如果字典的key是"add_task",则添加新任务,(未确定实现方式)
        if "add_task" in executor_output:
            info = executor_output["add_task"]
            # 创建新的任务状态
            new_task = TaskState(
                task_intention=info["task_intention"],
                task_group=info["task_group"]
            )
            # 将新任务添加到任务字典中
            self.add_task(new_task)
            print(f"[SyncState] 已添加新任务 {task_state.task_id} 到任务字典中")


        # TODO: 如果字典的key是"add_stage",则为任务添加新阶段,(未确定实现方式)
        if "add_stage" in executor_output:
            info = executor_output["add_stage"]
            # 获取任务状态
            task_state = self.all_tasks.get(info["task_id"])
            # 创建新阶段状态
            if task_state:
                stage_state = StageState(
                    task_id=info["task_id"],
                    stage_id=info["stage_id"],
                    stage_intention=info["stage_intention"],
                    agent_allocation=info["agent_allocation"]
                )
                # 将新阶段添加到任务状态中
                task_state.add_stage(stage_state)
                print(f"[SyncState] 已为任务{info["task_id"]}添加新阶段 {stage_state.stage_id}")

        # TODO: 如果字典的key是"update_task_state",则更新任务状态,(未确定实现方式)
        if "update_task_stage" in executor_output:
            info = executor_output["update_task_stage"]
            # 获取任务状态
            task_state = self.all_tasks.get(info["task_id"])
            # 更新任务状态
            if task_state:
                task_state.update_execution_state(info["execution_state"])
                print(f"[SyncState] 已更新任务{info["task_id"]}的状态为 {info["execution_state"]}")

        # TODO: 如果字典的key是"update_stage_state",则更新阶段状态,(未确定实现方式)
        if "update_stage_state" in executor_output:
            info = executor_output["update_stage_state"]
            # 获取任务状态
            task_state = self.all_tasks.get(info["task_id"])
            if task_state:
                # 获取对应阶段状态
                stage_state = task_state.get_stage(info["stage_id"])
                if stage_state:
                    # 更新阶段状态
                    stage_state.update_execution_state(info["execution_state"])
                    print(f"[SyncState] 已更新任务{info["task_id"]}的阶段{info["stage_id"]}的状态为 {info["execution_state"]}")
                