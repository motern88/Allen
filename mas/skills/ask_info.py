'''
技能名称: Ask Info
期望作用: Agent通过Ask Info获取自身以外的系统和任务信息
    Ask Info向Agent提供了查看自身以外的信息的能力包括其他Agent的profile及状态，
    由SyncState帮助收集上级stage_state，task_state等信息，使用Message传递回Agent。

我们通过提示词约束LLM以特定格式返回获取相应信息的特定指令，通过这些特定指令指导SyncState进行特定查询操作，
查询结果通过Message消息传递回Agent。

技能支持的查询选项有：
    1. 查看自身所管理的task_state及其附属stage_state的信息
    2. 查看自身所参与的task_state及参与的stage_state的信息
    3. 查看指定task_state的信息
    4. 查看指定stage_stage的信息

    5. 查看所有可直接实例化的Agent配置信息
    6. 查看MAS中所有Agent的profile
    7. 查看Team中所有Agent的profile  TODO：Team未实现
    8. 查看指定task_id的task_group中所有Agent的profile
    9. 查看指定stage下协作的所有Agent的profile
    10. 查看指定agent_id或多个agent_id的详细agent_state信息

    11. 查看MAS中所有技能与工具

说明：
    Ask Info本质上是一种的特殊消息发送技能，它起两个作用（1.向Agent提供信息查询选项，2.向SyncState传递信息查询指令）。
    SyncState接收到消息查询指令后立刻回复消息给Agent，Agent立即使用process_message step来接收。
    因此，Ask Info技能需要实时性，Ask Info会触发等待通信的步骤锁，直到收到返回消息（执行process_message step）


提示词顺序（系统 → 角色 → (目标 → 规则) → 记忆）

具体实现:
    1. 组装提示词:
        1.1 MAS系统提示词（# 一级标题）
        1.2 Agent角色:（# 一级标题）
            1.2.1 Agent角色背景提示词（## 二级标题）
            1.2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        1.3 ask_info step:（# 一级标题）
            1.3.1 step.step_intention 当前步骤的简要意图
            1.3.2 step.text_content 具体目标
            1.3.3 技能规则提示(ask_info_config["use_prompt"])
        1.4 持续性记忆:（# 一级标题）
            1.4.1 Agent持续性记忆说明提示词（## 二级标题）
            1.4.2 Agent持续性记忆内容提示词（## 二级标题）

    2. llm调用
    3. 解析llm返回的查询信息
    4. 解析llm返回的持续性记忆信息，追加到Agent的持续性记忆中
    5. 必定触发通信等待的步骤锁
    6. 返回用于指导状态同步的execute_output
'''
import re
import json
import uuid
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union

from mas.agent.base.executor_base import Executor
from mas.agent.state.step_state import StepState, AgentStep



@Executor.register(executor_type="skill", executor_name="ask_info")
class AskInfoSkill(Executor):
    def __init__(self):
        super().__init__()

    def extract_ask_info(self, text: str) -> Optional[Dict[str, Any]]:
        '''
        从文本中提取查询指令
        '''
        # 使用正则表达式提取<ask_info>和</ask_info>之间的内容
        matches = re.findall(r"<ask_info>\s*(.*?)\s*</ask_info>", text, re.DOTALL)

        if matches:
            ask_instruction = matches[-1]  # 获取最后一个匹配内容 排除是在<think></think>思考期间的内容

            try:
                ask_instruction_dict = json.loads(ask_instruction)
                return ask_instruction_dict
            except json.JSONDecodeError:
                print("JSON解析错误:", ask_instruction)
                return None
        else:
            print("没有找到<task_instruction>标签")
            return None


    def get_ask_info_prompt(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        组装提示词
        1 MAS系统提示词（# 一级标题）
        2 Agent角色:（# 一级标题）
            2.1 Agent角色背景提示词（## 二级标题）
            2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        3 ask_info step:（# 一级标题）
            3.1 step.step_intention 当前步骤的简要意图
            3.2 step.text_content 具体目标
            3.3 技能规则提示(ask_info_config["use_prompt"])
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
        available_skills_and_tools = self.get_skill_and_tool_prompt(agent_state["skills"],agent_state["tools"])  # 包含###三级标题的md
        md_output.append(f"## 角色可用技能与工具 available_skills_and_tools\n"
                         f"{available_skills_and_tools}\n")


        # 3. Ask Info step提示词
        md_output.append(f"# 当前需要执行的步骤 current_step\n")
        current_step = self.get_current_skill_step_prompt(step_id, agent_state)  # 不包含标题的md格式文本
        md_output.append(f"{current_step}\n")


        # 4. 持续性记忆提示词
        md_output.append("# 持续性记忆persistent_memory\n")
        # 获取persistent_memory的使用说明
        base_persistent_memory_prompt = self.get_base_prompt(key="persistent_memory_prompt")  # 不包含标题的md格式文本
        md_output.append(f"## 持续性记忆使用规则说明：\n"
                         f"{base_persistent_memory_prompt}\n")
        # persistent_memory的具体内容
        persistent_memory = self.get_persistent_memory_prompt(agent_state)  # 不包含标题的md格式文本
        md_output.append(f"## 你已有的持续性记忆内容：\n"
                         f"{persistent_memory}\n")

        # print("\n".join(md_output))
        return "\n".join(md_output)

    def get_execute_output(
        self,
        step_id: str,
        agent_state: Dict[str, Any],
        update_agent_situation: str,
        shared_step_situation: str,
        ask_instruction: Optional[Dict[str, Any]] = None,
    ):
        '''
        构造Ask Info技能的execute_output。这部分使用代码固定构造，不由LLM输出构造。
        1. update_agent_situation:
            通过update_stage_agent_state字段指导sync_state更新stage_state.every_agent_state中自己的状态
            (一般情况下，只有Summary技能完成时，该字段传入finished，其他步骤完成时，该字段都传入working)
        2. shared_step_situation:
            添加步骤信息到task共享消息池
        3. ask_instruction:
            通过ask_info字段指导sync_state进行信息查询，返回包含唯一等待标识ID的信息
            包含多种不同查询选项，由sync_state完成查询指令的解析、具体执行与消息返回
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
            "content": f"执行Ask Info步骤:{shared_step_situation}，"
        }

        # 3. ask_info,由sync_state完成查询指令的解析、具体执行与消息返回
        if ask_instruction:
            # 获取查询者的ID和所属任务ID
            sender_id = agent_state["agent_id"]
            sender_task_id = task_id
            # 添加到查询指令中
            ask_instruction["sender_id"] = sender_id
            ask_instruction["sender_task_id"] = sender_task_id

            execute_output["ask_info"] = ask_instruction
            # 此时execute_output["ask_instruction"] = {
            #   "type":"<不同查询选项>",
            #   "waiting_id":"<唯一等待标识ID>",
            #   "sender_id":"<查询者的agent_id>"
            #   "sender_task_id":"<查询者的task_id>"
            #   ...
            # }

        return execute_output

    def execute(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        Ask Info技能的具体执行方法:
        1. 组装 LLM Ask Info 提示词
        2. llm调用
        3. 解析llm返回的查询信息
        4. 解析llm返回的持续性记忆信息，追加到Agent的持续性记忆中
        5. 添加通信等待机制的步骤锁
        6. 返回用于指导状态同步的execute_output
        '''

        # step状态更新为 running
        agent_state["agent_step"].update_step_status(step_id, "running")

        # 1. 组装 LLM Ask Info 提示词 (基础提示词与技能提示词)
        ask_info_step_prompt = self.get_ask_info_prompt(step_id, agent_state)  # 包含 # 一级标题的md格式文本
        # print(ask_info_step_prompt)
        # 2. llm调用
        llm_client = agent_state["llm_client"]  # 使用agent_state中维护的 LLM 客户端
        chat_context = agent_state["llm_context"]  # 使用agent_state中维护的 LLM 上下文

        chat_context.add_message("assistant", "好的，我会作为你提供的Agent角色，执行ask_info操作。"
                                              "我会选择对应的查询选项，构造正确查询指令字典，"
                                              "并在<ask_info>和</ask_info>之间输出规划结果，"
                                              "在<persistent_memory>和</persistent_memory>之间输出我要追加的持续性记忆(如果我认为不需要追加我会空着)，")

        response = llm_client.call(
            ask_info_step_prompt,
            context=chat_context
        )

        # 3. 解析llm返回的查询信息
        ask_instruction = self.extract_ask_info(response)

        # 如果无法解析到查询指令，说明LLM没有返回规定格式的查询指令
        if not ask_instruction:
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

        else:  # 如果解析到查询指令
            # 记录ask info结果到execute_result
            step = agent_state["agent_step"].get_step(step_id)[0]
            execute_result = {"ask_instruction": ask_instruction}  # 构造符合execute_result格式的执行结果
            step.update_execute_result(execute_result)

            # 4. 解析persistent_memory指令内容并应用到Agent持续性记忆中
            instructions = self.extract_persistent_memory(response)  # 提取<persistent_memory>和</persistent_memory>之间的指令内容
            self.apply_persistent_memory(agent_state, instructions)  # 将指令内容应用到Agent的持续性记忆中

            # 5. 添加通信等待机制的步骤锁
            # 生成唯一等待标识ID，直到SyncState回复消息中包含该ID（Agent回收步骤锁后），Agent才可进行后续step执行。
            waiting_id = str(uuid.uuid4())
            agent_state["step_lock"].append(waiting_id)  # 添加等待标识ID到步骤锁列表中
            # 将等待标识ID添加到ask_instruction中
            ask_instruction["waiting_id"] = waiting_id

            # step状态更新为 finished
            agent_state["agent_step"].update_step_status(step_id, "finished")

            # 6. 构造execute_output，
            # 用于更新task_state.communication_queue和stage_state.every_agent_state
            # 传递查询指令
            execute_output = self.get_execute_output(
                step_id,
                agent_state,
                update_agent_situation="working",
                shared_step_situation="finished",
                ask_instruction=ask_instruction
            )

            # 清空对话历史
            chat_context.clear()
            return execute_output


# Debug
if __name__ == "__main__":  
    '''  
    测试ask_info需在根目录下执行 python -m mas.skills.ask_info 
    '''
    from mas.agent.configs.llm_config import LLMConfig

    print("测试Ask Info技能的调用")
    # 创建一个模拟的代理状态  
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
                   "ask_info"],
        "tools": [],  
    }

    # 构造虚假的历史步骤
    step1 = StepState(
        task_id="0001",
        stage_id="0001",
        agent_id="0001",
        step_intention="查看阶段状态",
        type="skill",
        executor="ask_info",
        text_content="task_id: 0001, stage_id: 0001",
        execute_result={},
    )

    agent_state["agent_step"].add_step(step1)

    step_id = agent_state["agent_step"].step_list[0].step_id  # 当前为第一个step

    ask_info_skill = AskInfoSkill()  # 实例化Ask Info技能
    ask_info_skill.execute(step_id, agent_state)

    # 打印step信息
    agent_state["agent_step"].print_all_steps()




    
