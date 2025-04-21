'''
技能名称: Send Message
期望作用: Agent在MAS系统内部的对另一个Agent实例的单向消息发送。
    Send Message会获取当前stage所有step执行情况的历史信息，使用LLM依据当前send_message_step意图进行汇总后，向指定Agent发送消息。

Send Message 首先需要构建发送对象列表。[<agent_id>, <agent_id>, ...]
其次需要确定发送的内容，通过 Send Message 技能的提示+LLM调用返回结果的解析可以得到。
需要根据发送的实际内容，LLM需要返回的信息:
<send_message>
{
    "sender_id": "<sender_agent_id>",
    "receiver": ["<agent_id>", "<agent_id>", ...],
    "message": "<message_content>",  # 消息文本
    "stage_relative": "<stage_id或no_relative>",  # 表示是否与任务阶段相关，是则填对应阶段Stage ID，否则为no_relative的字符串
    "need_reply": <bool>,  # 需要回复则为True，否则为False
}
</send_message>

说明：
1.消息如何被发送：
    消息体通过execute_output,由sync_state将消息放入task_state的消息处理对列中，
    会由MAS系统的消息处理模块定期扫描task_state的消息处理队列，执行消息传递任务。

2.Agent通信方式/流程：
    接收者以被追加一个step（Process Message/Send Message）的方式处理消息。
    如果发送者认为需要回复，则接收者被追加一个指向发送者的Send Message step，
    如果发送者认为不需要回复，则接收者被追加一个Process Message step，Process Message 不需要向其他实体传递消息或回复

    因此，如果是一个单向消息，则通过Send Message和Process Message可以完成；
    如果是长期多轮对话，则通过一系列的Send Message和最后一个Process Message实现。

3.send_message与process_message这类消息step是否隶属某一个stage：
    - 如果这类消息传递是任务阶段相关的话，应当属于某一个stage。
      这样通讯消息也是完成任务的一部分，stage完成与否也必须等待这些通讯消息的结束。
    - 如果这类消息是任务阶段无关的，则不应属于某一个stage。step中的stage_id应当为"no_stage"，
      这样这些消息的完成与否不会影响任务阶段的完成，任务阶段的完成也不会中断这些通讯消息的执行。

    一般情况下，由Agent自主规划的Send Message的消息传递均是与任务阶段相关的，因此在发送消息时需要指定stage_id。


提示词顺序（系统 → 角色 → (目标 → 规则) → 记忆）

具体实现:
    1. 组装提示词:
        1.1 MAS系统提示词（# 一级标题）
        1.2 Agent角色:（# 一级标题）
            1.2.1 Agent角色背景提示词（## 二级标题）
            1.2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        1.3 send_message step:（# 一级标题）
            1.3.1 step.step_intention 当前步骤的简要意图（## 二级标题）
            1.3.2 step.text_content 具体目标（## 二级标题）
            1.3.3 技能规则提示(send_message_config["use_prompt"])（## 二级标题）
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



# 注册规划技能到类型 "skill", 名称 "send_message"
@Executor.register(executor_type="skill", executor_name="send_message")
class SendMessageSkill(Executor):
    def __init__(self):
        super().__init__()  # 调用父类的构造方法

    def extract_send_message(self, text: str) -> Optional[Dict[str, Any]]:
        '''
        从文本中提取消息构造体
        '''
        # 使用正则表达式提取<send_message>和</send_message>之间的内容
        matches = re.findall(r"<send_message>\s*(.*?)\s*</send_message>", text, re.DOTALL)

        if matches:
            message = matches[-1]  # 获取最后一个匹配内容 排除是在<think></think>思考期间的内容

            try:
                message_dict = json.loads(message)
                return message_dict
            except json.JSONDecodeError:
                print("JSON解析错误:", message)
                return None
        else:
            print("没有找到<send_message>标签")
            return None


    def get_send_message_prompt(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        组装提示词
        1 MAS系统提示词（# 一级标题）
        2 Agent角色提示词:（# 一级标题）
            2.1 Agent角色背景提示词（## 二级标题）
            2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        3 send_message step:（# 一级标题）
            3.1 step.step_intention 当前步骤的简要意图（## 二级标题）
            3.2 step.text_content 具体目标（## 二级标题）
            3.3 技能规则提示(send_message_config["use_prompt"])（## 二级标题）
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

        # 3. Send Message step提示词
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
        send_message: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        '''
        构造Send Message技能的execute_output。这部分使用代码固定构造，不由LLM输出构造。
        1. update_agent_situation:
            通过update_stage_agent_state字段指导sync_state更新stage_state.every_agent_state中自己的状态
        2. shared_step_situation:
            添加步骤信息到task共享消息池
        3. send_message:
            添加待处理消息到task_state.communication_queue
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
            "content": f"执行Send Message步骤:{shared_step_situation}，"
        }

        # 3. 添加待处理消息到task_state.communication_queue
        if send_message:
            # 获取当前步骤的task_id与stage_id
            task_id = step_state.task_id
            # 为消息体添加task_id
            send_message["task_id"] = task_id
            # 构造execute_output
            execute_output["send_message"] = send_message
            # 此时send_message构造体包含：
            # "task_id": task_id,
            # "sender_id": "<sender_agent_id>",
            # "receiver": ["<agent_id>", "<agent_id>", ...],
            # "message": "<message_content>",
            # "stage_relative": "<stage_id或no_relative>",  # 表示是否与任务阶段相关，是则填对应阶段Stage ID，否则为no_relative的字符串
            # "need_reply": <bool>,  # 需要回复则为True，否则为False

        return execute_output

    def execute(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        Send Message技能的具体执行方法:

        1. 组装 LLM Send Message 提示词
        2. LLM调用
        3. 解析llm返回的消息体
        4. 解析persistent_memory并追加到Agent持续性记忆中
        5. 生成并返回execute_output指令
            （向task_state.communication_queue追加消息,更新stage_state.every_agent_state中自己的状态）
        '''

        # step状态更新为 running
        agent_state["agent_step"].update_step_status(step_id, "running")

        # 1. 组装 LLM Send Message 提示词 (基础提示词与技能提示词)
        send_message_step_prompt = self.get_send_message_prompt(step_id, agent_state)
        print(send_message_step_prompt)
        # 2. LLM调用
        llm_config = agent_state["llm_config"]
        llm_client = LLMClient(llm_config)  # 创建 LLM 客户端
        chat_context = LLMContext(context_size=15)  # 创建一个对话上下文, 限制上下文轮数 15

        chat_context.add_message("assistant", "好的，我会作为你提供的Agent角色，执行send_message操作"
                                              "我会根据 history_step 和当前step指示，精确我要发送的消息内容，"
                                              "我会严格遵从你的skill_prompt技能指示，并在<send_message>和</send_message>之间输出规划结果，"
                                              "在<persistent_memory>和</persistent_memory>之间输出我要追加的持续性记忆(如果我认为不需要追加我会空着)。")
        response = llm_client.call(
            send_message_step_prompt,
            context=chat_context
        )

        # 3. 解析llm返回的消息体
        message = self.extract_send_message(response)

        # 如果无法解析到消息体，说明LLM没有返回发送消息
        if not message:
            # step状态更新为 failed
            agent_state["agent_step"].update_step_status(step_id, "failed")
            # 构造execute_output用于更新自己在stage_state.every_agent_state中的状态
            execute_output = self.get_execute_output(step_id, agent_state, update_agent_situation="failed",shared_step_situation="failed")
            return execute_output

        else:  # 如果解析到消息体
            # 记录send message结果到execute_result
            step = agent_state["agent_step"].get_step(step_id)[0]
            execute_result = {"send_message": message}  # 构造符合execute_result格式的执行结果
            step.update_execute_result(execute_result)

            # 4. 解析persistent_memory并追加到Agent持续性记忆中
            new_persistent_memory = self.extract_persistent_memory(response)
            agent_state["persistent_memory"] += "\n" + new_persistent_memory

            # step状态更新为 finished
            agent_state["agent_step"].update_step_status(step_id, "finished")

            # 5. 构造execute_output，用于更新task_state.communication_queue和stage_state.every_agent_state
            execute_output = self.get_execute_output(
                step_id,
                agent_state,
                update_agent_situation="finished",
                shared_step_situation="finished",
                send_message=message
            )

            # 清空对话历史
            chat_context.clear()
            return execute_output

# Debug
if __name__ == "__main__":
    '''
    测试send_message需在Allen根目录下执行 python -m mas.skills.send_message
    '''
    from mas.agent.configs.llm_config import LLMConfig

    print("测试Send Message技能的调用")
    agent_state = {
        "agent_id": "0001",
        "name": "小灰",
        "role": "心理咨询专员",
        "profile": "心理咨询师，擅长倾听与分析。主要帮助同事（其他Agent）疏导心理压力",
        "working_state": "Unassigned tasks",
        "llm_config": LLMConfig.from_yaml("mas/role_config/qwq32b.yaml"),
        "working_memory": {},
        "persistent_memory": "",
        "agent_step": AgentStep("0001"),
        "skills": ["planning", "reflection", "summary",
                   "instruction_generation", "quick_think", "think",
                   "send_message"],
        "tools": [],
    }

    # 构造虚假的历史步骤
    step1 = StepState(
        task_id="task_001",
        stage_id="stage_001",
        agent_id="0001",
        step_intention="询问并了解其他Agent心理状况",
        step_type="skill",
        executor="planning",
        text_content="询问其他Agent心理状况",
        execute_result={
            "planned_step": [
                {
                    "step_intention": "询问协作Agent的心理状况",
                    "type": "skill",
                    "executor": "send_message",
                    "text_content": "当前任务的Agent ID有: 0001,0005,0098",
                },
            ]
        },
    )
    step2 = StepState(
        task_id="task_001",
        stage_id="stage_001",
        agent_id="0001",
        step_intention="询问协作Agent的心理状况",
        step_type="skill",
        executor="send_message",
        text_content="当前任务的Agent ID有: 0001,0005,0098",
        execute_result={},
    )

    agent_state["agent_step"].add_step(step1)
    agent_state["agent_step"].add_step(step2)

    step_id = agent_state["agent_step"].step_list[1].step_id  # 当前为第二个step

    send_message = SendMessageSkill()
    send_message.execute(step_id, agent_state)

    # 打印step信息
    agent_state["agent_step"].print_all_steps()


