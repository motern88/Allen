'''
技能名称: Tool Decision
期望作用: Agent通过Tool Decision处理长尾工具的返回结果，并决定下一步该工具的执行或是结束长尾工具调用
    该技能会调用LLM接收并处理长尾工具的返回结果，并决定下一步该工具的调用的方向（指导指令生成步骤）或是结束长尾工具调用。

如果工具返回结果需要向LLM确认，并反复多次调用该工具的，这种情况为工具的长尾调用。
同一个工具的连续多次调用，需要由LLM不断判断每一步工具使用的方向。
长尾工具会在工具步骤执行后将工具返回结果经由SyncState以消息的方式,让Agent追加一个Tool Decision来决策工具否继续调用及如何继续调用

因此多次调用的长尾工具:
    以InstructionGeneration开始，以ToolDecision结尾，其中可能包含多次(指令生成-工具执行)的步骤。
    ([I.G.] -> [Tool]) -> [ToolDecision] -> ([I.G.] -> [Tool]) -> [ToolDecision] -> ...

    对于单次调用的一般工具：以InstructionGeneration开始，以具体工具步骤结尾。
    对于多次调用的长尾工具：以InstructionGeneration开始，以ToolDecision结尾，其中可能包含多次 (指令生成-工具执行) 的步骤。


LLM需要获取足够进行决策判断的条件:
1. 工具最初调用的意图  TODO（未确定获取来源）

2. 工具当次调用的执行结果
    由长尾工具在执行后将工具返回结果通过execute_output传出，使用"need_tool_decision"字段，SyncState会捕获该字段内容。
    need_tool_decision字段需要包含：
        "task_id" 指导SyncState构造的消息应当存于哪个任务消息队列中
        "Stage_id" 保证和Stage相关性，可同一清除
        "agent_id" 指导MessageDispatcher从任务消息队列中获取到消息时，应当将消息发送给谁
        "tool_name" 指导Agent接收到消息后，追加ToolDecision技能步骤的决策结果应当使用哪个工具
    注：工具当次调用结果不需要单独传出，由Tool Decision执行时，获取该工具的历史调用结果一并获取即可。

3. 工具历史调用的执行结果  TODO（未确定获取来源）

4. 由工具定义的不同决策对应不同格式指令的说明  TODO
    Tool Decision不需要知道具体工具指令调用方式，Tool Decision只需要给出下一步工具调用的执行方向，
    由Instruction Generation根据工具具体提示生成具体工具调用指令


说明:
    该Tool Decision是MAS中的一个经典循环，执行该技能前有：
        Step（具体工具Tool执行）-> SyncState（生成指令消息）-> MessageDispatcher（分发消息给对应Agent）->
        Agent（receive_message处理消息）-> Step（插入一个ToolDecision步骤）
    
    TODO：ToolDecision执行暂未实现
    执行该技能后，如果Tool Decision继续工具调用则有： TODO：追加step还需要经过SyncState吗？
        Step（ToolDecision技能执行）-> SyncState（生成指令消息）-> MessageDispatcher（分发消息给对应Agent）->
        Agent（receive_message处理消息）-> Step（插入一个InstructionGeneration步骤和对应的Tool步骤）

    执行该技能后，如果Tool Decision终止工具继续调用则有：
        Step（ToolDecision技能执行）


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
        1.4 该工具历史执行结果（# 一级标题） TODO未实现
        1.5 持续性记忆:（# 一级标题）
            1.5.1 Agent持续性记忆说明提示词（## 二级标题）
            1.5.2 Agent持续性记忆内容提示词（## 二级标题）

    2. llm调用获取决策
    3. 解析llm返回的决策指令（工具继续/终止）
    4. 提取llm返回的持续性记忆信息，追加到Agent的持续性记忆中
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
        组装提示词:
        1 MAS系统提示词（# 一级标题）
        2 Agent角色:（# 一级标题）
            2.1 Agent角色背景提示词（## 二级标题）
            2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        3 tool_decision step:（# 一级标题）
            3.1 step.step_intention 当前步骤的简要意图
            3.2 step.text_content 长尾工具提供的返回结果
            3.3 技能规则提示(tool_decision_config["use_prompt"])
        4 该工具历史执行结果（# 一级标题） TODO未实现
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
        md_output.append(f"# 工具历史执行结果 history_tools_result\n")
        history_tools_result = self.get_history_tools_result_prompt(step_id, agent_state, tool_name)  # TODO 未实现
        md_output.append(f"{history_tools_result}\n")


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
