'''
技能名称: Decision
期望作用: 一种更自由的即时的决策技能。
    Decision技能与Stage解耦，不再依赖Stage的状态来进行决策。同时Decision规划的步骤均以插入形式添加而非在末尾追加。

与其他决策技能的区别:
- Decision技能不依赖Stage的状态来进行决策。Decision决策自由度更高，能够更自由的应对非任务相关的决策，例如突发的消息回复
- Decision技能的规划步骤以插入形式添加，而非在末尾追加。Decision决策的步骤优先级更高

提示词顺序（系统 → 角色 → (目标 → 规则) → 记忆）

具体实现:
    1. 组装提示词:
        1.1 MAS系统提示词（# 一级标题）
        1.2 Agent角色:（# 一级标题）
            1.2.1 Agent角色背景提示词（## 二级标题）
            1.2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        1.3 decision step:（# 一级标题）
            1.3.1 step.step_intention 当前步骤的简要意图
            1.3.2 step.text_content 具体目标
            1.3.3 技能规则提示(decision_config["use_prompt"])
        1.4 历史步骤执行结果（# 一级标题）
        1.5 持续性记忆:（# 一级标题）
            1.5.1 Agent持续性记忆说明提示词（## 二级标题）
            1.5.2 Agent持续性记忆内容提示词（## 二级标题）

    2. llm调用
    3. 解析llm返回的步骤信息，更新AgentStep中的步骤列表
    4. 解析llm返回的持续性记忆信息，追加到Agent的持续性记忆中
    5. 返回用于指导状态同步的execute_output
'''
import re
import json
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union

from mas.agent.base.executor_base import Executor
from mas.agent.base.llm_base import LLMContext, LLMClient
from mas.agent.state.step_state import StepState, AgentStep



# 注册规划技能到类型 "skill", 名称 "decision"
@Executor.register(executor_type="skill", executor_name="decision")
class DecisionSkill(Executor):
    def __init__(self):
        super().__init__()  # 调用父类的构造方法

    def extract_decision_step(self, text: str) -> Optional[List[Dict[str, Any]]]:
        '''
        从LLM返回中解析决策步骤
        '''
        # 使用正则表达式提取 <decision_step> ... </decision_step> 之间的内容
        matches = re.findall(r"<decision_step>\s*(.*?)\s*</decision_step>", text, re.DOTALL)

        if matches:
            step_content = matches[-1]  # 获取最后一个匹配内容 排除是在<think></think>思考期间的内容
            # print("解析json：",step_content)
            try:
                # 将字符串解析为 Python 列表
                decision_step = json.loads(step_content)
                return decision_step
            except json.JSONDecodeError:
                print("解析 JSON 失败，请检查格式")
                return None
        else:
            print("未找到 <decision_step> 标记")
            return None

    def get_decision_prompt(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        组装提示词:
        1 MAS系统提示词（# 一级标题）
        2 Agent角色:（# 一级标题）
            2.1 Agent角色背景提示词（## 二级标题）
            2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        3 decision step:（# 一级标题）
            3.1 step.step_intention 当前步骤的简要意图
            3.2 step.text_content 具体目标
            3.3 技能规则提示(decision_config["use_prompt"])
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
                                                                    agent_state["tools"])  # 包含###三级标题的md
        md_output.append(f"## 角色可用技能与工具 available_skills_and_tools\n"
                         f"{available_skills_and_tools}\n")

        # 3. Decision step提示词
        md_output.append(f"# 当前需要执行的步骤 current_step\n")
        current_step = self.get_current_skill_step_prompt(step_id, agent_state)  # 不包含标题的md格式文本
        md_output.append(f"{current_step}\n")

        # 4. 历史步骤（包括已执行和待执行）执行结果
        md_output.append(f"# 历史步骤（包括已执行和待执行） history_step\n")
        history_steps = self.get_history_steps_prompt(step_id, agent_state)  # 不包含标题的md格式文本
        md_output.append(f"{history_steps}\n")

        # 5. 持续性记忆提示词
        md_output.append("# 持续性记忆persistent_memory\n")
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
        构造Decision技能的execute_output。这部分使用代码固定构造，不由LLM输出构造。
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
            "content": f"执行Decision步骤:{shared_step_situation}，"
        }

        return execute_output

    def execute(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        Decision技能的具体执行方法:
        (step_state需要在execute内完成更新)

        1. 组装 LLM Decision 提示词
        2. LLM调用
        3. 规则判定：
            保证Decision的多个step不超出Agent的权限范畴。如果超出，给出提示并重新 <2. LLM调用> 进行规划
        4. 记录规划结果到execute_result，并更新AgentStep中的步骤列表
        5. 解析persistent_memory并追加到Agent持续性记忆中
        6. 构造execute_output用于指导sync_state更新stage_state.every_agent_state中自己的状态
        '''

        # step状态更新为 running
        agent_state["agent_step"].update_step_status(step_id, "running")

        # 1. 组装 LLM Decision 提示词 (基础提示词与技能提示词)
        decision_step_prompt = self.get_decision_prompt(step_id, agent_state)  # 包含 # 一级标题的md格式文本

        # 2. LLM调用
        llm_config = agent_state["llm_config"]
        llm_client = LLMClient(llm_config)  # 创建 LLM 客户端
        chat_context = LLMContext(context_size=15)  # 创建一个对话上下文, 限制上下文轮数 15

        chat_context.add_message("assistant", "好的，我会作为你提供的Agent角色，执行decision操作，"
                                              "根据上文current_step的要求使用available_skills_and_tools中提供的权限规划后续step，"
                                              "并在<decision_step>和</decision_step>之间输出规划结果，"
                                              "在<persistent_memory>和</persistent_memory>之间输出我要追加或删除的持续性记忆指令(如果我认为不需要变更我会空着)，")

        response = llm_client.call(
            decision_step_prompt,
            context=chat_context
        )
        # print(f"[Debug][Decision] LLM返回:\n{response}\n")

        # 3. 规则判定
        # 结构化输出判定，保证决策追加的步骤结果位于<decision_step>和</decision_step>之间，
        if "<decision_step>" not in response or "</decision_step>" not in response:
            print("[Skill][decision] 未返回<decision_step>，正在重新规划...")
            response = llm_client.call(
                f"**决策结果首尾用<decision_step>和</decision_step>标记，不要将其放在代码块或其他地方，否则将无法被系统识别。**",
                context=chat_context
            )

        # 解析decision_step内容
        decision_step = self.extract_decision_step(response)

        # 如果没有解析到有效的decision_step内容，说明LLM没有返回有效的决策步骤
        if not decision_step:
            # step状态更新为 failed
            agent_state["agent_step"].update_step_status(step_id, "failed")
            # 记录失败的LLM输出到execute_result
            step = agent_state["agent_step"].get_step(step_id)[0]
            execute_result = {"llm_response": response}  # execute_result记录失败的llm输出
            step.update_execute_result(execute_result)
            # 构造execute_output用于更新自己在stage_state.every_agent_state中的状态
            execute_output = self.get_execute_output(step_id, agent_state, update_agent_situation="failed",
                                                     shared_step_situation="failed")
            return execute_output

        else: # 解析到决策步骤
            # 技能与工具权限判定，保证Decision的多个step不超出Agent的权限范畴
            not_allowed_executors = [
                step["executor"]
                for step in decision_step
                # 是skill则查找是否位于skills中，是tool则查找是否位于tools中，否则将step["executor"]追加进列表
                if (step["type"] == "skill" and step["executor"] not in agent_state["skills"])
                   or (step["type"] == "tool" and step["executor"] not in agent_state["tools"])
            ]
            if len(not_allowed_executors) != 0:  # 如果超出，给出提示并重新 <2. LLM调用> 进行规划
                print("Decision技能增加的步骤中包含不在使用权限内的技能与工具，正在重新决策...")
                response = llm_client.call(
                    f"以下技能与工具不在使用权限内:{not_allowed_executors}。请确保只使用 available_skills_and_tools 小节中提示的可用技能与工具来添加决策step。**规划结果放在<decision_step>和</decision_step>之间。**",
                    context=chat_context
                )
                decision_step = self.extract_decision_step(response)

                # 4. 记录decision反思结果到execute_result，并更新AgentStep中的步骤列表（以插入形式）
                step = agent_state["agent_step"].get_step(step_id)[0]
                execute_result = {"decision_step": decision_step}  # 构造符合execute_result格式的执行结果
                step.update_execute_result(execute_result)
                # 更新AgentStep中的步骤列表
                self.add_next_step(decision_step, step_id, agent_state)  # 将规划的步骤列表插入到AgentStep中

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
    测试decision需在Allen根目录下执行 python -m mas.skills.decision
    '''
    from mas.agent.configs.llm_config import LLMConfig

    print("测试Decision技能的调用")
    agent_state = {
        "agent_id": "0001",
        "name": "小灰",
        "role": "合同提取专员",
        "profile": "负责合同提取，将合同内容按字段提取录入系统",
        "working_state": "idle",
        "llm_config": LLMConfig.from_yaml("mas/role_config/doubao.yaml"),
        "working_memory": {},
        "persistent_memory": {
            "15153252":"我需要获取agent_id为0002的Agent的详细信息，并将其发送给用户（agent_id：0003）",
        },
        "agent_step": AgentStep("0001"),
        "skills": [
            "planning", "reflection", "summary", "instruction_generation", "quick_think", "think",
            "tool_decision", "send_message", "process_message",
            "task_manager", "agent_manager", "ask_info"
        ],
        "tools": [],
    }

    # 构造虚假的历史步骤
    step1 = StepState(
        task_id="task_001",
        stage_id="no_relative",
        agent_id="0001",
        step_intention="获取Agent详细信息",
        type="skill",
        executor="decision",
        execution_state="init",
        text_content="获取agent_id：0003的Agent详细信息，重点关注其技能与工具权限",
        execute_result={},
    )
    step2 = StepState(
        task_id="task_001",
        stage_id="no_relative",
        agent_id="0001",
        step_intention="发送Agent详细信息给用户",
        type="skill",
        executor="send_message",
        execution_state="init",
        text_content="用户的agent_id：0003，你需要获取的Agent的详细信息的agent_id:0002",
        execute_result={},
    )

    agent_state["agent_step"].add_step(step1)
    agent_state["agent_step"].add_step(step2)

    step_id = agent_state["agent_step"].step_list[0].step_id  # 当前为第一个step

    decision_skill = DecisionSkill()
    decision_skill.execute(step_id, agent_state)
    # 打印step信息
    print("\n[Debug] Decision技能执行后，AgentStep中的步骤信息:\n")
    agent_state["agent_step"].print_all_steps()








