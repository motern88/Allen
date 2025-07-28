'''
在MAS中，sync_state状态同步器专门负责管理不属于单一Agent的状态，stage_state与task_state。
相对而言，Agent自身的局部状态，agent_state与step_state会在executor执行过程中更新。无需sync_state参与。

executor执行器返回的executor_output用于指导sync_state工作

具体实现：
    SyncState作为task_state与stage_state的管理类
    Agent在实例化时需要向SyncState注册，以方便SyncState可以获取到Agent的私有属性，例如agent_id、agent_state等
'''

from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union, TYPE_CHECKING
from mas.agent.state.task_state import TaskState
from mas.agent.state.stage_state import StageState

if TYPE_CHECKING:  # 避免循环导入和mas.py产生冲突
    from mas.mas import MultiAgentSystem
from mas.agent.configs.llm_config import LLMConfig
from mas.utils.message import Message
import json
import os
import yaml
from pathlib import Path
import weakref



class SyncState:
    '''
    SyncState类用于管理任务状态和阶段状态的同步。

    所有任务将被注册进 all_tasks 字典中（task_id -> TaskState）

    属性:
        all_tasks (Dict[str, TaskState]): 所有任务的状态信息，键为task_id
        _agents (List[weakref.ref]): 所有注册的Agent（用弱引用，防止Agent被强引用导致不能销毁）
        system (MultiAgentSystem): 对 MultiAgentSystem 的引用，用于访问系统级别的信息和方法
    '''
    def __init__(self, system: 'MultiAgentSystem'):
        self.all_tasks: Dict[str, TaskState] = {}  # 存储系统中所有任务状态，键为 task_id，值为对应的 TaskState 实例
        # 保存所有注册的 Agent（用弱引用，防止 Agent 被强引用导致不能销毁）
        self._agents = []
        # 保存对 MultiAgentSystem 的引用
        self.system = system

    def load_yaml_recursive(self, root_dir):
        """
        递归读取目录及其子目录下所有.yaml/.yml文件
        :param root_dir: 根目录路径(支持str或Path对象)
        :return: 生成器，产生 (file_path, data) 元组
        """
        root_path = Path(root_dir) if isinstance(root_dir, str) else root_dir

        if not root_path.is_dir():
            raise ValueError(f"路径不存在或不是目录: {root_path}")

        for file_path in root_path.rglob("*"):
            if file_path.suffix.lower() in ('.yaml', '.yml'):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = yaml.safe_load(f)
                        yield str(file_path), data
                except yaml.YAMLError as e:
                    print(f"[YAML解析错误] {file_path}: {e}")
                except UnicodeDecodeError:
                    print(f"[编码错误] 无法用UTF-8读取 {file_path}")
                except Exception as e:
                    print(f"[系统错误] 处理 {file_path} 时出错: {e}")

    def register_agent(self, agent):
        '''
        该方法和初始化时的self._agents是为了在SyncState中也能获取到所有注册的Agent的agent_state信息
        '''
        self._agents.append(weakref.ref(agent))  # 只保存弱引用

    def get_all_agents(self):
        '''
        返回所有活着的 Agent 实例
        '''
        return [ref() for ref in self._agents if ref() is not None]

    def get_private_attr(self, attr_name: str):
        """
        获取所有Agent的指定私有属性
        :param attr_name: 属性名，比如 'agent_state' 等
        :return: 返回一个列表，包含所有 Agent 的对应属性值
        """
        result = []
        for agent in self.get_all_agents():
            value = getattr(agent, attr_name, None)  # 获取私有属性
            result.append((agent, value))
        return result

    def init_new_agent(self, agent_config_dict):
        '''
        根据配置字典实例化新的Agent
        通过system引用将新Agent添加到system的agents_list中

        agent_config_dict 是一个包含 Agent 配置的字典，包含 name、role、profile 等信息。
        将agent_config_dict和LLM config合并，用于实例化AgentBase对象
        '''
        # 获取LLMconfig
        llm_config = LLMConfig.from_yaml("mas/role_config/default_llm_config.yaml")
        # 合并配置
        agent_config_dict["llm_config"] = llm_config
        # 实例化AgentBase对象
        self.system.add_agent(agent_config_dict)

    def add_task(self, task_state: TaskState):
        '''
        添加任务状态到SyncState任务字典中中
        '''
        # print(f"[Debug][SyncState] 添加任务 {task_state.task_id} 到 SyncState")
        self.all_tasks[task_state.task_id] = task_state

    def add_agents_2_task_group(self, task_id: str, agents: list[str]):
        '''
        将Agent添加到任务群组中
        如果Agent不在任务群组中，则添加到任务群组中
        '''
        task_state = self.all_tasks.get(task_id)
        if task_state:
            for agent_id in agents:
                if agent_id not in task_state.task_group:
                    task_state.task_group.append(agent_id)

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

    # 开启任务中的一个阶段(对Agent发送指令)
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
            # 构造包含start_stage指令的消息
            message:Message = {
                "task_id": task_id,
                "sender_id": sender_id,
                "receiver": [agent_id for agent_id in stage_state.agent_allocation.keys()],
                "message": "<instruction>" + json.dumps(instruction) + "</instruction>",
                "stage_relative": stage_id,
                "need_reply": False,
                "waiting": None,
                "return_waiting_id": None
            }
            # 将消息添加到任务的通讯队列中
            task_state.communication_queue.put(message)

    # 结束任务中的一个阶段(对Agent发送指令)
    def finish_stage(self, task_id: str, stage_id: str, sender_id: str):
        '''
        由SyncState负责结束任务中的一个阶段，使用message中包含相应指令来触发相应Agent去执行
        主要作用是清除Agent的工作记忆与相关agent_step
        '''
        # 构造start_stage指令
        instruction = {"finish_stage": {"stage_id": stage_id}}

        # 将指令消息发送给stage涉及到的每一个Agent
        task_state = self.all_tasks.get(task_id)
        stage_state = self.get_stage_state(task_id, stage_id)
        if stage_state:
            # 构造包含finish_stage指令的消息
            message: Message = {
                "task_id": task_id,
                "sender_id": sender_id,
                "receiver": [agent_id for agent_id in stage_state.agent_allocation.keys()],
                "message": "<instruction>" + json.dumps(instruction) + "</instruction>",
                "stage_relative": stage_id,
                "need_reply": False,
                "waiting": None,
                "return_waiting_id": None
            }
            # 将消息添加到任务的通讯队列中
            task_state.communication_queue.put(message)

    # 结束任务(对Agent发送指令)
    def finish_task(self, task_id: str, sender_id: str):
        '''
        由SyncState负责结束任务，使用message中包含相应指令来触发相应Agent去执行
        主要作用是清除Agent的工作记忆与相关agent_step
        '''
        # 构造finish_task指令
        instruction = {"finish_task": {"task_id": task_id}}

        # 将指令消息发送给stage涉及到的每一个Agent
        task_state = self.all_tasks.get(task_id)
        if task_state:
            # 构造包含finish_task指令的消息
            message: Message = {
                "task_id": task_id,
                "sender_id": sender_id,
                "receiver": [agent_id for agent_id in task_state.task_group],
                "message": "<instruction>" + json.dumps(instruction) + "</instruction>",
                "stage_relative": "no_relative",
                "need_reply": False,
                "waiting": None,
                "return_waiting_id": None
            }
            # 将消息添加到任务的通讯队列中
            task_state.communication_queue.put(message)

    # 任务完成判定
    def check_task_completion(self, task_id: str):
        '''
        由finish_stage是若不存在下一个阶段，则触发任务完成判定：
        使用消息通知管理Agent，要求其对任务完成情况进行判断（使用ask_info获取信息，使用task_manager进行任务交付或任务修正）
        '''
        task_state = self.all_tasks.get(task_id)

        # 构造任务完成判定的通知消息
        message: Message = {
            "task_id": task_id,
            "sender_id": "[TaskState系统通知]",
            "receiver": task_state.task_manager,
            "message": f"[TaskState] 已侦测到任务 {task_id} 下所有Stage均已完成。\n"
                       f"**现在你作为管理Agent需要对该任务完成情况进行判断，"
                       f"你需要通过ask_info技能主动获取该任务的详细信息进行任务完成判定。**\n"
                       f"- 如果任务完成情况满足预期，则使用task_manager技能的finish_task交付该任务\n"
                       f"- 如果任务完成情况不满足预期，则可以考虑使用task_manager技能的add_stage为该任务添加新的阶段，以弥补不满足预期的部分。\n",
            "stage_relative": "no_relative",
            "need_reply": False,
            "waiting": None,
            "return_waiting_id": None
        }
        # 将构造好的消息放入任务的通信队列中
        task_state.communication_queue.put(message)

    # 实现解析executor_output并更新task/stage状态
    def sync_state(self, executor_output: Dict[str, any]):
        '''
        解析执行器返回的输出结果 executor_output ，更新任务状态与阶段状态。
        一般情况下只有 任务管理Agent 会变更任务状态与阶段状态。
        普通Agent完成自己所处阶段的任务目标后会更新stage_state.every_agent_state中自己的状态
        '''
        # print(f"[Debug][executor_output] \n{executor_output}")
        # 如果字典的key是"update_stage_agent_state",则更新Agent在stage中的状态
        if "update_stage_agent_state" in executor_output:
            info = executor_output["update_stage_agent_state"]
            # 获取任务状态
            task_state = self.all_tasks.get(info["task_id"])
            # 获取对应阶段状态
            stage_state = task_state.get_stage(info["stage_id"])
            # 更新阶段中agent状态，如果不与任何阶段相关，则跳过
            if stage_state is not None:
                stage_state.update_agent_state(info["agent_id"], info["state"])
                print(f"[SyncState] 已更新 stage{info['stage_id']}"
                      f" 中 agent{info['agent_id']} 的状态为 {info['state']}")


        # 如果字典的key是"send_shared_info",则添加共享消息到任务共享消息池
        if "send_shared_info" in executor_output:
            info = executor_output["send_shared_info"]
            # 获取任务状态
            task_state = self.all_tasks.get(info["task_id"])
            # 将消息添加到共享消息池中
            task_state.add_shared_info(
                info["agent_id"],
                info["role"],
                info["stage_id"],
                info["content"]
            )
            print(f"[SyncState] 已更新任务{info['task_id']}的共享信息池，"
                    f"添加了来自 agent{info['agent_id']} 的消息")


        # 如果字典的key是"update_stage_agent_completion",则更新阶段中Agent完成情况
        if "update_stage_agent_completion" in executor_output:
            info = executor_output["update_stage_agent_completion"]
            # 获取任务状态
            task_state = self.all_tasks.get(info["task_id"])
            # 获取对应阶段状态
            stage_state = task_state.get_stage(info["stage_id"])
            # 更新阶段中agent完成情况
            stage_state.update_agent_completion(info["agent_id"], info["completion_summary"])
            print(f"[SyncState] 已更新 stage{info['stage_id']}"
                  f"中 agent{info['agent_id']} 的完成情况")


        # 如果字典的key是"send_message",则添加消息到任务通讯队列
        if "send_message" in executor_output:
            info = executor_output["send_message"]
            # 获取任务状态
            task_state = self.all_tasks.get(info["task_id"])
            # 将消息添加到任务的通讯队列中
            task_state.communication_queue.put(info)
            print(f"[SyncState] 已更新任务{info['task_id']}的通讯队列，"
                  f"添加了来自 agent{info['sender_id']} 的消息")


        # 如果字典的key是"task_instruction",则解析并执行具体任务管理操作
        if "task_instruction" in executor_output:
            task_instruction = executor_output["task_instruction"]

            # 1.创建任务 add_task
            if task_instruction["action"] == "add_task":
                '''
                {
                    "agent_id": "<agent_id>",  # 发起者Agent id
                    "action": "add_task",
                    "task_name": "<task_name>"
                    "task_intention": "<task_intention>",
                }
                1.创建task_state
                2.同步工作记忆到任务管理者
                '''
                # 1. 实例化一个TaskState
                task_state = TaskState(
                    task_name=task_instruction["task_name"],
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

            # 2.为任务创建阶段 add_stage
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
                2.如果stage中的agent不在task群组中，则添加到task群组中
                3.同步工作记忆到参与者
                '''
                # 获取任务id的task_state
                task_state = self.all_tasks.get(task_instruction["task_id"])
                if not task_state:
                    print(f"[SyncState][task_instruction] 任务ID：{task_instruction['task_id']}不正确无法添加任务阶段")
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

                    # 2. 如果stage中的agent不在task群组中，则添加到task群组中
                    for agent_id in stage_info["agent_allocation"].keys():
                        self.add_agents_2_task_group(task_instruction["task_id"],[agent_id])

                    # 3. 同步工作记忆到任务参与者
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
                          f"到任务{task_instruction['task_id']}中")

            # 3.结束任务 finish_task
            if task_instruction["action"] == "finish_task":
                '''
                {
                    "agent_id": "<agent_id>",  # 发起者Agent id
                    "action": "finish_stage",
                    "task_id": "<task_id>",  # 任务ID
                    "summary": "<task_summary>",  # 任务总结
                }
                进入任务结束流程，通知所有Agent任务结束（以message指令形式）
                '''
                task_state = self.all_tasks.get(task_instruction["task_id"])
                if task_state.execution_state != "failed":
                    task_state.update_task_execution_state("finished")
                # 更新任务总结信息
                task_state.task_summary = task_instruction.get("summary", "无总结信息")
                # 向Agent发送任务结束的指令
                self.finish_task(task_instruction["task_id"], task_instruction["agent_id"])
                print(f"[SyncState] 任务{task_instruction['task_id']}已结束")

            # 4.结束阶段 finish_stage
            if task_instruction["action"] == "finish_stage":
                '''
                {
                    "agent_id": "<agent_id>",  # 发起者Agent id
                    "action": "finish_stage",
                    "task_id": "<task_id>",  # 任务ID
                    "stage_id": "<stage_id>",  # 阶段ID
                }
                进入阶段结束流程，如果有下一个阶段，则sync_state需要负责开启下一个阶段
                如果结束的阶段是任务中最后一个阶段，则需要触发任务完成判定
                '''
                # 结束当前阶段
                stage_state = self.get_stage_state(task_instruction["task_id"], task_instruction["stage_id"])
                if stage_state.execution_state != "failed":
                    stage_state.execution_state = "finished"
                # 向Agent发送结束当前阶段的指令
                self.finish_stage(task_instruction["task_id"], task_instruction["stage_id"], task_instruction["agent_id"])
                print(f"[SyncState] 任务{task_instruction['task_id']}的阶段{task_instruction['stage_id']}已结束")

                # 查询下一个阶段
                task_state = self.all_tasks.get(task_instruction["task_id"])
                next_stage = task_state.get_current_or_next_stage()
                if next_stage:
                    # 如果还有下一个阶段，则开启下一个阶段
                    next_stage.execution_state = "running"
                    # 向Agent发送开启下一个阶段的指令
                    self.start_stage(task_instruction["task_id"], next_stage.stage_id, task_instruction["agent_id"])
                    print(f"[SyncState] 任务{task_instruction['task_id']}的阶段{next_stage.stage_id}已开启")
                else:
                    # 如果没有下一个阶段，则触发任务完成判定
                    self.check_task_completion(task_instruction["task_id"])
                    print(f"[SyncState] 任务{task_instruction['task_id']}的所有阶段已结束，触发任务完成判定...")

            # 5.重试阶段 retry_stage
            if task_instruction["action"] == "retry_stage":
                '''
                {
                    "action": "retry_stage",
                    "task_id": "<task_id>",  # 任务ID
                    "old_stage_id": "<stage_id>",  # 旧的执行失败的阶段ID
                    "new_stage_intention": "<new_stage_intention>",  # 新阶段意图, 较为详细的阶段目标说明
                    "new_agent_allocation": Dict[<agent_id>, <agent_stage_goal>],  # 新阶段中Agent的分配情况，key为Agent ID，value为Agent在这个阶段职责的详细说明
                }
                重试阶段 retry_stage 会创建一个新的相同目标的阶段去执行，达到重试的效果：
                1.插入新的阶段到任务状态中
                    1.1 实例化一个新的StageState
                    1.2 插入新的阶段状态到任务状态中
                    1.3 如果stage中的agent不在task群组中，则添加到task群组中
                    1.4 同步工作记忆到任务参与者
                2.将旧阶段的状态设置为"failed"
                    2.1 获取旧阶段状态并设置为"failed"
                    2.2 向Agent发送结束当前阶段的指令
                3.开启新的阶段
                '''
                # 获取任务id的task_state
                task_state = self.all_tasks.get(task_instruction["task_id"])

                # 1.插入新的阶段到任务状态中
                # 1.1 实例化一个新的StageState
                stage_state = StageState(
                    task_id=task_instruction["task_id"],
                    stage_intention=task_instruction["new_stage_intention"],
                    agent_allocation=task_instruction["new_agent_allocation"],
                    execution_state="init",
                )
                # 1.2 插入新的阶段状态到任务状态中
                task_state.add_next_stage(stage_state)
                # 1.3 如果stage中的agent不在task群组中，则添加到task群组中
                for agent_id in task_instruction["new_agent_allocation"].keys():
                    self.add_agents_2_task_group(task_instruction["task_id"], [agent_id])

                # 1.4 同步工作记忆到任务参与者
                instruction = {
                    "update_working_memory": {"task_id": task_state.task_id, "stage_id": stage_state.stage_id}}
                message: Message = {
                    "task_id": task_state.task_id,
                    "sender_id": task_instruction["agent_id"],
                    "receiver": [agent_id for agent_id in task_instruction["new_agent_allocation"].keys()],
                    "message": "<instruction>" + json.dumps(instruction) + "</instruction>",
                    "stage_relative": "no_relative",
                    "need_reply": False,
                    "waiting": None,
                    "return_waiting_id": None
                }
                # 将消息添加到任务的通讯队列中
                task_state.communication_queue.put(message)
                print(f"[SyncState] 已插入阶段{stage_state.stage_id}，"
                      f"到任务{task_instruction['task_id']}中")

                # 2.将旧阶段的状态设置为"failed"
                # 2.1 获取旧阶段状态并设置为"failed"
                old_stage_state = self.get_stage_state(task_instruction["task_id"], task_instruction["stage_id"])
                if old_stage_state:
                    old_stage_state.execution_state = "failed"
                # 2.2 向Agent发送结束当前阶段的指令
                self.finish_stage(task_instruction["task_id"], task_instruction["stage_id"],
                                  task_instruction["agent_id"])
                print(f"[SyncState] 任务{task_instruction['task_id']}的阶段{task_instruction['stage_id']}已结束")

                # 3.开启新的阶段
                next_stage = task_state.get_current_or_next_stage()
                if next_stage:
                    next_stage.execution_state = "running"
                    # 向Agent发送开启下一个阶段的指令
                    self.start_stage(task_instruction["task_id"], next_stage.stage_id, task_instruction["agent_id"])
                    print(f"[SyncState] 任务{task_instruction['task_id']}的阶段{next_stage.stage_id}已开启")


        # 如果字典的key是"agent_instruction",则解析并执行具体agent管理操作
        if "agent_instruction" in executor_output:
            agent_instruction = executor_output["agent_instruction"]

            # 实例化新Agent
            if agent_instruction["action"] == "init_new_agent":
                '''
                {
                    "action": "init_new_agent",
                    "agent_config": {  # 新Agent的配置信息
                        "name": "<agent_name>",  # 新Agent的名称
                        "role": "<agent_role>",  # 新Agent的角色
                        "profile": "<agent_profile>",  # 新Agent的简介
                        "skills": ["<skill_1>", "<skill_2>", ...],  # 新Agent的技能列表
                        "tools": ["<tool_1>", "<tool_2>", ...],  # 新Agent的工具列表
                    }
                }
                '''
                self.init_new_agent(agent_instruction["agent_config"])
                print(f"[SyncState] 已实例化新Agent{agent_instruction['agent_config']['name']}")

            # 为任务添加参与Agent
            if agent_instruction["action"] == "add_task_participant":
                '''
                {
                    "agent_id": "<agent_id>",  # 发起者Agent id
                    "action": "add_task_participant",
                    "task_id": "<task_id>",  # 任务ID
                    "agents": [
                        "<agent_id_1>", "<agent_id_2>" # 参与者Agent id
                    ]
                }
                '''
                self.add_agents_2_task_group(task_id=agent_instruction["task_id"], agents=agent_instruction["agents"])
                print(f"[SyncState] 已添加Agent{agent_instruction['agents']}于任务群组{agent_instruction['task_id']}中")


        # 如果字典的key是"ask_info",则解析并执行具体信息查询操作
        if "ask_info" in executor_output:
            ask_info = executor_output["ask_info"]
            return_ask_info_md = []  # 初始化用于生成markdown格式文本的列表， 限制md文本从三级标题开始！

            # 1 查询Agent管理的任务及其附属阶段信息（不包括任务共享消息池信息）
            if ask_info["type"] == "managed_task_and_stage_info":
                '''
                {
                    "type":"<不同查询选项>", 
                    "waiting_id":"<唯一等待标识ID>",
                    "sender_id":"<查询者的agent_id>"
                    "sender_task_id":"<查询者的task_id>"
                }
                '''
                # 遍历所有task_state
                for task_id, task_state in self.all_tasks.items():
                    # 如果自己是该task的管理者
                    if task_state.task_manager == ask_info["sender_id"]:
                        # 添加任务信息（除共享消息池的信息）
                        return_ask_info_md.append(f"### 任务信息 task info\n")
                        return_ask_info_md.append(f"任务ID：{task_state.task_id}\n"
                                                  f"任务名称：{task_state.task_name}\n"
                                                  f"任务意图：{task_state.task_intention}\n\n"
                                                  f"任务群组：{task_state.task_group}\n\n"
                                                  f"任务当前执行状态：{task_state.execution_state}\n\n"
                                                  f"任务完成后总结：{task_state.task_summary}\n")
                        # 遍历阶段信息
                        for stage_state in task_state.stage_list:
                            # 添加阶段信息
                            return_ask_info_md.append(f"#### 阶段信息 stage info\n")
                            return_ask_info_md.append(f"阶段ID：{stage_state.stage_id}\n"
                                                      f"阶段意图：{stage_state.stage_intention}\n\n"
                                                      f"阶段分配情况：{stage_state.agent_allocation}\n\n"
                                                      f"阶段执行状态：{stage_state.execution_state}\n\n"
                                                      f"阶段涉及的Agent状态：{stage_state.every_agent_state}\n\n"
                                                      f"阶段完成情况：{stage_state.completion_summary}\n\n")

            # 2 查询Agent参与的任务及参与的阶段的信息（不包括任务共享消息池信息）
            if ask_info["type"] == "assigned_task_and_stage_info":
                '''
                {
                    "type":"<不同查询选项>", 
                    "waiting_id":"<唯一等待标识ID>",
                    "sender_id":"<查询者的agent_id>"
                    "sender_task_id":"<查询者的task_id>"
                }
                '''
                # 遍历所有task_state
                for task_id, task_state in self.all_tasks.items():
                    # 如果自己是该task的参与者
                    if ask_info["sender_id"] in task_state.task_group:
                        # 添加任务信息（除共享消息池的信息）
                        return_ask_info_md.append(f"### 任务信息 task info\n")
                        return_ask_info_md.append(f"任务ID：{task_state.task_id}\n"
                                                  f"任务名称：{task_state.task_name}\n"
                                                  f"任务意图：{task_state.task_intention}\n\n"
                                                  f"任务群组：{task_state.task_group}\n\n"
                                                  f"任务当前执行状态：{task_state.execution_state}\n\n"
                                                  f"任务完成后总结：{task_state.task_summary}\n")
                        # 遍历阶段信息
                        for stage_state in task_state.stage_list:
                            # 如果自己是该阶段的参与者
                            if ask_info["sender_id"] in stage_state.agent_allocation.keys():
                                # 添加阶段信息
                                return_ask_info_md.append(f"#### 阶段信息 stage info\n")
                                return_ask_info_md.append(f"阶段ID：{stage_state.stage_id}\n"
                                                          f"阶段意图：{stage_state.stage_intention}\n\n"
                                                          f"阶段分配情况：{stage_state.agent_allocation}\n\n"
                                                          f"阶段执行状态：{stage_state.execution_state}\n\n"
                                                          f"阶段涉及的Agent状态：{stage_state.every_agent_state}\n\n"
                                                          f"阶段完成情况：{stage_state.completion_summary}\n\n")

            # 3 获取指定任务的详细信息（不包括附属阶段信息）
            if ask_info["type"] == "task_info":
                '''
                {
                    "type":"<不同查询选项>", 
                    "waiting_id":"<唯一等待标识ID>",
                    "sender_id":"<查询者的agent_id>"
                    "sender_task_id":"<查询者的task_id>"
                    "task_id": "<task_id>"  # 要查询的任务ID
                }
                '''
                # 获取指定task_state
                task_state = self.all_tasks.get(ask_info["task_id"], None)
                if task_state:
                    # 添加任务详细信息
                    return_ask_info_md.append(f"### 任务信息 task info\n")
                    return_ask_info_md.append(f"任务ID：{task_state.task_id}\n"
                                              f"任务名称：{task_state.task_name}\n"
                                              f"任务意图：{task_state.task_intention}\n\n"
                                              f"任务群组：{task_state.task_group}\n\n"
                                              f"任务当前执行状态：{task_state.execution_state}\n\n"
                                              f"任务完成后总结：{task_state.task_summary}\n")
                    return_ask_info_md.append(f"## 共享信息池中近20条信息 shared_info_pool info (用'---'分隔)\n")
                    # 遍历共享信息池
                    for dict in task_state.get_shared_info(20):  # 通过 get_shared_info 方法获取共享消息池中近20条信息
                        return_ask_info_md.append(f"---"
                                                  f"Agent ID：{dict['agent_id']}\n"
                                                  f"角色：{dict['role']}\n"
                                                  f"阶段ID：{dict['stage_id']}\n"
                                                  f"内容：{dict['content']}\n\n")

            # 4 获取指定阶段的详细信息
            if ask_info["type"] == "stage_info":
                '''
                {
                    "type":"<不同查询选项>", 
                    "waiting_id":"<唯一等待标识ID>",
                    "sender_id":"<查询者的agent_id>"
                    "sender_task_id":"<查询者的task_id>"
                    "task_id": "<task_id>",  # 要查询的任务ID
                    "stage_id": "<stage_id>"  # 要查询的阶段ID
                }
                '''
                # 获取指定stage_state
                stage_state = self.get_stage_state(ask_info["task_id"], ask_info["stage_id"])
                # 添加阶段信息
                return_ask_info_md.append(f"### 阶段信息 stage info\n")
                return_ask_info_md.append(f"阶段ID：{stage_state.stage_id}\n"
                                          f"阶段意图：{stage_state.stage_intention}\n\n"
                                          f"阶段分配情况：{stage_state.agent_allocation}\n\n"
                                          f"阶段执行状态：{stage_state.execution_state}\n\n"
                                          f"阶段涉及的Agent状态：{stage_state.every_agent_state}\n\n"
                                          f"阶段完成情况：{stage_state.completion_summary}\n\n")

            # 5 获取所有可实例化agent配置信息（包含已激活和未激活的）
            if ask_info["type"] == "available_agents_config":
                '''
                {
                    "type": "available_agents_config",
                    "waiting_id": "<唯一等待标识ID>",
                    "sender_id": "<查询者的agent_id>",
                    "sender_task_id": "<查询者的task_id>"
                }
                '''
                # 获取 role_config 目录的绝对路径，该目录位于当前文件的上两级目录中的 "role_config" 文件夹内
                role_config_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../role_config'))
                # 列出 role_config 目录中所有以 .yaml 结尾的文件名（即所有 Agent 配置文件）
                agent_files = [f for f in os.listdir(role_config_dir) if f.endswith('.yaml')]

                # 添加可直接新增Agent的配置信息
                return_ask_info_md.append(f"### 系统已有的可直接实例化的Agent配置 available_agents_config\n")
                return_ask_info_md.append(f"说明："
                                          f".yaml的Agent配置文件用于实例化新的Agent。"
                                          f"你可以参考这些Agent配置中不同角色的能力和人格特质。"
                                          f"(在实例化的时候请保证name名字不重复)\n")

                # 遍历所有配置文件
                for file_name in agent_files:
                    # 获取当前文件的完整路径
                    fpath = os.path.join(role_config_dir, file_name)
                    try:
                        # 打开该 YAML 文件并读取内容，使用 utf-8 编码
                        with open(fpath, 'r', encoding='utf-8') as f:
                            ydata = yaml.safe_load(f)
                            return_ask_info_md.append(f"#### Agent配置: {file_name}\n")
                            # 遍历需要展示的关键字段：
                            for key in ['name', 'role', 'profile', 'skills', 'tools']:
                                return_ask_info_md.append(f"{key}:\n"
                                                          f"{ydata[key]}\n\n")

                    except Exception as e:
                        return_ask_info_md.append(f"#### Agent配置: {file_name}\n"
                                                  f"(读取失败：{str(e)})\n\n")

            # 6 获取多智能体系统MAS中所有Agent的基本信息
            if ask_info["type"] == "all_agents":
                '''
                {
                    "type":"<不同查询选项>", 
                    "waiting_id":"<唯一等待标识ID>",
                    "sender_id":"<查询者的agent_id>"
                    "sender_task_id":"<查询者的task_id>"
                }
                '''
                return_ask_info_md.append(f"### 所有Agent的基本信息 all agents\n")

                # 获取所有Agent
                all_agents = self.get_all_agents()
                # 遍历所有Agent
                for agent in all_agents:
                    agent_state = getattr(agent, "agent_state", None)
                    if agent_state:
                        # 添加Agent的基本信息(不包含Agent持续性记忆)
                        return_ask_info_md.append(f"#### Agent信息\n")
                        return_ask_info_md.append(f"Agent ID：{agent_state['agent_id']}\n"
                                                  f"名字 name：{agent_state['name']}\n"
                                                  f"角色 role：{agent_state['role']}\n"
                                                  f"角色简介 profile：{agent_state['profile']}\n\n"
                                                  f"工作状态 working_state：{agent_state['working_state']}\n"
                                                  f"工作记忆 working_memory：{agent_state['working_memory']}\n\n"
                                                  f"可用技能 skills：{agent_state['skills']}\n"
                                                  f"可用工具 tools：{agent_state['tools']}\n\n")

            # 7 获取团队Team中所有Agent的基本信息, TODO：当前Team概念未实现
            if ask_info["type"] == "team_agents":
                '''
                {
                    "type":"<不同查询选项>", 
                    "waiting_id":"<唯一等待标识ID>",
                    "sender_id":"<查询者的agent_id>"
                    "sender_task_id":"<查询者的task_id>"
                    "team_id": "<team_id>"  # 要查询的团队ID
                }
                '''
                # raise NotImplementedError("Team概念未实现")
                return_ask_info_md.append(f"[Error] Team概念未实现，无法获取团队中Agent信息。\n")

            # 8 获取指定任务群组中所有Agent的信息
            if ask_info["type"] == "task_agents":
                '''
                {
                    "type":"<不同查询选项>", 
                    "waiting_id":"<唯一等待标识ID>",
                    "sender_id":"<查询者的agent_id>"
                    "sender_task_id":"<查询者的task_id>"
                    "task_id": "<task_id>"  # 要查询的任务ID
                }
                '''
                return_ask_info_md.append(f"### 任务群组中Agent信息 task agents\n")

                # 获取指定task_state
                task_state = self.all_tasks.get(ask_info["task_id"], None)
                if task_state:
                    for agent_id in task_state.task_group:
                        # 遍历所有Agents找到id符合的
                        for agents in self.get_all_agents():
                            if agents.agent_id == agent_id:
                                agent_state = getattr(agents, "agent_state", None)
                                if agent_state:
                                    # 添加Agent的基本信息(不包含Agent持续性记忆)
                                    return_ask_info_md.append(f"#### Agent信息\n")
                                    return_ask_info_md.append(f"Agent ID：{agent_state['agent_id']}\n"
                                                              f"名字 name：{agent_state['name']}\n"
                                                              f"角色 role：{agent_state['role']}\n"
                                                              f"角色简介 profile：{agent_state['profile']}\n\n"
                                                              f"工作状态 working_state：{agent_state['working_state']}\n"
                                                              f"工作记忆 working_memory：{agent_state['working_memory']}\n\n"
                                                              f"可用技能 skills：{agent_state['skills']}\n"
                                                              f"可用工具 tools：{agent_state['tools']}\n\n")

            # 9 获取指定阶段下协作的所有Agent的信息
            if ask_info["type"] == "stage_agents":
                '''
                {
                    "type":"<不同查询选项>", 
                    "waiting_id":"<唯一等待标识ID>",
                    "sender_id":"<查询者的agent_id>"
                    "sender_task_id":"<查询者的task_id>"
                    "task_id": "<task_id>",  # 要查询的任务ID
                    "stage_id": "<stage_id>"  # 要查询的阶段ID
                }
                '''
                return_ask_info_md.append(f"### 阶段中所有协作Agent信息 stage agents\n")
                # 获取指定stage_state
                stage_state = self.get_stage_state(ask_info["task_id"], ask_info["stage_id"])
                for agent_id in stage_state.agent_allocation.keys():
                    # 遍历所有Agents找到id符合的
                    for agents in self.get_all_agents():
                        if agents.agent_id == agent_id:
                            agent_state = getattr(agents, "agent_state", None)
                            if agent_state:
                                # 添加Agent的基本信息(不包含Agent持续性记忆)
                                return_ask_info_md.append(f"#### Agent信息\n")
                                return_ask_info_md.append(f"Agent ID：{agent_state['agent_id']}\n"
                                                          f"名字 name：{agent_state['name']}\n"
                                                          f"角色 role：{agent_state['role']}\n"
                                                          f"角色简介 profile：{agent_state['profile']}\n\n"
                                                          f"工作状态 working_state：{agent_state['working_state']}\n"
                                                          f"工作记忆 working_memory：{agent_state['working_memory']}\n\n"
                                                          f"可用技能 skills：{agent_state['skills']}\n"
                                                          f"可用工具 tools：{agent_state['tools']}\n\n")

            # 10 获取指定Agent的详细状态信息
            if ask_info["type"] == "agent":
                '''
                {
                    "type":"<不同查询选项>", 
                    "waiting_id":"<唯一等待标识ID>",
                    "sender_id":"<查询者的agent_id>"
                    "sender_task_id":"<查询者的task_id>"
                    "agent_id": [<agent_id>,<agent_id>,...]  # 包含Agent ID的列表 List[str]
                }
                '''
                for agent_id in ask_info["agent_id"]:
                    # 遍历所有Agents找到id符合的
                    for agents in self.get_all_agents():
                        if agents.agent_id == agent_id:
                            agent_state = getattr(agents, "agent_state", None)
                            if agent_state:
                                # 添加Agent的基本信息
                                return_ask_info_md.append(f"#### Agent信息\n")
                                return_ask_info_md.append(f"Agent ID：{agent_state['agent_id']}\n"
                                                          f"名字 name：{agent_state['name']}\n"
                                                          f"角色 role：{agent_state['role']}\n"
                                                          f"角色简介 profile：{agent_state['profile']}\n\n"
                                                          f"工作状态 working_state：{agent_state['working_state']}\n"
                                                          f"工作记忆 working_memory：{agent_state['working_memory']}\n\n"
                                                          f"可用技能 skills：{agent_state['skills']}\n"
                                                          f"可用工具 tools：{agent_state['tools']}\n\n")
                                return_ask_info_md.append(f"持续性记忆 persistent_memory：\n"
                                                          f"{agent_state['persistent_memory']}\n\n")

            # 11 获取MAS中所有技能与工具的详细说明
            if ask_info["type"] == "skills_and_tools":
                '''
                {
                    "type":"<不同查询选项>", 
                    "waiting_id":"<唯一等待标识ID>",
                    "sender_id":"<查询者的agent_id>"
                    "sender_task_id":"<查询者的task_id>"
                }
                '''
                # 添加技能与工具的详细说明
                return_ask_info_md.append(f"### 所有技能与工具的详细说明 skills and tools\n")

                # 遍历所有技能提示文件
                for file_path, yaml_data in self.load_yaml_recursive("mas/skills"):
                    skill_name = yaml_data["use_guide"]["skill_name"]
                    description = yaml_data["use_guide"]["description"]
                    skill_prompt = yaml_data["use_prompt"]["skill_prompt"]
                    return_format = yaml_data["use_prompt"]["return_format"]
                    return_ask_info_md.append(f"#### 技能 Skill: {skill_name}\n")
                    return_ask_info_md.append(
                        f"技能描述 description:\n"
                        f"{description}\n\n"
                        f"技能提示词 skill_prompt:\n"
                        f"{skill_prompt}\n\n"
                        f"返回格式 return_format:\n"
                        f"{return_format}\n\n"
                    )

                # TODO:需不需要支持获取MCPClient中缓存的具体能力调用参数说明？
                #     当前仅获取的是MCPServer启动配置中的粗略描述
                # 遍历所有工具提示文件
                for file_path, yaml_data in self.load_yaml_recursive("mas/tools/mcp_server_config"):
                    tool_name = yaml_data["use_guide"]["tool_name"]
                    description = yaml_data["use_guide"]["description"]
                    return_format = yaml_data["use_prompt"]["return_format"]
                    return_ask_info_md.append(f"#### 工具 Tool: {tool_name}\n")
                    return_ask_info_md.append(
                        f"MCP Server 工具描述 description:\n"
                        f"{description}\n\n"
                        f"返回格式 return_format:\n"
                        f"{return_format}\n\n"
                    )

            # 构造返回消息，消息内容为md格式的查询结果
            message: Message = {
                "task_id": ask_info["sender_task_id"],  # 发送者所处的任务
                "sender_id": ask_info["sender_id"],  # 发送者
                "receiver": [ask_info["sender_id"]],  # 接收者
                "message": "\n".join(return_ask_info_md),  # 返回md格式的查询结果
                "stage_relative": "no_relative",
                "need_reply": False,
                "waiting": None,
                "return_waiting_id": ask_info["waiting_id"]  # 返回唯一等待标识ID
            }
            # 获取任务id的task_state
            task_state = self.all_tasks.get(ask_info["sender_task_id"])
            # 将返回消息添加到任务的通讯队列中
            task_state.communication_queue.put(message)
            print(f"[SyncState] Agent{ask_info['sender_id']}的查询{ask_info['type']}，结果已返回")


        # 如果字典的key是"need_tool_decision"，则处理长尾工具，并为Agent添加tool_decision步骤
        if "need_tool_decision" in executor_output:
            info = executor_output["tool_execution"]
            task_id = info["task_id"]
            stage_id= info["stage_id"]
            agent_id = info["agent_id"]
            tool_name = info["tool_name"]

            # 获取任务状态
            task_state = self.all_tasks.get(task_id)
            if task_state:
                # 将工具执行结果作为消息发送给Agent，以方便Agent添加Tool Decision步骤
                tool_decision_instruction = {
                    "add_tool_decision": {
                        "task_id": task_id,
                        "stage_id": stage_id,
                        "tool_name": tool_name,
                    }
                }
                
                # 构造消息
                message: Message = {
                    "task_id": task_id,
                    "sender_id": agent_id,  # agent自身是该消息的发起方
                    "receiver": [agent_id],  # agent自身是该消息的接收方
                    "message": "<instruction>" + json.dumps(tool_decision_instruction) + "</instruction>",
                    "stage_relative": stage_id,
                    "need_reply": False,
                    "waiting": None,
                    "return_waiting_id": None
                }
                
                # 将消息添加到任务的通讯队列中
                task_state.communication_queue.put(message)
                print(f"[SyncState] 为长尾工具{tool_name}，添加Tool Decision步骤")
