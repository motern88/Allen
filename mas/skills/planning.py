'''
技能名称: Planning
期望作用: Agent通过Planning技能规划任务执行步骤，生成多个step的执行计划。

Planning需要有操作Agent中AgentStep的能力，AgentStep是Agent的执行步骤管理器，用于管理Agent的执行步骤列表。
我们通过提示词约束LLM以特定格式返回规划的步骤信息，然后基于规则的代码解析这些信息，增加相应的步骤到AgentStep中。

提示词顺序（系统 → 角色 → (目标 → 规则) → 记忆）

具体实现:
    1. 组装提示词:
        1.1 MAS系统提示词（# 一级标题）
        1.2 Agent角色:（# 一级标题）
            1.2.1 Agent角色背景提示词（## 二级标题）
            1.2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        1.3 planning step:（# 一级标题）
            1.3.1 step.step_intention 当前步骤的简要意图（## 二级标题）
            1.3.2 step.text_content 具体目标（## 二级标题）
            1.3.3 技能规则提示(planning_config["use_prompt"])（## 二级标题）
        1.4 持续性记忆:（# 一级标题）
            1.4.1 Agent持续性记忆说明提示词（## 二级标题）
            1.4.2 Agent持续性记忆内容提示词（## 二级标题）

    2. llm调用
    3. 解析llm返回的步骤信息，更新AgentStep中的步骤列表
    4. 解析llm返回的持续性记忆信息，追加到Agent的持续性记忆中
    5. 返回用于指导状态同步的execute_result（如果有的话）
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
            # print("解析json：",step_content)
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
        组装提示词
        1 MAS系统提示词（# 一级标题）
        2 Agent角色:（# 一级标题）
            2.1 Agent角色背景提示词（## 二级标题）
            2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        3 planning step:（# 一级标题）
            3.1 step.step_intention 当前步骤的简要意图（## 二级标题）
            3.2 step.text_content 具体目标（## 二级标题）
            3.3 技能规则提示(planning_config["use_prompt"])（## 二级标题）
        4 持续性记忆:（# 一级标题）
            4.1 Agent持续性记忆说明提示词（## 二级标题）
            4.2 Agent持续性记忆内容提示词（## 二级标题）
        '''
        md_output = []

        # 1. 获取MAS系统的基础提示词
        md_output.append("# 系统提示 system_prompt\n")
        system_prompt = self.get_base_prompt(key="system_prompt")  # 已包含 # 一级标题的md
        md_output.append(f"{system_prompt}\n")


        # 2. 组装角色提示词
        md_output.append("# Agent角色\n")
        # 角色背景
        agent_role_prompt = self.get_agent_role_prompt(agent_state)  # 不包含标题的md格式文本
        md_output.append(f"## 你的角色信息 agent_role\n"
                         f"{agent_role_prompt}\n")
        # 工具与技能权限
        available_skills_and_tools = self.get_skill_and_tool_prompt(agent_state["skills"],agent_state["tools"])  # 包含 # 三级标题的md
        md_output.append(f"## 角色可用技能与工具 available_skills_and_tools\n"
                         f"{available_skills_and_tools}\n")


        # 3. Planning step提示词
        md_output.append(f"# 当前需要执行的步骤 current_step\n")
        current_step = self.get_current_skill_step_prompt(step_id, agent_state)  # 不包含标题的md格式文本
        md_output.append(f"{current_step}\n")


        # 4. 持续性记忆提示词
        md_output.append("# 持续性记忆persistent_memory\n")
        # 获取persistent_memory的使用说明
        base_persistent_memory_prompt = self.get_base_prompt(key="persistent_memory_prompt")  # 不包含标题的md格式文本
        md_output.append(f"## 持续性记忆使用规则说明：\n"
                         f"{base_persistent_memory_prompt}\n")
        # persistent_memory的具体内容
        persistent_memory = self.get_persistent_memory_prompt(agent_state)  # 不包含标题的md格式文本
        md_output.append(f"## 你已有的持续性记忆内容：\n"
                         f"{persistent_memory}\n")

        # print("\n".join(md_output))
        return "\n".join(md_output)


    def execute(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        Planning技能的具体执行方法:

        1. 组装 LLM Planning 提示词
        2. LLM调用
        3. 规则判定：
            保证Planning的多个step不超出Agent的权限范畴。如果超出，给出提示并重新 <2. LLM调用> 进行规划
        4. 更新AgentStep中的步骤列表
        5. 解析persistent_memory并追加到Agent持续性记忆中
        '''

        # 更新当前step状态为 running
        agent_state["agent_step"].update_step_status(step_id, "running")

        # 1. 组装 LLM Planning 提示词 (基础提示词与技能提示词)
        planning_step_prompt = self.get_planning_prompt(step_id, agent_state)  # 包含 # 一级标题的md格式文本
        print(planning_step_prompt)
        # 2. LLM调用
        llm_config = agent_state["llm_config"]
        llm_client = LLMClient(llm_config)  # 创建 LLM 客户端
        chat_context = LLMContext(context_size=15)  # 创建一个对话上下文, 限制上下文轮数 15

        chat_context.add_message("assistant", "好的，我会扮演你提供的Agent角色信息，"
                                              "根据上文current_step的要求使用available_skills_and_tools中提供的权限规划后续step，"
                                              "并在<planned_step>和</planned_step>之间输出规划结果，"
                                              "在<persistent_memory>和</persistent_memory>之间输出我要追加的持续性记忆(如果我认为不需要追加我会空着)，")
        response = llm_client.call(
            planning_step_prompt,
            context=chat_context
        )

        # 3. 规则判定
        # 结构化输出判定，保证规划结果位于<planned_step>和</planned_step>之间，
        # 持续性记忆位于<persistent_memory>和</persistent_memory>之间
        if "<planned_step>" not in response :
            response = llm_client.call(
                f"****规划结果首尾用<planned_step>和</planned_step>标记，不要将其放在代码块中，否则将无法被系统识别。**",
                context=chat_context
            )
        if "<persistent_memory>" not in response:
            response = llm_client.call(
                f"**追加的持续性记忆首位用<persistent_memory>和</persistent_memory>标记。**",
                context=chat_context
            )

        # 打印LLM返回结果
        print(response)

        # 解析Planning_step
        planned_step = self.extract_planned_step(response) or {}

        # 技能与工具权限判定，保证Planning的多个step不超出Agent的权限范畴
        not_allowed_executors = [
            step["executor"]
            for step in planned_step
            # 是skill则查找是否位于skills中，是tool则查找是否位于tools中，否则将step["executor"]追加进列表
            if (step["type"] == "skill" and step["executor"] not in agent_state["skills"])
            or (step["type"] == "tool" and step["executor"] not in agent_state["tools"])
        ]
        if len(not_allowed_executors) != 0:  # 如果超出，给出提示并重新 <2. LLM调用> 进行规划
            print("planning技能规划的步骤中包含不在使用权限内的技能与工具，正在重新规划...")
            response = llm_client.call(
                f"以下技能与工具不在使用权限内:{not_allowed_executors}。请确保只使用 available_skills_and_tools 小节中提示的可用技能与工具来完成当前阶段Stage目标。**规划结果放在<planned_step>和</planned_step>之间。**",
                context=chat_context
            )
            planned_step = self.extract_planned_step(response)

        # 清空对话历史
        chat_context.clear()

        # 4. 更新AgentStep中的步骤列表
        self.add_step(planned_step, step_id, agent_state)  # 将规划的步骤列表添加到AgentStep中

        # 5. 解析persistent_memory并追加到Agent持续性记忆中
        new_persistent_memory = self.extract_persistent_memory(response)
        agent_state["persistent_memory"] += "\n" + new_persistent_memory

        return None  # Planning技能无execute_result返回值


# Debug
if __name__ == "__main__":
    '''
    测试planning需在Allen根目录下执行 python -m mas.skills.planning
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