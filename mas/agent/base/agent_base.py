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


class AgentBase():
    '''
    基础Agent类，定义各基础模块的流转逻辑

    整体分为两个部分，执行线程和任务分发线程
    执行线程action方法只负责执行每一个step，有新的step就执行新的step。
    任务线程用于管理任务进度，（当一个任务阶段的所有step都执行完毕后，再执行下一个任务阶段）。

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
        self.agent_state_lock = threading.Lock()


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

    # TODO:考虑开始一个stage到完成当前stage进入下一个stage的过程，是根据工作记忆来执行还是根据todo_list执行？
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

    def start_stage(
        self,
        stage_state: StageState,  # Agent从当前StageState来获取信息明确目标
    ):
        '''
        用于开始一个任务阶段:一个stage的第一个step必定是planning方法

        1. 从stage_state中获取当前阶段的目标
        2. 构造Agent规划当前阶段的提示词
        3. 如果当前stage没有任何step，则增加一个规划step
        '''
        agent_id = self.agent_state["agent_id"]

        # 1. 从stage_state中获取当前阶段的目标等属性
        task_id = stage_state["task_id"]
        stage_id = stage_state["stage_id"]
        stage_intention = stage_state["stage_intention"]  # 整体阶段目标 (str)
        agent_goal = stage_state["agent_allocation"][agent_id]  # 阶段中这个Agent自己的目标

        # 2. 构造Agent规划当前阶段的提示词
        agent_stage_prompt = (f"你被分配协助完成当前阶段stage的目标。"
                              f"当前阶段整体目标为：{stage_intention},"
                              f"你的所负责的具体目标为：{agent_goal}")

        # 3. 如果没有任何step,则增加step_0,一个规划模块
        if len(self.agent_state["agent_step"].get_step(stage_id=stage_id)) == 0:
            self.add_step(
                task_id = task_id,
                stage_id = stage_id,
                step_intention = f"规划Agent执行当前阶段需要哪些具体step",
                step_type = "skill",
                executor = "planning",
                text_content = agent_stage_prompt
            )


    # 上：Agent的任务逻辑
    # ---------------------------------------------------------------------------------------------
    # 下：Agent的工具方法


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











