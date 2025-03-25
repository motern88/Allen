from mas.agent.base.agent_base import AgentBase
from typing import Dict, Any, List





class Agent(AgentBase):
    '''
    继承自AgentBase类的Agent
    '''

    def __init__(self, **kwargs):
        super().__init__(**kwargs)



    # Agent被实例化时需要初始化自己的 agent_state, agent_state 会被持续维护用于记录Agent的基本信息、状态与记忆。
    # 不同的Agent唯一的区别就是 agent_state 的区别
    def init_agent_state(
        self,
        agent_id: str,
        name: str,
        role: str,
        profile: str,
        memories: Dict[str, Any] = None,
        tools: List[str] = None,
        skills: List[str] = None,
    ):
        agent_state = {}
        agent_state["agent_id"] = agent_id  # Agent的唯一标识符
        agent_state["name"] = name  # Agent的名称
        agent_state["role"] = role  # Agent的角色
        agent_state["profile"] = profile  # Agent的角色简介

        # Unassigned 未分配任务, idle 空闲, working 工作中, awaiting 等待执行反馈中,
        agent_state["working_state"] = "Unassigned tasks"  # Agent的当前工作状态

        # Agent的记忆{<task_id>: {<stage_id>: {<step_id>: <step_state>,...},...},...}
        # Agent记忆包含多个task，每个task多个stage，每个stage多个step的状态信息
        agent_state["memories"] = memories if memories else {}

        # Agent可用的技能与工具库
        agent_state["tools"] = tools if tools else []
        agent_state["skills"] = skills if skills else []

        return agent_state