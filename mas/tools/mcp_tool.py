'''
工具名称: MCP
期望作用: Agent通过调用该工具，从而能够调度任意MCP（Model Context Protocol）的服务器端点。（本mcp tool用于在MAS中兼容MCP协议的服务器端实现。）
    对于Agent而言，MCP工具连接多个MCP的服务端。对于真正的MCP Server端点而言，该MCP Server工具是他们的Client客户端。

Agent  -->  MCP Tool    -->  MCP Server Endpoint
Agent  <--  MCP Client  <--  MCP Server Endpoint


Agent通过mcp工具能够实现调用符合MCP协议的任意服务器端点。

对于工具使用流程而言，在MAS中：
    1. 获取到 MCP Server 级别描述：
        Agent通过每个技能Executor中提示词“available_skills_and_tools”部分，
        可以获取到每个工具server写在 mas/tools/mcp_server_config 下 <tool_name>_mcp_config.yaml 文件中的描述，
        并根据此做出是否调用的决策。
    2. 获取到 MCP Server 的具体能力级别的描述：
        MCPTool Executor 通过调用 MCPClient 获取到当前工具下所有可用的能力的list
        （根据该MCP Server支持的能力，获取其所有能力对应的调用list）
        并根据此做出具体调用哪个具体能力的决策。
    3. 调用 MCP Server 的具体能力：
        根据第2步获取到的能力列表，Agent可以选择调用其中的某个能力。并按照其格式
        MCPTool Executor 通过调用 MCPClient 的 execute 方法，传入具体的能力名称和参数，
        来执行该能力并获取结果。

说明：
1.指令生成和工具决策技能均能够获取 mcp_base_prompt 提示词，
    指令生成技能instruction generation在组装tool step提示词中包含mcp_base_prompt，
    工具决策技能tool decision在get_tool_decision_prompt()方法中包含mcp_base_prompt

2.对于工具调用，有别于技能调用，技能调用直接找到StepState.executor对应的技能executor即可。
    （如果不接入MCP，则为每一个工具都实现一个Executor，此时执行步骤时传入的StepState.executor对应上相应的工具Executor即可；
    然而，我们全盘接入MCP，则始终仅有一个MCPToolExecutor对应所有的MCP Server。
    即所有的工具Step，不论StepState.executor是什么，均会调用这一个MCPToolExecutor。
    这一部分调用逻辑在Router路由中设置。）

    但是工具中的StepState.executor实际上是MCP Server的名字，而只要是StepState。
    因此调用MCPToolExecutor的依据是StepState.type = tool就调用。


'''
import re
import json
import asyncio
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union

from mas.agent.base.executor_base import Executor
from mas.agent.state.step_state import StepState, AgentStep
from mas.async_loop import MCPClientWrapper


@Executor.register(executor_type="tool", executor_name="mcp_tool")
class MCPTool(Executor):
    def __init__(self):
        super().__init__()

    def add_next_tool_decision_step(
        self,
        step_intention: str,
        text_content: str,
        step_id: str,
        agent_state: Dict[str, Any],
    ):
        '''
        在AgentStep中追加插入下一个工具决策步骤。
        需要传入工具决策步骤的step_intention步骤意图和text_content文本说明。
        需要传入step_id和agent_state，以便调用ExecutorBase方法中添加下一个步骤。
        '''
        # 构造工具决策步骤的字典
        tool_decision_step = {
            "step_intention": step_intention,
            "text_content": text_content,
            "type": "skill",  # 步骤类型默认为"skill"
            "executor": "tool_decision",  # 执行器默认为"tool_decision"
        }
        # 调用ExecutorBase的方法，在AgentStep中添加下一个步骤
        self.add_next_step([tool_decision_step], step_id, agent_state)

    def get_execute_output(
        self,
        step_id: str,
        agent_state: Dict[str, Any],
        update_agent_situation: str,
        shared_step_situation: str,
    ) -> Dict[str, Any]:
        '''
        构造MCP Tool工具的execute_output。
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
            "content": f"执行MCP Tool步骤:{shared_step_situation}，"
        }

        return execute_output

    def execute(self, step_id: str, agent_state: Dict[str, Any], mcp_client_wrapper: MCPClientWrapper):
        '''
        执行MCP工具，调用MCP客户端的execute方法。

        1. 获取step_state.instruction_content中的指令内容。
        2. 根据指令类型执行相应的操作。
            - 如果指令类型"instruction_type"字段是"get_description"，则获取MCP服务的能力列表描述。
            - 如果指令类型"instruction_type"字段是"function_call"，则执行MCP服务的具体能力。
        '''

        # step状态更新为 running
        agent_state["agent_step"].update_step_status(step_id, "running")

        # 1. 获取step_state.instruction_content中的指令内容
        step_state = agent_state["agent_step"].get_step(step_id)[0]  # 获取当前StepState
        instruction_content = step_state.instruction_content

        # 2. 根据指令类型执行相应的操作
        # 如果指令类型"instruction_type"字段是"get_description"，则获取MCP服务的能力列表描述
        if instruction_content["instruction_type"] == "get_description":
            '''
            如果instruction_content中的指令内容：
            {
                "instruction_type": "get_description",
            }
            则说明该操作是需要获取MCP服务的能力列表描述。
            '''
            # 获取MCP服务的能力列表描述
            mcp_server_name = step_state.executor  # 工具执行器名称即为MCP服务名称
            capabilities_list_description = mcp_client_wrapper.get_capabilities_list_description(mcp_server_name)
            # print("[Debug][mcp_tool]获取到的MCP Server能力列表描述:", capabilities_list_description)

            if capabilities_list_description is None:
                # 如果没有获取到能力列表描述，则更新执行结果为失败
                agent_state["agent_step"].update_step_status(step_id, "failed")  # step状态更新为 failed
                step_state.update_execute_result({"error": "获取MCP Server的能力列表描述失败"})
                # 构造execute_output用于更新自己在stage_state.every_agent_state中的状态
                execute_output = self.get_execute_output(
                    step_id,
                    agent_state,
                    update_agent_situation="failed",
                    shared_step_situation="failed",
                )
                return execute_output
            else:
                # 如果获取到能力列表描述，同时触发tool_decision技能进一步决策调用哪个具体能力
                self.add_next_tool_decision_step(
                    step_intention="决策调用MCP Server的具体能力",
                    text_content=f"根据上一步工具调用结果返回的capabilities_list_description能力列表描述，"
                                 f"决策使用哪个具体的能力进行下一步操作，以满足工具调用目标。\n"
                                 f"需要决策的工具名：<tool_name>{mcp_server_name}</tool_name>",
                    step_id=step_id,
                    agent_state=agent_state,
                )
                # 并则更新执行结果为成功
                agent_state["agent_step"].update_step_status(step_id, "finished")  # step状态更新为 finished
                step_state.update_execute_result({"capabilities_list_description": capabilities_list_description})
                # 构造execute_output用于更新自己在stage_state.every_agent_state中的状态
                execute_output = self.get_execute_output(
                    step_id,
                    agent_state,
                    update_agent_situation="working",
                    shared_step_situation="finished",
                )
                return execute_output

        # 如果指令类型"instruction_type"字段是"function_call"，则执行MCP服务的具体能力
        elif instruction_content["instruction_type"] == "function_call":
            '''
            如果instruction_content中的指令内容：
            {
                "instruction_type": "function_call",
                ...
            }
            则说明该操作是执行MCP服务的具体能力。
            '''
            if "tool_name" in instruction_content.keys():
                # 如果指令内容中包含"tool_name"字段，则说明需要调用MCP服务的具体工具。
                # {"tool_name": "<TOOL_NAME>"}
                capability_type = "tools"
                capability_name = instruction_content["tool_name"]
            elif "resource_name" in instruction_content.keys():
                # 如果指令内容中包含"resource_name"字段，则说明需要调用MCP服务的具体资源。
                # {"resource_name": "<RESOURCE_NAME>"}
                capability_type = "resources"
                capability_name = instruction_content["resource_name"]
            elif "prompt_name" in instruction_content.keys():
                # 如果指令内容中包含"prompt_name"字段，则说明需要调用MCP服务的具体提示词。
                # {"prompt_name": "<PROMPT_NAME>"}
                capability_type = "prompts"
                capability_name = instruction_content["prompt_name"]
            else:
                # 如果指令内容中没有可执行的指令类型，则更新执行结果为失败
                agent_state["agent_step"].update_step_status(step_id, "failed")  # step状态更新为 failed
                step_state.update_execute_result({"error": "当前工具步骤中instruction_content部分没有可执行的指令类型"})
                # 构造execute_output用于更新自己在stage_state.every_agent_state中的状态
                execute_output = self.get_execute_output(
                    step_id,
                    agent_state,
                    update_agent_situation="failed",
                    shared_step_situation="failed",
                )
                return execute_output

            # 执行MCP服务的具体能力
            server_name = step_state.executor  # 工具执行器名称即为MCP服务名称
            arguments = instruction_content.get("arguments", {})  # 获取指令内容中的参数，如果没有则默认为空字典
            mcp_server_result = mcp_client_wrapper.use_capability_sync(
                server_name=server_name,
                capability_type=capability_type,
                capability_name=capability_name,
                arguments=arguments,
            )

            # 更新执行结果，同时触发tool_decision技能进行工具调用的完成判定
            self.add_next_tool_decision_step(
                step_intention="决策工具调用完成与否",
                text_content=f"根据上一步工具调用步骤的execute_result执行结果中返回的mcp_server_result具体调用结果，"
                             f"决策当前工具调用目标是否达成。\n"
                             f"需要决策的工具名：<tool_name>{server_name}</tool_name>，",
                step_id=step_id,
                agent_state=agent_state,
            )
            # 并则更新执行结果为成功
            agent_state["agent_step"].update_step_status(step_id, "finished")  # step状态更新为 finished
            step_state.update_execute_result({"mcp_server_result": mcp_server_result})
            # 构造execute_output用于更新自己在stage_state.every_agent_state中的状态
            execute_output = self.get_execute_output(
                step_id,
                agent_state,
                update_agent_situation="working",
                shared_step_situation="finished",
            )
            return execute_output

        # instruction_content中instruction_type既不是获取能力列表也不是执行具体能力，则更新执行结果为失败
        else:
            # 更新执行结果为失败
            agent_state["agent_step"].update_step_status(step_id, "failed")  # step状态更新为 failed
            step_state.update_execute_result({"error": "当前工具步骤中instruction_content部分没有可执行的指令类型"})
            # 构造execute_output用于更新自己在stage_state.every_agent_state中的状态
            execute_output = self.get_execute_output(
                step_id,
                agent_state,
                update_agent_situation="failed",
                shared_step_situation="failed",
            )
            return execute_output

# Debug
if __name__ == "__main__":
    '''
    测试mcp_tool需要在Allen根目录下执行 python -m mas.tools.mcp_tool
    '''
    from mas.agent.configs.llm_config import LLMConfig
    from mas.async_loop import AsyncLoopThread, MCPClientWrapper
    from mas.tools.mcp_client import MCPClient

    agent_state = {
        "agent_id": "0001",
        "name": "小灰",
        "role": "工具调用专家",
        "profile": "负责工具调用，帮助MAS系统实现与真实环节的交互",
        "working_state": "idle",
        "llm_config": LLMConfig.from_yaml("mas/agent/configs/test_llm_config.yaml"),
        "working_memory": {},
        "persistent_memory": {},
        "agent_step": AgentStep("0001"),
        "skills": [
            "planning", "reflection", "summary", "instruction_generation", "quick_think", "think", "tool_decision",  # 步骤执行基础技能
            "send_message", "process_message",  # 通信基础技能
            "task_manager", "agent_manager", "ask_info",  # 管理技能
        ],
        "tools": [
            "amap_maps","everything","playwright"
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
        execute_result={'tool_decision': [
            {'step_intention': '生成指令', 'type': 'skill', 'executor': 'instruction_generation',
             'text_content': '根据MCP Server能力列表描述，生成调用具体工具能力的function_call指令'},
            {'step_intention': '调用MCP Server具体工具能力', 'type': 'tool', 'executor': 'every_thing',
             'text_content': '根据能力列表选择目标工具/资源/提示，生成对应的function_call指令并执行'}]}
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
        instruction_content={'instruction_type': 'function_call', 'tool_name': 'echo',
                             'arguments': {'message': '测试回声消息'}},
        execute_result={'mcp_server_result': "[TextContent(type='text', text='Echo: 测试回声消息', annotations=None, meta=None)]"}
    )

    agent_state["agent_step"].add_step(step1)
    agent_state["agent_step"].add_step(step2)
    agent_state["agent_step"].add_step(step3)
    agent_state["agent_step"].add_step(step4)
    agent_state["agent_step"].add_step(step5)

    step_id = agent_state["agent_step"].step_list[4].step_id  # 当前为第五个step


    # 模拟MAS中初始化AsyncLoopThread，MCPClient和MCPClientWrapper
    # ---------------------------------------------------------------------------------------------
    async_loop = AsyncLoopThread()  # 实例化异步事件循环线程，用于在多线程环境中运行异步任务，例如MCPClient的异步调用
    async_loop.start()

    async def _init_mcp_client():
        '''
        异步初始化 MCPClient。
        '''
        mcp_client = MCPClient()
        await mcp_client.initialize_servers()
        return mcp_client

    # 在事件循环中创建 MCPClient 并初始化
    future = async_loop.run_coroutine(_init_mcp_client())
    mcp_client = future.result()  # 同步等待初始化完成
    # 实例化 MCPClientWrapper
    mcp_client_wrapper = MCPClientWrapper(mcp_client, async_loop)
    # ---------------------------------------------------------------------------------------------


    print("[Test] MCP Client已实例化，当前可用的MCP Server描述：\n", mcp_client.server_descriptions, "\n")
    # 实例化 MCPTool
    mcp_tool = MCPTool()
    mcp_tool.execute(step_id, agent_state, mcp_client_wrapper=mcp_client_wrapper)

    # 打印step信息
    print("[Test] 执行完毕，当前AgentStep状态：\n")
    agent_state["agent_step"].print_all_steps()

















