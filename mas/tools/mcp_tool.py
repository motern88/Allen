'''
工具名称: MCP
期望作用: Agent通过调用该工具，从而能够调度任意MCP（Model Context Protocol）的服务器端点。（本mcp tool用于在MAS中兼容MCP协议的服务器端实现。）
    对于Agent而言，MCP工具连接多个MCP的服务端。对于真正的MCP Server端点而言，该MCP Server工具是他们的Client客户端。

Agent --> MCP Tool --> MCP Server Endpoint
Agent <--  "MCP Client"   <-- MCP Server Endpoint


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

注：指令生成和工具决策技能均能够获取 mcp_base_prompt 提示词，
    指令生成在组装tool step提示词中包含mcp_base_prompt，
    工具决策在组装get_tool_decision_prompt时包含mcp_base_prompt

'''
import re
import json
import asyncio
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union

from mas.tools.mcp_client import MCPClient
from mas.agent.base.executor_base import Executor


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

    def get_capabilities_list_description(self, mcp_server_name, mcp_client):
        '''
        获取MCP服务的能力列表描述。
        1. 获取MCPClient.server_descriptions中对应的mcp_server_name的能力范围。
        2. 调用MCPClient.get_server_descriptions方法获取具体的能力列表。
            分别获取prompts、resources和tools的描述（根据Sever是否支持该能力）。
        '''
        capabilities_list_description = {}

        # 1. 获取MCPClient.server_descriptions中对应的mcp_server_name的能力范围
        server_capabilities = mcp_client.server_descriptions.get(mcp_server_name, {})
        if not server_capabilities:
            return None

        # 2. 调用MCPClient.get_server_descriptions方法获取具体的能力列表
        if server_capabilities["prompts"] is True:
            # 如果prompts为True，则获取所有prompts的描述
            prompts_description = mcp_client.get_server_descriptions(mcp_server_name, "prompts")
            if prompts_description is not None:
                capabilities_list_description["prompts"] = prompts_description

        if server_capabilities["resources"] is True:
            # 如果resources为True，则获取所有resources的描述
            resources_description = mcp_client.get_server_descriptions(mcp_server_name, "resources")
            if resources_description is not None:
                capabilities_list_description["resources"] = resources_description

        if server_capabilities["tools"] is True:
            # 如果tools为True，则获取所有tools的描述
            tools_description = mcp_client.get_server_descriptions(mcp_server_name, "tools")
            if tools_description is not None:
                capabilities_list_description["tools"] = tools_description

        if capabilities_list_description == {}:
            return None
        else:
            return capabilities_list_description

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

    def execute(self, step_id: str, agent_state: Dict[str, Any], mcp_client: MCPClient):
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
            capabilities_list_description = self.get_capabilities_list_description(mcp_server_name, mcp_client)

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
                                 f"决策使用哪个具体的能力进行下一步操作，以满足工具调用目标。",
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
            mcp_server_result = mcp_client.use_capability(
                server_name=server_name,
                capability_type=capability_type,
                capability_name=capability_name,
                arguments=arguments,
            )

            # 更新执行结果，同时触发tool_decision技能进行工具调用的完成判定
            self.add_next_tool_decision_step(
                step_intention="决策工具调用完成与否",
                text_content=f"根据上一步工具调用步骤的execute_result执行结果中返回的mcp_server_result具体调用结果，"
                             f"决策当前工具调用目标是否达成。",
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
