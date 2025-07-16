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

todo：指令生成和工具决策技能均能够获取 mcp_base_prompt 提示词

'''
import re
import json
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union

from mas.tools.mcp_client import MCPClient
from mas.agent.base.executor_base import Executor

@Executor.register(executor_type="tool", executor_name="mcp_tool")
class MCPTool(Executor):
    def __init__(self):
        super().__init__()

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
            "content": f"执行Instruction Generation步骤:{shared_step_situation}，"
        }

        return execute_output

    def execute(self, step_id: str, agent_state: Dict[str, Any], mcp_client: MCPClient):
        '''
        执行MCP工具，调用MCP客户端的execute方法。

        1. 获取step_state.instruction_content中的指令内容。
        2. 根据指令类型执行相应的操作。 TODO：instruction_generation尚未实现相应指令生提示
            - 如果指令类型"instruction_type"字段是"get_description"，则获取MCP服务的能力列表描述。
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
            TODO:如果成功则追加tool_decision技能进一步决策调用哪个具体能力
            '''
            # 获取MCP服务的能力列表描述
            mcp_server_name = instruction_content["mcp_server_name"]
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
                # 如果获取到能力列表描述，则更新执行结果为成功
                # TODO:同时触发tool_decision技能进一步决策调用哪个具体能力
                agent_state["agent_step"].update_step_status(step_id, "finished")  # step状态更新为 finished
                step_state.update_execute_result({"capabilities_list_description": capabilities_list_description})
                # 构造execute_output用于更新自己在stage_state.every_agent_state中的状态
                execute_output = self.get_execute_output(
                    step_id,
                    agent_state,
                    update_agent_situation="finished",
                    shared_step_situation="获取MCP Server的能力列表描述成功",
                )
                return execute_output




