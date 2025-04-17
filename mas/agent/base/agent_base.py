'''
Agent基础类，这里实现关于LLM驱动的相关基础功能，不涉及到任何具体Agent_state
'''


from mas.agent.state.step_state import StepState, AgentStep
from mas.agent.state.stage_state import StageState
from mas.agent.state.sync_state import SyncState
from mas.agent.base.router import Router

from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union
import threading
import queue
import time
import re
import json



class AgentBase():
    '''
    基础Agent类，定义各基础模块的流转逻辑

    整体分为两个部分，执行线程和任务分发线程
    - 执行
        action方法只负责不断地执行执行每一个step，有新的step就执行新的step。
        action方法执行step时不会区分是否与当前stage相关，只要在agent_step.todo_list中就会执行。
        执行线程保证了Agent生命的自主性与持续性。
    - 任务管理
        任务管理用于管理任务进度，保证Agent的可控性。所有的任务管理都通过消息传递，Agent会使用receive_message接收。
        receive_message方法：
            Agent接收和处理来自其他Agent的不可预知的消息，提供了Agent之间主动相互干预的能力。
            该方法最终会根据是否需要回复消息走入两个不同的分支，process message分支和send message分支

    process_message方法:
        根据解析出的指令的不同进入不同方法
        start_stage方法:
            当一个任务阶段的所有step都执行完毕后，帮助Agent建立下一个任务阶段的第一个step: planning_step）。

    '''
    def __init__(
        self,
        agent_id: str,  # Agent ID 由更高层级的Agent管理器生成，不由配置文件中读取
        config,  # Agent配置文件
        sync_state: SyncState,  # 所有Agents接受同一个状态同步器(整个系统只维护一个SyncState，通过实例化传递给Agent)，由外部实例化后传给所有Agent
    ):
        self.router = Router()  # 在action中用于分发具体executor的路由器，用于同步stage_state与task_state
        self.sync_state = sync_state  # 状态同步器
        # 初始化Agent状态
        self.agent_state = self.init_agent_state(
            agent_id,
            name,
            role,
            profile,
            working_memory,
            tools,
            skills,
            llm_config,
        )  # TODO: 传入字段的获取来源

        # 初始化线程锁
        self.agent_state_lock = threading.Lock()  # TODO：使用统一AgentState全局锁，还是细分为分区锁？


    # Agent被实例化时需要初始化自己的 agent_state, agent_state 会被持续维护用于记录Agent的基本信息、状态与记忆。
    # 不同的Agent唯一的区别就是 agent_state 的区别
    def init_agent_state(
        self,
        agent_id: str,  # Agent ID 由更高层级的Agent管理器生成，不由配置文件中读取
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

        # Unassigned 未分配任务, idle 空闲, working 工作中, awaiting 等待执行反馈中,
        agent_state["working_state"] = "Unassigned tasks"  # Agent的当前工作状态

        # 从配置文件中获取 LLM 配置
        agent_state["llm_config"] = llm_config

        # TODO:Agent工作记忆
        # Agent工作记忆 {<task_id>: {<stage_id>: [<step_id>,...],...},...} 记录Agent还未完成的属于自己的任务
        # Agent工作记忆以任务视角，包含多个task，每个task多个stage，每个stage多个step
        # 注意：工作记忆不要放到提示词里面，提示词里面放持续性记忆
        agent_state["working_memory"] = working_memory if working_memory else {}

        # 永久追加精简记忆，用于记录Agent的持久性记忆，不会因为任务,阶段,步骤的结束而被清空
        agent_state["persistent_memory"] = ""  # md格式纯文本，里面只能用三级标题 ### 及以下！不允许出现一二级标题！
        # TODO：实现持久性记忆的清除，(目前已实现持久性记忆的追加)

        # 初始化AgentStep,用于管理Agent的执行步骤列表
        # （一般情况下步骤中只包含当前任务当前阶段的步骤，在下一个阶段时，
        # 上一个阶段的step_state会被同步到stage_state中，不会在列表中留存）
        agent_state["agent_step"] = AgentStep(agent_id)

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
        1. 根据Step的executor执行具体的Action，由路由器分发执行器
        2. 执行器执行
        3. 更新Step的执行状态
        '''
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


    def action(self):
        """
        不断从 agent_step.todo_list 获取 step_id 并执行 step_action
        agent_step.todo_list 是一个queue.Queue()共享队列，用于存放待执行的 step_id
        对 todo_list.get() 到的每个step执行step_action()
        """
        agent_step = self.agent_state["agent_step"]

        while True:
            # 1. 从agent_state.todo_list获取step_id
            step_id = agent_step.todo_list.get()
            if step_id is None:
                time.sleep(1)  # 队列为空时等待，避免 CPU 空转
                continue

            # 2. 根据step_id获取step_state
            step_state = agent_step.get_step(step_id)[0]
            step_type = step_state.step_type
            step_executor = step_state.executor

            # 3. 执行step_action
            self.step_action(step_id, step_type, step_executor)

            print("打印所有step_state:")
            agent_step.print_all_steps()  # 打印所有step_state

            # 5. 通知队列任务完成
            agent_step.todo_list.task_done()

    # 上：Agent的执行逻辑
    # ---------------------------------------------------------------------------------------------
    # 下：Agent的任务逻辑

    def receive_message(self, message):
        '''
        接收来自其他Agent的消息（该消息由MAS中的message_dispatcher转发），
        根据消息内容添加不同的step：
        - 如果需要回复则添加send_message step
        - 如果不需要回复则考虑执行消息中的指令或添加process_message step

        message格式：
        {
            "task_id": task_id,
            "sender_id": "<sender_agent_id>",
            "receiver": ["<agent_id>", "<agent_id>", ...],
            "message": "<message_content>",  # 消息文本
            "stage_relative": "<stage_id或no_relative>",  # 表示是否与任务阶段相关，是则填对应阶段Stage ID，否则为no_relative的字符串
            "need_reply": <bool>,  # 需要回复则为True，否则为False
        }
        '''
        # 1. 判断消息是否需要回复
        if message["need_reply"]:
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


    # TODO：完善其他管理指令
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
        }

        1. 对于需要LLM理解并消化的消息，添加process_message step
        2. 对于start_stage指令，执行start_stage

        '''
        # 解析文本中的指令和非指令文本
        instruction, text = self.extract_instruction(message["message"])

        # 1. 对于需要LLM理解并消化的消息，添加process_message step
        if text:
            # 为AgentStep添加process_message step用于回复。
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
            # 指令内容 {"start_stage": {"stage_id": <stage_id> }}  # TODO：完成生成该指令的技能
            task_id = message["task_id"]
            stage_id = instruction["start_stage"]["stage_id"]
            self.start_stage(task_id=task_id, stage_id=stage_id)




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
        task_id = stage_state["task_id"]
        stage_id = stage_state["stage_id"]

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

        task_id = stage_state["task_id"]
        stage_id = stage_state["stage_id"]

        stage_intention = stage_state["stage_intention"]  # 整体阶段目标 (str)
        agent_allocation = stage_state["agent_allocation"]  # 阶段中Agent的分配情况 (Dict[<agent_id>, <agent_stage_goal>])
        agent_goal = stage_state["agent_allocation"][agent_id]  # 阶段中这个Agent自己的目标

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
            step_state.update_execution_state = "pending"

        # 2. 添加一个该Step到agent_step中
        self.agent_state["agent_step"].add_step(step_state)

        # 3. 返回添加的step_id, 记录在工作记忆中  # TODO:实现工作记忆
        self.agent_state["working_memory"][task_id][stage_id].append(step_state.step_id)

    # TODO: 清除Agent某一个stage的所有step (记得同步工作记忆)











