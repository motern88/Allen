'''
技能名称: Instruction Generation
期望作用: 为下一个工具step生成实际工具调用指令。

Instruction Generation会获取下一个工具step的信息，并具备更新下一个工具step的能力。
我们将获取到的下一个工具step中工具的提示信息和指令生成的提示信息以特定格式输入LLM进行指令生成，同时捕获LLM以特定格式返回的指令内容。
然后基于规则的代码解析这些信息，并更新下一个工具step的指令内容。

NOTE:
一种可能的特殊情况是，在instruction_generation_step和tool_step之间被插入了一个额外tool_step,(插入step很常见，任务分配线程有权利这么做)
这将会导致instruction_generation为错误的tool_step生成指令。
实际上插入step的操作只会插入在下一个未执行的step前：
    如果 instruction_generation_step 未执行，则插入step会插入在 instruction_generation_step 之前；
    如果 instruction_generation_step 正在执行，则线程锁会暂时禁止AgentStep被Agent的任务分配线程插入step；
    如果 instruction_generation_step 执行完成，原定下一个 tool_step 未执行，这时插入step会插入在 tool_step 之前，
    但此时原定下一个 tool_step 已经被生成完指令了，因此也不会对工具执行造成影响。
因此，只要Agent的任务执行线程、Agent的任务分配线程、线程锁等逻辑不发生改变，则指令生成一般都能够顺利为正确工具生成指令。

提示词顺序（系统 → 角色 → (目标 → 规则) → 记忆）

具体实现:
    1. 组装提示词:
        1.1 MAS系统提示词（# 一级标题）
        1.2 Agent角色提示词:（# 一级标题）
            1.2.1 Agent角色背景提示词（## 二级标题）
            1.2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        1.3 instruction_generation step:（# 一级标题）
            1.3.1 指令生成step.step_intention 当前步骤的简要意图
            1.3.2 指令生成step.text_content 具体目标
            1.3.3 技能规则提示(instruction_generation_config["use_prompt"])
        1.4 tool step:（# 一级标题）
            1.4.1 工具step.step_intention 当前步骤的简要意图（## 二级标题）
            1.4.2 工具step.text_content 具体目标（## 二级标题）
            1.4.3 MCP工具调用的基础规则提示（#### 四级标题）
            1.4.4 当前MCP工具的简要描述
        1.5 持续性记忆:（# 一级标题）
            1.5.1 Agent持续性记忆说明提示词（## 二级标题）
            1.5.2 Agent持续性记忆内容提示词（## 二级标题）

    2. llm调用
    3. 解析 LLM 返回的指令内容，并追加到下一个工具step的指令内容中
    4. 解析llm返回的持续性记忆信息，追加到Agent的持续性记忆中
    5. 构造并返回 execute_output(更新stage_state.every_agent_state中自己的状态)
'''
import re
import json5
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union

from mas.agent.base.executor_base import Executor
from mas.agent.state.step_state import StepState, AgentStep



# 注册指令生成技能到类型 "skill", 名称 "instruction_generation"
@Executor.register(executor_type="skill", executor_name="instruction_generation")
class InstructionGenerationSkill(Executor):
    def __init__(self):
        super().__init__()  # 调用父类的构造方法

    def extract_tool_instruction(self, text: str):
        '''
        从文本中解析工具调用指令,解析成字典形式
        '''
        # 使用正则表达式提取 <tool_instruction> ... </tool_instruction> 之间的内容
        match = re.findall(r"<tool_instruction>\s*(.*?)\s*</tool_instruction>", text, re.DOTALL)
        if match:
            tool_instruction_str = match[-1]  # 获取最后一个匹配内容 排除是在<think></think>思考期间的内容
            try:
                tool_instruction_json = json5.loads(tool_instruction_str)  # 使用json5解析，支持单引号、注释和未转义的双引号等
                return tool_instruction_json
            except Exception as e:
                print(f"[InstructionGeneration]JSON解析失败 {e}:", tool_instruction_str)
                return None
        else:
            return None


    def get_instruction_generation_prompt(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        组装提示词:
        1 MAS系统提示词（# 一级标题）
        2 Agent角色提示词:（# 一级标题）
            2.1 Agent角色背景提示词（## 二级标题）
            2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        3 instruction_generation step:（# 一级标题）
            3.1 指令生成step.step_intention 当前步骤的简要意图
            3.2 指令生成step.text_content 具体目标
            3.3 技能规则提示(instruction_generation_config["use_prompt"])
        4 tool step:（# 一级标题）
            4.1 工具step.step_intention 当前步骤的简要意图
            4.2 工具step.text_content 具体目标
            4.3 MCP工具调用的基础规则提示（#### 四级标题）
            4.4 当前MCP工具的简要描述
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


        # 3. Instruction Generation step提示词
        md_output.append(f"# 当前需要执行的步骤 current_step\n")
        current_step = self.get_current_skill_step_prompt(step_id, agent_state)  # 不包含标题的md格式文本
        md_output.append(f"{current_step}\n")


        # 4. 工具step的提示词
        md_output.append(f"# 生成实际工具调用指令的提示 tool_step\n")
        tool_prompt = self.get_tool_instruction_generation_step_prompt(step_id, agent_state)  # 不包含标题的md格式文本
        md_output.append(f"{tool_prompt}\n")


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
    ) -> Dict[str, Any]:
        '''
        构造Instruction Generation技能的execute_output。这部分使用代码固定构造，不由LLM输出构造。
        1. update_agent_situation:
            通过update_stage_agent_state字段指导sync_state更新stage_state.every_agent_state中自己的状态
            (一般情况下，只有Summary技能完成时，该字段传入finished，其他步骤完成时，该字段都传入working)
        2. shared_step_situation:
            添加步骤信息到task共享信息池
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
            "content": f"执行Instruction Generation步骤:{shared_step_situation}，"
        }

        return execute_output

    def execute(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        Instruction Generation技能的具体执行方法:
        (工具step的指令部分在execute内完成更新)

        1. 组装 LLM Instruction Generation 提示词
        2. LLM调用
        3. 解析 LLM 返回的指令内容，并追加到下一个工具step的指令内容中
        4. 解析persistent_memory并追加到Agent持续性记忆中
        5. 构造并返回 execute_output，更新stage_state.every_agent_state中自己的状态

        '''

        # step状态更新为 running
        agent_state["agent_step"].update_step_status(step_id, "running")

        # 1. 组装 LLM Instruction Generation 提示词 (基础提示词、技能提示词与工具提示词)
        instruction_generation_prompt = self.get_instruction_generation_prompt(step_id, agent_state)  # 包含 # 一级标题的md格式文本

        # 2. LLM调用
        llm_client = agent_state["llm_client"]  # 使用agent_state中维护的 LLM 客户端
        chat_context = agent_state["llm_context"]  # 使用agent_state中维护的 LLM 上下文

        chat_context.add_message("assistant", "好的，我会作为你提供的Agent角色，执行instruction_generation操作"
                                              "我会根据 tool_step，遵从tool_prompt工具调用规则，并生成相应工具调用指令。"
                                              "并在<tool_instruction>和</tool_instruction>之间输出指令内容，"
                                              "在<persistent_memory>和</persistent_memory>之间输出我要追加的持续性记忆(如果我认为不需要追加我会空着)。")

        response = llm_client.call(
            instruction_generation_prompt,
            context=chat_context
        )
        # print(f"LLM完整响应:\n{response}")  # 添加响应输出

        # 3. 解析 LLM 返回的指令内容，并追加到下一个工具step的指令内容中
        tool_instruction = self.extract_tool_instruction(response)
        next_tool_step = self.get_next_tool_step(step_id, agent_state)  # 获取下一个工具step

        # 添加调试信息  
        # print(f"提取的指令内容: {tool_instruction}")

        # 如果无法解析到指令信息，或无法获取到下一个工具step
        if not tool_instruction or not next_tool_step:
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
            )
            return execute_output

        else:  # 解析到指令信息
            # 记录指令结果到execute_result
            step = agent_state["agent_step"].get_step(step_id)[0]
            execute_result = {"instruction_generation": tool_instruction}  # 构造符合execute_result格式的执行结果
            step.update_execute_result(execute_result)

            # 追加指令结果到下一个工具step中
            next_tool_step.update_instruction_content(tool_instruction)

            # 4. 解析persistent_memory指令内容并应用到Agent持续性记忆中
            instructions = self.extract_persistent_memory(response)  # 提取<persistent_memory>和</persistent_memory>之间的指令内容
            self.apply_persistent_memory(agent_state, instructions)  # 将指令内容应用到Agent的持续性记忆中

            # step状态更新为 finished
            agent_state["agent_step"].update_step_status(step_id, "finished")

            # 5. 构造execute_output，用于更新stage_state.every_agent_state
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
    测试instruction_generation需在Allen根目录下执行 python -m mas.skills.instruction_generation
    '''
    from mas.agent.configs.llm_config import LLMConfig

    print("测试Instruction Generation技能的调用")
    # 创建一个模拟的代理状态
    agent_state = {
        "agent_id": "0001",
        "name": "灰风/小灰",
        "role": "工具调用专家",
        "profile": "负责工具调用，帮助MAS系统实现与真实环节的交互",
        "working_state": "idle",
        "llm_config": LLMConfig.from_yaml("mas/agent/configs/test_llm_config.yaml"),
        "working_memory": {},
        "persistent_memory": {},
        "agent_step": AgentStep("0001"),
        "skills": [
            "planning", "reflection", "summary", "instruction_generation", "quick_think", "think", "tool_decision",
            # 步骤执行基础技能
            "send_message", "process_message",  # 通信基础技能
            "task_manager", "agent_manager", "ask_info",  # 管理技能
        ],
        "tools": [
            "amap_maps", "everything", "playwright"
        ],
    }

    # 构造虚假的历史步骤
    step1 = StepState(
        task_id="0001", stage_id="0001", agent_id="0001",
        step_intention="指令生成",
        type="skill",
        executor="instruction_generation",
        text_content="为下一个工具生成指令",
        execute_result={"instruction_generation": {"instruction_type": "get_description"}},
    )
    step2 = StepState(
        task_id="0001", stage_id="0001", agent_id="0001",
        step_intention="指令生成",
        type="tool",
        executor="everything",
        text_content="调用everything其中一种工具用作测试",
        instruction_content={
            "instruction_type": "get_description"
        },
        execute_result={
            'capabilities_list_description':
                {'tools': {
                    'echo': {'description': 'Echoes back the input', 'title': None, 'input_schema': {'type': 'object',
                                                                                                     'properties': {
                                                                                                         'message': {
                                                                                                             'type': 'string',
                                                                                                             'description': 'Message to echo'}},
                                                                                                     'required': [
                                                                                                         'message'],
                                                                                                     'additionalProperties': False,
                                                                                                     '$schema': 'http://json-schema.org/draft-07/schema#'},
                             'output_schema': None, 'required': None},
                    'add': {'description': 'Adds two numbers', 'title': None, 'input_schema': {'type': 'object',
                                                                                               'properties': {'a': {
                                                                                                   'type': 'number',
                                                                                                   'description': 'First number'},
                                                                                                   'b': {
                                                                                                       'type': 'number',
                                                                                                       'description': 'Second number'}},
                                                                                               'required': ['a', 'b'],
                                                                                               'additionalProperties': False,
                                                                                               '$schema': 'http://json-schema.org/draft-07/schema#'},
                            'output_schema': None, 'required': None}, 'printEnv': {
                        'description': 'Prints all environment variables, helpful for debugging MCP server configuration',
                        'title': None,
                        'input_schema': {'type': 'object', 'properties': {}, 'additionalProperties': False,
                                         '$schema': 'http://json-schema.org/draft-07/schema#'}, 'output_schema': None,
                        'required': None}, 'longRunningOperation': {
                        'description': 'Demonstrates a long running operation with progress updates', 'title': None,
                        'input_schema': {'type': 'object', 'properties': {'duration': {'type': 'number', 'default': 10,
                                                                                       'description': 'Duration of the operation in seconds'},
                                                                          'steps': {'type': 'number', 'default': 5,
                                                                                    'description': 'Number of steps in the operation'}},
                                         'additionalProperties': False,
                                         '$schema': 'http://json-schema.org/draft-07/schema#'}, 'output_schema': None,
                        'required': None},
                    'sampleLLM': {'description': "Samples from an LLM using MCP's sampling feature", 'title': None,
                                  'input_schema': {'type': 'object', 'properties': {
                                      'prompt': {'type': 'string', 'description': 'The prompt to send to the LLM'},
                                      'maxTokens': {'type': 'number', 'default': 100,
                                                    'description': 'Maximum number of tokens to generate'}},
                                                   'required': ['prompt'], 'additionalProperties': False,
                                                   '$schema': 'http://json-schema.org/draft-07/schema#'},
                                  'output_schema': None, 'required': None},
                    'getTinyImage': {'description': 'Returns the MCP_TINY_IMAGE', 'title': None,
                                     'input_schema': {'type': 'object', 'properties': {}, 'additionalProperties': False,
                                                      '$schema': 'http://json-schema.org/draft-07/schema#'},
                                     'output_schema': None, 'required': None}, 'annotatedMessage': {
                        'description': 'Demonstrates how annotations can be used to provide metadata about content',
                        'title': None, 'input_schema': {'type': 'object', 'properties': {
                            'messageType': {'type': 'string', 'enum': ['error', 'success', 'debug'],
                                            'description': 'Type of message to demonstrate different annotation patterns'},
                            'includeImage': {'type': 'boolean', 'default': False,
                                             'description': 'Whether to include an example image'}},
                                                        'required': ['messageType'], 'additionalProperties': False,
                                                        '$schema': 'http://json-schema.org/draft-07/schema#'},
                        'output_schema': None, 'required': None}, 'getResourceReference': {
                        'description': 'Returns a resource reference that can be used by MCP clients', 'title': None,
                        'input_schema': {'type': 'object', 'properties': {
                            'resourceId': {'type': 'number', 'minimum': 1, 'maximum': 100,
                                           'description': 'ID of the resource to reference (1-100)'}},
                                         'required': ['resourceId'], 'additionalProperties': False,
                                         '$schema': 'http://json-schema.org/draft-07/schema#'}, 'output_schema': None,
                        'required': None}}}
        },
    )
    step3 = StepState(
        task_id="0001", stage_id="0001", agent_id="0001",
        step_intention="决策调用MCP Server的具体能力",
        type="skill",
        executor="tool_decision",
        text_content="根据上一步工具调用结果返回的capabilities_list_description能力列表描述，决策使用哪个具体的能力进行下一步操作，以满足工具调用目标。\n需要决策的工具名：<tool_name>everything</tool_name>",
        instruction_content={},
        execute_result={'tool_decision': [{'step_intention': '生成指令', 'type': 'skill', 'executor': 'instruction_generation', 'text_content': '根据MCP Server能力列表描述，生成调用具体工具能力的function_call指令'}, {'step_intention': '调用MCP Server具体工具能力', 'type': 'tool', 'executor': 'every_thing', 'text_content': '根据能力列表选择目标工具/资源/提示，生成对应的function_call指令并执行'}]}
    )
    step4 = StepState(
        task_id="0001", stage_id="0001", agent_id="0001",
        step_intention="生成指令",
        type="skill",
        executor="instruction_generation",
        text_content="根据MCP Server能力列表描述，生成调用具体工具能力的function_call指令",
        instruction_content={},
        execute_result={}
    )
    step5 = StepState(
        task_id="0001", stage_id="0001", agent_id="0001",
        step_intention="调用MCP Server具体工具能力",
        type="tool",
        executor="everything",
        text_content="使用MCP Server的tools能力调用echo工具，传入message参数进行测试。具体调用格式为：<tool_instruction>{'instruction_type': 'function_call', 'tool_name': 'echo', 'arguments': {'message': '测试回声消息'}}</tool_instruction>",
        instruction_content={'instruction_type': 'function_call', 'tool_name': 'echo', 'arguments': {'message': '测试回声消息'}},
        execute_result={}
    )


    agent_state["agent_step"].add_step(step1)
    agent_state["agent_step"].add_step(step2)
    agent_state["agent_step"].add_step(step3)
    agent_state["agent_step"].add_step(step4)
    agent_state["agent_step"].add_step(step5)

    step_id = agent_state["agent_step"].step_list[3].step_id  # 当前为第四个step

    instruction_generation_skill = InstructionGenerationSkill()
    instruction_generation_skill.execute(step_id, agent_state)

    # 打印step信息
    agent_state["agent_step"].print_all_steps()








