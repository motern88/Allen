'''
技能名称: Tool Decision
期望作用: Agent通过Tool Decision处理长尾工具的返回结果，并决定下一步该工具的执行或是结束长尾工具调用
    该技能会调用LLM接收并处理长尾工具的返回结果，并决定下一步该工具的调用的方向（指导指令生成步骤）或是结束长尾工具调用。
    如果该技能不终止继续调用工具，则该技能能够为Agent追加一个Instruction Generation和一个该工具步骤

如果工具返回结果需要向LLM确认，并反复多次调用该工具的，这种情况为工具的长尾调用。
同一个工具的连续多次调用，需要由LLM不断判断每一步工具使用的方向。
长尾工具会在工具步骤执行后将工具返回结果经由SyncState以消息的方式,让Agent追加一个Tool Decision来决策工具否继续调用及如何继续调用

因此多次调用的长尾工具:
    以InstructionGeneration开始，以ToolDecision结尾，其中可能包含多次(指令生成-工具执行)的步骤。
    ([I.G.] -> [Tool]) -> [ToolDecision] -> ([I.G.] -> [Tool]) -> [ToolDecision] -> ...

    对于单次调用的一般工具：以InstructionGeneration开始，以具体工具步骤结尾。
    对于多次调用的长尾工具：以InstructionGeneration开始，以ToolDecision结尾，其中可能包含多次 (指令生成-工具执行) 的步骤。


LLM需要获取足够进行决策判断的条件:
1. 工具最初调用的意图
    工具最初的调用意图放在和工具的历史调用结果一并获取，executor_base.get_tool_history_prompt

2. 工具当次调用的执行结果
    由长尾工具在执行后将工具返回结果通过execute_output传出，使用"need_tool_decision"字段，SyncState会捕获该字段内容。
    need_tool_decision字段需要包含：
        "task_id" 指导SyncState构造的消息应当存于哪个任务消息队列中
        "Stage_id" 保证和Stage相关性，可同一清除
        "agent_id" 指导MessageDispatcher从任务消息队列中获取到消息时，应当将消息发送给谁
        "tool_name" 指导Agent接收到消息后，追加ToolDecision技能步骤的决策结果应当使用哪个工具
    注：工具当次调用结果不需要单独传出，由Tool Decision执行时，获取该工具的历史调用结果一并获取即可。

3. 该长尾工具的历史调用的执行结果和每次调用之间的历史决策
    executor_base.get_tool_history_prompt获取。

4. 由工具定义的不同决策对应不同格式指令的说明
    Tool Decision不需要知道具体工具指令调用方式，Tool Decision只需要给出下一步工具调用的执行方向，
    由Instruction Generation根据工具具体提示生成具体工具调用指令


说明:
    该Tool Decision是MAS中的一个经典循环，执行该技能前有：
        Step（具体工具Tool执行）-> SyncState（生成指令消息）-> MessageDispatcher（分发消息给对应Agent）->
        Agent（receive_message处理消息）-> Step（插入一个ToolDecision步骤）

    执行该技能后，如果Tool Decision继续工具调用则有：
        Step（ToolDecision技能确认工具继续调用，追加接下来的工具调用步骤）-> Step（InstructionGeneration）-> Step（对应Tool）

    执行该技能后，如果Tool Decision终止工具继续调用则有：
        Step（ToolDecision技能终止工具继续调用）


提示词顺序（系统 → 角色 → (目标 → 规则) → 记忆）

具体实现:
    1. 组装提示词:
        1.1 MAS系统提示词（# 一级标题）
        1.2 Agent角色:（# 一级标题）
            1.2.1 Agent角色背景提示词（## 二级标题）
            1.2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        1.3 tool_decision step:（# 一级标题）
            1.3.1 step.step_intention 当前步骤的简要意图
            1.3.2 step.text_content 长尾工具提供的返回结果
            1.3.3 技能规则提示(tool_decision_config["use_prompt"])
        1.4 该工具的历史执行结果（# 一级标题）
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


@Executor.register(executor_type="skill", executor_name="tool_decision")
class ToolDecisionSkill(Executor):
    def __init__(self):
        super().__init__()

    def extract_tool_decision_step(self, text: str) -> Optional[Dict[str, Any]]:
        '''
        从文本中提取工具决策步骤
        '''
        # 使用正则表达式提取<tool_decision>和</tool_decision>之间的内容
        matches = re.findall(r"<tool_decision>\s*(.*?)\s*</tool_decision>", text, re.DOTALL)

        if matches:
            step_content = matches[-1]  # 获取最后一个匹配内容 排除是在<think></think>思考期间的内容

            if not step_content:
                # 内容为空，视为无决策，返回空列表
                return []

            try:
                # 将字符串解析为 Python 列表
                tool_decision_step = json.loads(step_content)
                return tool_decision_step
            except json.JSONDecodeError:
                print("解析 JSON 失败，请检查格式")
                return None
        else:
            print("没有找到 <tool_decision> 标记")
            return None

    def get_tool_decision_prompt(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        组装提示词:
        1 MAS系统提示词（# 一级标题）
        2 Agent角色:（# 一级标题）
            2.1 Agent角色背景提示词（## 二级标题）
            2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        3 tool_decision step:（# 一级标题）
            3.1 step.step_intention 当前步骤的简要意图
            3.2 step.text_content 长尾工具提供的返回结果
            3.3 技能规则提示(tool_decision_config["use_prompt"])
        4 该工具历史执行结果（# 一级标题）
        5 持续性记忆:（# 一级标题）
            5.1 Agent持续性记忆说明提示词（## 二级标题）
            5.2 Agent持续性记忆内容提示词（## 二级标题）
        '''
        md_output = []

        # 提前获取该技能需要决策的工具名称，以便获取工具历史结果提示词时传入
        step_state = agent_state["agent_step"].get_step(step_id)[0]
        text_content = step_state.text_content  # text_content中包含 <tool_name></tool_name> 用于指示技能执行时获取哪些工具历史结果
        match = re.search(r"<tool_name>\s*(.*?)\s*</tool_name>", text_content)
        tool_name = match.group(1)

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


        # 3. Tool Decision step提示词
        md_output.append(f"# 当前需要执行的步骤 current_step\n")
        current_step = self.get_current_skill_step_prompt(step_id, agent_state)  # 不包含标题的md格式文本
        md_output.append(f"{current_step}\n")


        # 4. 获取该工具历史执行结果
        md_output.append(f"# 该工具历史的历史信息 tool_history\n")
        history_tools_result = self.get_tool_history_prompt(step_id, agent_state, tool_name)  # 不包含标题的md格式文本
        md_output.append(f"{history_tools_result}\n")
        print(history_tools_result)

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

    def get_execute_output(
        self,
        step_id: str,
        agent_state: Dict[str, Any],
        update_agent_situation: str,
        shared_step_situation: str,
    ) -> Dict[str, Any]:
        '''
        构造Tool Decision技能的execute_output
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
            "content": f"执行Tool Decision步骤: {shared_step_situation}，"
        }

        return execute_output

    def execute(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        Tool Decision技能的具体执行方法:
        (如果继续工具调用，则要追加指令生成和工具step在execute内完成追加)

        1. 组装 LLM Tool Decision 提示词
        2. llm调用
        3. 记录规划结果到execute_result，并更新AgentStep中的步骤列表
        4. 解析persistent_memory并追加到Agent持续性记忆中
        5. 构造execute_output用于指导sync_state更新stage_state.every_agent_state中自己的状态
        '''

        # step状态更新为 running
        agent_state["agent_step"].update_step_status(step_id, "running")
        
        # 1. 组装Tool Decision提示词
        tool_decision_prompt = self.get_tool_decision_prompt(step_id, agent_state)  # 包含 # 一级标题的md格式文本
        # print(tool_decision_prompt)
        
        # 2. LLM调用
        llm_config = agent_state["llm_config"]
        llm_client = LLMClient(llm_config)  # 创建 LLM 客户端
        chat_context = LLMContext(context_size=15)  # 创建一个对话上下文, 限制上下文轮数 15

        chat_context.add_message("assistant", "好的，我会作为你提供的Agent角色，执行tool_decision操作，"
                                              "根据工具历史调用信息 tool_history 进行准确的工具决策。"
                                              "并在<tool_decision>和</tool_decision>之间输出我的工具决策结果，"
                                              "(如果我认为需要继续调用工具，则输出的工具决策结果是要追加的指令生成和工具步骤；"
                                              "如果我认为不需要继续调用工具，则输出的工具决策结果是空。)"
                                              "在<persistent_memory>和</persistent_memory>之间输出我要追加的持续性记忆(如果我认为不需要追加我会空着)，")

        response = llm_client.call(
            tool_decision_prompt,
            context=chat_context
        )

        # 打印LLM返回结果
        print(response)

        # 解析tool_decision_step
        tool_decision_step = self.extract_tool_decision_step(response)

        # 如果无法解析到工具决策步骤，说明LLM没有返回<tool_decision>包裹的决策
        if not tool_decision_step:
            # step状态更新为 failed
            agent_state["agent_step"].update_step_status(step_id, "failed")
            # 构造execute_output用于更新自己在stage_state.every_agent_state中的状态
            execute_output = self.get_execute_output(step_id, agent_state, update_agent_situation="failed",
                                                     shared_step_situation="failed")
            return execute_output

        else: # 解析到工具决策步骤
            # LLM认为不需要继续调用工具，返回空的tool_decision_step
            if len(tool_decision_step) == 0:
                # 3. 记录tool_decision决策结果到execute_result
                step = agent_state["agent_step"].get_step(step_id)[0]
                execute_result = {"tool_decision": "结束该长尾工具的继续调用"}  # 构造符合execute_result格式的执行结果
                step.update_execute_result(execute_result)

            else:
                # 3. 记录tool_decision决策结果到execute_result，并更新AgentStep中的步骤列表
                step = agent_state["agent_step"].get_step(step_id)[0]
                execute_result = {"tool_decision": tool_decision_step}  # 构造符合execute_result格式的执行结果
                step.update_execute_result(execute_result)
                # 更新AgentStep中的步骤列表
                self.add_next_step(tool_decision_step, step_id, agent_state)

            # 4. 解析persistent_memory并追加到Agent持续性记忆中
            new_persistent_memory = self.extract_persistent_memory(response)
            agent_state["persistent_memory"] += "\n" + new_persistent_memory

            # step状态更新为 finished
            agent_state["agent_step"].update_step_status(step_id, "finished")

            # 5. 构造execute_output用于指导sync_state更新stage_state.every_agent_state中自己的状态
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
    测试tool_decision需在根目录下执行 python -m mas.skills.tool_decision 
    '''
    from mas.agent.configs.llm_config import LLMConfig
    
    print("测试Tool Decision技能的调用")
    # 创建一个模拟的代理状态  
    agent_state = {  
        "agent_id": "0001",  
        "name": "灰风/小灰",
        "role": "网页操作员",
        "profile": "负责操作网页",
        "working_state": "idle",
        "llm_config": LLMConfig.from_yaml("mas/role_config/qwen235b.yaml"),  
        "working_memory": {},  
        "persistent_memory": "",
        "agent_step": AgentStep("0001"),  
        "skills": ["planning", "reflection", "summary",  
                   "instruction_generation", "quick_think", "think", "tool_decision",
                   "send_message", "process_message"],
        "tools": ["browser_use",],
    }

    # 构造虚假的历史步骤
    step1 = StepState(
        task_id="0001",stage_id="0001",agent_id="0001",
        step_intention="指令生成",
        step_type="skill",
        executor="instruction_generation",
        text_content="为下一个工具生成指令",
        execute_result={"instruction_generation": "<错误获取！！！>"},
    )
    step2 = StepState(
        task_id="0001",stage_id="0001",agent_id="0001",
        step_intention="获取候选人简历",
        step_type="skill",
        executor="browser_use",
        text_content="打开Boss直聘网站获取候选人简历",
        execute_result={"browser_use":
            {
                "执行意图": "打开小弟直聘网站",
                "执行命令": "<执行命令>",
                "执行结果": "<执行错误！！！>",
            }
        },
    )
    step3 = StepState(
        task_id="0001",stage_id="0001",agent_id="0001",
        step_intention="反思",
        step_type="skill",
        executor="reflection",
        text_content="进行反思",
        execute_result={"reflection": "<工具步骤失败，重新执行工具步骤>"
        },
    )
    step4 = StepState(
        task_id="0001", stage_id="0001", agent_id="0001",
        step_intention="指令生成",
        step_type="skill",
        executor="instruction_generation",
        text_content="为下一个工具生成指令",
        execute_result={"instruction_generation": "<正确工具指令>"},
    )
    step5 = StepState(
        task_id="0001", stage_id="0001", agent_id="0001",
        step_intention="获取候选人简历",
        step_type="skill",
        executor="browser_use",
        text_content="打开Boss直聘网站获取候选人简历",
        execute_result={"browser_use":
            {
                "执行意图": "打开小弟直聘网站",
                "执行命令": "<执行命令>",
                "执行结果": "<已经打开网站,呈现一些页面元素：1.候选人简历下载;2.简历上传;3.重置账号密码>",
            }
        },
    )
    step6 = StepState(
        task_id="0001", stage_id="0001", agent_id="0001",
        step_intention="进行工具决策",
        step_type="skill",
        executor="tool_decision",
        text_content="进行工具决策<tool_name>browser_use</tool_name>",
        execute_result={"tool_decision":
            [
                {
                    "step_intention": "生成指令",
                    "type": "skill",
                    "executor": "instruction_generation",
                    "text_content": "为下一个工具生成具体工具调用指令",
                },
                {
                    "step_intention": "下载候选人简历",
                    "type": "tool",
                    "executor": "browser_use",
                    "text_content": "在当前页面上点击候选人简历下载按钮",
                }
            ]
        },
    )
    step7 = StepState(
        task_id="0001", stage_id="0001", agent_id="0001",
        step_intention="紧急处理消息恢复",
        step_type="skill",
        executor="send_message",
        text_content="紧急处理消息恢复",
        execute_result={"send_message": "<发送消息>"},
    )
    step8 = StepState(
        task_id="0001", stage_id="0001", agent_id="0001",
        step_intention="指令生成",
        step_type="skill",
        executor="instruction_generation",
        text_content="为下一个工具生成指令",
        execute_result={"instruction_generation": "<正确工具指令>"},
    )
    step9 = StepState(
        task_id="0001", stage_id="0001", agent_id="0001",
        step_intention="下载候选人简历",
        step_type="skill",
        executor="browser_use",
        text_content="在当前页面上点击候选人简历下载按钮",
        execute_result={"browser_use":
            {
                "执行意图": "下载候选人简历",
                "执行命令": "<执行命令>",
                "执行结果": "<点击候选人简历下载按钮,呈现一些页面元素：请先输入账号密码>",
            }
        },
    )
    step10 = StepState(
        task_id="0001", stage_id="0001", agent_id="0001",
        step_intention="进行工具决策",
        step_type="skill",
        executor="tool_decision",
        text_content="进行工具决策<tool_name>browser_use</tool_name>",
        execute_result={},
    )

    agent_state["agent_step"].add_step(step1)
    agent_state["agent_step"].add_step(step2)
    agent_state["agent_step"].add_step(step3)
    agent_state["agent_step"].add_step(step4)
    agent_state["agent_step"].add_step(step5)
    agent_state["agent_step"].add_step(step6)
    agent_state["agent_step"].add_step(step7)
    agent_state["agent_step"].add_step(step8)
    agent_state["agent_step"].add_step(step9)
    agent_state["agent_step"].add_step(step10)

    step_id = agent_state["agent_step"].step_list[9].step_id  # 当前为第十个step

    tool_decision_skill = ToolDecisionSkill()  # 实例化Tool Decision技能
    execute_output = tool_decision_skill.execute(step_id, agent_state)
    # 打印step信息
    agent_state["agent_step"].print_all_steps()
