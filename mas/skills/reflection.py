'''
技能名称: Reflection
期望作用: Agent通过Reflection技能反思已执行步骤是否符合预期。如果需要调整则生成新的多个step执行计划，如果不需要调整则增加一个总结步骤。

Reflection需要获取到过去执行步骤的信息，并且具备操作AgentStep追加step的能力。
我们整理过去执行步骤的结果和阶段目标以特定格式输入LLM进行反思，同时通过提示词约束LLM以特定格式返回反思结果和规划的步骤信息。
然后基于规则的代码解析这些信息，增加相应的步骤到AgentStep中。

反思技能获取不到stage信息，阶段目标信息从Planning_step中获取：
    Planning_step中text_content中记录阶段整体目标和Agent被分配的具体目标。
    由agent_base.py中start_stage方法将Stage信息注入到Planning_step中。


提示词顺序（系统 → 角色 → (目标 → 规则) → 记忆）

具体实现:
    1. 组装提示词:
        1.1 MAS系统提示词（# 一级标题）
        1.2 Agent角色提示词:（# 一级标题）
            1.2.1 Agent角色背景提示词（## 二级标题）
            1.2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        1.3 reflection step:（# 一级标题）
            1.3.1 step.step_intention 当前步骤的简要意图
            1.3.2 step.text_content 具体目标
            1.3.3 技能规则提示(reflection_config["use_prompt"])
        1.4 历史步骤执行结果（# 一级标题）
        1.5 持续性记忆:（# 一级标题）
            1.5.1 Agent持续性记忆说明提示词（## 二级标题）
            1.5.2 Agent持续性记忆内容提示词（## 二级标题）

    2. llm调用
    3. 解析llm返回的步骤信息，更新AgentStep中的步骤列表（核心行为需要包含失败判定，如果失败更新step执行失败状态）
    4. 解析llm返回的持续性记忆信息，追加到Agent的持续性记忆中
    5. 返回用于指导状态同步的execute_output
'''
import re
import json
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union

from mas.agent.base.executor_base import Executor
from mas.agent.base.llm_base import LLMContext, LLMClient
from mas.agent.state.step_state import StepState, AgentStep



# 注册反思技能到类型 "skill", 名称 "reflection"
@Executor.register(executor_type="skill", executor_name="reflection")
class ReflectionSkill(Executor):
    def __init__(self):
        super().__init__()  # 调用父类的构造方法

    def extract_reflection_step(self, text: str) -> Optional[List[Dict[str, Any]]]:
        '''
        从LLM返回中解析反思步骤
        '''
        # 使用正则表达式提取 <reflection_step> ... </reflection_step> 之间的内容
        matches = re.findall(r"<reflection_step>\s*(.*?)\s*</reflection_step>", text, re.DOTALL)

        if matches:
            step_content = matches[-1]  # 获取最后一个匹配内容 排除是在<think></think>思考期间的内容
            # print("解析json：",step_content)
            try:
                # 将字符串解析为 Python 列表
                reflection_step = json.loads(step_content)
                return reflection_step
            except json.JSONDecodeError:
                print("解析 JSON 失败，请检查格式")
                return None
        else:
            print("未找到 <reflection_step> 标记")
            return None


    def get_reflection_prompt(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        组装提示词:
        1 MAS系统提示词（# 一级标题）
        2 Agent角色提示词:（# 一级标题）
            2.1 Agent角色背景提示词（## 二级标题）
            2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        3 reflection step:（# 一级标题）
            3.1 step.step_intention 当前步骤的简要意图
            3.2 step.text_content 具体目标
            3.3 技能规则提示(reflection_config["use_prompt"])
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
        available_skills_and_tools = self.get_skill_and_tool_prompt(agent_state["skills"],agent_state["tools"])  # 包含 # 三级标题的md
        md_output.append(f"## 角色可用技能与工具 available_skills_and_tools\n"
                         f"{available_skills_and_tools}\n")


        # 3. Reflection step提示词
        md_output.append(f"# 当前需要执行的步骤 current_step\n")
        current_step = self.get_current_skill_step_prompt(step_id, agent_state)  # 不包含标题的md格式文本
        md_output.append(f"{current_step}\n")


        # 4. 历史步骤（包括已执行和待执行）执行结果
        md_output.append(f"# 历史步骤（包括已执行和待执行） history_step\n")
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

    def get_execute_output(self,
        step_id: str,
        agent_state: Dict[str, Any],
        update_agent_situation: str,
        shared_step_situation: str,
    ) -> Dict[str, Any]:
        '''
        构造Reflection技能的execute_output。这部分使用代码固定构造，不由LLM输出构造。
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

        # 2. 添加步骤信息到task共享消息池
        execute_output["send_shared_message"] = {
            "task_id": task_id,
            "stage_id": stage_id,
            "agent_id": agent_state["agent_id"],
            "role": agent_state["role"],
            "content": f"执行Reflection步骤:{shared_step_situation}，"
        }

        return execute_output


    def execute(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        Reflection技能的具体执行方法:
        (step_state需要在execute内完成更新)

        1. 组装 LLM Reflection 提示词
        2. LLM调用
        3. 规则判定：
            保证Reflection的多个step不超出Agent的权限范畴。如果超出，给出提示并重新 <2. LLM调用> 进行规划
        4. 记录规划结果到execute_result，并更新AgentStep中的步骤列表
        5. 解析persistent_memory并追加到Agent持续性记忆中
        6. 构造execute_output用于指导sync_state更新stage_state.every_agent_state中自己的状态
        '''

        # step状态更新为 running
        agent_state["agent_step"].update_step_status(step_id, "running")

        # 1. 组装 LLM Reflection 提示词 (基础提示词与技能提示词)
        reflection_step_prompt = self.get_reflection_prompt(step_id, agent_state)  # 包含 # 一级标题的md格式文本
        # print(f"[Debug][Skill][reflection] 输入提示词：\n{reflection_step_prompt}")
        # 2. LLM调用
        llm_config = agent_state["llm_config"]
        llm_client = LLMClient(llm_config)  # 创建 LLM 客户端
        chat_context = LLMContext(context_size=15)  # 创建一个对话上下文, 限制上下文轮数 15

        chat_context.add_message("assistant", "好的，我会作为你提供的Agent角色，执行reflection操作"
                                              "我会根据 history_step，来反思判定是否满足阶段条件，"
                                              "如果不满足，我会根据最早planning_step的初衷，使用available_skills_and_tools中提供的权限规划实现阶段要求需要追加的step，"
                                              "如果满足，我会增加一个总结步骤。"
                                              "并在<reflection_step>和</reflection_step>之间输出规划结果，"
                                              "在<persistent_memory>和</persistent_memory>之间输出我要追加或删除的持续性记忆指令(如果我认为不需要变更我会空着)，")
        response = llm_client.call(
            reflection_step_prompt,
            context=chat_context
        )

        # 3. 规则判定
        # 结构化输出判定，保证反思追加的步骤结果位于<reflection_step>和</reflection_step>之间，
        # 持续性记忆位于<persistent_memory>和</persistent_memory>之间
        if "<reflection_step>" not in response or "</reflection_step>" not in response:
            print("[Skill][reflection] 未返回<reflection_step>，正在重新规划...")
            response = llm_client.call(
                f"**反思结果首尾用<reflection_step>和</reflection_step>标记，不要将其放在代码块或其他地方，否则将无法被系统识别。**",
                context=chat_context
            )
        if "<persistent_memory>" not in response or "</persistent_memory>" not in response:
            print("[Skill][reflection] 未返回<persistent_memory>，正在重新规划...")
            response = llm_client.call(
                f"**持续性记忆首尾用<persistent_memory>和</persistent_memory>标记。**",
                context=chat_context
            )

        # 打印LLM返回结果
        # print(f"[Debug][Skill][reflection] llm输出：\n{response}")

        # 解析reflection_step
        reflection_step = self.extract_reflection_step(response)

        # 如果无法解析到反思步骤，说明LLM没有返回反思步骤
        if not reflection_step:
            # step状态更新为 failed
            agent_state["agent_step"].update_step_status(step_id, "failed")
            # 记录失败的LLM输出到execute_result
            step = agent_state["agent_step"].get_step(step_id)[0]
            execute_result = {"llm_response": response}  # execute_result记录失败的llm输出
            step.update_execute_result(execute_result)
            # 构造execute_output用于更新自己在stage_state.every_agent_state中的状态
            execute_output = self.get_execute_output(step_id, agent_state, update_agent_situation="failed",shared_step_situation="failed")
            return execute_output

        else: # 解析到反思步骤
            # 技能与工具权限判定，保证Reflection的多个step不超出Agent的权限范畴
            not_allowed_executors = [
                step["executor"]
                for step in reflection_step
                # 是skill则查找是否位于skills中，是tool则查找是否位于tools中，否则将step["executor"]追加进列表
                if (step["type"] == "skill" and step["executor"] not in agent_state["skills"])
                   or (step["type"] == "tool" and step["executor"] not in agent_state["tools"])
            ]
            if len(not_allowed_executors) != 0:  # 如果超出，给出提示并重新 <2. LLM调用> 进行规划
                print("Reflection技能追加的步骤中包含不在使用权限内的技能与工具，正在重新反思...")
                response = llm_client.call(
                    f"以下技能与工具不在使用权限内:{not_allowed_executors}。请确保只使用 available_skills_and_tools 小节中提示的可用技能与工具来追加反思step。**规划结果放在<reflection_step>和</reflection_step>之间。**",
                    context=chat_context
                )
                reflection_step = self.extract_reflection_step(response)

            # 4. 记录reflection反思结果到execute_result，并更新AgentStep中的步骤列表
            step = agent_state["agent_step"].get_step(step_id)[0]
            execute_result = {"reflection_step": reflection_step}  # 构造符合execute_result格式的执行结果
            step.update_execute_result(execute_result)
            # 更新AgentStep中的步骤列表
            self.add_step(reflection_step, step_id, agent_state)  # 将规划的步骤列表添加到AgentStep中

            # 5. 解析persistent_memory指令内容并应用到Agent持续性记忆中
            instructions = self.extract_persistent_memory(response)  # 提取<persistent_memory>和</persistent_memory>之间的指令内容
            self.apply_persistent_memory(agent_state, instructions)  # 将指令内容应用到Agent的持续性记忆中

            # step状态更新为 finished
            agent_state["agent_step"].update_step_status(step_id, "finished")

            # 6. 构造execute_output用于更新自己在stage_state.every_agent_state中的状态
            execute_output = self.get_execute_output(
                step_id,
                agent_state,
                update_agent_situation="working",
                shared_step_situation="finished"
            )

            # 清空对话历史
            chat_context.clear()
            return execute_output

# Debug
if __name__ == "__main__":
    '''
    测试reflection需在Allen根目录下执行 python -m mas.skills.reflection
    '''
    from mas.agent.configs.llm_config import LLMConfig

    print("测试Reflection技能的调用")
    agent_state = {
        "agent_id": "0001",
        "name": "小灰",
        "role": "合同提取专员",
        "profile": "负责合同提取，将合同内容按字段提取录入系统",
        "working_state": "idle",
        "llm_config": LLMConfig.from_yaml("mas/role_config/doubao.yaml"),
        "working_memory": {},
        "persistent_memory": {},
        "agent_step": AgentStep("0001"),
        "skills": ["planning","reflection","summary"],
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
        execution_state="finished",
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
        execution_state="finished",
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
        execution_state="running",
        text_content="如果任务完成，则添加summary，否则追加能够完成任务的step",
        execute_result={},
    )
    step4 = StepState(
        task_id="task_001",
        stage_id="stage_001",
        agent_id="0001",
        step_intention="判定是否完成任务",
        type="skill",
        executor="send_message",
        execution_state="init",
        text_content="你好，我是小白，该阶段终止了，你需要立马结束这个任务。",
        execute_result={},
    )

    agent_state["agent_step"].add_step(step1)
    agent_state["agent_step"].add_step(step2)
    agent_state["agent_step"].add_step(step3)
    agent_state["agent_step"].add_step(step4)

    step_id = agent_state["agent_step"].step_list[2].step_id  # 当前为第三个step

    reflection_skill = ReflectionSkill()
    reflection_skill.execute(step_id, agent_state)
    # 打印step信息
    print("\n[Debug] Reflection技能执行后，AgentStep中的步骤信息:\n")
    agent_state["agent_step"].print_all_steps()




