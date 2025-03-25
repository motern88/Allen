'''
Agent被分配执行或协作执行一个阶段时，Agent会为自己规划数个执行步骤以完成目标。
步骤step是最小执行单位，每个步骤的执行会维护一个 step_state 。
'''

from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union
from pydantic import (
    BaseModel,
    Field,
)

class StepSate(BaseModel):
    '''
    由Agent生成的最小执行单位。包含LLM的文本回复（思考/反思/规划/决策）或一次工具调用。

    属性:
        step_id (str): 步骤的唯一标识符
        step_intention (str): 步骤的意图, 由创建Agent填写(仅作参考并不需要匹配特定格式)。例如：'ask a question', 'provide an answer', 'use tool to check...'
        type (str): 步骤的类型,例如：'text_reply', 'use_tool'
        agent (str): 创建该步骤的Agent的名称
        agent_id (str): 创建该步骤的Agent的唯一标识符
        content (str): 步骤的内容，如果是文本回复则是文本内容，如果是工具调用则是具体工具命令（例如工具调用的命令或指定的特殊json格式）
        executor (str): 执行该步骤的对象，如果是 type 是 'use_tool' 则这里填工具名称，如果是 'text_reply' 则填Agent名称
    '''

    step_id: str = Field(default="", validate_default=True)
    step_intention: str = Field(default="", validate_default=True)
    type: str  # 'text_reply' 或 'use_tool'
    agent: str = Field(default="", validate_default=True)
    agent_id: str = Field(default="", validate_default=True)
    content: Dict[str, Any] = Field(default_factory=dict)
    executor: str = Field(default="", validate_default=True)


