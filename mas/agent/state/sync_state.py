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

from mas.agent.base.message import Message
import json

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

    def get_stage_state(self, task_id: str, stage_id: str) -> Optional[StageState]:
        '''
        获取指定任务阶段的状态
        '''
        task_state = self.get_task_state(task_id)
        if task_state:
            for stage in task_state.stage_list:
                if stage.stage_id == stage_id:
                    return stage
        return None

    # 开启任务中的一个阶段
    def start_stage(self, task_id: str, stage_id: str, sender_id: str):
        '''
        由SyncState负责开启任务中的一个阶段，使用message中包含相应指令来触发相应Agent去执行
        '''
        # 构造start_stage指令
        instruction = {"start_stage": {"stage_id": stage_id}}

        # 将指令消息发送给stage涉及到的每一个Agent
        task_state = self.all_tasks.get(task_id)
        stage_state = self.get_stage_state(task_id, stage_id)
        if stage_state:
            for agent_id in stage_state.agent_allocation.keys():
                # 构造包含start_stage指令的消息
                message:Message = {
                    "task_id": task_id,
                    "sender_id": sender_id,
                    "receiver": [agent_id],
                    "message": "<instruction>" + json.dumps(instruction) + "</instruction>",
                    "stage_relative": stage_id,
                    "need_reply": False,
                    "waiting": None,
                    "return_waiting_id": None
                }
                # 将消息添加到任务的通讯队列中
                task_state.communication_queue.put(message)

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


        # 如果字典的key是"task_instruction",则解析并执行具体任务管理操作
        if "task_instruction" in executor_output:
            task_instruction = executor_output["task_instruction"]

            # 创建任务 add_task
            if task_instruction["action"] == "add_task":
                '''
                {
                    "agent_id": "<agent_id>",  # 发起者Agent id
                    "action": "add_task",
                    "task_intention": "<task_intention>",
                }
                1.创建task_state
                2.同步工作记忆到任务管理者
                '''
                # 1. 实例化一个TaskState
                task_state = TaskState(
                    task_intention=task_instruction["task_intention"],
                    task_manager=task_instruction["agent_id"],
                    task_group=None,
                )
                # 添加到任务字典中
                self.add_task(task_state)
                # 2. 同步工作记忆到任务管理者
                instruction = {"update_working_memory":{"task_id": task_state.task_id, "stage_id": None}}
                message: Message = {
                    "task_id": task_state.task_id,
                    "sender_id": task_instruction["agent_id"],
                    "receiver": [task_instruction["agent_id"]],
                    "message": "<instruction>" + json.dumps(instruction) + "</instruction>",
                    "stage_relative": "no_relative",
                    "need_reply": False,
                    "waiting": None,
                    "return_waiting_id": None
                }
                # 将消息添加到任务的通讯队列中
                task_state.communication_queue.put(message)

                print(f"[SyncState] 已添加任务{task_state.task_id}，"
                      f"任务管理者{task_state.task_manager}")

            # 为任务创建阶段 add_stage
            if task_instruction["action"] == "add_stage":
                '''
                {
                    "agent_id": "<agent_id>",  # 发起者Agent id
                    "action": "add_stage",
                    "task_id": "<task_id>",  # 任务ID
                    "stages": [
                        {
                          "stage_intention": "<stage_intention>",  # 阶段意图, 较为详细的阶段目标说明
                          "agent_allocation": Dict[<agent_id>, <agent_stage_goal>],  # 阶段中Agent的分配情况，key为Agent ID，value为Agent在这个阶段职责的详细说明
                        },
                        ...
                    ] 
                }
                1.创建stage_state
                2.同步工作记忆到参与者
                '''
                # 获取任务id的task_state
                task_state = self.all_tasks.get(task_instruction["task_id"])
                # 遍历阶段列表
                for stage_info in task_instruction["stages"]:
                    # 1. 实例化一个StageState
                    stage_state = StageState(
                        task_id=task_instruction["task_id"],
                        stage_intention=stage_info["stage_intention"],
                        agent_allocation=stage_info["agent_allocation"],
                        execution_state="init",
                    )
                    # 添加阶段到任务状态中
                    task_state.add_stage(stage_state)

                    # 2. 同步工作记忆到任务参与者
                    instruction = {"update_working_memory": {"task_id": task_state.task_id, "stage_id": stage_state.stage_id}}
                    message: Message = {
                        "task_id": task_state.task_id,
                        "sender_id": task_instruction["agent_id"],
                        "receiver": [agent_id for agent_id in stage_info["agent_allocation"].keys()],
                        "message": "<instruction>" + json.dumps(instruction) + "</instruction>",
                        "stage_relative": "no_relative",
                        "need_reply": False,
                        "waiting": None,
                        "return_waiting_id": None
                    }
                    # 将消息添加到任务的通讯队列中
                    task_state.communication_queue.put(message)

                    print(f"[SyncState] 已添加阶段{stage_state.stage_id}，"
                          f"到任务{task_instruction["task_id"]}中")

            # TODO: 结束任务 finish_task
            if task_instruction["action"] == "finish_task":
                '''
                '''
                pass

            # 结束阶段 finish_stage
            if task_instruction["action"] == "finish_stage":
                '''
                {
                    "agent_id": "<agent_id>",  # 发起者Agent id
                    "action": "finish_stage",
                    "task_id": "<task_id>",  # 任务ID
                    "stage_id": "<stage_id>",  # 阶段ID
                }
                进入阶段结束流程，如果有下一个阶段，则sync_state需要负责开启下一个阶段
                '''
                # 结束当前阶段
                stage_state = self.get_stage_state(task_instruction["task_id"], task_instruction["stage_id"])
                if stage_state.execution_state is not "failed":
                    stage_state.execution_state = "finished"
                    print(f"[SyncState] 任务{task_instruction["task_id"]}的阶段{task_instruction["stage_id"]}已结束")
                # 如果还有下一个阶段，则开启下一个阶段
                task_state = self.all_tasks.get(task_instruction["task_id"])
                next_stage = task_state.get_current_or_next_stage()
                if next_stage:
                    next_stage.execution_state = "running"
                    self.start_stage(task_instruction["task_id"], next_stage.stage_id, task_instruction["agent_id"])
                    print(f"[SyncState] 任务{task_instruction["task_id"]}的阶段{next_stage.stage_id}已开启")
                else:
                    print(f"[SyncState] 任务{task_instruction["task_id"]}的所有阶段已结束")


