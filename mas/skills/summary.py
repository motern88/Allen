'''
技能名称: Summary
期望作用: Agent通过Summary总结并结束自己的一个stage，标志着一个stage的结束。
    整理该stage内所有step的信息并通过execute_output同步在stage_state.completion_summary(Dict[<agent_id>, <completion_summary>])中
    (Summary只负责Agent执行step的汇总，不负责交付阶段stage结果。
    例如假设阶段目标是输出一段文本，那么输出文本的这个交付过程应当由一个交付工具例如"send_message"执行，而非留给Summary技能来完成。)

Summary需要获取到过去执行步骤的信息。
我们整理过去执行步骤的结果和阶段目标以特定格式输入LLM进行总结，同时通过同时通过提示词约束LLM以特定格式返回其总结结果。
然后基于规则的代码解析这些信息，生成对应的execute_output。

Summary技能对stage信息的获取来源于第一个步骤Planning_step：
    Planning_step中text_content中记录阶段整体目标和Agent被分配的具体目标。
    由agent_base.py中start_stage方法将Stage信息注入到Planning_step中。

提示词顺序（系统 → 角色 → (目标 → 规则) → 记忆）

具体实现:
    1. 组装提示词:
        1.1 MAS系统提示词（# 一级标题）
        1.2 Agent角色提示词:（# 一级标题）
            1.2.1 Agent角色背景提示词（## 二级标题）
            1.2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        1.3 summary step:（# 一级标题）
            1.3.1 step.step_intention 当前步骤的简要意图（## 二级标题）
            1.3.2 step.text_content 具体目标（## 二级标题）
            1.3.3 技能规则提示(reflection_config["use_prompt"])（## 二级标题）
        1.4 历史步骤执行结果（# 一级标题）
        1.5 持续性记忆:（# 一级标题）
            1.5.1 Agent持续性记忆说明提示词（## 二级标题）
            1.5.2 Agent持续性记忆内容提示词（## 二级标题）

    2. llm调用
    3. 解析llm返回的步骤信息，生成execute_output指令（更新stage_state.completion_summary的指令）
    4. 解析llm返回的持续性记忆信息，追加到Agent的持续性记忆中
    5. 返回用于指导状态同步的execute_output
'''
import re
import json
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union

from mas.agent.base.executor_base import Executor
from mas.agent.base.llm_base import LLMContext, LLMClient
from mas.agent.state.step_state import StepState, AgentStep



# 注册总结技能到类型 "skill", 名称 "summary"
@Executor.register(executor_type="skill", executor_name="summary")
class SummarySkill(Executor):
    def __init__(self):
        super().__init__()  # 调用父类的构造方法

    def execute(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        Summary技能的具体执行方法:

        1. 组装 LLM Summary 提示词
        2. LLM调用
        3. 解析 LLM 返回的步骤信息，生成 execute_output 指令
        4. 解析persistent_memory并追加到Agent持续性记忆中
        '''

        # step状态更新为 running
        agent_state["agent_step"].update_step_status(step_id, "running")

        # 1. 组装 LLM Summary 提示词 (基础提示词与技能提示词)
        summary_step_prompt = self.get_summary_prompt(step_id, agent_state)  # 包含 # 一级标题的md格式文本
        print(summary_step_prompt)

































