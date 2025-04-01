'''
技能名称: Planning
期望作用: Agent通过Planning技能规划任务执行步骤，生成多个step的执行计划。

Planning需要有操作Agent中AgentStep的能力，AgentStep是Agent的执行步骤管理器，用于管理Agent的执行步骤列表。
'''
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union

from mas.agent.base.executor_base import Executor

# 注册规划技能到类型 "skill", 名称 "planning"
@Executor.register(executor_type="skill", executor_name="planning")
class PlanningSkill(Executor):
    def __init__(self):
        super().__init__()  # 调用父类的构造方法（如果有）


    def get_planning_prompt(self, step_id, agent_state):
        '''
        组装planning技能的完整提示词

        1. 组装Agent角色提示词，返回 ## agent_role 二级标题下的md格式文本
        2. 组装Agent工具与技能权限提示词，返回 ## available_skills_and_tools 二级标题下的md格式文本
        3. 组装Agent持续性记忆提示词，返回 ## working_memory 二级标题下的md格式文本
        4. 组装Agent执行当前step的具体提示词，包含step目标与具体技能提示，
            返回 ## current_step 二级标题下的md格式文本

        最后返回 # planning 技能规划提示 一级标题的md格式文本
        '''
        # 1.组装Agent角色提示词
        agent_role_prompt = self.get_agent_role_prompt(agent_state)  # 包含 # 二级标题的md格式文本

        # 2.组装Agent工具与技能权限提示词
        agent_skills = agent_state["skills"]
        agent_tools = agent_state["tools"]
        available_skills_and_tools = self.get_skill_and_tool_prompt(agent_skills, agent_tools)  # 包含 # 二级标题的md格式文本

        # 3.组装Agent持续性记忆提示词
        persistent_memory = self.get_persistent_memory_prompt(agent_state)  # 包含 # 二级标题的md格式文本

        # 4.组装Agent执行当前step的具体提示词
        current_step = self.get_current_skill_step_prompt(step_id, agent_state)  # 包含 # 二级标题的md格式文本

        # 最后组装planning技能的完整提示词
        planning_prompt = [
            "# planning 技能规划提示\n",
            agent_role_prompt,
            available_skills_and_tools,
            persistent_memory,
            current_step
        ]

        return "\n".join(planning_prompt)


    def execute(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        Planning技能的具体执行方法:

        1. 组装 LLM Planning 提示词 （基础提示词+技能planning提示词）
        2. LLM调用
        3. 权限判定，保证Planning的多个step不超出Agent的权限范畴。如果超出，给出提示并重新 <2. LLM调用> 进行规划
        4. 更新AgentStep中的步骤列表
        '''

        # 1. 组装 LLM Planning 提示词 (基础提示词与技能提示词)

        # 获取MAS系统的基础提示词
        base_prompt = self.get_base_prompt(key="base_prompt")  # 包含 # 一级标题的md格式文本
        # 获取Planning技能的提示词
        prompt = self.get_planning_prompt(step_id, agent_state)  # 包含 # 一级标题的md格式文本

        # TODO 2. LLM调用






        return executor_output, agent_state


