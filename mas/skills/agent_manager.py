'''
技能名称: Agent Manager
期望作用: Agent对其他Agent的操控与调度。（一种特殊权限的技能，一般只有管理者Agent拥有）
    Agent Manager会参考自身历史步骤信息（前面步骤获取相关Agent信息），生成用于操控其他Agent的指令

任务管理者Agent会通过该技能生成相应操作的指令，指令会在MAS系统中操作对应组件完成实际行动，

说明:
1.创建一个新Agent:
    实例化一个新的Agent init_new_agent
    该操作会有管理Agent自主创建一个新Agent实例
    通过在SyncState中调用MultiAgentSystem的add_agent方法实现

2.将Agent添加到任务中:
    添加agent到任务群组中 add_task_participant
    该操作会为指定任务添加Agent，Agent会被添加到该任务的任务群组task_group中
    所有参与该任务的Agent都应当存在于该任务的任务群组中

提示词顺序（系统 → 角色 → (目标 → 规则) → 记忆）

具体实现:
    1. 组装提示词:
        1.1 MAS系统提示词（# 一级标题）
        1.2 Agent角色:（# 一级标题）
            1.2.1 Agent角色背景提示词（## 二级标题）
            1.2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        1.3 agent_manager step:（# 一级标题）
            1.3.1 step.step_intention 当前步骤的简要意图
            1.3.2 step.text_content 具体目标
            1.3.3 技能规则提示(agent_manager_config["use_prompt"])
        1.4 历史步骤执行结果（# 一级标题）
        1.5 持续性记忆:（# 一级标题）
            1.5.1 Agent持续性记忆说明提示词（## 二级标题）
            1.5.2 Agent持续性记忆内容提示词（## 二级标题）

    2. llm调用
    3. 解析llm返回的指令构造
    4. 解析llm返回的持续性记忆信息，追加到Agent的持续性记忆中
    5. 返回用于指导状态同步的execute_output
'''
import re
import json
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union

from mas.agent.base.executor_base import Executor
from mas.agent.state.step_state import StepState, AgentStep



# 注册规划技能到类型 "skill", 名称 "agent_manager"
@Executor.register(executor_type="skill", executor_name="agent_manager")
class AgentManagerSkill(Executor):
    def __init__(self):
        super().__init__()  # 调用父类的构造方法

    def extract_agent_instruction(self, text: str) -> Optional[Dict[str, Any]]:
        '''
        从文本中提取任务指令
        '''
        # 使用正则表达式提取<agent_instruction>和</agent_instruction>之间的内容
        matches = re.findall(r"<agent_instruction>\s*(.*?)\s*</agent_instruction>", text, re.DOTALL)

        if matches:
            agent_instruction = matches[-1]  # 获取最后一个匹配内容 排除是在<think></think>思考期间的内容

            try:
                agent_instruction_dict = json.loads(agent_instruction)
                return agent_instruction_dict
            except json.JSONDecodeError:
                print("JSON解析错误:", agent_instruction)
                return None
        else:
            print("没有找到<agent_instruction>标签")
            return None

    def get_agent_manager_prompt(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        组装提示词:
        1 MAS系统提示词（# 一级标题）
        2 Agent角色:（# 一级标题）
            2.1 Agent角色背景提示词（## 二级标题）
            2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        3 agent_manager step:（# 一级标题）
            3.1 step.step_intention 当前步骤的简要意图
            3.2 step.text_content 具体目标
            3.3 技能规则提示(agent_manager_config["use_prompt"])
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

        # 3. Agent Manager step提示词
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

    def get_execute_output(
        self,
        step_id: str,
        agent_state: Dict[str, Any],
        update_agent_situation: str,
        shared_step_situation: str,
        agent_instruction: Optional[Dict[str, Any]] = None,
    ):
        '''
        构造Task Manager技能的execute_output。这部分使用代码固定构造，不由LLM输出构造。
        1. update_agent_situation:
            通过update_stage_agent_state字段指导sync_state更新stage_state.every_agent_state中自己的状态
            (一般情况下，只有Summary技能完成时，该字段传入finished，其他步骤完成时，该字段都传入working)
        2. shared_step_situation:
            添加步骤信息到task共享消息池
        3. agent_instruction:
            包含多种不同操作行为，由sync_state完成Agent指令的解析与具体执行
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
            "content": f"执行Agent Manager步骤:{shared_step_situation}，"
        }

        # 3. 由sync_state完成agent操作指令的解析与具体执行
        if agent_instruction:
            agent_instruction["agent_id"] = agent_state["agent_id"]  # 在指令中添加自身agent_id
            execute_output["agent_instruction"] = agent_instruction
            # 此时task_instruction中包含"agent_id","action"和其他具体操作指令涉及的字段

        return execute_output


    def execute(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        Agent Manager技能的具体执行方法:

        1. 组装 LLM Agent Manager 提示词
        2. LLM调用
        3. 解析llm返回的消息体
        4. 解析persistent_memory并追加到Agent持续性记忆中
        5. 生成并返回execute_output指令
        '''

        # step状态更新为 running
        agent_state["agent_step"].update_step_status(step_id, "running")

        # 1. 组装 LLM Agent Manager 提示词 (基础提示词与技能提示词)
        agent_manager_step_prompt = self.get_agent_manager_prompt(step_id, agent_state)
        # print(agent_manager_step_prompt)
        # 2. LLM调用
        llm_client = agent_state["llm_client"]  # 使用agent_state中维护的 LLM 客户端
        chat_context = agent_state["llm_context"]  # 使用agent_state中维护的 LLM 上下文

        chat_context.add_message("assistant", "好的，我会作为你提供的Agent角色，执行agent_manager操作"
                                              "我会根据 history_step 和当前step指示，精确我要发送的消息内容，"
                                              "我会严格遵从你的skill_prompt技能指示，并在<agent_instruction>和</agent_instruction>之间输出指令结果，"
                                              "在<persistent_memory>和</persistent_memory>之间输出我要追加的持续性记忆(如果我认为不需要追加我会空着)。")
        response = llm_client.call(
            agent_manager_step_prompt,
            context=chat_context
        )

        # 3. 解析llm返回的消息体
        agent_instruction = self.extract_agent_instruction(response)

        # 如果无法解析到Agent操作指令，说明LLM没有返回规定格式操作指令
        if not agent_instruction:
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

        else: # 如果解析到任务指令
            # 记录agent manager结果到execute_result
            step = agent_state["agent_step"].get_step(step_id)[0]
            execute_result = {"agent_instruction": agent_instruction}  # 构造符合execute_result格式的执行结果
            step.update_execute_result(execute_result)

            # 4. 解析persistent_memory指令内容并应用到Agent持续性记忆中
            instructions = self.extract_persistent_memory(response)  # 提取<persistent_memory>和</persistent_memory>之间的指令内容
            self.apply_persistent_memory(agent_state, instructions)  # 将指令内容应用到Agent的持续性记忆中

            # step状态更新为 finished
            agent_state["agent_step"].update_step_status(step_id, "finished")

            # 5. 构造execute_output，
            # 用于更新task_state.communication_queue和stage_state.every_agent_state
            # 传递Agent操作指令
            execute_output = self.get_execute_output(
                step_id,
                agent_state,
                update_agent_situation="working",
                shared_step_situation="finished",
                agent_instruction=agent_instruction
            )

            # 清空对话历史
            chat_context.clear()
            return execute_output

# Debug
if __name__ == "__main__":
    '''
    测试agent_manager需在Allen根目录下执行 python -m mas.skills.agent_manager
    '''
    from mas.agent.configs.llm_config import LLMConfig

    print("测试Agent Manager技能的调用")
    # 创建一个示例的Agent
    agent_state = {
        "agent_id": "0001",
        "name": "灰风/小灰",
        "role": "任务管理者",
        "profile": "我是一名任务管理者，负责协调和管理任务的执行。",
        "working_state": "Assigned tasks",
        "llm_config": LLMConfig.from_yaml("mas/role_config/qwq32b.yaml"),
        "working_memory": {},
        "persistent_memory": {},
        "agent_step": AgentStep("0001"),
        "skills": ["planning", "reflection", "summary",
                   "instruction_generation", "quick_think", "think",
                   "send_message", "process_message", "task_manager",
                   "ask_info", "agent_manager"],
        "tools": [],
    }

    # 构造虚假的历史步骤
    step1 = StepState(
        task_id="0001",
        stage_id="0001",
        agent_id="0001",
        step_intention="创建一个新Agent",
        type="skill",
        executor="agent_manager",
        text_content="为你自己创建一个助手",
        execute_result={},
    )

    agent_state["agent_step"].add_step(step1)

    step_id = agent_state["agent_step"].step_list[0].step_id  # 当前为第一个step

    agent_manager_skill = AgentManagerSkill()  # 实例化Ask Info技能
    agent_manager_skill.execute(step_id, agent_state)

    # 打印step信息
    agent_state["agent_step"].print_all_steps()










