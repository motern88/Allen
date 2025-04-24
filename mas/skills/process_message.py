'''
技能名称: Process Message
期望作用: Agent处理MAS内部来自另一个Agent实例的单项消息，且该消息明确不需要回复。
    接收到消息后，Agent会使用process_message step，调用llm来处理消息的非指令部分（指令部分在agent_base中process_message方法中处理），
    一般情况下意味着该消息需要被LLM消化并整理，也有可能仅仅作为多轮对话的结尾。

在AgentBase类中的process_message方法主要用于处理message中的指令部分，依照指令进行实际操作。
在技能库中的ProcessMessageSkill主要用于让LLM理解并消化消息的文本内容。

NOTE: Message内容可能包含md标题，为了防止与其他提示的md标题形成标题冲突，因此得调整提示词顺序。见具体实现。

提示词顺序（系统 → 角色 → (目标 → 规则) → 记忆）

具体实现:
    1. 组装预提示词:
        1.1 MAS系统提示词（# 一级标题）
        1.2 Agent角色:（# 一级标题）
            1.2.1 Agent角色背景提示词（## 二级标题）
            1.2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        1.3 历史步骤执行结果（# 一级标题）
        1.4 持续性记忆:（# 一级标题）
            1.4.1 Agent持续性记忆说明提示词（## 二级标题）
            1.4.2 Agent持续性记忆内容提示词（## 二级标题）
    2. 组装消息处理步骤提示词:
        2.1 process_message step:
            2.1.1 step.step_intention 当前步骤的简要意图
            2.1.2 step.text_content 接收到的消息内容
            2.1.3 技能规则提示(process_message_config["use_prompt"])

    2. llm调用
    3. 解析llm返回的消息读后感
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
class ProcessMessageSkill(Executor):
    def __init__(self):
        super().__init__()  # 调用父类的构造方法

    def extract_process_message(self, text: str) -> Optional[Dict[str, Any]]:
        '''
        从文本中提取消息构造体
        '''
        # 使用正则表达式提取<process_message>和</process_message>之间的内容
        matches = re.findall(r"<process_message>\s*(.*?)\s*</process_message>", text, re.DOTALL)

        if matches:
            message = matches[-1]  # 获取最后一个匹配内容 排除是在<think></think>思考期间的内容

            try:
                message_dict = json.loads(message)
                return message_dict
            except json.JSONDecodeError:
                print("JSON解析错误:", message)
                return None
        else:
            print("没有找到<process_message>标签")
            return None


    def get_pre_process_message_prompt(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        组装预提示词
        1 MAS系统提示词（# 一级标题）
        2 Agent角色提示词:（# 一级标题）
            2.1 Agent角色背景提示词（## 二级标题）
            2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        3 历史步骤执行结果（# 一级标题）
        4 持续性记忆:（# 一级标题）
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

        # 3. 历史步骤执行结果
        md_output.append(f"# 历史已执行步骤 history_step\n")
        history_steps = self.get_history_steps_prompt(step_id, agent_state)  # 不包含标题的md格式文本
        md_output.append(f"{history_steps}\n")

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

    def get_process_message_prompt(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        组装消息处理步骤提示词
        1 process_message step:
            1.1 step.step_intention 当前步骤的简要意图
            1.2 step.text_content 具体目标
            1.3 技能规则提示(process_message_config["use_prompt"])
        '''
        md_output = []

        # Process Message step提示词
        md_output.append(f"当前需要执行的步骤 current_step:\n")
        current_step = self.get_current_skill_step_prompt(step_id, agent_state)  # 不包含标题的md格式文本
        md_output.append(f"{current_step}\n")

        return "\n".join(md_output)

    def get_execute_output(
        self,
        step_id: str,
        agent_state: Dict[str, Any],
        update_agent_situation: str,
        shared_step_situation: str,
    ) -> Dict[str, Any]:
        '''
        构造Process Message技能的execute_output。这部分使用代码固定构造，不由LLM输出构造。
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
            "agent_id": agent_state["agent_id"],
            "role": agent_state["role"],
            "stage_id": stage_id,
            "content": f"执行Process Message步骤:{shared_step_situation}，"
        }

        return execute_output

    def execute(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        Process Message技能的具体执行方法:

        1. 组装 LLM 系统预提示词 (这里将当前步骤的提示和其他提示分开，以防止消息中包含md标题冲突)
        2. 组装 Process Message 步骤提示词
        3. LLM调用
        4. 解析llm返回的消息体
        5. 解析persistent_memory并追加到Agent持续性记忆中
        6. 生成并返回execute_output指令
        '''

        # step状态更新为 running
        agent_state["agent_step"].update_step_status(step_id, "running")

        # 1. 组装 LLM 系统预提示词 (这里将当前步骤的提示和其他提示分开，以防止消息中包含md标题冲突)
        pre_process_message_step_prompt = self.get_pre_process_message_prompt(step_id, agent_state)
        print(pre_process_message_step_prompt)

        # 2. 组装 Process Message 步骤提示词
        process_message_step_prompt = self.get_process_message_prompt(step_id, agent_state)
        print(process_message_step_prompt)

        # 3. LLM调用 (这里将当前步骤的提示和其他提示分开，以防止消息中包含md标题冲突)
        llm_config = agent_state["llm_config"]
        llm_client = LLMClient(llm_config)  # 创建 LLM 客户端
        chat_context = LLMContext(context_size=15)  # 创建一个对话上下文, 限制上下文轮数 15

        chat_context.add_message("assistant", "好的，我会作为你提供的Agent角色，执行process_message操作"
                                              "我会参考 history_step ，准确理解并消化当前step中记录的有关接收到的消息内容，"
                                              "我会严格遵从skill_prompt的技能指示，在<process_message>和</process_message>之间输出我理解并消化的结论，"
                                              "我会将我理解的消息内容精简在<persistent_memory>和</persistent_memory>之间输出，以此追加在我的持续性记忆中。")
        # 输入系统预提示词
        chat_context.add_message("user", pre_process_message_step_prompt)
        # 输入当前步骤提示词
        response = llm_client.call(
            process_message_step_prompt,
            context=chat_context
        )

        # 4. 解析llm返回的对消息的理解信息
        process_message = self.extract_process_message(response)

        # 如果无法解析到消息体，说明LLM没有返回理解的信息
        if not process_message:
            # step状态更新为 failed
            agent_state["agent_step"].update_step_status(step_id, "failed")
            # 构造execute_output用于更新自己在stage_state.every_agent_state中的状态
            execute_output = self.get_execute_output(step_id, agent_state, update_agent_situation="failed",
                                                     shared_step_situation="failed")
            return execute_output

        else:  # 如果解析到LLM返回的理解的消息
            # 记录process message结果到execute_result
            step = agent_state["agent_step"].get_step(step_id)[0]
            execute_result = {"process_message": process_message}  # 构造符合execute_result格式的执行结果
            step.update_execute_result(execute_result)

            # 5. 解析persistent_memory并追加到Agent持续性记忆中
            new_persistent_memory = self.extract_persistent_memory(response)
            agent_state["persistent_memory"] += "\n" + new_persistent_memory

            # step状态更新为 finished
            agent_state["agent_step"].update_step_status(step_id, "finished")

            # 6. 构造execute_output，用于更新stage_state.every_agent_state
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
    测试process_message需在Allen根目录下执行 python -m mas.skills.process_message
    '''
    from mas.agent.configs.llm_config import LLMConfig

    print("测试Process Message技能的调用")
    agent_state = {
        "agent_id": "0001",
        "name": "小灰",
        "role": "合同审查",
        "profile": "审查合同是否有误",
        "working_state": "idle",
        "llm_config": LLMConfig.from_yaml("mas/role_config/qwq32b.yaml"),
        "working_memory": {},
        "persistent_memory": "",
        "agent_step": AgentStep("0001"),
        "skills": ["planning", "reflection", "summary",
                   "instruction_generation", "quick_think", "think",
                   "send_message", "process_message"],
        "tools": [],
    }
    # 构造虚假的历史步骤
    step1 = StepState(
        task_id="task_001",
        stage_id="stage_001",
        agent_id="0001",
        step_intention="提取合同的信息",
        step_type="tool",
        executor="contract_extract",
        text_content="根据工具提取合同的重要信息，查明合同金额是否有误，是否涉嫌诈骗",
        execute_result={
            "contract_extract": "<测试文本（假设返回一些合同信息）>"
        },
    )
    step2 = StepState(
        task_id="task_001",
        stage_id="stage_001",
        agent_id="0001",
        step_intention="审查合同",
        step_type="skill",
        executor="think",
        text_content="审查合同金额是否有误，是否涉嫌诈骗",
        execute_result={
            "think": "合同审查无误，不存在诈骗嫌疑",
        },
    )
    step3 = StepState(
        task_id="task_001",
        stage_id="stage_001",
        agent_id="0001",
        step_intention="接收并处理来自其他Agent的消息",
        step_type="skill",
        executor="process_message",
        text_content="你好，我是合同提取专员，我向你发送消息是想提醒你，合同金额有误，其中合同款本应是3000RMB却被写成了3000美金，请知悉",
        execute_result={},
    )

    agent_state["agent_step"].add_step(step1)
    agent_state["agent_step"].add_step(step2)
    agent_state["agent_step"].add_step(step3)

    step_id = agent_state["agent_step"].step_list[2].step_id  # 当前为第三个step

    process_message_skill = ProcessMessageSkill()
    process_message_skill.execute(step_id, agent_state)

    # 打印step信息
    agent_state["agent_step"].print_all_steps()