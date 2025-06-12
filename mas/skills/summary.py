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
            1.3.1 step.step_intention 当前步骤的简要意图
            1.3.2 step.text_content 具体目标
            1.3.3 技能规则提示(summary_config["use_prompt"])
        1.4 历史步骤执行结果（# 一级标题）
        1.5 持续性记忆:（# 一级标题）
            1.5.1 Agent持续性记忆说明提示词（## 二级标题）
            1.5.2 Agent持续性记忆内容提示词（## 二级标题）

    2. llm调用
    3. 解析llm返回的总结信息
    4. 解析llm返回的持续性记忆信息，追加到Agent的持续性记忆中
    5. 生成并返回execute_output指令
        （更新stage_state.completion_summary的指令，更新stage_state.every_agent_state中自己的状态）
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

    def extract_summary(self, text: str):
        '''
        从文本中解析summary信息
        '''
        # 使用正则表达式提取 <summary> ... </summary> 之间的内容
        match = re.findall(r"<summary>\s*(.*?)\s*</summary>", text, re.DOTALL)
        if match:
            summary = match[-1] # 获取最后一个匹配内容 排除是在<think></think>思考期间的内容
            return summary
        else:
            return None

    def get_summary_prompt(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        组装提示词:
        1 MAS系统提示词（# 一级标题）
        2 Agent角色提示词:（# 一级标题）
            2.1 Agent角色背景提示词（## 二级标题）
            2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        3 summary step:（# 一级标题）
            3.1 step.step_intention 当前步骤的简要意图
            3.2 step.text_content 具体目标
            3.3 技能规则提示(summary_config["use_prompt"])
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

        # 3. Summary step提示词
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
            (一般情况下，只有Summary技能完成时，该字段传入finished，其他步骤完成时，该字段都传入working)
        2. shared_step_situation:
            添加步骤信息到task共享消息池
        3. agent_completion_summary:
            更新此Agent的阶段完成情况到stage_state.completion_summary
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
            "task_id": task_id,
            "stage_id": stage_id,
            "agent_id": agent_state["agent_id"],
            "role": agent_state["role"],
            "content": f"执行Summary步骤:{shared_step_situation}，"
        }

        # 3. 更新此Agent的阶段完成情况到stage_state.completion_summary
        execute_output["update_stage_agent_completion"] = {
            "task_id": task_id,
            "stage_id": stage_id,
            "agent_id": agent_state["agent_id"],
            "completion_summary": agent_completion_summary,
        }

        return execute_output


    def execute(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        Summary技能的具体执行方法:

        1. 组装 LLM Summary 提示词
        2. LLM调用
        3. 解析 LLM 返回的总结信息
        4. 解析persistent_memory并追加到Agent持续性记忆中
        5. 构造并返回 execute_output:
            （更新stage_state.completion_summary的指令,
            更新stage_state.every_agent_state中自己的状态)
        '''

        # step状态更新为 running
        agent_state["agent_step"].update_step_status(step_id, "running")

        # 1. 组装 LLM Summary 提示词 (基础提示词与技能提示词)
        summary_step_prompt = self.get_summary_prompt(step_id, agent_state)  # 包含 # 一级标题的md格式文本
        # print(summary_step_prompt)
        # 2. LLM调用
        llm_config = agent_state["llm_config"]
        llm_client = LLMClient(llm_config)  # 创建 LLM 客户端
        chat_context = LLMContext(context_size=15)  # 创建一个对话上下文, 限制上下文轮数 15

        chat_context.add_message("assistant", "好的，我会作为你提供的Agent角色，执行summary操作"
                                              "我会根据 history_step，来总结当前阶段完成情况，"
                                              "我的总结会包含关键的步骤信息，我会严格遵从你的skill_prompt技能指示。"
                                              "并在<summary>和</summary>之间输出规划结果，"
                                              "在<persistent_memory>和</persistent_memory>之间输出我要追加的持续性记忆(如果我认为不需要追加我会空着)。")
        response = llm_client.call(
            summary_step_prompt,
            context=chat_context
        )

        # 3. 解析 LLM 返回的总结信息
        summary = self.extract_summary(response)

        # 如果无法解析到总结信息，说明LLM没有按格式返回总结信息
        if not summary:
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
                agent_completion_summary="(任务完成情况总结失败)",
            )
            return execute_output

        else:  # 解析到总结信息
            # 记录summary结果到execute_result
            step = agent_state["agent_step"].get_step(step_id)[0]
            execute_result = {"summary": summary}  # 构造符合execute_result格式的执行结果
            step.update_execute_result(execute_result)

            # 4. 解析persistent_memory并追加到Agent持续性记忆中
            new_persistent_memory = self.extract_persistent_memory(response)
            agent_state["persistent_memory"] += "\n" + new_persistent_memory

            # step状态更新为 finished
            agent_state["agent_step"].update_step_status(step_id, "finished")

            # 5. 构造execute_output，用于更新stage_state.completion_summary和stage_state.every_agent_state
            execute_output = self.get_execute_output(
                step_id,
                agent_state,
                update_agent_situation="finished",
                shared_step_situation="finished",
                agent_completion_summary=summary
            )

            # 清空对话历史
            chat_context.clear()
            return execute_output

# Debug
if __name__ == "__main__":
    '''
    测试summary需在Allen根目录下执行 python -m mas.skills.summary
    '''
    from mas.agent.configs.llm_config import LLMConfig

    print("测试Summary技能的调用")
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
        "skills": ["planning", "reflection", "summary"],
        "tools": [],
    }

    # 构造虚假的历史步骤
    step1 = StepState(
        task_id="task_001",
        stage_id="stage_001",
        agent_id="0001",
        step_intention="将合同提取任务分解为多个步骤",
        type="skill",
        executor="planning",
        text_content="分析任务并制定执行计划",
        execute_result={
            "planned_step": [
                {
                    "step_intention": "获取合同信息",
                    "type": "skill",
                    "executor": "contract_extractor",
                    "text_content": "提取合同中的关键信息"
                },
                {
                    "step_intention": "判定是否完成任务",
                    "type": "skill",
                    "executor": "reflection",
                    "text_content": "如果任务完成，则添加summary，否则追加能够完成任务的step"
                }
            ]
        },
    )
    step2 = StepState(
        task_id="task_001",
        stage_id="stage_001",
        agent_id="0001",
        step_intention="获取合同信息",
        type="skill",
        executor="contract_extractor",
        text_content="提取合同中的关键信息",
        execute_result={
            "contract_key_word": "<测试文本（假设能满足阶段要求）>"
        },
    )
    step3 = StepState(
        task_id="task_001",
        stage_id="stage_001",
        agent_id="0001",
        step_intention="判定是否完成任务",
        type="skill",
        executor="reflection",
        text_content="如果任务完成，则添加summary，否则追加能够完成任务的step",
        execute_result={
            "reflection_step": '['
                               '{'
                               '"step_intention": "总结阶段执行结果",'
                               '"type": "skill",'
                               '"executor": "summary",'
                               '"text_content": "整理合同关键字段提取结果，并同步至阶段状态完成标记"'
                               '}'
                               ']'
        },
    )
    step4 = StepState(
        task_id="task_001",
        stage_id="stage_001",
        agent_id="0001",
        step_intention="总结阶段执行结果",
        type="skill",
        executor="summary",
        text_content="整理合同关键字段提取结果，并同步至阶段状态完成标记",
        execute_result={},
    )

    agent_state["agent_step"].add_step(step1)
    agent_state["agent_step"].add_step(step2)
    agent_state["agent_step"].add_step(step3)
    agent_state["agent_step"].add_step(step4)

    step_id = agent_state["agent_step"].step_list[3].step_id  # 当前为第四个step

    summery_skill = SummarySkill()
    summery_skill.execute(step_id, agent_state)

    # 打印step信息
    agent_state["agent_step"].print_all_steps()





















