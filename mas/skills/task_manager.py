'''
技能名称: Task Manager
期望作用: Agent对任务的管理与调度。（一种特殊权限的技能，一般只有管理者Agent拥有）
    Task Manager会参考自身历史步骤信息（前面步骤获取任务信息与阶段信息），生成用于管理任务进程的指令。

任务管理者Agent会通过该技能生成相应操作的指令，指令会在MAS系统中操作对应组件完成实际行动，
例如通过SyncState操作task_state与stage_state,通过send_message形式通知相应Agent.

说明:
1. 发起一个Task:
    创建任务 add_task。
    该操作会创建一个 task_state,包含 task_intention 任务意图

2. 为任务分配Agent与阶段目标:
    为任务创建阶段 add_stage。
    该操作会为 task_state 创建一个或多个 stage_state,
    包含 stage_intention 阶段意图与 agent_allocation 阶段中Agent的分配情况。

3. 任务判定已完成，交付任务:
    结束任务 finish_task。
    该操作会将 task_state 的状态更新为 finished 或 failed，并通知task_group中所有Agent。
    同时该操作需要管理Agent生成任务总结信息。


4. 任务阶段判定已完成，进入下一个任务阶段:
    结束阶段 finish_stage。
    该操作会将 stage_state 的状态更新为 finished
    对该阶段进行交付，阶段完成进入下一个阶段。

5. 阶段失败后的重试:
    重试执行失败的阶段 retry_stage。
    该操作首先会更新旧阶段状态为"failed"，然后根据经验总结创建一个更好的相同的新阶段用于再次执行。
    （旧的失败阶段状态会保留，我们会插入一个修正后的相同目标的新阶段，并立即执行该阶段。）



提示词顺序（系统 → 角色 → (目标 → 规则) → 记忆）

具体实现:
    1. 组装提示词:
        1.1 MAS系统提示词（# 一级标题）
        1.2 Agent角色:（# 一级标题）
            1.2.1 Agent角色背景提示词（## 二级标题）
            1.2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        1.3 task_manager step:（# 一级标题）
            1.3.1 step.step_intention 当前步骤的简要意图
            1.3.2 step.text_content 具体目标
            1.3.3 技能规则提示(task_manager_config["use_prompt"])
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
            3.1 step.step_intention 当前步骤的简要意图
            3.2 step.text_content 具体目标
            3.3 技能规则提示(task_manager_config["use_prompt"])
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

        # 3. Task Manager step提示词
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
        task_instruction: Optional[Dict[str, Any]] = None,
    ):
        '''
        构造Task Manager技能的execute_output。这部分使用代码固定构造，不由LLM输出构造。
        1. update_agent_situation:
            通过update_stage_agent_state字段指导sync_state更新stage_state.every_agent_state中自己的状态
            (一般情况下，只有Summary技能完成时，该字段传入finished，其他步骤完成时，该字段都传入working)
        2. shared_step_situation:
            添加步骤信息到task共享消息池
        3. task_instruction:
            包含多种不同操作行为，由sync_state完成任务指令的解析与具体执行
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
            "content": f"执行Task Manager步骤:{shared_step_situation}，"
        }

        # 3. 由sync_state完成任务指令的解析与具体执行
        if task_instruction:
            task_instruction["agent_id"] = agent_state["agent_id"]  # 在指令中添加自身agent_id
            execute_output["task_instruction"] = task_instruction
            # 此时task_instruction中包含"agent_id","action"和其他具体操作指令涉及的字段

        return execute_output

    def execute(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        Task Manager技能的具体执行方法:

        1. 组装 LLM Task Manager 提示词
        2. LLM调用
        3. 解析llm返回的消息体
        4. 解析persistent_memory并追加到Agent持续性记忆中
        5. 生成并返回execute_output指令
        '''

        # step状态更新为 running
        agent_state["agent_step"].update_step_status(step_id, "running")

        # 1. 组装 LLM Task Manager 提示词 (基础提示词与技能提示词)
        task_manager_step_prompt = self.get_task_manager_prompt(step_id, agent_state)
        # print(task_manager_step_prompt)
        # 2. LLM调用
        llm_config = agent_state["llm_config"]
        llm_client = LLMClient(llm_config)  # 创建 LLM 客户端
        chat_context = LLMContext(context_size=15)  # 创建一个对话上下文, 限制上下文轮数 15

        chat_context.add_message("assistant", "好的，我会作为你提供的Agent角色，执行task_manager操作"
                                              "我会根据 history_step 和当前step指示，精确我要发送的消息内容，"
                                              "我会严格遵从你的skill_prompt技能指示，并在<task_instruction>和</task_instruction>之间输出指令结果，"
                                              "在<persistent_memory>和</persistent_memory>之间输出我要追加的持续性记忆(如果我认为不需要追加我会空着)。")
        response = llm_client.call(
            task_manager_step_prompt,
            context=chat_context
        )

        # 3. 解析llm返回的消息体
        task_instruction = self.extract_task_instruction(response)

        # 如果无法解析到任务指令，说明LLM没有返回规定格式任务指令
        if not task_instruction:
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
            # 记录task manager结果到execute_result
            step = agent_state["agent_step"].get_step(step_id)[0]
            execute_result = {"task_instruction": task_instruction}  # 构造符合execute_result格式的执行结果
            step.update_execute_result(execute_result)

            # 4. 解析persistent_memory指令内容并应用到Agent持续性记忆中
            instructions = self.extract_persistent_memory(response)  # 提取<persistent_memory>和</persistent_memory>之间的指令内容
            self.apply_persistent_memory(agent_state, instructions)  # 将指令内容应用到Agent的持续性记忆中

            # step状态更新为 finished
            agent_state["agent_step"].update_step_status(step_id, "finished")

            # 5. 构造execute_output，
            # 用于更新task_state.communication_queue和stage_state.every_agent_state
            # 传递任务指令
            execute_output = self.get_execute_output(
                step_id,
                agent_state,
                update_agent_situation="working",
                shared_step_situation="finished",
                task_instruction=task_instruction
            )

            # 清空对话历史
            chat_context.clear()
            return execute_output


# Debug
if __name__ == "__main__":
    '''
    测试task_manager需在Allen根目录下执行 python -m mas.skills.task_manager
    '''
    from mas.agent.configs.llm_config import LLMConfig

    print("测试Task Manager技能的调用")
    agent_state = {
        "agent_id": "0001",
        "name": "灰风",
        "role": "管理员",
        "profile": "一般负责直接和人类操作员对接，理解人类意图并创建相应的任务，组织相应Agent参与任务，协调各个Agent的协同执行。",
        "working_state": "idle",
        "llm_config": LLMConfig.from_yaml("mas/role_config/qwq32b.yaml"),
        "working_memory": {},
        "persistent_memory": {},
        "agent_step": AgentStep("0001"),
        "skills": ["planning", "reflection", "summary",
                   "instruction_generation", "quick_think", "think",
                   "send_message", "process_message", "task_manager"],
        "tools": [],
    }

    # 构造虚假的历史步骤
    step1 = StepState(
        task_id="0001",
        stage_id="0001",
        agent_id="0001",
        step_intention="创建任务",
        type="skill",
        executor="task_manager",
        text_content="你需要创建一个用于合同处理的任务",
        execute_result={},
    )

    agent_state["agent_step"].add_step(step1)

    step_id = agent_state["agent_step"].step_list[0].step_id  # 当前为第一个step

    task_manager_skill = TaskManagerSkill()
    task_manager_skill.execute(step_id, agent_state)

    # 打印step信息
    agent_state["agent_step"].print_all_steps()





