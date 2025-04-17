'''
技能名称: Process Message
期望作用: Agent处理MAS内部来自另一个Agent实例的单项消息，且该消息明确不需要回复。
    接收到消息后，Agent会使用process_message step，调用llm来处理消息的非指令部分（指令部分在agent_base中process_message方法中处理），
    一般情况下意味着该消息需要被LLM消化并整理，也有可能仅仅作为多轮对话的结尾。

提示词顺序（系统 → 角色 → (目标 → 规则) → 记忆）

具体实现:
    1. 组装提示词:
        1.1 MAS系统提示词（# 一级标题）
        1.2 Agent角色:（# 一级标题）
            1.2.1 Agent角色背景提示词（## 二级标题）
            1.2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        1.3 process_message step:（# 一级标题）
            1.3.1 step.step_intention 当前步骤的简要意图（## 二级标题）
            1.3.2 step.text_content 接收到的消息内容（## 二级标题）
            1.3.3 技能规则提示(process_message_config["use_prompt"])（## 二级标题）
        1.4 历史步骤执行结果（# 一级标题）
        1.5 持续性记忆:（# 一级标题）
            1.5.1 Agent持续性记忆说明提示词（## 二级标题）
            1.5.2 Agent持续性记忆内容提示词（## 二级标题）

    2. llm调用
    3. 解析llm返回的消息体构造
    4. 解析llm返回的持续性记忆信息，追加到Agent的持续性记忆中
    5. 返回用于指导状态同步的execute_output
'''
import re
import json
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union

from mas.agent.base.executor_base import Executor
from mas.agent.base.llm_base import LLMContext, LLMClient
from mas.agent.state.step_state import StepState, AgentStep



# 注册规划技能到类型 "skill", 名称 "process_message"
@Executor.register(executor_type="skill", executor_name="process_message")
class ProcessMessageSkill(Executor)
    def __init__(self):
        super().__init__()  # 调用父类的构造方法

    def execute(self, step_id: str, agent_state: Dict[str, Any]):
        '''

        '''













