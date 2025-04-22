'''
技能名称: Task Manager
期望作用: Agent对任务的管理与调度。（一种特殊权限的技能，一般只有管理者Agent拥有）
    Task Manager会获取任务信息与阶段信息，结合自身历史步骤信息，生成用于管理任务进程的指令。

任务管理者Agent会通过该技能生成相应操作的指令，指令会再MAS系统中操作对应组件完成实际行动，
例如通过SyncState操作task_state与stage_state,通过send_message形式通知相应Agent

说明:
1. 发起一个Task:  TODO：待实现
    创建任务 add_task。
    该操作会创建一个 task_state,包含 task_intention 任务意图

2. 为任务分配Agent与阶段目标:  TODO：待实现
    为任务创建阶段 add_stage。
    该操作会为 task_state 创建一个或多个 stage_state,
    包含 stage_intention 阶段意图与 agent_allocation 阶段中Agent的分配情况。

3. 任务判定已完成，交付任务:  TODO：待实现
    结束任务 finish_task。
    该操作会将 task_state 的状态更新为 finished 或 failed
    并自动进入任务结束流程（包括任务总结，任务汇报，任务日志记录入库等）。

4. 任务阶段判定已结束，进入下一个任务阶段:  TODO：待实现
    结束阶段 finish_stage。
    该操作会将 stage_state 的状态更新为 finished 或 failed
    阶段完成则进入下一个阶段，如果失败则反馈给任务管理者。

提示词顺序（系统 → 角色 → (目标 → 规则) → 记忆）

具体实现:
    1. 组装提示词:
        1.1 MAS系统提示词（# 一级标题）
        1.2 Agent角色:（# 一级标题）
            1.2.1 Agent角色背景提示词（## 二级标题）
            1.2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        1.3 task_manager step:（# 一级标题）
            1.3.1 step.step_intention 当前步骤的简要意图（## 二级标题）
            1.3.2 step.text_content 具体目标（## 二级标题）
            1.3.3 技能规则提示(task_manager_config["use_prompt"])（## 二级标题）
        1.4 Agent所管理的任务及附属阶段的信息（# 一级标题）
        1.5 历史步骤执行结果（# 一级标题）
        1.6 持续性记忆:（# 一级标题）
            1.6.1 Agent持续性记忆说明提示词（## 二级标题）
            1.6.2 Agent持续性记忆内容提示词（## 二级标题）

    2. llm调用
    3. 解析llm返回的指令构造
    4. 解析llm返回的持续性记忆信息，追加到Agent的持续性记忆中
    5. 返回用于指导状态同步的execute_output
'''
import re
import json
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union

from mas.agent.base.executor_base import Executor
from mas.agent.base.llm_base import LLMContext, LLMClient
from mas.agent.state.step_state import StepState, AgentStep



# 注册规划技能到类型 "skill", 名称 "task_manager"
@Executor.register(executor_type="skill", executor_name="task_manager")
class TaskManagerSkill(Executor):
    def __init__(self):
        super().__init__()  # 调用父类的构造方法

    def extract_task_instruction(self, text: str) -> Optional[Dict[str, Any]]:
        '''
        从文本中提取任务指令
        '''
        # 使用正则表达式提取<task_instruction>和</task_instruction>之间的内容
        matches = re.findall(r"<task_instruction>\s*(.*?)\s*</task_instruction>", text, re.DOTALL)

        if matches:
            task_instruction = matches[-1]  # 获取最后一个匹配内容 排除是在<think></think>思考期间的内容

            try:
                task_instruction_dict = json.loads(task_instruction)
                return task_instruction_dict
            except json.JSONDecodeError:
                print("JSON解析错误:", task_instruction)
                return None
        else:
            print("没有找到<task_instruction>标签")
            return None

    def get_task_manager_prompt(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        组装提示词:
        1 MAS系统提示词（# 一级标题）
        2 Agent角色:（# 一级标题）
            2.1 Agent角色背景提示词（## 二级标题）
            2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        3 task_manager step:（# 一级标题）
            3.1 step.step_intention 当前步骤的简要意图（## 二级标题）
            3.2 step.text_content 具体目标（## 二级标题）
            3.3 技能规则提示(task_manager_config["use_prompt"])（## 二级标题）
        4 Agent所管理的任务及附属阶段的信息（# 一级标题）  # TODO:是否要单独做成一个技能
        5 历史步骤执行结果（# 一级标题）
        6 持续性记忆:（# 一级标题）
            6.1 Agent持续性记忆说明提示词（## 二级标题）
            6.2 Agent持续性记忆内容提示词（## 二级标题）
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
        available_skills_and_tools = self.get_skill_and_tool_prompt(agent_state["skills"],
                                                                    agent_state["tools"])  # 包含 # 三级标题的md
        md_output.append(f"## 角色可用技能与工具 available_skills_and_tools\n"
                         f"{available_skills_and_tools}\n")

        # 3. Task Manager step提示词
        md_output.append(f"# 当前需要执行的步骤 current_step\n")
        current_step = self.get_current_skill_step_prompt(step_id, agent_state)  # 不包含标题的md格式文本
        md_output.append(f"{current_step}\n")

        # 4. Agent所管理的任务及附属阶段的信息 TODO
        md_output.append(f"# 你所涉及的任务信息\n")
        task_info = self.get_task_info_prompt(agent_state["agent_id"])  # TODO:包含几级标题？
        md_output.append(f"{task_info}\n")

        # 5. 历史步骤执行结果
        md_output.append(f"# 历史已执行步骤 history_step\n")
        history_steps = self.get_history_steps_prompt(step_id, agent_state)  # 不包含标题的md格式文本
        md_output.append(f"{history_steps}\n")

        # 6. 持续性记忆提示词
        md_output.append("# 持续性记忆 persistent_memory\n")
        # 获取persistent_memory的使用说明
        base_persistent_memory_prompt = self.get_base_prompt(key="persistent_memory_prompt")  # 不包含标题的md格式文本
        md_output.append(f"## 持续性记忆使用规则说明：\n"
                         f"{base_persistent_memory_prompt}\n")
        # persistent_memory的具体内容
        persistent_memory = self.get_persistent_memory_prompt(agent_state)  # 不包含标题的md格式文本
        md_output.append(f"## 你已有的持续性记忆内容：\n"
                         f"{persistent_memory}\n")

        return "\n".join(md_output)





















