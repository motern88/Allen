'''
技能名称: Send Message
期望作用: Agent在MAS系统内部的对另一个Agent实例的单向消息发送。
    Send Message会获取当前stage所有step执行情况的历史信息，使用LLM依据当前send_message_step意图进行汇总后，向指定Agent发送消息。

Send Message首先会判断当前Agent已有的信息是否满足发送消息的条件，即要发送的正确消息内容，当前Agent是否已知。
- 如果存在未获取的信息，不能支撑当前Agent发送消息内容，则会进入"获取更多信息分支"。
- 如果当前Agent已有的信息满足发送消息的条件，则会进入"直接消息发送分支"。

获取更多信息分支:
    当前Send Message执行时，Agent已有的信息不满足发送消息的条件（由LLM自行判断），进入获取更多信息分支。
    该分支的主要目的是将Send Message变为一个长尾技能，通过插入追加一个Decision Step来获取更多信息。
    LLM会根据当前Agent已有的信息，判断需要获取哪些更多信息，返回:
    <get_more_info>
    {
        "step_intention": "获取系统中XXX文档的XXX内容",
        "text_content": "我需要获取系统中关于XXX文档的XXX内容，需要精确到具体的XXX信息，以便我可以完成后续的消息发送。",
    }
    </get_more_info>
    我们会根据LLM返回的内容，追插入一个对应属性的Decision Step
    和与当前Send Message属性相同Send Message Step到当前Agent的步骤列表中。
    (于construct_decision_step_and_send_message_step方法中构造)


直接消息发送分支:
    Send Message 首先需要构建发送对象列表。[<agent_id>, <agent_id>, ...]
    其次需要确定发送的内容，通过 Send Message 技能的提示+LLM调用返回结果的解析可以得到。
    需要根据发送的实际内容，LLM需要返回的信息:
    <send_message>
    {
        "receiver": ["<agent_id>", "<agent_id>", ...],
        "message": "<message_content>",  # 消息文本
        "stage_relative": "<stage_id或no_relative>",  # 表示是否与任务阶段相关，是则填对应阶段Stage ID，否则为no_relative的字符串
        "need_reply": <bool>,  # 需要回复则为True，否则为False
        "waiting": <bool>  # 需要等待则为True，否则为False
    }
    </send_message>

    消息构造体经过executor处理和sync_state处理，最终在task_state的消息处理队列中的格式应当为：
    {
        task_id: str  # 任务ID,
        sender_id: str  # 发送者ID
        receiver: List[str]  # 用列表包裹的接收者agent_id
        message: str  # 消息文本

        stage_relative: str  # 表示是否与任务阶段相关，是则填对应阶段Stage ID，否则为no_relative的字符串
        need_reply: bool  # 需要回复则为True，否则为False

        waiting: Optional[List[str]]  # 如果发送者需要等待回复，则为所有发送对象填写唯一等待ID。不等待则为 None
            # LLM如果认为需要等待，则由代码为每个接收对象生成唯一等待ID
        return_waiting_id: Optional[str]  # 如果消息发送者需要等待回复，则返回消息时填写接收到的消息中包含的来自发送者的唯一等待ID
            # 来自上一个发送者消息的唯一等待ID，如果本send_message是为了回复上一个消息，且上一个消息带有唯一等待ID，则需要返回对应的这个唯一等待ID
            # 一般该return_waiting_id会在agent_base接收到对方正在等待回复的消息时，被包裹在<return_waiting_id>和</return_waiting_id>之间放在回复step.text_content中
    }

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

4.消息等待机制与Agent步骤锁
    如果发送者需要等待回复，则为所有发送对象填写唯一等待标识ID。不等待则为 None。
    如果等待，则发起者将在回收全部等待标识前不会进行任何步骤执行。

提示词顺序（系统 → 角色 → (目标 → 规则) → 记忆）

具体实现:
    1. 组装提示词:
        1.1 MAS系统提示词（# 一级标题）
        1.2 Agent角色:（# 一级标题）
            1.2.1 Agent角色背景提示词（## 二级标题）
            1.2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        1.3 send_message step:（# 一级标题）
            1.3.1 step.step_intention 当前步骤的简要意图
            1.3.2 step.text_content 具体目标
            1.3.3 技能规则提示(send_message_config["use_prompt"])
        1.4 历史步骤执行结果（# 一级标题）
        1.5 持续性记忆:（# 一级标题）
            1.5.1 Agent持续性记忆说明提示词（## 二级标题）
            1.5.2 Agent持续性记忆内容提示词（## 二级标题）

    2. llm调用
    3. 解析llm返回的消息体构造

    如果进入直接消息发送分支：
        4. 解析llm返回的持续性记忆信息，追加到Agent的持续性记忆中
        5. 如果发送消息需要等待回复，则触发步骤锁机制
        6. 返回用于指导状态同步的execute_output

    如果进入获取更多信息分支：
        4. 解析llm返回的持续性记忆信息，追加到Agent的持续性记忆中
        5. 构造插入的Decision Step与Send Message Step，插入到Agent的步骤列表中
        6. 返回用于指导状态同步的execute_output
'''
import re
import json5
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union, cast

from mas.agent.base.executor_base import Executor
from mas.agent.state.step_state import StepState, AgentStep

from mas.utils.message import Message
import uuid



# 注册规划技能到类型 "skill", 名称 "send_message"
@Executor.register(executor_type="skill", executor_name="send_message")
class SendMessageSkill(Executor):
    def __init__(self):
        super().__init__()  # 调用父类的构造方法

    def extract_send_message(self, text: str) -> Optional[Dict[str, Any]]:
        '''
        从文本中提取消息构造体(如果Send Message进入直接消息发送分支)
        '''
        # 使用正则表达式提取<send_message>和</send_message>之间的内容
        matches = re.findall(r"<send_message>\s*(.*?)\s*</send_message>", text, re.DOTALL)

        if matches:
            message = matches[-1]  # 获取最后一个匹配内容 排除是在<think></think>思考期间的内容

            try:
                message_dict = json5.loads(message)  # 使用json5解析，支持单引号、注释和未转义的双引号等
                return message_dict
            except Exception as e:
                print(f"[SendMessage]JSON解析错误 {e}:", message)
                return None
        else:
            # print("没有找到<send_message>标签")
            return None

    def extract_get_more_info(self, text: str) -> Optional[Dict[str, Any]]:
        '''
        从文本中提取获取更多信息的指令(如果Send Message进入获取更多信息分支)
        '''
        # 使用正则表达式提取<get_more_info>和</get_more_info>之间的内容
        matches = re.findall(r"<get_more_info>\s*(.*?)\s*</get_more_info>", text, re.DOTALL)

        if matches:
            get_more_info = matches[-1] # 获取最后一个匹配内容 排除是在<think></think>思考期间的内容
            try:
                get_more_info_dict = json.loads(get_more_info)
                return get_more_info_dict
            except json.JSONDecodeError:
                print("JSON解析错误:", get_more_info)
                return None
        else:
            # print("没有找到<get_more_info>标签")
            return None

    def extract_return_waiting_id(self,text):
        '''
        从文本中提取return_waiting_id
        '''
        matches = re.findall(r"<return_waiting_id>\s*(.*?)\s*</return_waiting_id>", text, re.DOTALL)
        if matches:
            return_waiting_id = matches[-1]  # 获取最后一个匹配内容 排除其他干扰内容
            return return_waiting_id
        else:
            # print("[Skill][send_message] 没有找到<return_waiting_id>标签")
            return None

    def construct_decision_step_and_send_message_step(self, instruction, step_id, agent_state):
        '''
        根据获取更多信息的指令，构造插入的Decision Step与Send Message Step
        获得的指令 instruction 如下：
        {
            "step_intention": "获取系统中XXX文档的XXX内容",
            "text_content": "我需要获取系统中关于XXX文档的XXX内容，需要精确到具体的XXX信息，以便我可以完成后续的消息发送。",
        }
        需要构造的Decision Step与Send Message Step如下：
        [
            {
                "step_intention": "获取系统中XXX文档的XXX内容",
                "type": "skill",
                "executor": "decision",
                "text_content": "我需要获取系统中关于XXX文档的XXX内容，需要精确到具体的XXX信息，以便我可以完成后续的消息发送。"
            },
            {
                "step_intention": 和当前step的step_intention相同,
                "type": "skill",
                "executor": "send_message",
                "text_content": 和当前step的text_content相同,
            }
        ]
        '''
        # 获取当前步骤的状态
        current_step = agent_state["agent_step"].get_step(step_id)[0]
        # 构造Decision Step与Send Message Step
        decision_step = {
            "step_intention": instruction["step_intention"],
            "type": "skill",
            "executor": "decision",
            "text_content": instruction["text_content"]
        }
        send_message_step = {
            "step_intention": current_step.step_intention,
            "type": "skill",
            "executor": "send_message",
            "text_content": current_step.text_content
        }

        return [decision_step, send_message_step]

    def get_send_message_prompt(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        组装提示词
        1 MAS系统提示词（# 一级标题）
        2 Agent角色提示词:（# 一级标题）
            2.1 Agent角色背景提示词（## 二级标题）
            2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        3 send_message step:（# 一级标题）
            3.1 step.step_intention 当前步骤的简要意图
            3.2 step.text_content 具体目标
            3.3 技能规则提示(send_message_config["use_prompt"])
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
        send_message: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        '''
        构造Send Message技能的execute_output。这部分使用代码固定构造，不由LLM输出构造。
        1. update_agent_situation:
            通过update_stage_agent_state字段指导sync_state更新stage_state.every_agent_state中自己的状态
            (一般情况下，只有Summary技能完成时，该字段传入finished，其他步骤完成时，该字段都传入working)
        2. shared_step_situation:
            添加步骤信息到task共享消息池
        3. send_message:
            将LLM生成的初步消息体转换为 MAS 中通用消息格式 Message，
            并添加待处理消息到task_state.communication_queue
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
            "content": f"执行Send Message步骤:{shared_step_situation}，"
        }

        # 3. 添加待处理消息到task_state.communication_queue
        if send_message:
            '''
            将LLM输出的消息体，转换为MAS内通用消息体Message
            LLM从输出中解析的消息构造体：
                "receiver": ["<agent_id>", "<agent_id>", ...],
                "message": "<message_content>",  # 消息文本
                "stage_relative": "<stage_id或no_relative>",  # 表示是否与任务阶段相关，是则填对应阶段Stage ID，否则为no_relative的字符串
                "need_reply": <bool>,  # 需要回复则为True，否则为False
                "waiting": List or None  # 如果需要等待，则外部已经将该字段生成每个接收对象的唯一等待ID列表
                "return_waiting_id": <str>  # 如果消息发送者需要等待回复，则返回消息时填写接收到的消息中包含的来自发送者的唯一等待ID
            
            最终Message构造体包含：
                task_id (str): 任务ID
                sender_id (str): 发送者ID
                receiver (List[str]): 接收者ID列表
                message (str): 消息内容
                stage_relative (str): 是否与任务阶段相关，"<stage_id或no_relative>"
                need_reply (bool): 是否需要回复
                waiting (Optional[List[str]]): 等待回复的唯一ID列表，不等待则为 None
                return_waiting_id (Optional[str]): 返回的唯一等待标识ID，不等待则为 None
            
            '''
            # 获取当前步骤的task_id与stage_id
            task_id = step_state.task_id

            # 如果对方在等待该回复，则解析并构造return_waiting_id
            # 从当前step的text_content中提取return_waiting_id
            return_waiting_id = self.extract_return_waiting_id(step_state.text_content)  # 如果存在<return_waiting_id>包裹的回复唯一等待ID则返回，否则返回None

            # 构造execute_output，中标准格式的消息
            execute_output["send_message"] = cast(Message,{
                "task_id": task_id,
                "sender_id": agent_state["agent_id"],
                "receiver": send_message["receiver"],
                "message": send_message["message"],
                "stage_relative": send_message["stage_relative"],
                "need_reply": send_message["need_reply"],
                "waiting": send_message["waiting"],
                "return_waiting_id": return_waiting_id,
            })

        return execute_output

    def execute(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        Send Message技能的具体执行方法:

        1. 组装 LLM Send Message 提示词
        2. LLM调用
        3. 解析llm返回的消息体

        如果进入直接消息发送分支：
            4. 解析persistent_memory并追加到Agent持续性记忆中
            5. 判定是否添加通信等待机制的步骤锁
            6. 生成并返回execute_output指令
                （向task_state.communication_queue追加消息,更新stage_state.every_agent_state中自己的状态）
                如果进入直接消息发送分支：

        如果进入获取更多信息分支：
            4. 解析persistent_memory并追加到Agent持续性记忆中
            5. 构造插入的Decision Step与Send Message Step，插入到Agent的步骤列表中
            6. 返回用于指导状态同步的execute_output
        '''

        # step状态更新为 running
        agent_state["agent_step"].update_step_status(step_id, "running")

        # 1. 组装 LLM Send Message 提示词 (基础提示词与技能提示词)
        send_message_step_prompt = self.get_send_message_prompt(step_id, agent_state)
        # print(send_message_step_prompt)
        # 2. LLM调用
        llm_client = agent_state["llm_client"]  # 使用agent_state中维护的 LLM 客户端
        chat_context = agent_state["llm_context"]  # 使用agent_state中维护的 LLM 上下文

        chat_context.add_message("assistant", "好的，我会作为你提供的Agent角色，执行send_message操作"
                                              "我会根据 history_step 和当前step指示，精确我要发送的消息内容，"
                                              "我会严格遵从你的skill_prompt技能指示，并在<send_message>和</send_message>之间输出规划结果，"
                                              "在<persistent_memory>和</persistent_memory>之间输出我要追加的持续性记忆(如果我认为不需要追加我会空着)。")
        response = llm_client.call(
            send_message_step_prompt,
            context=chat_context
        )

        # print("[Skill][send_message] LLM Response:", response)

        # 3. 解析llm返回的消息体
        message = self.extract_send_message(response)  # 尝试提取直接消息发送的消息体
        instruction = self.extract_get_more_info(response)  # 尝试提取获取更多信息的指令

        # 如果无法解析到消息体，也无法解析到指令，说明LLM没有进入到任何一个分支
        if not message and not instruction:
            # step状态更新为 failed
            agent_state["agent_step"].update_step_status(step_id, "failed")
            # 记录失败的LLM输出到execute_result
            step = agent_state["agent_step"].get_step(step_id)[0]
            execute_result = {"llm_response": response}  # execute_result记录失败的llm输出
            step.update_execute_result(execute_result)
            # 构造execute_output用于更新自己在stage_state.every_agent_state中的状态
            execute_output = self.get_execute_output(step_id, agent_state, update_agent_situation="failed",shared_step_situation="failed")
            return execute_output

        # 直接消息发送分支
        elif message:  # 如果解析到消息体
            # 记录send message结果到execute_result
            step = agent_state["agent_step"].get_step(step_id)[0]
            execute_result = {"send_message": message}  # 构造符合execute_result格式的执行结果
            step.update_execute_result(execute_result)

            # 4. 解析persistent_memory指令内容并应用到Agent持续性记忆中
            persistent_memory_instructions = self.extract_persistent_memory(response)  # 提取<persistent_memory>和</persistent_memory>之间的指令内容
            self.apply_persistent_memory(agent_state, persistent_memory_instructions)  # 将指令内容应用到Agent的持续性记忆中

            # step状态更新为 finished
            agent_state["agent_step"].update_step_status(step_id, "finished")

            # 5. 如果发送消息需要等待回复，则触发步骤锁机制
            # 向agent_state["step_lock"]中添加生成的唯一等待ID
            if message["waiting"]:
                # 为每个receiver生成唯一等待标识ID
                waiting_id_list = [str(uuid.uuid4()) for _ in message["receiver"]]
                # 将全部唯一等待标识ID添加到agent_state["step_lock"]中，
                # 在Agent回收全部标识ID（收到包含标识ID的信息）前，步骤锁一直生效，暂停后续step的执行。
                agent_state["step_lock"].extend(waiting_id_list)

                # 将消息中的["waiting"]字段替换为生成的唯一等待ID
                message["waiting"] = waiting_id_list
            else:
                # 如果不需要等待，则将waiting字段设置为None
                message["waiting"] = None
                # 此时message["waiting"]字段值已经从 bool -> optional[list[str]]

            # 6. 构造execute_output，用于更新task_state.communication_queue和stage_state.every_agent_state
            execute_output = self.get_execute_output(
                step_id,
                agent_state,
                update_agent_situation="working",
                shared_step_situation="finished",
                send_message=message
            )

            # 清空对话历史
            chat_context.clear()
            return execute_output

        # 获取更多信息分支
        elif instruction:
            # 记录send message中get_more_info分支结果到execute_result
            step = agent_state["agent_step"].get_step(step_id)[0]
            execute_result = {"get_more_info": instruction}  # 构造符合execute_result格式的执行结果
            step.update_execute_result(execute_result)

            # 4. 解析persistent_memory指令内容并应用到Agent持续性记忆中
            persistent_memory_instructions = self.extract_persistent_memory(response)  # 提取<persistent_memory>和</persistent_memory>之间的指令内容
            self.apply_persistent_memory(agent_state, persistent_memory_instructions)  # 将指令内容应用到Agent的持续性记忆中

            # step状态更新为 finished
            agent_state["agent_step"].update_step_status(step_id, "finished")

            # 5. 构造插入的Decision Step与Send Message Step
            step_list = self.construct_decision_step_and_send_message_step(instruction, step_id, agent_state)
            # 将构造的步骤插入到当前Agent的步骤列表中
            self.add_next_step(step_list, step_id, agent_state)  # 将规划的步骤列表添加到AgentStep中

            # 6. 构造execute_output
            execute_output = self.get_execute_output(
                step_id,
                agent_state,
                update_agent_situation="working",
                shared_step_situation="finished",
            )  # 获取更多消息分支不发送消息，不传get_execute_output的send_message字段
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
        "working_state": "idle",
        "llm_config": LLMConfig.from_yaml("mas/role_config/doubao.yaml"),
        "working_memory": {},
        "persistent_memory": {},
        "agent_step": AgentStep("0001"),
        "skills": ["planning", "reflection", "summary",
                   "instruction_generation", "quick_think", "think",
                   "send_message", "process_message", ],
        "tools": [],
    }

    step1 = StepState(
        task_id="task_001",
        stage_id="no_relative",
        agent_id="0001",
        step_intention="根据MAS帮助文档中的询问指南，询问协作Agent的心理状况",
        type="skill",
        executor="send_message",
        text_content="严格按照MAS帮助文档中的'询问指南'章节中的详细询问步骤（需要获取到MAS帮助文档），询协作Agent的心理状况，其中当前任务的Agent ID有: 0001,0005,0098",
        execute_result={},
    )

    agent_state["agent_step"].add_step(step1)
    # agent_state["agent_step"].add_step(step2)

    step_id = agent_state["agent_step"].step_list[0].step_id  # 当前为第二个step

    send_message = SendMessageSkill()
    send_message.execute(step_id, agent_state)

    # 打印step信息
    agent_state["agent_step"].print_all_steps()


