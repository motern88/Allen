'''
Agent基础类，这里实现关于LLM驱动的相关基础功能，不涉及到任何具体Agent_state
'''


from mas.agent.state.step_state import StepState, AgentStep
from mas.agent.state.stage_state import StageState
from mas.agent.state.sync_state import SyncState
from mas.agent.base.router import Router
from mas.utils.monitor import StateMonitor

from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union
import threading
import time
import re
import json
import uuid

@StateMonitor.track  # 注册状态监控器，主要监控agent_state
class AgentBase():
    '''
    基础Agent类，定义各基础模块的流转逻辑

    整体分为两个部分，执行线程和任务分发线程
    - 执行线程（在Agent实例化时就启动）
        action方法只负责不断地执行执行每一个step，有新的step就执行新的step。
        action方法执行step时不会区分是否与当前stage相关，只要在agent_step.todo_list中就会执行。
        执行线程保证了Agent生命的自主性与持续性。
    - 任务管理（被动触发）
        任务管理用于管理任务进度，保证Agent的可控性。所有的任务管理都通过消息传递，Agent会使用receive_message接收。
        receive_message方法：
            Agent接收和处理来自其他Agent的不可预知的消息，提供了Agent之间主动相互干预的能力。
            该方法最终会根据是否需要回复消息走入两个不同的分支，process message分支和send message分支

    process_message方法:
        根据解析出的指令的不同进入不同方法
        start_stage方法:
            当一个任务阶段的所有step都执行完毕后，帮助Agent建立下一个任务阶段的第一个step: planning_step。
        finish_stage方法:
            当一个任务阶段的所有step都执行完毕后，执行清除该stage的所有step并且清除相应working_memory。
        finish_task方法:
            当一个任务的所有阶段都执行完毕后，执行清除该task的所有step并且清除相应working_memory。
        update_working_memory方法:
            Agent被分配到新的任务/阶段中时，更新Agent的工作记忆。

    '''
    def __init__(
        self,
        config,  # Agent配置文件,接收已经从yaml解析后的字典
        sync_state: SyncState,  # 所有Agents接受同一个状态同步器(整个系统只维护一个SyncState，通过实例化传递给Agent)，由外部实例化后传给所有Agent
    ):
        self.agent_id =  str(uuid.uuid4())# 生成唯一ID
        self.router = Router()  # 在action中用于分发具体executor的路由器，用于同步stage_state与task_state

        self.sync_state = sync_state  # 状态同步器
        self.sync_state.register_agent(self)  # 向状态同步器注册自身，以便sync_state可以访问到自身的属性

        # 初始化Agent状态
        self.agent_state = self.init_agent_state(
            agent_id = self.agent_id,
            name = config.get("name",""),
            role = config.get("role",""),
            profile = config.get("profile",""),
            working_memory = config.get("working_memory",{}),  # 以任务视角的工作记忆
            tools = config.get("tools",[]),  # Agent可用的工具
            skills = config.get("skills",[]),  # Agent可用的技能
            llm_config = config.get("llm_config",{}),  # LLM配置
        )

        # 初始化线程锁
        self.agent_state_lock = threading.Lock()  # TODO：使用统一AgentState全局锁，还是细分为分区锁？

        # 启动Agent的执行线程
        self.action_thread = threading.Thread(target=self.action)
        self.action_thread.daemon = True  # 设置为守护线程，主线程退出时自动退出
        self.action_thread.start()  # 启动执行线程


    # Agent被实例化时需要初始化自己的 agent_state, agent_state 会被持续维护用于记录Agent的基本信息、状态与记忆。
    # 不同的Agent唯一的区别就是 agent_state 的区别
    def init_agent_state(
        self,
        agent_id: str,  # agent_id
        name: str,  # Agent 名称
        role: str,  # Agent 角色
        profile: str,  # Agent 角色简介
        working_memory: Dict[str, Any] = None,  # 以任务视角的工作记忆
        tools: List[str] = None,
        skills: List[str] = None,
        llm_config: Dict[str, Any] = None,
    ):
        '''
        初始化Agent状态

        agent_state 是 Agent的重要承载体，它包含了一个Agent的所有状态信息
        所有Agent使用相同的类，具有相同的方法属性，相同的代码构造。
        不同Agent的区别仅有 `Agent State` 的不同，可以通过 `Agent State` 还原出一样的Agent 。
        '''
        agent_state = {}
        agent_state["agent_id"] = agent_id  # Agent的唯一标识符
        agent_state["name"] = name  # Agent的名称
        agent_state["role"] = role  # Agent的角色
        agent_state["profile"] = profile  # Agent的角色简介

        # idle 空闲, working 工作中, waiting 等待执行反馈中,
        agent_state["working_state"] = "idle"  # Agent的当前工作状态

        # 从配置文件中获取 LLM 配置
        agent_state["llm_config"] = llm_config

        # Agent工作记忆
        # Agent工作记忆 {<task_id>: {<stage_id>: [<step_id>,...],...},...} 记录Agent还未完成的属于自己的任务
        # Agent工作记忆以任务视角，包含多个task，每个task多个stage，每个stage多个step
        #
        # 工作记忆step的增加通过AgentBase.add_step或executor_base.add_step
        # 工作记忆stage和task的增加通过sync_state生成增加指令，由AgentBase.receive_message的process_message分支增加
        # 注意：工作记忆不要放到提示词里面，提示词里面放持续性记忆
        agent_state["working_memory"] = working_memory if working_memory else {}

        # 永久追加精简记忆，用于记录Agent的持久性记忆，不会因为任务,阶段,步骤的结束而被清空
        agent_state["persistent_memory"] = ""  # md格式纯文本，里面只能用三级标题 ### 及以下！不允许出现一二级标题！
        # TODO：实现持久性记忆的清除，(目前已实现持久性记忆的追加)

        # 初始化AgentStep,用于管理Agent的执行步骤列表
        # （一般情况下步骤中只包含当前任务当前阶段的步骤，在下一个阶段时，
        # 上一个阶段的step_state会被同步到stage_state中，不会在列表中留存）
        agent_state["agent_step"] = AgentStep(agent_id)

        # 步骤锁，由多个唯一ID组成的列表。只有当列表为空，所有的通信唯一等待ID都被回收时，才能取消步骤锁
        agent_state["step_lock"] = []  # 步骤锁，在通信机制中，如果需要等待消息回复则用过步骤锁暂停step的执行

        # Agent可用的技能与工具库
        agent_state["tools"] = tools if tools else []
        agent_state["skills"] = skills if skills else []

        return agent_state

    # 上：初始化
    # ---------------------------------------------------------------------------------------------
    # 下：Agent的执行逻辑

    def step_action(
        self,
        step_id,
        step_type,
        step_executor,
    ):
        '''
        执行单个step_state的具体Action

        Agent和Step状态更新说明:
            step_action开始时更新Agent状态为 working，结束时更新Agent状态为 idle
            step执行状态的更新在step_action中开始时，结束状态的更新于executor.execute中结束时。

        1. 根据Step的executor执行具体的Action，由路由器分发执行器
        2. 执行器执行
        3. 更新Step的执行状态
        '''
        # 更新Agent状态为工作中 working
        self.agent_state["working_state"] = "working"
        # 更新step状态为执行中 running
        self.agent_state["agent_step"].update_step_status(step_id, "running")

        # 1. 根据Step的executor执行具体的Action，由路由器分发执行
        # 接收一个type和executor的str，返回一个具体执行器
        executor = self.router.get_executor(type=step_type, executor=step_executor)

        # 2. 执行路由器返回的执行器
        with self.agent_state_lock:  # 防止任务分配线程与任务执行线程同时修改agent_state，这里优先保证任务执行线程的修改
            executor_output = executor.execute(step_id=step_id, agent_state=self.agent_state)  # 部分执行器需要具备操作agent本身的能力

        # 3. 使用sync_state专门同步stage_state与task_state
        self.sync_state.sync_state(executor_output)  # 根据executor_output更新stage,task相应状态

        # 4. 更新Agent状态为空闲 idle
        self.agent_state["working_state"] = "idle"

    def action(self):
        """
        不断从 agent_step.todo_list 获取 step_id 并执行 step_action
        agent_step.todo_list 是一个deque()支持双向插入的队列，用于存放待执行的 step_id
        对 todo_list.popleft() 到的每个step执行step_action()
        """
        agent_step = self.agent_state["agent_step"]

        while True:
            if len(self.agent_state["step_lock"]) > 0:
                # 如果有步骤锁，则等待
                self.agent_state["working_state"] = "waiting"
                time.sleep(1)
                continue

            # 1. 从agent_state.todo_list获取step_id
            if agent_step.todo_list:
                # 如果队列不为空，则获取第一个step_id
                step_id = agent_step.todo_list.popleft()
            else:
                time.sleep(1)  # 队列为空时等待，避免 CPU 空转
                continue

            # 2. 根据step_id获取step_state
            step_state = agent_step.get_step(step_id)[0]
            step_type = step_state.step_type
            step_executor = step_state.executor

            # 3. 执行step_action
            self.step_action(step_id, step_type, step_executor)

            # print("打印所有step_state:")
            # agent_step.print_all_steps()  # 打印所有step_state

    # 上：Agent的执行逻辑
    # ---------------------------------------------------------------------------------------------
    # 下：Agent的任务逻辑

    def receive_message(self, message):
        '''
        接收来自其他Agent的消息（该消息由MAS中的message_dispatcher转发），
        根据消息内容添加不同的step：
        - 如果需要回复则添加send_message step
            - 如果对方在等待该消息的回复，则解析出对应的唯一等待ID，添加在消息内容中
        - 如果不需要回复则考虑执行消息中的指令或添加process_message step

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
        # 1. 判断消息是否需要回复
        if message["need_reply"]:

            # 2. 判断对方是否等待该消息的回复
            if message["waiting"] is not None:
                # 解析出自己对应的唯一等待ID
                return_waiting_id = message["waiting"][message["receiver"].index(self.agent_state["agent_id"])]

                # 进入到回复消息的分支，为AgentStep插队添加send_message step用于回复。
                self.add_next_step(
                    task_id=message["task_id"],
                    stage_id=message["stage_relative"],  # 可能是no_relative 与阶段无关
                    step_intention=f"回复来自Agent {message['sender_id']}的消息，**消息内容见当前步骤的text_content**",
                    step_type="skill",
                    executor="send_message",
                    text_content=message["message"] + f"\n\n<return_waiting_id>{return_waiting_id}</return_waiting_id>"  # 将消息内容和回应等待ID一起填充
                )

            else:
                # 进入到回复消息的分支，为AgentStep添加send_message step用于回复。
                self.add_step(
                    task_id = message["task_id"],
                    stage_id = message["stage_relative"],  # 可能是no_relative 与阶段无关
                    step_intention = f"回复来自Agent {message['sender_id']}的消息，**消息内容见当前步骤的text_content**",
                    step_type = "skill",
                    executor = "send_message",
                    text_content = message["message"]
                )

        else:
            # 进入到消息处理的分支，处理不需要回复的消息
            self.process_message(message)

        # 3. 尝试获取消息中的return_waiting_id，回收步骤锁
        if message["return_waiting_id"] is not None:
            # 回收步骤锁
            self.agent_state["step_lock"].remove(message["return_waiting_id"])


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

        1. 对于需要LLM理解并消化的消息，添加process_message step
        2. 对于start_stage指令，执行start_stage
        3. 对于finish_stage指令，清除该stage的所有step，和相应工作记忆
        4. 对于finish_task指令，清除该task所有step，和相应工作记忆
        5. 对于update_working_memory指令，更新Agent的工作记忆
        6. 对于add_tool_decision指令，插入追加tool_decision

        '''
        # 解析文本中的指令和非指令文本
        instruction, text = self.extract_instruction(message["message"])

        # 1. 对于需要LLM理解并消化的消息，添加process_message step
        if text:
            if message["return_waiting_id"] is not None:
                # 说明自己用步骤锁在等待该消息的回复，则插队添加处理该消息的步骤
                self.add_next_step(
                    task_id=message["task_id"],
                    stage_id=message["stage_relative"],  # 可能是no_relative 与阶段无关
                    step_intention=f"处理来自Agent {message['sender_id']}的消息，**消息内容见当前步骤的text_content**。"
                                   f"你需要理解并消化该消息的内容，必要的时候需要将重要信息记录在你的persistent_memory中",
                    step_type="skill",
                    executor="process_message",
                    text_content=message["message"]
                )
            else:
                # 为AgentStep添加process_message step用于处理消息。
                self.add_step(
                    task_id=message["task_id"],
                    stage_id=message["stage_relative"],  # 可能是no_relative 与阶段无关
                    step_intention=f"处理来自Agent {message['sender_id']}的消息，**消息内容见当前步骤的text_content**。"
                                   f"你需要理解并消化该消息的内容，必要的时候需要将重要信息记录在你的persistent_memory中",
                    step_type="skill",
                    executor="process_message",
                    text_content=message["message"]
                )



        # 2. 如果instruction字典包含start_stage的key,则执行start_stage
        if instruction and "start_stage" in instruction:
            # 指令内容 {"start_stage": {"stage_id": <stage_id> }}  # 由sync_state生成
            task_id = message["task_id"]
            stage_id = instruction["start_stage"]["stage_id"]
            self.start_stage(task_id=task_id, stage_id=stage_id)

        # 3. 如果instruction字典包含finish_stage的key,则执行清除该stage的所有step并且清除相应working_memory
        if instruction and "finish_stage" in instruction:
            # 指令内容 {"finish_stage": {"stage_id": <stage_id> }}  # 由sync_state生成
            task_id = message["task_id"]
            stage_id = instruction["finish_stage"]["stage_id"]
            # 清除该stage的所有step
            self.agent_state["agent_step"].remove_step(stage_id=stage_id)
            # 清除相应的工作记忆
            if task_id in self.agent_state["working_memory"]:
                if stage_id in self.agent_state["working_memory"][task_id]:
                    del self.agent_state["working_memory"][task_id][stage_id]

        # 4. 如果instruction字典包含finish_task的key,则执行清除该task的所有step并且清除相应working_memory
        if instruction and "finish_task" in instruction:
            # 指令内容 {"finish_task": {"task_id": <task_id> }}  # 由sync_state生成
            task_id = instruction["finish_task"]["task_id"]
            # 清除该task的所有step
            self.agent_state["agent_step"].remove_step(task_id=task_id)
            # 清除相应的工作记忆
            if task_id in self.agent_state["working_memory"]:
                del self.agent_state["working_memory"][task_id]

        # 5. 如果instruction字典包含update_working_memory的key,则更新Agent的工作记忆
        if instruction and "update_working_memory" in instruction:
            # 指令内容 {"update_working_memory": {"task_id": <task_id>, "stage_id": <stage_id>或None}}
            task_id = instruction["update_working_memory"]["task_id"]
            stage_id = instruction["update_working_memory"]["stage_id"]
            self.agent_state["working_memory"][task_id] = stage_id
        
        # 6. 如果instruction字典包含add_tool_decision的key,则添加一个Tool Decision步骤
        if instruction and "add_tool_decision" in instruction:
            # 指令内容 {"add_tool_decision": {"task_id": <task_id>, "stage_id": <stage_id>,"tool_name": <tool_name>}}
            task_id = instruction["add_tool_decision"]["task_id"]
            stage_id = instruction["add_tool_decision"]["stage_id"]
            tool_name = instruction["add_tool_decision"]["tool_name"]
            
            # 准备工具决策步骤的意图描述
            step_intention = (f"决定长尾工具{tool_name}下一步的执行方向或终止执行。")
            text_content = (f"该工具{tool_name}返回结果需要向LLM确认，并反复多次调用该工具(这种情况为工具的长尾调用)\n"
                            f"现在需要处理长尾工具返回的结果并决定下一次工具调用的方向或停止继续调用工具，因此你正在使用该技能ToolDecision。\n"
                            f"长尾工具以指令生成开始，以工具决策结尾。这一系列步骤示意如下：\n"
                            f"([InstructionGeneration] -> [Tool]) -> [ToolDecision] -> ([InstructionGeneration] -> [Tool]) -> [ToolDecision] -> ...\n"
                            f"\n"
                            f"<tool_name>{tool_name}</tool_name>")

            # 添加Tool Decision步骤
            self.add_next_step(
                task_id=task_id,
                stage_id=stage_id,
                step_intention=step_intention,
                step_type="skill",
                executor="tool_decision",
                text_content=text_content  # text_content中包含 <tool_name></tool_name> 包裹的工具名称，用于指示技能执行时获取哪些工具历史结果
            )
            
            print(f"[AgentBase] 已为长尾工具 {tool_name} 添加Tool Decision步骤")



    def start_stage(
        self,
        task_id: str,
        stage_id: str,
    ):
        '''
        用于开始一个任务阶段:一个stage的第一个step必定是planning方法

        1. 构造Agent规划当前阶段的提示词
        2. 如果当前stage没有任何step，则增加一个规划step
        '''

        stage_state = self.sync_state.get_stage_state(task_id=task_id, stage_id=stage_id)
        # Agent从当前StageState来获取信息明确目标
        agent_id = self.agent_state["agent_id"]
        task_id = stage_state.task_id
        stage_id = stage_state.stage_id

        # 1. 构造Agent规划当前阶段的提示词
        agent_stage_prompt = self.get_stage_prompt(agent_id, stage_state)

        # 2. 如果没有任何step,则增加step_0,一个规划模块
        if len(self.agent_state["agent_step"].get_step(stage_id=stage_id)) == 0:
            self.add_step(
                task_id=task_id,
                stage_id=stage_id,
                step_intention=f"规划Agent执行当前阶段需要哪些具体step",
                step_type="skill",
                executor="planning",
                text_content=agent_stage_prompt
            )

    # 上：Agent的任务逻辑
    # ---------------------------------------------------------------------------------------------
    # 下：Agent的工具方法

    def extract_instruction(self, text: str):
        '''
        从文本中提取指令字典和剩余文本
        (当前仅支持消息中包含一条指令)

        返回:
            - instruction_dict: JSON指令字典（如果解析失败则为 None）
            - rest_text: 去除该<instruction>后的剩余文本
        '''
        # 使用正则表达式提取<send_message>和</send_message>之间的内容
        matches = list(re.finditer(r"<instruction>\s*(.*?)\s*</instruction>", text, re.DOTALL))

        if matches:
            last_match = matches[-1]
            instruction_text = last_match.group(1)
            start, end = last_match.span()

            try:
                instruction_dict = json.loads(instruction_text)
            except json.JSONDecodeError:
                print("JSON解析错误:", instruction_text)
                instruction_dict = None

            # 去掉最后一个 <instruction> ... </instruction> 的文本
            rest_text = text[:start] + text[end:]
            return instruction_dict, rest_text.strip()
        else:
            return None, text.strip()


    def get_stage_prompt(self, agent_id, stage_state):
        '''
        获取当前阶段内容的提示词
        '''
        md_output = []

        task_id = stage_state.task_id
        stage_id = stage_state.stage_id

        stage_intention = stage_state.stage_intention  # 整体阶段目标 (str)
        agent_allocation = stage_state.agent_allocation  # 阶段中Agent的分配情况 (Dict[<agent_id>, <agent_stage_goal>])
        agent_goal = stage_state.agent_allocation[agent_id]  # 阶段中这个Agent自己的目标

        md_output.append("你被分配协助完成当前阶段stage的目标\n")
        md_output.append(
            f"当前阶段stage的信息如下：\n,"
            f"- 任务ID为：{task_id}\n,"
            f"- 阶段ID为：{stage_id}\n,"
            f"- 阶段整体目标stage_intention为：{stage_intention}\n,"
            f"- 阶段中所有Agent的分配情况agent_allocation为：{agent_allocation}\n,"
        )
        md_output.append(f"**你的所负责的具体目标为**：{agent_goal}\n")

        return "\n".join(md_output)

    def add_step(
        self,
        task_id: str,
        stage_id: str,
        step_intention: str,  # Step的目的
        step_type: str,  # Step的类型 'skill', 'tool'
        executor: str,  # Step的执行模块
        text_content: Optional[str] = None,  # Step的文本内容
        instruction_content: Optional[Dict[str, Any]] = None,  # Step的指令内容
    ):
        '''
        为agent_step的列表中添加一个Step
        '''
        # 1. 构造一个完整的StepState
        step_state = StepState(
            task_id = task_id,
            stage_id = stage_id,
            agent_id = self.agent_state["agent_id"],
            step_intention = step_intention,
            step_type = step_type,
            executor = executor,
            execution_state = "init",  # 'init', 'pending', 'running', 'finished', 'failed'
            text_content = text_content,  # Optional[str]
            instruction_content = instruction_content,  # Optional[Dict[str, Any]]
            execute_result = None,  # Optional[Dict[str, Any]]
            )

        if step_type == "tool" and instruction_content is None:
            # 如果是工具调用且没有具体指令，则状态为待填充 pending
            step_state.update_execution_state("pending")

            # 2. 添加一个该Step到agent_step中
            self.agent_state["agent_step"].add_step(step_state)

            # 3. 返回添加的step_id, 记录在工作记忆中
            self.agent_state["working_memory"][task_id][stage_id].append(step_state.step_id)


    def add_next_step(
        self,
        task_id: str,
        stage_id: str,
        step_intention: str,  # Step的目的
        step_type: str,  # Step的类型 'skill', 'tool'
        executor: str,  # Step的执行模块
        text_content: Optional[str] = None,  # Step的文本内容
        instruction_content: Optional[Dict[str, Any]] = None,  # Step的指令内容
    ):
        '''
        为agent_step的列表中插队添加一个Step,将该Step直接添加到下一个要处理的step位置上
        '''
        # 1. 构造一个完整的StepState
        step_state = StepState(
                task_id=task_id,
                stage_id=stage_id,
                agent_id=self.agent_state["agent_id"],
                step_intention=step_intention,
                step_type=step_type,
                executor=executor,
                execution_state="init",  # 'init', 'pending', 'running', 'finished', 'failed'
                text_content=text_content,  # Optional[str]
                instruction_content=instruction_content,  # Optional[Dict[str, Any]]
                execute_result=None,  # Optional[Dict[str, Any]]
            )

        if step_type == "tool" and instruction_content is None:
            # 如果是工具调用且没有具体指令，则状态为待填充 pending
            step_state.update_execution_state("pending")

            # 2. 添加一个该Step到agent_step中,插队到下一个step之前
            self.agent_state["agent_step"].add_next_step(step_state)

            # 3. 返回添加的step_id, 记录在工作记忆中
            self.agent_state["working_memory"][task_id][stage_id].append(step_state.step_id)








