'''
Agent基础类，这里实现关于LLM驱动的相关基础功能，不涉及到任何具体Agent_state
'''


from mas.agent.state.step_state import (
    StepState,
    AgentStep
)

from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union


class AgentBase():
    '''
    基础Agent类，定义各基础模块的流转逻辑
    '''
    def __init__(
        self,
        agent_id: str,  # Agent ID 由更高层级的Agent管理器生成，不由配置文件中读取
        config,  # Agent配置文件
    ):


        # 初始化Agent状态
        self.agent_state = self.init_agent_state(agent_id)  # TODO: 传入字段
        pass

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
        # Agent工作记忆 {<task_id>: {<stage_id>: {<step_id>: <step_state>,...},...},...}
        # Agent工作记忆以任务视角，包含多个task，每个task多个stage，每个stage多个step的状态信息
        agent_state["working_memory"] = working_memory if working_memory else {}

        # TODO:Agent持续性记忆
        # 永久追加精简记忆，用于记录Agent的持久性记忆，不会因为任务,阶段,步骤的结束而被清空
        agent_state["persistent_memory"] = {}

        # 初始化AgentStep,用于管理Agent的执行步骤列表
        # （一般情况下步骤中只包含当前任务当前阶段的步骤，在下一个阶段时，
        # 上一个阶段的step_state会被同步到stage_state中，不会在列表中留存）
        agent_state["agent_step"] = AgentStep(agent_id)

        # Agent可用的技能与工具库
        agent_state["tools"] = tools if tools else []
        agent_state["skills"] = skills if skills else []

        return agent_state


    def action_step(
        self,

    ):
        '''
        执行每一个Step的具体Action
        '''
        pass


    def action_stage(
        self,
        stage_state: StageState,  # Agent从当前StageState来获取信息明确目标
    ):
        '''
        Agent执行当前 任务-阶段 的目标的具体实现:

        1. 从stage_state中获取当前阶段的目标
        2. Agent执行逻辑的具体实现，不断循环执行每一个Step的具体Action
        '''

        # 1.从stage_state中获取当前阶段的目标等属性  # TODO:实现stage_state类
        task_id = stage_state["task_id"]
        stage_id = stage_state["stage_id"]
        stage_goal_prompt = stage_state[]  # 阶段目标  # TODO:实现stage_state中指定这个Agent做的事情，构造阶段目标提示



        # 获取
        agent_step = self.agent_state["agent_step"]

        # 如果没有任何step,则增加step_0,一个规划模块
        if len(agent_step.get_step(stage_id=stage_id)) == 0:
            self.add_step(
                task_id = task_id,
                stage_id = stage_id,
                step_intention = "规划Agent执行当前阶段需要哪些具体step",
                step_type = "skill",
                executor = "planning",
                text_content = stage_goal_prompt
            )




    def add_step(
        self,
        task_id: str,
        stage_id: str,
        step_intention: str,  # Step的目的
        step_type: str,  # Step的类型 'skill', 'tool'
        executor: str,  # Step的执行模块
        text_content: Optional[Dict[str, Any]] = None,  # Step的文本内容
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
            text_content = text_content,  # Optional[Dict[str, Any]]
            instruction_content = instruction_content,  # Optional[Dict[str, Any]]
            execute_result = None,  # Optional[Dict[str, Any]]
        )

        # 2. 添加一个该Step到agent_step中
        agent_step = self.agent_state["agent_step"]
        agent_step.add_step(step_state)

















