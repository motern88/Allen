'''
技能名称: Tool Decision
期望作用: Agent通过Tool Decision处理长尾工具的返回结果，并决定下一步该工具的执行或是结束长尾工具调用

Tool Decision向Agent提供了处理长尾工具返回结果的能力，能够根据工具的返回结果决定：
1. 是否继续调用工具
2. 如果继续，调用哪个工具及其参数
3. 如果不继续，如何结束工具调用流程

提示词顺序（系统 → 角色 → (目标 → 规则) → 记忆）

具体实现:
    1. 组装提示词:
        1.1 MAS系统提示词（# 一级标题）
        1.2 Agent角色:（# 一级标题）
            1.2.1 Agent角色背景提示词（## 二级标题）
            1.2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        1.3 tool_decision step:（# 一级标题）
            1.3.1 step.step_intention 当前步骤的简要意图
            1.3.2 step.text_content 工具返回结果和相关上下文
            1.3.3 技能规则提示(tool_decision_config["use_prompt"])
        1.4 持续性记忆:（# 一级标题）
            1.4.1 Agent持续性记忆说明提示词（## 二级标题）
            1.4.2 Agent持续性记忆内容提示词（## 二级标题）

    2. llm调用
    3. 解析llm返回的决策指令
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
    '''
    工具决策技能
    处理长尾工具调用，根据上一步骤的工具执行结果，决定是继续调用工具还是结束调用
    '''
    def __init__(self):
        super().__init__()

    def extract_tool_decision(self, text: str) -> Optional[Dict[str, Any]]:
        '''
        从文本中提取工具决策指令
        '''
        # 使用正则表达式提取<tool_decision>和</tool_decision>之间的内容
        matches = re.findall(r"<tool_decision>\s*(.*?)\s*</tool_decision>", text, re.DOTALL)

        if matches:
            tool_decision = matches[-1]  # 获取最后一个匹配内容 排除是在<think></think>思考期间的内容

            try:
                tool_decision_dict = json.loads(tool_decision)
                return tool_decision_dict
            except json.JSONDecodeError:
                print("JSON解析错误:", tool_decision)
                return None
        else:
            print("没有找到<tool_decision>标签")
            return None

    def extract_persistent_memory(self, text: str) -> str:
        '''
        从文本中提取持续性记忆内容
        '''
        # 使用正则表达式提取<persistent_memory>和</persistent_memory>之间的内容
        matches = re.findall(r"<persistent_memory>\s*(.*?)\s*</persistent_memory>", text, re.DOTALL)
        
        if matches:
            return matches[-1].strip()  # 获取最后一个匹配的持续性记忆
        else:
            return ""  # 如果没有匹配，返回空字符串

    def get_tool_decision_prompt(self, step_id: str, agent_state: Dict[str, Any]):
        '''
        组装提示词
        1. MAS系统提示词（# 一级标题）
        2. Agent角色提示词（# 一级标题）
        3. Tool Decision步骤提示词（# 一级标题）
        4. 持续性记忆提示词（# 一级标题）
        '''
        # 获取当前步骤信息
        step = agent_state["agent_step"].get_step(step_id)[0]
        step_intention = step.step_intention
        text_content = step.text_content
        
        # 组装最终的提示词
        md_output = []
        
        # 1. 获取基础MAS系统提示词
        system_prompt = self.get_base_prompt(key="system_prompt")
        md_output.append(f"# 多智能体系统 MAS\n{system_prompt}\n")
        md_output.append("Tool Decision是连接工具执行和指令生成的关键决策步骤，\n"
                       "你需要基于工具返回结果决定是继续调用工具还是结束工具调用流程。\n")
        
        # 2. 获取Agent角色提示词
        role_prompt = self.get_agent_role_prompt(agent_state)
        md_output.append(f"# Agent角色\n{role_prompt}\n")
        
        # 3. 获取技能与工具提示
        skills_tools_prompt = self.get_skill_and_tool_prompt(agent_state["skills"], agent_state["tools"])
        md_output.append(f"{skills_tools_prompt}\n")

        # 4. Tool Decision step提示词
        md_output.append(f"# 当前需要执行的步骤 current_step\n")
        current_step = self.get_current_skill_step_prompt(step_id, agent_state)  # 不包含标题的md格式文本
        md_output.append(f"{current_step}\n")
        
        # 从step.text_content中再次强调上一个工具的相关信息，帮助tool_decision技能进行决策
        if text_content:
            prvious_tool_info = text_content
            md_output.append(f"**上一个工具相关信息**, 这是你决定是继续调用工具还是结束工具调用的主要依据:{prvious_tool_info}\n")
        
        # 4. 持续性记忆提示词
        # 获取基础持续性记忆提示词
        base_persistent_memory_prompt = self.get_base_prompt(key="persistent_memory_prompt")
        md_output.append(f"# 持续性记忆\n\n"
                       f"## 持续性记忆使用规则说明:\n"
                       f"{base_persistent_memory_prompt}\n")
        
        # 获取当前持续性记忆内容
        persistent_memory = self.get_persistent_memory_prompt(agent_state)
        md_output.append(f"## 你已有的持续性记忆内容:\n"
                       f"{persistent_memory}\n")
        
        return "\n".join(md_output)

    def get_execute_output(
        self,
        step_id: str,
        agent_state: Dict[str, Any],
        update_agent_situation: str,
        shared_step_situation: str,
        tool_decision: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        '''
        构造Tool Decision技能的execute_output
        1. update_agent_situation: "working" | "finished" | "failed"
        2. shared_step_situation: 在任务共享消息池中显示的状态
        3. tool_decision: 工具决策指令，可选
        '''
        # 获取步骤中的任务ID和阶段ID
        step = agent_state["agent_step"].get_step(step_id)[0]
        task_id = step.task_id
        stage_id = step.stage_id
        
        # 构造基本的execute_output
        execute_output = {
            "update_stage_agent_state": {
                "task_id": task_id,
                "stage_id": stage_id,
                "agent_id": agent_state["agent_id"],
                "state": update_agent_situation,
            },
            "send_shared_message": {
                "agent_id": agent_state["agent_id"],
                "role": agent_state["role"],
                "stage_id": stage_id,
                "content": f"执行Tool Decision步骤: {shared_step_situation}"
            }
        }
        
        # 如果有工具决策指令，添加到execute_output中
        if tool_decision:
            execute_output["tool_decision"] = tool_decision
        
        return execute_output

    def execute(self, step_id: str, agent_state: Dict[str, Any]) -> Dict[str, Any]:
        '''
        Tool Decision技能的具体执行方法:
        1. 组装 LLM Tool Decision 提示词
        2. llm调用
        3. 解析llm返回的决策指令
        4. 解析llm返回的持续性记忆信息，追加到Agent的持续性记忆中
        5. 返回用于指导状态同步的execute_output
        '''
        # 1. 更新步骤状态为运行中
        agent_state["agent_step"].update_step_status(step_id, "running")
        
        # 2. 组装Tool Decision提示词
        tool_decision_prompt = self.get_tool_decision_prompt(step_id, agent_state)
        
        # 3. 创建LLM上下文
        llm_config = agent_state["llm_config"]
        llm_client = LLMClient(llm_config)
        chat_context = LLMContext()
        
        # 4. 调用LLM
        response = llm_client.chat_completion(
            tool_decision_prompt,
            context=chat_context
        )
        
        # 5. 解析LLM返回的决策指令
        tool_decision = self.extract_tool_decision(response)
        
        # 如果无法解析到决策指令，说明LLM没有返回规定格式的决策指令
        if not tool_decision:
            # 步骤状态更新为失败
            agent_state["agent_step"].update_step_status(step_id, "failed")
            # 构造execute_output用于更新自己在stage_state.every_agent_state中的状态
            execute_output = self.get_execute_output(
                step_id, 
                agent_state, 
                update_agent_situation="failed",
                shared_step_situation="决策失败，无法解析决策指令"
            )
            return execute_output
        
        # 6. 记录决策结果到execute_result
        step = agent_state["agent_step"].get_step(step_id)[0]
        execute_result = {"tool_decision": tool_decision}  # 构造符合execute_result格式的执行结果
        step.update_execute_result(execute_result)
        
        # 7. 解析LLM返回的持续性记忆信息，追加到Agent的持续性记忆中
        new_persistent_memory = self.extract_persistent_memory(response)
        if new_persistent_memory:
            agent_state["persistent_memory"] += "\n" + new_persistent_memory
        
        # 8. 步骤状态更新为已完成
        agent_state["agent_step"].update_step_status(step_id, "finished")
        
        # 9. 构造execute_output
        if tool_decision["action"] == "continue":
            # 确保 tool_decision 中包含必要的字段
            if "tool_name" not in tool_decision:
                tool_decision["tool_name"] = "" # 防止缺失需要的字段
                
            if "tool_params" not in tool_decision or not isinstance(tool_decision["tool_params"], dict):
                tool_decision["tool_params"] = {} # 防止缺失需要的字段
                
            if "reason" not in tool_decision:
                tool_decision["reason"] = "需要继续执行以完成任务"
                    
            # 生成决策信息用于共享消息
            shared_message = f"决定继续调用工具: {tool_decision['tool_name']}, 原因: {tool_decision['reason']}"
            print(f"[ToolDecisionSkill] 决定继续执行工具 {tool_decision['tool_name']}")
            
            # 记录日志
            print(f"[ToolDecisionSkill] Tool decision (continue): {json.dumps(tool_decision, ensure_ascii=False)}")
            
        else:  # action == "terminate"
            # 确保 tool_decision 中包含必要的字段
            if "result" not in tool_decision:
                tool_decision["result"] = "没有返回明确的结果"
                
            if "reason" not in tool_decision:
                tool_decision["reason"] = "任务已完成或无法继续"
            
            # 生成决策信息用于共享消息
            shared_message = f"决定结束工具调用流程, 结果: {tool_decision['result']}, 原因: {tool_decision['reason']}"
            print(f"[ToolDecisionSkill] 决定结束工具调用流程")
            
            # 记录日志
            print(f"[ToolDecisionSkill] Tool decision (terminate): {json.dumps(tool_decision, ensure_ascii=False)}")
            
        
        execute_output = self.get_execute_output(
            step_id,
            agent_state,
            update_agent_situation="finished",
            shared_step_situation=shared_message,
            tool_decision=tool_decision
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
        "role": "任务管理者",
        "profile": "我是一名任务管理者，负责协调和管理任务的执行。",
        "working_state": "Assigned tasks",  
        "llm_config": LLMConfig.from_yaml("mas/role_config/qwen235b.yaml"),  
        "working_memory": {},  
        "persistent_memory": "之前我曾成功调用搜索工具获取信息",  
        "agent_step": AgentStep("0001"),  
        "skills": ["planning", "reflection", "summary",  
                   "instruction_generation", "quick_think", "think",  
                   "send_message", "process_message", "task_manager",
                   "tool_decision"],
        "tools": ["search", "code_interpreter", "file_operation"],  
    }

    # 构造虚假的历史步骤
    # 模拟前一个工具执行步骤
    tool_step = StepState(
        task_id="0001",
        stage_id="0001",
        agent_id="0001",
        step_intention="执行搜索工具",
        step_type="tool",
        executor="search",
        text_content="搜索关键词：人工智能应用",
        execute_result={"status": "success", "results": ["文章1", "文章2", "文章3"]},
    )
    
    # 模拟工具决策步骤
    step1 = StepState(
        task_id="0001",
        stage_id="0001",
        agent_id="0001",
        step_intention="处理搜索工具返回结果并决定下一步",
        step_type="skill",
        executor="tool_decision",
        text_content="搜索工具返回结果：\n找到3篇关于人工智能应用的文章，但内容不够详细。需要决定是否继续搜索或使用其他工具获取更多信息。",
        execute_result={},
    )

    agent_state["agent_step"].add_step(tool_step)
    agent_state["agent_step"].add_step(step1)

    step_id = agent_state["agent_step"].step_list[0].step_id  # 当前为第一个step

    tool_decision_skill = ToolDecisionSkill()  # 实例化Tool Decision技能
    execute_output = tool_decision_skill.execute(step_id, agent_state)

    # 打印执行结果
    print("\n执行结果：")
    print(json.dumps(execute_output, indent=2, ensure_ascii=False))

    # 打印step信息
    agent_state["agent_step"].print_all_steps()
