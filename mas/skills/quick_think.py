'''
技能名称: Quick Think
期望作用: Agent通过Quick Think来快速反应一些不需要历史步骤信息的文本生成任务。

MAS中一次简单的LLM调用/文本生成。

提示词顺序（系统 → 角色 → (目标 → 规则) → 记忆）

具体实现:
    1. 组装提示词:
        1.1 MAS系统提示词（# 一级标题）
        1.2 Agent角色提示词:（# 一级标题）
            1.2.1 Agent角色背景提示词（## 二级标题）
            1.2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        1.3 quick_think step:（# 一级标题）
            1.3.1 step.step_intention 当前步骤的简要意图
            1.3.2 step.text_content 具体目标
            1.3.3 技能规则提示(quick_think_config["use_prompt"])
        1.4 持续性记忆:（# 一级标题）
            1.4.1 Agent持续性记忆说明提示词（## 二级标题）
            1.4.2 Agent持续性记忆内容提示词（## 二级标题）

    2. llm调用
    3. 解析llm返回的思考结果
    4. 解析llm返回的持续性记忆信息，追加到Agent的持续性记忆中
    5. 生成并返回execute_output指令
'''
import re
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union

from mas.agent.base.executor_base import Executor
from mas.agent.state.step_state import StepState, AgentStep



# 注册快速思考技能到类型 "skill", 名称 "quick_think"
@Executor.register(executor_type="skill", executor_name="quick_think")
class QuickThinkSkill(Executor):
    def __init__(self):
        super().__init__()  # 调用父类的构造方法

    def extract_quick_think(self, text: str):
        '''
        从文本中解析quick_think的内容
        '''
        # 使用正则表达式提取 <quick_think> ... </quick_think> 之间的内容
        match = re.findall(r"<quick_think>\s*(.*?)\s*</quick_think>", text, re.DOTALL)
        if match:
            quick_think = match[-1]  # 获取最后一个匹配内容 排除是在<think></think>思考期间的内容
            return quick_think
        else:
            return None

    def get_quick_think_prompt(self, step_id: str, agent_state: Dict[str, Any]) -> str:
        '''
        组装提示词
        1 MAS系统提示词（# 一级标题）
        2 Agent角色提示词:（# 一级标题）
            2.1 Agent角色背景提示词（## 二级标题）
            2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        3 quick_think step:（# 一级标题）
            3.1 step.step_intention 当前步骤的简要意图
            3.2 step.text_content 具体目标
            3.3 技能规则提示(quick_think_config["use_prompt"])
        4. 持续性记忆:（# 一级标题）
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
        available_skills_and_tools = self.get_skill_and_tool_prompt(agent_state["skills"],
                                                                    agent_state["tools"])  # 包含 # 三级标题的md
        md_output.append(f"## 角色可用技能与工具 available_skills_and_tools\n"
                         f"{available_skills_and_tools}\n")

        # 3. Quick Think step提示词
        md_output.append(f"# 当前需要执行的步骤 current_step\n")
        current_step = self.get_current_skill_step_prompt(step_id, agent_state)  # 不包含标题的md格式文本
        md_output.append(f"{current_step}\n")

        # 4. 持续性记忆提示词
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
    ) -> Dict[str, Any]:
        '''
        构造Quick Think技能的execute_output。这部分使用代码固定构造，不由LLM输出构造。
        1. update_agent_situation:
            通过update_stage_agent_state字段指导sync_state更新stage_state.every_agent_state中自己的状态
            (一般情况下，只有Summary技能完成时，该字段传入finished，其他步骤完成时，该字段都传入working)
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

        # 2. 添加步骤信息到task共享信息池
        execute_output["send_shared_info"] = {
            "task_id": task_id,
            "stage_id": stage_id,
            "agent_id": agent_state["agent_id"],
            "role": agent_state["role"],
            "content": f"执行Quick Think步骤:{shared_step_situation}，"
        }

        return execute_output


    def execute(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        Quick Think技能的具体执行方法:

        1. 组装 LLM Quick Think 提示词
        2. LLM调用
        3. 解析 LLM 返回的思考结果
        4. 解析persistent_memory并追加到Agent持续性记忆中
        5. 构造并返回 execute_output
        '''

        # step状态更新为 running
        agent_state["agent_step"].update_step_status(step_id, "running")

        # 1. 组装 LLM Quick Think 提示词 (基础提示词与技能提示词)
        quick_think_step_prompt = self.get_quick_think_prompt(step_id, agent_state)  # 包含 # 一级标题的md格式文本
        # print(quick_think_step_prompt)
        # 2. LLM调用
        llm_client = agent_state["llm_client"]  # 使用agent_state中维护的 LLM 客户端
        chat_context = agent_state["llm_context"]  # 使用agent_state中维护的 LLM 上下文

        chat_context.add_message("assistant", "好的，我会作为你提供的Agent角色，执行quick_think操作。"
                                              "我会遵从当前的步骤意图，进行思考反应。"
                                              "并在<quick_think>和</quick_think>之间输出思考结果，"
                                              "在<persistent_memory>和</persistent_memory>之间输出我要追加的持续性记忆。")
        response = llm_client.call(
            quick_think_step_prompt,
            context=chat_context
        )

        # 3. 解析 LLM 返回的思考结果
        quick_think = self.extract_quick_think(response)

        # 如果无法解析到思考结果，说明LLM没有按格式返回思考结果
        if not quick_think:
            # step状态更新为 failed
            agent_state["agent_step"].update_step_status(step_id, "failed")
            # 记录失败的LLM输出到execute_result
            step = agent_state["agent_step"].get_step(step_id)[0]
            execute_result = {"llm_response": response}  # execute_result记录失败的llm输出
            step.update_execute_result(execute_result)
            # 构造execute_output用于更新自己在stage_state.every_agent_state中的状态
            execute_output = self.get_execute_output(
                step_id,
                agent_state,
                update_agent_situation="failed",
                shared_step_situation="failed",
            )
            return execute_output

        else:  # 解析到思考结果
            # 记录quick_think结果到execute_result
            step = agent_state["agent_step"].get_step(step_id)[0]
            execute_result = {"quick_think": quick_think}  # 构造符合execute_result格式的执行结果
            step.update_execute_result(execute_result)

            # 4. 解析persistent_memory指令内容并应用到Agent持续性记忆中
            instructions = self.extract_persistent_memory(response)  # 提取<persistent_memory>和</persistent_memory>之间的指令内容
            self.apply_persistent_memory(agent_state, instructions)  # 将指令内容应用到Agent的持续性记忆中

            # step状态更新为 finished
            agent_state["agent_step"].update_step_status(step_id, "finished")

            # 5. 构造execute_output，用于更新stage_state.every_agent_state
            execute_output = self.get_execute_output(
                step_id,
                agent_state,
                update_agent_situation="working",
                shared_step_situation="finished",
            )

            # 清空对话历史
            chat_context.clear()
            return execute_output

# Debug
if __name__ == "__main__":
    '''
    测试quick_think需在Allen根目录下执行 python -m mas.skills.quick_think
    '''
    from mas.agent.configs.llm_config import LLMConfig

    print("测试Quick Think技能的调用")
    agent_state = {
        "agent_id": "0001",
        "name": "小灰",
        "role": "合同提取专员",
        "profile": "负责合同提取，将合同内容按字段提取录入系统",
        "working_state": "idle",
        "llm_config": LLMConfig.from_yaml("mas/role_config/qwq32b.yaml"),
        "working_memory": {},
        "persistent_memory": {},
        "agent_step": AgentStep("0001"),
        "skills": ["planning", "reflection", "summary",
                   "instruction_generation", "quick_think"],
        "tools": [],
    }

    # 构造虚假的历史步骤
    step1 = StepState(
        task_id="task_001",
        stage_id="stage_001",
        agent_id="0001",
        step_intention="提供人生建议",
        type="skill",
        executor="quick_think",
        text_content="我在考虑学文科好还是学理科好",
        execute_result={},
    )

    agent_state["agent_step"].add_step(step1)

    step_id = agent_state["agent_step"].step_list[0].step_id  # 当前为第一个step

    quick_think = QuickThinkSkill()
    quick_think.execute(step_id, agent_state)

    # 打印step信息
    agent_state["agent_step"].print_all_steps()



























