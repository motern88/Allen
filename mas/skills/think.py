'''
技能名称: Think
期望作用: Agent通过Think来处理一些需要历史步骤信息的文本生成任务。

MAS中常规的基于历史步骤信息的LLM调用/文本生成。

提示词顺序（系统 → 角色 → (目标 → 规则) → 记忆）

具体实现:
    1. 组装提示词:
        1.1 MAS系统提示词（# 一级标题）
        1.2 Agent角色提示词:（# 一级标题）
            1.2.1 Agent角色背景提示词（## 二级标题）
            1.2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        1.3 think step:（# 一级标题）
            1.3.1 step.step_intention 当前步骤的简要意图
            1.3.2 step.text_content 具体目标
            1.3.3 技能规则提示(think_config["use_prompt"])
        1.4 历史步骤执行结果（# 一级标题）
        1.5 持续性记忆:（# 一级标题）
            1.5.1 Agent持续性记忆说明提示词（## 二级标题）
            1.5.2 Agent持续性记忆内容提示词（## 二级标题）

    2. llm调用
    3. 解析llm返回的思考信息
    4. 解析llm返回的持续性记忆信息，追加到Agent的持续性记忆中
    5. 生成并返回execute_output指令
'''
import re
import json
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union

from mas.agent.base.executor_base import Executor
from mas.agent.base.llm_base import LLMContext, LLMClient
from mas.agent.state.step_state import StepState, AgentStep



# 注册总结技能到类型 "skill", 名称 "think"
@Executor.register(executor_type="skill", executor_name="think")
class ThinkSkill(Executor):
    def __init__(self):
        super().__init__()  # 调用父类的构造方法

    def extract_think(self, text: str):
        '''
        从文本中解析think信息
        '''
        # 使用正则表达式提取 <_think> ... </_think> 之间的内容
        match = re.findall(r"<_think>\s*(.*?)\s*</_think>", text, re.DOTALL)
        if match:
            think = match[-1] # 获取最后一个匹配内容 排除是在<think></think>思考期间的内容
            return think
        else:
            return None

    def get_think_prompt(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        组装提示词:
        1 MAS系统提示词（# 一级标题）
        2 Agent角色提示词:（# 一级标题）
            2.1 Agent角色背景提示词（## 二级标题）
            2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        3 think step:（# 一级标题）
            3.1 step.step_intention 当前步骤的简要意图
            3.2 step.text_content 具体目标
            3.3 技能规则提示(think_config["use_prompt"])
        4 历史步骤执行结果（# 一级标题）
        5 持续性记忆:（# 一级标题）
            5.1 Agent持续性记忆说明提示词（## 二级标题）
            5.2 Agent持续性记忆内容提示词（## 二级标题）
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

        # 3. Think step提示词
        md_output.append(f"# 当前需要执行的步骤 current_step\n")
        current_step = self.get_current_skill_step_prompt(step_id, agent_state)  # 不包含标题的md格式文本
        md_output.append(f"{current_step}\n")

        # 4. 历史步骤执行结果
        md_output.append(f"# 历史已执行步骤 history_step\n")
        history_steps = self.get_history_steps_prompt(step_id, agent_state)  # 不包含标题的md格式文本
        md_output.append(f"{history_steps}\n")

        # 5. 持续性记忆提示词
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


    def get_execute_output(
        self,
        step_id: str,
        agent_state: Dict[str, Any],
        update_agent_situation: str,
        shared_step_situation: str,
        agent_completion_summary: str,
    ) -> Dict[str, Any]:
        '''
        构造Summary技能的execute_output。这部分使用代码固定构造，不由LLM输出构造。
        1. update_agent_situation:
            通过update_stage_agent_state字段指导sync_state更新stage_state.every_agent_state中自己的状态
        2. shared_step_situation:
            添加步骤信息到task共享消息池
        '''
        execute_output = {}

        # 1. 通过update_stage_agent_state字段指导sync_state更新stage_state.every_agent_state中自己的状态
        # 获取当前步骤的task_id与stage_id
        step_state = agent_state["agent_step"].get_step(step_id)[0]
        task_id = step_state.task_id
        stage_id = step_state.stage_id
        # 构造execute_output
        execute_output["update_stage_agent_state"] = {
            "task_id": task_id,
            "stage_id": stage_id,
            "agent_id": agent_state["agent_id"],
            "state": update_agent_situation,
        }

        # 2. 添加步骤信息到task共享消息池
        execute_output["send_shared_message"] = {
            "agent_id": agent_state["agent_id"],
            "role": agent_state["role"],
            "stage_id": stage_id,
            "content": f"执行Think步骤:{shared_step_situation}，"
        }

        return execute_output


    def execute(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        Think技能的具体执行方法:

        1. 组装 LLM Think 提示词
        2. LLM调用
        3. 解析 LLM 返回的思考信息
        4. 解析persistent_memory并追加到Agent持续性记忆中
        5. 构造并返回 execute_output:
        '''

        # step状态更新为 running
        agent_state["agent_step"].update_step_status(step_id, "running")

        # 1. 组装 LLM Think 提示词 (基础提示词与技能提示词)
        think_step_prompt = self.get_think_prompt(step_id, agent_state)  # 包含 # 一级标题的md格式文本
        print(think_step_prompt)
        # 2. LLM调用
        llm_config = agent_state["llm_config"]
        llm_client = LLMClient(llm_config)  # 创建 LLM 客户端
        chat_context = LLMContext(context_size=15)  # 创建一个对话上下文, 限制上下文轮数 15

        chat_context.add_message("assistant", "好的，我会作为你提供的Agent角色，执行think操作。"
                                              "我会遵从当前的步骤意图，参考 history_step 信息完成思考。"
                                              "并在<_think>和</_think>之间输出规划结果，"
                                              "在<persistent_memory>和</persistent_memory>之间输出我要追加的持续性记忆。")
        response = llm_client.call(
            think_step_prompt,
            context=chat_context
        )

        # 3. 解析 LLM 返回的思考结果
        think = self.extract_think(response)

        # 如果无法解析到思考结果，说明LLM没有按格式返回思考结果
        if not think:
            # step状态更新为 failed
            agent_state["agent_step"].update_step_status(step_id, "failed")
            # 构造execute_output用于更新自己在stage_state.every_agent_state中的状态
            execute_output = self.get_execute_output(
                step_id,
                agent_state,
                update_agent_situation="failed",
                shared_step_situation="failed",
            )
            return execute_output

        else:  # 解析到思考结果
            # 记录think结果到execute_result
            step = agent_state["agent_step"].get_step(step_id)[0]
            execute_result = {"think": think}  # 构造符合execute_result格式的执行结果
            step.update_execute_result(execute_result)

            # 4. 解析persistent_memory并追加到Agent持续性记忆中
            new_persistent_memory = self.extract_persistent_memory(response)
            agent_state["persistent_memory"] += "\n" + new_persistent_memory

            # step状态更新为 finished
            agent_state["agent_step"].update_step_status(step_id, "finished")

            # 5. 构造execute_output，用于更新stage_state.every_agent_state
            execute_output = self.get_execute_output(
                step_id,
                agent_state,
                update_agent_situation="finished",
                shared_step_situation="finished",
            )

            # 清空对话历史
            chat_context.clear()
            return execute_output

# Debug
if __name__ == "__main__":
    '''
    测试think需在Allen根目录下执行 python -m mas.skills.think
    '''
    from mas.agent.configs.llm_config import LLMConfig

    print("测试Think技能的调用")
    agent_state = {
        "agent_id": "0001",
        "name": "小灰",
        "role": "合同提取专员",
        "profile": "负责合同提取，将合同内容按字段提取录入系统",
        "working_state": "idle",
        "llm_config": LLMConfig.from_yaml("mas/role_config/qwq32b.yaml"),
        "working_memory": {},
        "persistent_memory": "",
        "agent_step": AgentStep("0001"),
        "skills": ["planning", "reflection", "summary",
                   "instruction_generation", "quick_think", "think"],
        "tools": [],
    }

    # 构造虚假的历史步骤
    step1 = StepState(
        task_id="task_001",
        stage_id="stage_001",
        agent_id="0001",
        step_intention="使用计算器计算数值",
        step_type="tools",
        executor="calculator",
        text_content="使用计算机计算1024*1024",
        execute_result={
            "calculate":[
                {
                    "operation": "1024*1024",
                    "result": "1048576",
                },
            ]
        },
    )
    step2 = StepState(
        task_id="task_001",
        stage_id="stage_001",
        agent_id="0001",
        step_intention="进行思考解释计算结果",
        step_type="skill",
        executor="think",
        text_content="详细解释1024*1024等于多少以及为什么",
        execute_result={},
    )

    agent_state["agent_step"].add_step(step1)
    agent_state["agent_step"].add_step(step2)

    step_id = agent_state["agent_step"].step_list[1].step_id  # 当前为第二个step

    think_skill = ThinkSkill()
    think_skill.execute(step_id, agent_state)

    # 打印step信息
    agent_state["agent_step"].print_all_steps()


























