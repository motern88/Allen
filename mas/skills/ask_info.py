'''
agent_viewer技能

描述
-----------
此技能提供查看和查询agent的资料及状态的功能，帮助模型做出关于智能体间通信和协作的决策。

功能
-------------
1. 资料查看：获取详细的agent资料信息  
2. 状态查询：检查agent的当前状态和可用性  
3. 能力搜索：查找具备特定能力的agent 
4. 协作建议：获取agent协作的推荐方案

核心方法
-----------
- execute(step_id, agent_state)：处理agent资料查看指令的主要入口  
- _get_agent_profile(agent_id)：获取agent的资料信息  
- _get_agent_state(agent_id)：获取agent的当前状态  
- _search_by_capability(capability)：查找具备特定能力的agent
'''

from typing import Dict, List, Any, Optional
import yaml
import json
import os
from mas.agent.base.llm_base import LLMContext, LLMClient
from mas.agent.base.executor_base import Executor
from mas.agent.state.step_state import StepState, AgentStep
from mas.agent.state.sync_state import SyncState


@Executor.register(executor_type="skill", executor_name="ask_info_skill")
class AskInfoSkill(Executor):
    def __init__(self):
        super().__init__()

    def get_ask_info_prompt(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        组装AskInfo技能的提示词，从get_info_config.yaml读取use_prompt.skill_prompt内容。
        '''
        import yaml
        config_path = os.path.join(os.path.dirname(__file__), 'get_info_config.yaml')
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        skill_prompt = config.get('use_prompt', {}).get('skill_prompt', '')
        # 可根据需要添加上下文信息，如当前step、agent等
        return skill_prompt

    def execute(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        AskInfoSkill主执行方法：
        1. 组装调用提示词（从配置文件读取）
        2. LLM调用（如有）
        3. 解析step内容决定查询类型并通过sync_state获取信息
        4. 结果通过message返回，并触发步骤锁（等待通信）。
        '''
        # step状态更新为 running
        agent_state["agent_step"].update_step_status(step_id, "running")
        step_state = agent_state["agent_step"].get_step(step_id)[0]

        # 1. 组装调用提示词
        ask_info_prompt = self.get_ask_info_prompt(step_id, agent_state)
        # 可用于LLM调用，或记录日志等
        agent_state.setdefault("debug_log", []).append({"ask_info_prompt": ask_info_prompt})

        # 2. 解析step内容决定查询类型
        query_type, query_args = self.parse_query(step_state.text_content)
        sync_state: SyncState = agent_state.get("sync_state")
        message = None

        # 3. 查询
        if query_type == "managed_tasks":
            message = self.query_managed_tasks(agent_state, sync_state)
        elif query_type == "participated_tasks":
            message = self.query_participated_tasks(agent_state, sync_state)
        elif query_type == "task_info":
            message = self.query_task_info(query_args.get("task_id"), sync_state)
        elif query_type == "stage_info":
            message = self.query_stage_info(query_args.get("stage_id"), sync_state)
        elif query_type == "all_agents_profile":
            message = self.query_all_agents_profile(sync_state)
        elif query_type == "team_agents_profile":
            message = self.query_team_agents_profile(agent_state, sync_state)
        elif query_type == "task_group_agents_profile":
            message = self.query_task_group_agents_profile(query_args.get("task_id"), sync_state)
        elif query_type == "stage_agents_profile":
            message = self.query_stage_agents_profile(query_args.get("stage_id"), sync_state)
        elif query_type == "agents_state":
            message = self.query_agents_state(query_args.get("agent_ids"), sync_state)
        else:
            message = {"error": "未知的AskInfo查询类型"}

        # 4. 步骤锁：等待通信
        agent_state.setdefault("step_lock", []).append(str(step_id))

        # 5. 构造execute_output，返回消息体
        execute_output = self.get_execute_output(
            step_id,
            agent_state,
            message=message
        )
        # step状态更新为 finished
        agent_state["agent_step"].update_step_status(step_id, "finished")
        return execute_output

    def parse_query(self, text: str):
        '''
        解析step.text_content，确定查询类型及参数。
        返回 (query_type, query_args_dict)
        '''
        # 这里建议用简单的约定格式或正则提取，实际可按需求扩展
        # 示例：<ask_info type="task_info" task_id="xxx" />
        import re
        m = re.search(r'<ask_info type="(\w+)"(.*?)\/>', text)
        if m:
            query_type = m.group(1)
            args_str = m.group(2)
            args = dict(re.findall(r'(\w+)="(.*?)"', args_str))
            # 对agent_ids特殊处理
            if "agent_ids" in args:
                args["agent_ids"] = args["agent_ids"].split(",")
            return query_type, args
        return None, {}

    def get_execute_output(self, step_id, agent_state, message):
        '''
        构造AskInfo技能的execute_output，返回消息体。
        '''
        step_state = agent_state["agent_step"].get_step(step_id)[0]
        task_id = getattr(step_state, "task_id", None)
        agent_id = agent_state["agent_id"]
        return {
            "send_message": {
                "task_id": task_id,
                "sender_id": agent_id,
                "receiver": [agent_id],
                "message": message,
                "stage_relative": getattr(step_state, "stage_id", "no_relative"),
                "need_reply": False,
                "waiting": None,
                "return_waiting_id": None,
            }
        }

    # 1. 查看自身所管理的task_state及其附属stage_state的信息
    def query_managed_tasks(self, agent_state, sync_state):
        # 假设sync_state有get_managed_tasks(agent_id)方法
        agent_id = agent_state["agent_id"]
        return sync_state.get_managed_tasks(agent_id)

    # 2. 查看自身所参与的task_state及参与的stage_state的信息
    def query_participated_tasks(self, agent_state, sync_state):
        agent_id = agent_state["agent_id"]
        return sync_state.get_participated_tasks(agent_id)

    # 3. 查看指定task_state的信息
    def query_task_info(self, task_id, sync_state):
        return sync_state.get_task_info(task_id)

    # 4. 查看指定stage_state的信息
    def query_stage_info(self, stage_id, sync_state):
        return sync_state.get_stage_info(stage_id)

    # 5. 查看MAS中所有Agent的profile
    def query_all_agents_profile(self, sync_state):
        return sync_state.get_all_agents_profile()

    # 6. 查看Team中所有Agent的profile
    def query_team_agents_profile(self, agent_state, sync_state):
        team_id = agent_state.get("team_id")
        return sync_state.get_team_agents_profile(team_id)

    # 7. 查看指定task_id的task_group中所有Agent的profile
    def query_task_group_agents_profile(self, task_id, sync_state):
        return sync_state.get_task_group_agents_profile(task_id)

    # 8. 查看指定stage下协作的所有Agent的profile
    def query_stage_agents_profile(self, stage_id, sync_state):
        return sync_state.get_stage_agents_profile(stage_id)

    # 9. 查看指定agent_id或多个agent_id的详细agent_state信息
    def query_agents_state(self, agent_ids, sync_state):
        return sync_state.get_agents_state(agent_ids)

    
    def get_agent_info_by_id(self, agent_id: str) -> Dict[str, Any]:  
        '''  
        从中央系统获取代理信息  
        这是一个示例方法，实际实现需要与MAS系统集成  
        '''  
        # 实际实现将从MAS系统中获取  
        # 这里返回一个假的示例  
        return {  
            "profile": {  
                "agent_id": agent_id,  
                "name": f"Agent {agent_id}",  
                "role": "Role information would be here",  
                "description": "Detailed description would be here"  
            },  
            "state": {  
                "working_state": "current working state",  
                "current_tasks": ["task_1", "task_2"],  
                # 其他状态信息  
            }  
        }  
    
    def get_agents_by_task_id(self, task_id: str) -> List[str]:
        '''
        根据task_id获取参与该任务的agent_id列表
        从task_state的task_group属性获取  
        '''
        # 获取task_state
        task_state = self.get_task_state_by_id(task_id)
        if task_state:
            return task_state.get("task_group", []) 
        else:
            return []
        
    def get_task_state_by_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        '''  
        TODO: 根据task_id获取task_state  
        '''  
        return central_task_registry.get_task_state(task_id)  
    
    def get_all_team_agents(self) -> List[str]:  
        '''  
        TODO: 获取当前团队中的所有Agent ID  
        '''  
        # 实际实现应从系统中获取所有团队成员  
        return central_team_registry.get_all_agent_ids()  
    
    def get_agent_viewer_prompt(self, agents_info: Dict[str, Any], agent_state: Dict[str, Any], task_id: Optional[str] = None) -> str:  
        '''  
        组装提示词  
        增加了task_id参数以在提示中提供任务上下文  
        '''  
        md_output = []  

        # 1. 基础提示词  
        md_output.append("# 系统提示 system_prompt\n")  
        system_prompt = self.get_base_prompt(key="system_prompt")  
        md_output.append(f"{system_prompt}\n")  

        # 2. 代理角色提示词  
        md_output.append("# 代理角色\n")  
        agent_role_prompt = self.get_agent_role_prompt(agent_state)  
        md_output.append(f"## 你的角色信息 agent_role\n{agent_role_prompt}\n")  

        # 3. 任务上下文（如果有）  
        if task_id:  
            task_state = self.get_task_state_by_id(task_id)  
            if task_state:  
                md_output.append("# 任务上下文\n")  
                md_output.append(f"## 任务ID: {task_id}\n")  
                md_output.append(f"## 任务意图: {task_state.get('task_intention', '无')}\n")  
                md_output.append(f"## 执行状态: {task_state.get('execution_state', '无')}\n")  
                # 可以添加更多任务相关信息  

        # 4. 查询的代理信息  
        md_output.append("# 查询的代理信息\n")  
        for agent_id, info in agents_info.items():  
            md_output.append(f"## 代理ID: {agent_id}\n")  
            md_output.append(f"### Profile:\n```json\n{json.dumps(info['profile'], indent=2)}\n```\n")  
            md_output.append(f"### State:\n```json\n{json.dumps(info['state'], indent=2)}\n```\n")  

        return "\n".join(md_output)  
    
    def extract_agent_viewer_result(self, text: str) -> Optional[Dict[str, Any]]:  
        '''  
        从LLM响应中提取代理查看的结果  
        可以使用正则表达式或其他方法解析包含在特定标记之间的内容  
        '''  
        # TODO: 实现解析逻辑，例如使用正则表达式提取<agent_viewer>标签中的内容  
        pass  

    def get_execute_output(self, step_id: str, agent_state: Dict[str, Any], agents_info: Dict[str, Any]) -> Dict[str, Any]:  
        '''  
        构造Agent Viewer技能的execute_output  
        '''  
        # 获取当前步骤的task_id与stage_id  
        step_state = agent_state["agent_step"].get_step(step_id)[0]  
        task_id = step_state.task_id  
        stage_id = step_state.stage_id  
        
        # 构造execute_output  
        execute_output = {  
            "update_stage_agent_state": {  
                "task_id": task_id,  
                "stage_id": stage_id,  
                "agent_id": agent_state["agent_id"],  
                "state": "finished"
            },  
            "send_shared_message": {  
                "agent_id": agent_state["agent_id"],  
                "role": agent_state["role"],  
                "stage_id": stage_id,  
                "content": f"查看了{len(agents_info)}个代理的信息"  
            },  
            "agent_information": agents_info  
        }  
        
        return execute_output  
    
    def execute(self, step_id: str, agent_state: Dict[str, Any], task_id: Optional[str] = None) -> Dict[str, Any]:  
        '''  
        AgentViewer技能的具体执行方法  
        参数:  
        - step_id: 当前步骤的ID  
        - task_id: 可选，特定任务的ID（如果为None则查看所有团队成员）  
        '''  
        # 更新步骤状态为running  
        agent_state["agent_step"].update_step_status(step_id, "running")  
        
        # 根据是否提供task_id选择获取Agent ID的方法  
        if task_id:  
            agent_ids = self.get_agents_by_task_id(task_id)  # 获取特定任务的代理  
        else:  
            agent_ids = self.get_all_team_agents()  # 获取整个团队的代理  
        
        # 获取代理详细信息  
        agents_info = self.extract_agent_info(agent_ids)  
        
        # 组装提示词  
        agent_viewer_prompt = self.get_agent_viewer_prompt(agents_info, agent_state, task_id)  
        
        # LLM调用  
        llm_config = agent_state["llm_config"]  
        llm_client = LLMClient(llm_config)  
        chat_context = LLMContext(context_size=15)  
        
        # 添加一条系统消息  
        system_message = "好的，我会查看这些代理的信息，并考虑如何与它们有效协作。"  
        chat_context.add_message("assistant", system_message)  
        
        # 调用LLM  
        response = llm_client.call(agent_viewer_prompt, context=chat_context)  
        
        # 解析LLM返回的信息（如果需要）  
        viewer_result = self.extract_agent_viewer_result(response)  
        
        # 记录结果  
        step = agent_state["agent_step"].get_step(step_id)[0]  
        execute_result = {"agent_viewer": agents_info}  
        if viewer_result:  
            execute_result["viewer_analysis"] = viewer_result  
        step.update_execute_result(execute_result)  
        
        # 更新步骤状态为finished  
        agent_state["agent_step"].update_step_status(step_id, "finished")  
        
        # 返回执行输出  
        execute_output = self.get_execute_output(step_id, agent_state, agents_info)  
        
        return execute_output  

if __name__ == "__main__":  
    '''  
    测试agent_viewer需在根目录下执行 python -m mas.skills.agent_viewer  
    '''
    from mas.agent.configs.llm_config import LLMConfig

    print("测试Agent Viewer技能的调用")  
    # 创建一个模拟的代理状态  
    agent_state = {  
        "agent_id": "0001",  
        "name": "小红",  
        "role": "项目协调",  
        "profile": "负责项目协调和团队协作",  
        "working_state": "Assigned tasks",  
        "llm_config": LLMConfig.from_yaml("mas/role_config/qwq32b.yaml"),  
        "working_memory": {},  
        "persistent_memory": "",  
        "agent_step": AgentStep("0001"),  
        "skills": ["planning", "reflection", "summary",  
                   "instruction_generation", "quick_think", "think",  
                   "send_message", "process_message", "agent_viewer"],  
        "tools": [],  
    }  

    # 构造一个测试步骤  
    test_step = StepState(  
        task_id="task_001",  
        stage_id="stage_001",  
        agent_id="0001",  
        step_intention="查看任务相关agent的信息",  
        step_type="skill",  
        executor="agent_viewer",  
        text_content="获取与任务task_001相关的所有代理信息，以便更好地协调合作",  
        execute_result={},  
    )  

    agent_state["agent_step"].add_step(test_step)
    step_id = agent_state["agent_step"].step_list[0].step_id

        # 模拟中央任务注册表和团队注册表  
    # 实际项目中应该通过正式的API获取  
    global central_task_registry, central_team_registry  
    central_task_registry = {  
        "get_task_state": lambda task_id: {  
            "task_id": task_id,  
            "task_intention": "完成项目计划制定",  
            "task_group": ["0001", "0002", "0003"],  
            "execution_state": "running",  
        }  
    }  
    
    central_team_registry = {  
        "get_all_agent_ids": lambda: ["0001", "0002", "0003", "0004", "0005"]  
    }  
    
    # 实例化并测试AgentViewerSkill  
    agent_viewer_skill = AgentViewerSkill()
    result = agent_viewer_skill.execute(step_id, agent_state, task_id="task_001")  
    
    print("执行结果:")  
    print(json.dumps(result, indent=2))  


    
