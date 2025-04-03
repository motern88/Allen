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
from mas.agent.state.step_state import StepState, AgentStep



# 注册规划技能到类型 "skill", 名称 "planning"
@Executor.register(executor_type="skill", executor_name="planning")
class PlanningSkill(Executor):
    def __init__(self):
        super().__init__()  # 调用父类的构造方法

    def extract_planned_step(self, text: str) -> Optional[List[Dict[str, Any]]]:
        '''
        从文本中提取规划步骤
        '''
        # 使用正则表达式提取 <planned_step> ... </planned_step> 之间的内容
        matches = re.findall(r"<planned_step>\s*(.*?)\s*</planned_step>", text, re.DOTALL)

        if matches:
            step_content = matches[-1]  # 获取最后一个匹配内容 排除是在<think></think>思考期间的内容
            print("解析json：",step_content)
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
        3. 组装Agent持续性记忆提示词，返回 ## persistent_memory 二级标题下的md格式文本
        4. 组装Agent执行当前step的具体提示词，包含step目标与具体技能提示，
            返回 ## current_step 二级标题下的md格式文本

        最后返回 # planning 技能规划提示 一级标题的md格式文本
        '''
        # 1.组装 角色 提示词
        agent_role_prompt = self.get_agent_role_prompt(agent_state)  # 包含 # 二级标题的md格式文本

        # 2.组装 工具与技能权限 提示词
        available_skills_and_tools = self.get_skill_and_tool_prompt(
            agent_state["skills"],
            agent_state["tools"]
        )  # 包含 # 二级标题的md格式文本

        # 3.组装 Agent持续性记忆 的具体提示词
        persistent_memory = self.get_persistent_memory_prompt(agent_state)  # 包含 # 二级标题的md格式文本

        # 4.组装 Agent执行当前step的 具体提示词
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

        1. 组装 LLM Planning 提示词 （基础提示词+持续性记忆提示词+技能planning提示词）
        2. LLM调用
        3. 权限判定，保证Planning的多个step不超出Agent的权限范畴。如果超出，给出提示并重新 <2. LLM调用> 进行规划
        4. 更新AgentStep中的步骤列表
        5. 解析persistent_memory并追加到Agent持续性记忆中
        '''

        # 更新当前step状态为 running
        agent_state["agent_step"].update_step_status(step_id, "running")

        # 1. 组装 LLM Planning 提示词 (基础提示词与技能提示词)

        # 获取MAS系统的基础提示词
        base_prompt = self.get_base_prompt(key="system_prompt")  # 包含 # 一级标题的md格式文本
        # 获取persistent_memory的使用说明
        base_persistent_memory_prompt = self.get_base_prompt(key="persistent_memory_prompt")

        # 获取Planning技能的提示词
        skill_prompt = self.get_planning_prompt(step_id, agent_state)  # 包含 # 一级标题的md格式文本

        # 2. LLM调用
        llm_config = agent_state["llm_config"]
        llm_client = LLMClient(llm_config)  # 创建 LLM 客户端
        chat_context = LLMContext(context_size=15)  # 创建一个对话上下文, 限制上下文轮数 15

        chat_context.add_message("user", base_prompt)
        chat_context.add_message("user", base_persistent_memory_prompt)

        response = llm_client.call(skill_prompt, context=chat_context)

        print(response) # print(chat_context.get_history())

        # 3. 技能与工具权限判定，保证Planning的多个step不超出Agent的权限范畴
        planned_step = self.extract_planned_step(response) or {}
        not_allowed_executors = [
            step["executor"]
            for step in planned_step
            # 是skill则查找是否位于skills中，是tool则查找是否位于tools中，否则将step["executor"]追加进列表
            if (step["type"] == "skill" and step["executor"] not in agent_state["skills"])
            or (step["type"] == "tool" and step["executor"] not in agent_state["tools"])
        ]

        # 如果超出，给出提示并重新 <2. LLM调用> 进行规划
        if len(not_allowed_executors) != 0:
            print("planning技能规划的步骤中包含不在使用权限内的技能与工具，正在重新规划...")
            response = llm_client.call(
                f"以下技能与工具不在使用权限内:{not_allowed_executors}。请确保只使用 available_skills_and_tools 小节中提示的可用技能与工具来完成当前阶段Stage目标。规划结果放在<planned_step>和</planned_step>之间。",
                context=chat_context
            )
            planned_step = self.extract_planned_step(response)

        # 清空对话历史
        chat_context.clear()

        # 4. 更新AgentStep中的步骤列表
        agent_step = agent_state["agent_step"]
        current_step = agent_step.get_step(step_id)[0]  # 获取当前Planning step的信息
        for step in planned_step:
            # 构造新的StepState
            step_state = StepState(
                task_id=current_step.task_id,
                stage_id=current_step.stage_id,
                agent_id=current_step.agent_id,
                step_intention=step["step_intention"],
                step_type=step["type"],
                executor=step["executor"],
                text_content=step["text_content"]
            )
            # 添加到AgentStep中
            agent_step.add_step(step_state)
            # 记录在工作记忆中
            agent_state["working_memory"][current_step.task_id][current_step.stage_id,].append(step_state.step_id)


        # 5. 解析persistent_memory并追加到Agent持续性记忆中
        new_persistent_memory = self.extract_persistent_memory(response)
        agent_state["persistent_memory"] += "\n" + new_persistent_memory

        return None  # Planning技能无execute_result返回值


# Debug
if __name__ == "__main__":
    '''
    运行脚本需在Allen根目录下执行 python -m mas.skills.planning
    '''
    from mas.agent.configs.llm_config import LLMConfig

    print("测试Planning技能的调用")
    agent_state = {
        "agent_id": "0001",
        "name": "小灰",
        "role": "合同提取专员",
        "profile": "负责合同提取，将合同内容按字段提取录入系统",
        "working_state": "Unassigned tasks",
        "llm_config": LLMConfig.from_yaml("mas/role_config/qwq32b.yaml"),
        "working_memory": {},
        "persistent_memory": "",
        "agent_step": AgentStep("0001"),
        "skills": ["planning"],
        "tools": [],
    }

    step_state = StepState(
        task_id="task_001",
        stage_id="stage_001",
        agent_id="0001",
        step_intention="将合同提取任务分解为多个步骤",
        step_type="planning",
        executor="planning",
        text_content="分析任务并制定执行计划"
    )

    agent_state["agent_step"].add_step(step_state)
    step_id = agent_state["agent_step"].step_list[0].step_id

    planning_skill = PlanningSkill()
    planning_skill.execute(step_id, agent_state)
    # 打印step信息
    agent_state["agent_step"].print_all_steps()