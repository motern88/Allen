'''
技能名称: Planning
期望作用: Agent通过Planning技能规划任务执行步骤，生成多个step的执行计划。

Planning需要有操作Agent中AgentStep的能力，AgentStep是Agent的执行步骤管理器，用于管理Agent的执行步骤列表。
'''
import re
import json
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union

from mas.agent.base.executor_base import Executor
from mas.agent.base.llm_base import LLMContext, LLMClient

# 注册规划技能到类型 "skill", 名称 "planning"
@Executor.register(executor_type="skill", executor_name="planning")
class PlanningSkill(Executor):
    def __init__(self):
        super().__init__()  # 调用父类的构造方法（如果有）

    def extract_planned_step(self, text: str) -> Optional[List[Dict[str, Any]]]:
        '''
        从文本中提取规划步骤
        '''
        # 使用正则表达式提取 <planned_step> ... </planned_step> 之间的内容
        match = re.search(r"<planned_step>\s*(.*?)\s*</planned_step>", text, re.DOTALL)

        if match:
            step_content = match.group(1)  # 获取匹配内容
            try:
                # 将字符串解析为 Python 列表
                planned_step = json.loads(step_content)
                return planned_step
            except json.JSONDecodeError:
                print("解析 JSON 失败，请检查格式")
                return None
        else:
            print("未找到 <planned_step> 标记")
            return None

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
        available_skills_and_tools = self.get_skill_and_tool_prompt(
            agent_state["skills"],
            agent_state["tools"]
        )  # 包含 # 二级标题的md格式文本

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
        skill_prompt = self.get_planning_prompt(step_id, agent_state)  # 包含 # 一级标题的md格式文本

        # 2. LLM调用
        llm_config = agent_state["llm_config"]
        llm_client = LLMClient(llm_config)  # 创建 LLM 客户端
        chat_context = LLMContext(context_size=15)  # 创建一个对话上下文, 限制上下文轮数 15

        chat_context.add_message("user", base_prompt)
        response = llm_client.call(skill_prompt, context=chat_context)
        print(response)

        # 3. 权限判定，保证Planning的多个step不超出Agent的权限范畴
        planned_step = self.extract_planned_step(response)
        not_allowed_executors = []
        for step in planned_step:
            if step["type"] is "skill" and step["executor"] not in agent_state["skills"]:
                not_allowed_executors.append(step["executor"])
            if step["type"] is "tool" and step["executor"] not in agent_state["tools"]:
                not_allowed_executors.append(step["executor"])

        # TODO


        # 如果超出，给出提示并重新 <2. LLM调用> 进行规划


        return executor_output, agent_state


