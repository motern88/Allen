'''
这里实现人类操作端 HumanAgent ，继承Agent基础类，拥有和LLM-Agent相同的构造与接口。
唯一的区别是人类操作端是由人类驱动而非LLM驱动。

HumanAgent即人类操作行为会被添加AgentStep来追踪。但实际不执行AgentStep:
其核心区别在于，LLM-Agent先添加AgentStep用于确定要执行什么操作，再具体执行该步骤。
Human-Agent人类操作员先实际执行操作，在添加AgentStep用于记录该操作


HumanAgent 的核心行为：
1. 参与MAS中通讯，接收与发送消息
    1.1 发起与维护会话组：
    1.2 接收到来自其他Agent的消息反馈展示给人类操作员：
        - 如果是系统消息，则加入到AgentState["conversation_pool"]["global_messages"]来展示
        - 如果是来自其他Agent的消息，则默认加入到AgentState["conversation_pool"]["conversation_privates"]中
            私聊对话组中只有Human-Agent和另一个Agent（可以是LLM-Agent或Human-Agent）


2. 执行操作，能够手动调用工具。同时会在AgentStep中记录工具执行调用结果（绑定在相应stage中）。

说明：
1. receive_message方法被覆写：
    HumanAgent的receive_message方法被覆写，其中收到来自其他Agent的消息均会添加到
    agent_state["conversation_pool"]["conversation_privates"]单独私聊对话中
    目前被动接听到的消息均会被作为私聊呼叫添加到一对一的私聊对话记录中(conversation_privates)
    注：这里的私聊对话记录按照AgentID和TaskID来区分，区分和谁的对话，同时也必须区分属于的任务

2. send_private_message方法实现：
    HumanAgent向其他Agent发送私聊消息，其中return_waiting_id字段由方法自动判定填充。
    消息默认记录在一对一的私聊对话记录中(conversation_privates)

3. send_group_message方法实现：
    HumanAgent向其他Agent发送群聊消息，其中return_waiting_id字段由传入时人为指定。
    消息默认同步在一对一的私聊对话记录中(conversation_privates)，

3. 对于群聊对话记录：
    我们不由HumanAgent维护群聊对话记录，我们将Task下所有的对话记录均收集在TaskState.shared_conversation_pool中，
    在人类操作端前端界面中从TaskState.shared_conversation_pool中筛选出特定聊天记录形成Task群组子集的聊天群组。


NEWS：
    目前HumanAgent已经实现关于通讯消息的：
    - 接收通知消息并添加到全局消息(global_messages)记录中
    - 接收消息并添加到私人对话(conversation_privates)记录中
    - 主动发起对多消息并一一添加到私人对话(conversation_privates)记录中

    未实现：

    - 各种工具在HumanAgent中的的直接手动操作

    TODO：需要注意或修复的特性
        因为Message中return_waiting_id只考虑返回单个唯一等待标识ID，
        因此Message无法面对同时回复多个Agent时区分每个Agent是否等待的情况，即当前反而无法实现一条消息回复多个Agent
        需要考虑将Message中的return_waiting_id改为List[str]类型，和receiver一一对应？这样就有一些地方需要改的
        (Date 25/07/08 :暂时不需要考虑这个问题)

'''


from mas.agent.base.agent_base import AgentBase
from mas.agent.state.step_state import StepState, AgentStep
from mas.agent.state.sync_state import SyncState
from mas.utils.async_loop import MCPClientWrapper
from mas.utils.monitor import StateMonitor

from mas.utils.message import Message

from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union
from datetime import datetime
import uuid

@StateMonitor.track  # 注册状态监控器，主要监控agent_state
class HumanAgent(AgentBase):
    '''
    人类操作端，继承AgentBase基础接口
    提供人类操作界面

    利用 agent_state["conversation_pool"] 来存储和管理人类操作端的对话消息,实时展示其中内容以呈现人类操作员的界面：
        - 将接收到的消息添加进 conversation_pool 中
        - 人类操作员主动发起的消息也添加进 conversation_pool 中
    其中：
        agent_state["conversation_pool"] = {
            "conversation_privates": {"agent_id":[<conversation_private>, ...]},  # Dict[str,List] 所有私聊对话组
            "global_messages": [str, ...],  # 全局消息, 用于提醒该人类操作员自己的信息
        }
    每个 <conversation_private> 是一个字典，代表一条与其他Agent的私聊对话信息：
        "agent_id": {
            "task_id" : [  # 私聊消息必须区分任务
                {
                    "sender_id": str,  # 发送者Agent ID
                    "content": str,  # 消息内容
                    "stage_relative": str,  # 如果消息与任务阶段相关，则填写对应阶段Stage ID，否则为"no_relative"
                    "timestamp": str,  # 消息发送时间戳
                    "need_reply": bool,  # 是否需要回复
                    "waiting": bool,  # 如果需要回复，发起方是否正在等待该消息回复
                    "return_waiting_id": Optional[str], # 如果发起方正在等待回复，那么需要返回的唯一等待标识ID
                },
                。。。
            ]
        }
    '''
    def __init__(
        self,
        config,  # HumanAgent人类操作端配置文件,接收已经从yaml解析后的字典
        sync_state: SyncState,  # 所有Agents接受同一个状态同步器(整个系统只维护一个SyncState，通过实例化传递给Agent)，由外部实例化后传给所有Agent
        mcp_client_wrapper: MCPClientWrapper,  # 所有Agents接收同一个MCP客户端(整个系统只维护一个MCPClient，通过实例化传递给Agent)，由外部实例化后传给所有Agent
        agent_id: Optional[str] = None,  # 可选的Agent ID，如果未提供则自动生成一个唯一ID
    ):
        if agent_id is not None:  # 如果提供了agent_id，则使用提供的ID
            self.agent_id = agent_id
        else:
            self.agent_id =  str(uuid.uuid4())  # 生成唯一ID

        self.sync_state = sync_state  # 状态同步器
        self.sync_state.register_agent(self)  # 向状态同步器注册自身，以便sync_state可以访问到自身的属性
        self.mcp_client_wrapper = mcp_client_wrapper  # MCP客户端，用于执行工具

        # 初始化人类操作端Agent状态
        self.agent_state = self.init_agent_state(
            agent_id = self.agent_id,
            name = config.get("name", ""),
            role = config.get("role", ""),
            profile = config.get("profile", ""),
            working_memory = config.get("working_memory", {}),  # 以任务视角的工作记忆
            tools = config.get("tools", []),  # Agent可用的工具
            skills = config.get("skills", []),  # Agent可用的技能
            human_config = config.get("human_config", None),  # 人类操作端账号信息
        )

    # Agent被实例化时需要初始化自己的 agent_state
    def init_agent_state(
        self,
        agent_id: str,  # agent_id
        name: str,  # Agent 名称
        role: str,  # Agent 角色
        profile: str,  # Agent 角色简介
        working_memory: Dict[str, Any] = None,  # 以任务视角的工作记忆
        tools: List[str] = None,
        skills: List[str] = None,
        human_config: Optional[Dict[str, Any]] = None,  # 人类操作端账号信息
    ):
        '''
        初始化Agent状态

        人类操作端的Agent状态：
        - agent_id: Agent的唯一标识符
        - name: Agent的名称
        - role: Agent的角色
        - profile: Agent的角色简介
        - working_state: Agent的当前工作状态（idle, working, waiting）
        - human_config: 人类操作端账号信息 （与AgentBase不同的是，这里人类操作端没有"llm_config"）
        - working_memory: 工作记忆，存储Agent在任务信息
        - persistent_memory: 永久追加精简记忆，用于记录Agent的持久性记忆
        - agent_step: 人类操作端不执行AgentStep
        - tools: 人类操作端可用的技能与工具库
        - skills: 人类操作端可用的技能与工具库
        - conversation_pool: 人类操作端的对话池，存储与其他Agent的对话
        '''
        agent_state = {}
        agent_state["agent_id"] = agent_id  # Agent的唯一标识符
        agent_state["name"] = name  # Agent的名称
        agent_state["role"] = role  # Agent的角色
        agent_state["profile"] = profile  # Agent的角色简介

        # idle 空闲, working 工作中, waiting 等待执行反馈中,
        agent_state["working_state"] = "idle"  # Agent的当前工作状态

        # 从配置文件中获取 人类操作员账号 信息
        agent_state["human_config"] = human_config

        # 工作记忆，存储Agent在任务中的临时信息
        agent_state["working_memory"] = working_memory if working_memory else {}

        # 永久追加精简记忆，用于记录Agent的持久性记忆，不会因为任务,阶段,步骤的结束而被清空  TODO：人类操作端需不需要持续性记忆？应该不需要
        agent_state["persistent_memory"] = {}  # Key为时间戳 %Y%m%dT%H%M%S ，值为md格式纯文本（里面只能用三级标题 ### 及以下！不允许出现一二级标题！）

        # 人类操作端不自动执行AgentStep，仅为了通过AgentStep来追踪人类操作员的操作步骤
        agent_state["agent_step"] = AgentStep(agent_id)

        # 人类操作端可用的技能与工具库
        agent_state["tools"] = tools if tools else []
        agent_state["skills"] = skills if skills else []

        # 人类操作端的对话池，存储与其他Agent的对话
        agent_state["conversation_pool"] = {
            "conversation_privates": {},  # Dict[str,Dict]  记录所有私聊对话组
            "global_messages": [],  # List[str] 用于通知人类操作员的全局重要消息
        }

        return agent_state

    # 上：初始化
    # ---------------------------------------------------------------------------------------------
    # 下：人类操作端消息输入输出接口

    # 人类操作端Agent的 receive_message 方法
    def receive_message(self, message):
        '''
        接收来自其他Agent的消息（该消息由MAS中的message_dispatcher转发），
        根据消息内容执行相应操作：
        - 如果消息需要回复，则提示人类操作员进行回复
            - 如果对方在等待该消息的回复，则提示人类操作员优先回复。并解析出对应的唯一等待ID，添加在返回消息内容中
        - 如果消息不需要回复，则直接处理消息内容

        message格式：
        {
            "task_id": task_id,
            "sender_id": "<sender_agent_id>",
            "receiver": ["<agent_id>", "<agent_id>", ...],
            "message": "<message_content>",  # 消息文本
            "stage_relative": "<stage_id或no_relative>",  # 表示是否与任务阶段相关，是则填对应阶段Stage ID，否则为no_relative的字符串
            "need_reply": <bool>,  # 需要回复则为True，否则为False
            "waiting": <list>,  # 如果发送者需要等待回复，则为所有发送对象填写唯一等待ID。不等待则为 None
            "return_waiting_id": <str>,  # 如果消息发送者需要等待回复，则返回消息时填写接收到的消息中包含的来自发送者的唯一等待ID
        }
        '''

        print(f"[DEBUG][HumanAgent]receive_message: {message}")

        # 1. 判断消息是否需要回复
        if message["need_reply"]:
            return_waiting_id = None
            # 2. 判断对方是否等待该消息的回复
            if message["waiting"] is not None:
                # 解析出自己对应的唯一等待ID
                return_waiting_id = message["waiting"][message["receiver"].index(self.agent_state["agent_id"])]

            # 将消息添加到 conversation_pool中私聊对话组中
            self.agent_state["conversation_pool"]["conversation_privates"].setdefault(message["sender_id"], {}).setdefault(message["task_id"], []).append(
                {
                    "sender_id": message["sender_id"],  # 发送者Agent ID
                    "content": message["message"],  # 消息内容
                    "stage_relative": message["stage_relative"],  # 如果消息与任务阶段相关，则填写对应阶段Stage ID，否则填写"no_relative"
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # 消息接收到的时间戳
                    "need_reply": True,  # 是否需要回复
                    "waiting": True if return_waiting_id else False,  # 如果需要回复，发起方是否正在等待该消息回复
                    "return_waiting_id": return_waiting_id,  # 如果发起方正在等待回复，那么唯一等待标识ID
                }
            )

            # 3. 提示人类操作员进行回复
            self.agent_state["conversation_pool"]["global_messages"].append(
                f"来自Agent[<agent_id>{message['sender_id']}</agent_id>]的消息需要您回复。"
            )

        else:
            # 进入到消息处理的分支，处理不需要回复的消息
            self.process_message(message)


    def process_message(self, message):
        '''
        对于不需要回复的消息，进入消息处理分支

        message格式：
        {
            "task_id": task_id,
            "sender_id": "<sender_agent_id>",
            "receiver": ["<agent_id>", "<agent_id>", ...],
            "message": "<message_content>",  # 消息文本
            "stage_relative": "<stage_id或no_relative>",  # 表示是否与任务阶段相关，是则填对应阶段Stage ID，否则为no_relative的字符串
            "need_reply": <bool>,  # 需要回复则为True，否则为False
            "waiting": <list>,  # 如果发送者需要等待回复，则为所有发送对象填写唯一等待ID。不等待则为 None
            "return_waiting_id": <str>,  # 如果消息发送者需要等待回复，则返回消息时填写接收到的消息中包含的来自发送者的唯一等待ID
        }

        1. 对于需要人类理解并消化的消息，添加到agent_state["conversation_pool"]["conversation_privates"]中
        2. 对于start_stage指令，提醒人类操作员
        3. 对于finish_stage指令，提醒人类操作员，并清除相应工作记忆
        4. 对于finish_task指令，提醒人类操作员，清除相应工作记忆
        5. 对于update_working_memory指令，更新Agent的工作记忆
        '''
        # 解析文本中的指令和非指令文本
        instruction, text = self.extract_instruction(message["message"])

        # 1. 对于需要人类理解并消化的消息，添加到 agent_state["conversation_pool"] 中
        if text:
            # 将消息添加到 conversation_pool中私聊对话组中
            self.agent_state["conversation_pool"]["conversation_privates"][message["sender_id"]][message["task_id"]].append(
                {
                    "sender_id": message["sender_id"],  # 发送者Agent ID
                    "content": text,  # 消息内容
                    "stage_relative": message["stage_relative"],
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # 消息接收到的时间戳
                    "need_reply": False,  # 是否需要回复
                    "waiting": False,  # 如果需要回复，发起方是否正在等待该消息回复
                    "return_waiting_id": None,  # 如果发起方正在等待回复，那么唯一等待标识ID
                }
            )

        # 2. 如果instruction字典包含start_stage的key,提醒人类
        if instruction and "start_stage" in instruction:
            # 指令内容 {"start_stage": {"stage_id": <stage_id> }}  # 由sync_state生成
            task_id = message["task_id"]
            stage_id = instruction["start_stage"]["stage_id"]
            # 提示人类操作员，现在已经开启某一个任务阶段
            self.agent_state["conversation_pool"]["global_messages"].append(
                f"任务[<task_id>{task_id}</task_id>]的阶段[<stage_id>{stage_id}</stage_id>]已开启，请查看相关信息参与协作。"
            )

        # 3. 如果instruction字典包含finish_stage的key,提醒人类,并清除该stage所有step且清除相应working_memory
        if instruction and "finish_stage" in instruction:
            # 指令内容 {"finish_stage": {"stage_id": <stage_id> }}  # 由sync_state生成
            task_id = message["task_id"]
            stage_id = instruction["finish_stage"]["stage_id"]
            # 提示人类操作员，现在已经结束某一个任务阶段
            self.agent_state["conversation_pool"]["global_messages"].append(
                f"任务[<task_id>{task_id}</task_id>]的阶段[<stage_id>{stage_id}</stage_id>]已结束。"
            )
            # 清除该stage的所有step
            self.agent_state["agent_step"].remove_step(stage_id=stage_id)
            # 清除相应的工作记忆
            if task_id in self.agent_state["working_memory"]:
                if stage_id in self.agent_state["working_memory"][task_id]:
                    del self.agent_state["working_memory"][task_id][stage_id]

        # 4. 如果instruction字典包含finish_task的key,提醒人类,并清除该task所有step且清除相应工作记忆
        if instruction and "finish_task" in instruction:
            '''
            1.清除step
            2.清除working_memory
            3.清除维护的该任务下的私聊记录
            '''
            # 指令内容 {"finish_task": {"task_id": <task_id> }}  # 由sync_state生成
            task_id = instruction["finish_task"]["task_id"]
            # 提示人类操作员，现在已经结束某一个任务
            self.agent_state["conversation_pool"]["global_messages"].append(
                f"任务[<task_id>{task_id}</task_id>]已结束。"
            )
            # 清除该task的所有step
            self.agent_state["agent_step"].remove_step(task_id=task_id)
            # 清除相应的工作记忆
            if task_id in self.agent_state["working_memory"]:
                del self.agent_state["working_memory"][task_id]
            # 清除私聊会话组中对应task的记录
            for agent_id in self.agent_state["conversation_pool"]["conversation_privates"].keys():
                if task_id in self.agent_state["conversation_pool"]["conversation_privates"][agent_id].keys():
                    del self.agent_state["conversation_pool"]["conversation_privates"][agent_id][task_id]


        # 5. 如果instruction字典包含update_working_memory的key,提醒人类,并更新Agent的工作记忆
        if instruction and "update_working_memory" in instruction:
            # 指令内容 {"update_working_memory": {"task_id": <task_id>, "stage_id": <stage_id>或None}}
            task_id = instruction["update_working_memory"]["task_id"]
            stage_id = instruction["update_working_memory"].get("stage_id", None)
            # 提醒人类操作员，更新被分配的任务
            if stage_id is None:
                self.agent_state["conversation_pool"]["global_messages"].append(
                    f"被分配任务情况更新：任务[<task_id>{task_id}</task_id>]。"
                )
            else:
                self.agent_state["conversation_pool"]["global_messages"].append(
                    f"被分配任务情况更新：任务[<task_id>{task_id}</task_id>]的阶段[<stage_id>{stage_id}</stage_id>]。"
                )
            # 更新工作记忆
            self.agent_state["working_memory"].setdefault(task_id, {}).setdefault(stage_id, [])


    # 人类操作端Agent在私聊中 send_message 方法, return_waiting_id由方法中自动判断并添加，无需传入
    def send_private_message(
        self,
        task_id: str,  # 任务ID
        receiver: List[str],  # 包含接收者Agent ID的列表
        context: str,  # 消息内容文本
        stage_relative: Optional[str] = None,  # 如果消息与任务阶段相关，则填写对应阶段Stage ID，否则为None
        need_reply: bool = True,  # 是否需要回复
        waiting: bool = True, # message中的步骤锁等待机制，但在Human-Agent中仅用作是否需要对方立即回复的功能，不用作步骤锁约束自身。如果是则True
    ):
        '''
        这是人类操作端发送私聊消息的方法，不是LLM-Agent的send_message技能

        1. 构造 message 消息格式
        2. 如果在 conversation_pool 的 conversation_privates 中发现该消息是回复上一条等待消息的，
            则追加 return_waiting_id 到构造好的 message 消息体中
        3. 将消息添加到 conversation_pool 中
        4. 构造execute_output将消息传递给 SyncState 进行后续分发
            注：如果人类向多个Agent发/回消息，其中只有一些Agent需要返回唯一等待ID，则不能使用SyncState进行群发，只能一条一条地单独发送。
            因为每一条消息在return_waiting_id中都是独一无二的
        5. 生成 AgentStep 来记录发送的消息操作

        '''
        # 如果需要等待，则为每个接收者生成一个唯一等待ID
        if waiting:
            waiting_ids = [str(uuid.uuid4()) for _ in receiver]
            # 与LLM-Agent的send_message中不同的是，这里Human-Agent没必要给自己上步骤锁
            # Human-Agent只是利用这个机制约束对方立即回复，而不用约束自己，自己不依赖步骤操作
        else:
            waiting_ids = None

        for receiver_id in receiver:
            # 1. 构造 message 消息格式
            message: Message = {
                "task_id": task_id,
                "sender_id": self.agent_state["agent_id"],
                "receiver": [receiver_id],  # 接收者Agent ID列表
                "message": context,  # 消息内容文本
                "stage_relative": stage_relative if stage_relative else "no_relative",  # 是否与任务阶段相关
                "need_reply": need_reply,  # 是否需要回复
                "waiting": waiting_ids,  # 如果发送者需要等待回复，则为所有发送对象填写唯一等待ID。不等待则为 None
            }

            # 2. 如果在 conversation_pool 的 conversation_privates 中发现该消息是回复上一条等待消息的，
            # 则追加 return_waiting_id 到构造好的 message 消息体中
            if self.agent_state["conversation_pool"]["conversation_privates"].get(receiver_id, []):
                # 获取最新的消息
                last_message = self.agent_state["conversation_pool"]["conversation_privates"][receiver_id][task_id][-1]
                # 如果最后一条消息是需要回复的，并且发起方正在等待该消息回复
                if last_message["need_reply"] and last_message["waiting"]:
                    # 追加 return_waiting_id 到构造好的 message 消息体中
                    message["return_waiting_id"] = last_message["return_waiting_id"]

            # 3. 将消息添加到 conversation_pool 中，如果没有则创建。
            if receiver_id not in self.agent_state["conversation_pool"]["conversation_privates"]:
                self.agent_state["conversation_pool"]["conversation_privates"][receiver_id][task_id] = []

            self.agent_state["conversation_pool"]["conversation_privates"][receiver_id][task_id].append(
                {
                    "sender_id": message["sender_id"],
                    "content": message["message"],
                    "stage_relative": message["stage_relative"],
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "need_reply": message["need_reply"],
                    "waiting": waiting_ids,
                    "return_waiting_id": message["return_waiting_id"],
                }
            )

            # 4. 将消息传递给 SyncState 进行后续分发
            execute_output = {}
            execute_output["send_message"] = message
            self.sync_state.sync_state(execute_output)

        if stage_relative == "no_relative":
            stage_id = None  # 如果没有阶段相关，则为None
        else:
            stage_id = stage_relative

        # 5. 生成 AgentStep 来记录发送的消息操作
        self.add_step(
            task_id=task_id,  # 任务ID
            step_intention="人类操作员发送消息",  # Step的目的
            type="skill",
            executor="send_message",  # Step的执行模块
            stage_id=stage_id,  # 阶段ID，如果没有则为None
            text_content="人类操作员发送消息",  # Step的文本内容
            instruction_content=None,  # Step的指令内容
            execute_result={"send_message":{
                "task_id": task_id,
                "sender_id": self.agent_state["agent_id"],
                "receiver": receiver,
                "message": context,
                "stage_relative": stage_relative if stage_relative else "no_relative",
                "need_reply": need_reply,
                "waiting": waiting_ids
            }},  # 这里记录发送的消息内容但是不包含return_waiting_id字段
        )

    # 人类操作端Agent在群聊中 send_message 方法, return_waiting_id由传入时指定
    def send_group_message(
        self,
        task_id: str,  # 任务ID
        receiver: List[str],  # 包含接收者Agent ID的列表
        context: str,  # 消息内容文本
        stage_relative: Optional[str] = None,  # 如果消息与任务阶段相关，则填写对应阶段Stage ID，否则为None
        need_reply: bool = True,  # 是否需要回复
        waiting: bool = True, # message中的步骤锁等待机制，但在Human-Agent中仅用作是否需要对方立即回复的功能，不用作步骤锁约束自身。如果是则True
        return_waiting_id: Optional[str] = None,  # 如果消息是回复上一条等待消息的，则填写对应的唯一等待ID，否则为None
    ):
        '''
        这是人类操作端发送群聊消息的方法，不是LLM-Agent的send_message技能

        1. 构造 message 消息格式
        2. 将消息添加到 conversation_pool 中
        3. 构造execute_output将消息传递给 SyncState 进行后续分发
            注：如果人类向多个Agent发/回消息，其中只有一些Agent需要返回唯一等待ID，则不能使用SyncState进行群发，只能一条一条地单独发送。
            因为每一条消息在return_waiting_id中都是独一无二的
        4. 生成 AgentStep 来记录发送的消息操作

        '''
        # 如果需要等待，则为每个接收者生成一个唯一等待ID
        if waiting:
            waiting_ids = [str(uuid.uuid4()) for _ in receiver]
            # 与LLM-Agent的send_message中不同的是，这里Human-Agent没必要给自己上步骤锁
            # Human-Agent只是利用这个机制约束对方立即回复，而不用约束自己，自己不依赖步骤操作
        else:
            waiting_ids = None

        for receiver_id in receiver:
            # 1. 构造 message 消息格式
            message: Message = {
                "task_id": task_id,
                "sender_id": self.agent_state["agent_id"],
                "receiver": [receiver_id],  # 接收者Agent ID列表
                "message": context,  # 消息内容文本
                "stage_relative": stage_relative if stage_relative else "no_relative",  # 是否与任务阶段相关
                "need_reply": need_reply,  # 是否需要回复
                "waiting": waiting_ids,  # 如果发送者需要等待回复，则为所有发送对象填写唯一等待ID。不等待则为 None
                "return_waiting_id": return_waiting_id,  # 如果消息发送者需要等待回复，则返回消息时填写接收到的消息中包含的来自发送者的唯一等待ID
            }

            # 2. 将消息添加到 conversation_pool 中，如果没有则创建。
            if receiver_id not in self.agent_state["conversation_pool"]["conversation_privates"]:
                self.agent_state["conversation_pool"]["conversation_privates"][receiver_id][task_id] = []

            self.agent_state["conversation_pool"]["conversation_privates"][receiver_id][task_id].append(
                {
                    "sender_id": message["sender_id"],
                    "content": message["message"],
                    "stage_relative": message["stage_relative"],
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "need_reply": message["need_reply"],
                    "waiting": waiting_ids,
                    "return_waiting_id": message["return_waiting_id"],
                }
            )

            # 3. 将消息传递给 SyncState 进行后续分发
            execute_output = {}
            execute_output["send_message"] = message
            self.sync_state.sync_state(execute_output)

        if stage_relative == "no_relative":
            stage_id = None  # 如果没有阶段相关，则为None
        else:
            stage_id = stage_relative

        # 4. 生成 AgentStep 来记录发送的消息操作
        self.add_step(
            task_id=task_id,  # 任务ID
            step_intention="人类操作员发送消息",  # Step的目的
            type="skill",
            executor="send_message",  # Step的执行模块
            stage_id=stage_id,  # 阶段ID，如果没有则为None
            text_content="人类操作员发送消息",  # Step的文本内容
            instruction_content=None,  # Step的指令内容
            execute_result={"send_message":{
                "task_id": task_id,
                "sender_id": self.agent_state["agent_id"],
                "receiver": receiver,
                "message": context,
                "stage_relative": stage_relative if stage_relative else "no_relative",
                "need_reply": need_reply,
                "waiting": waiting_ids
            }},  # 这里记录发送的消息内容但是不包含return_waiting_id字段
        )


    # 上：人类操作端消息输入输出接口
    # ---------------------------------------------------------------------------------------------
    # 下：人类操作端其他工具方法


    # 添加一个已经完成的用于记录的步骤到AgentStep中
    def add_step(
        self,
        task_id: str,  # 任务ID
        step_intention: str,  # Step的目的
        type: str,  # Step的类型 'skill', 'tool'
        executor: str,  # Step的执行模块
        stage_id: Optional[str] = None,  # 阶段ID，如果没有则为None
        text_content: Optional[str] = None,  # Step的文本内容
        instruction_content: Optional[Dict[str, Any]] = None,  # Step的指令内容
        execute_result: Optional[Dict[str, Any]] = None,  # Step的执行结果
    ):
        # 构造一个完整的StepState
        step_state = StepState(
            task_id=task_id,
            stage_id=stage_id,
            agent_id=self.agent_state["agent_id"],
            step_intention=step_intention,
            type=type,
            executor=executor,
            execution_state="finished",  # 人类操作记录的step均为 'finished' 状态
            text_content=text_content,  # Optional[str]
            instruction_content=instruction_content,  # Optional[Dict[str, Any]]
            execute_result=execute_result,  # Optional[Dict[str, Any]]
        )
        # 添加到agent_state["agent_step"]中
        self.agent_state["agent_step"].add_step(step_state)
        # 返回添加的step_id, 记录在工作记忆中
        if not stage_id: # 如果没有阶段ID，则使用默认的"no_stage",保证能够正常添加工作记忆
            stage_id = "no_stage"
        # 使用setdefault级联初始化，如果不存在字段则自动创建
        self.agent_state["working_memory"].setdefault(task_id, {}).setdefault(stage_id, []).append(step_state.step_id)






