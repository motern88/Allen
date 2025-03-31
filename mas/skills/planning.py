'''
技能名称: Planning
期望作用: Agent通过Planning技能规划任务执行步骤，生成多个step的执行计划。

Planning需要有操作Agent中AgentStep的能力，AgentStep是Agent的执行步骤管理器，用于管理Agent的执行步骤列表。
'''
from platform import system

from mas.agent.base.executor_base import Executor

# 注册规划技能到类型 "skill", 名称 "planning"
@Executor.register(executor_type="skill", executor_name="planning")
class PlanningSkill(Executor):
    def __init__(self):
        super().__init__()  # 调用父类的构造方法（如果有）


    def get_planning_prompt(self, agent_state):
        '''
        组装planning技能的完整提示词

        1. 组装Agent角色提示词，返回 ## agent_role 二级目录下的md格式文本
        2. 组装Agent工具与技能权限提示词，返回 ## available_skills_and_tools 二级目录下的md格式文本
        3. 组装Agent工作记忆提示词，返回 ## working_memory 二级目录下的md格式文本
        4. 组装Agent执行当前step的具体提示词，返回 ## current_step 二级目录下的md格式文本
        '''
        # 1.组装Agent角色提示词
        agent_role_prompt = self.get_agent_role_prompt(agent_state)  # TODO:实现父类get_agent_role_prompt方法

        # 2.组装Agent工具与技能权限提示词
        agent_skills = agent_state["skills"]
        agent_tools = agent_state["tools"]
        available_skills_and_tools = self.get_skill_and_tool_prompt(agent_skills, agent_tools)

        # 3.组装Agent工作记忆提示词


        return planning_prompt


    def execute(self, agent_state):
        '''
        Planning技能的具体执行方法:

        1. 组装 LLM Planning 提示词
        2. LLM调用
        3. 权限判定，保证Planning的多个step不超出Agent的权限范畴。如果超出，给出提示并重新 <2. LLM调用> 进行规划
        2. 更新AgentStep中的步骤列表
        '''

        # 1. 组装 LLM Planning 提示词

        # 获取MAS系统的基础提示词
        base_prompt =
        #
        prompt = self.get_planning_prompt(agent_state)







        return executor_output, agent_state


