'''
Agent被分配执行或协作执行一个阶段时，Agent会为自己规划数个执行步骤以完成目标。
步骤step是最小执行单位，每个步骤的执行会维护一个 step_state 。

具体实现:封装一个AgentStep类，该类用于管理其内部的step_state的列表
'''
import uuid
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union
import queue

class StepSate:
    '''
    由Agent生成的最小执行单位。包含LLM的文本回复（思考/反思/规划/决策）或一次工具调用。

    属性:
        task_id (str): 任务ID，用于标识一个任务的唯一ID
        stage_id (str): 阶段ID，用于标识一个阶段的唯一ID
        agent_id (str): Agent ID，用于标识一个Agent的唯一ID
        step_id (str): 步骤ID，用于标识一个步骤的唯一ID，自动生成
        step_intention (str): 步骤的意图, 由创建Agent填写(仅作参考并不需要匹配特定格式)。例如：'ask a question', 'provide an answer', 'use tool to check...'

        type (str): 步骤的类型,例如：'skill', 'tool'
        executor (str): 执行该步骤的对象，如果是 type 是 'tool' 则填工具名称，如果是 'skill' 则填技能名称
        execution_state (str): 步骤的执行状态：
            'init' 初始化（步骤已创建）
            'pending' 等待内容填充中（依赖数据未就绪），一般情况下只出现在工具指令填充，技能使用不需要等待前一步step去填充
            'running' 执行中
            'finished' 已完成
            'failed' 失败（步骤执行异常终止）

        text_content (str): 文本内容，如果是技能调用则是填入技能调用的提示文本（不是Skill规则的系统提示，而是需要这个skill做什么具体任务的目标提示文本）
        instruction_content (str): 指令内容，如果是工具调用则是具体工具命令
        execute_result (str): 执行结果，如果是文本回复则是文本内容，如果是工具调用则是工具返回结果

    '''

    def __init__(
        self,
        task_id: str,
        stage_id: str,
        agent_id: str,
        step_intention: str,
        step_type: str,
        executor: str,  # TODO：实现一个executor的枚举类用于约束该字段
        execution_state: str = "init",  # 'init', 'pending', 'running', 'finished', 'failed'
        text_content: Optional[Dict[str, Any]] = None,
        instruction_content: Optional[Dict[str, Any]] = None,
        execute_result: Optional[Dict[str, Any]] = None,
    ):
        # step基本信息（id与简略意图）
        self.task_id = task_id
        self.stage_id = stage_id
        self.agent_id = agent_id
        self.step_id = str(uuid.uuid4())  # 自动生成唯一 step_id

        # step意图
        self.step_intention = step_intention

        # step执行属性（具体执行模块，执行状态）
        self.type = step_type  # 'skill' or 'tool'
        self.executor = executor  # 执行该步骤的对象
        self.execution_state = execution_state  # 'init', 'pending', 'running', 'finished', 'failed'

        # step内容
        self.text_content = text_content or {}
        self.instruction_content = instruction_content or {}
        self.execute_result = execute_result or {}

    def update_execution_state(self, new_state: str):
        """更新执行状态"""
        self.execution_state = new_state

    def update_instruction_content(self, new_content: Dict[str, Any]):
        """
        更新指令内容

        当前Step为工具调用时，由上一step（Instruction Generation）生成的工具指令内容
        """
        self.instruction_content = new_content

    def update_execute_result(self, new_result: Dict[str, Any]):
        """更新执行结果"""
        self.execute_result = new_result


class AgentStep:
    '''
    Agent的执行步骤管理类，用于管理Agent的执行步骤列表。
    包括添加、删除、修改、查询等操作。

    初始化会对应上agent_id，会初始化一个step_list用于承载StepState，同时将每个未执行的StepState的step_id放入todo_list中。
    Agent执行Action是按照todo_list的共享队列顺序执行，但是更新与修改操作可以根据step_id、stage_id、task_id操作
    '''
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.todo_list = queue.Queue()  # 只存放待执行的 step_id，执行者从队列里取出任务进行处理，一旦执行完就不会再回到 todo_list
        self.step_list: List[StepState] = []  # 持续记录所有 StepState，即使执行完毕也不会被删除，方便后续查询、状态更新和管理。

    # 添加step
    def add_step(self, step: StepState) -> int:
        """
        添加新的 step 到队列
        如果 step 未被执行过，则自动添加到待执行队列todo_list
        """
        self.step_list.append(step)
        # 如果step未被执行过，则添加到待执行队列
        if step.execution_state not in ["finished", "failed"]:
            self.todo_list.put(step.step_id)
            print(f"step {step.step_id} 已添加到todo_list")

    # 移除step
    def remove_step(
        self,
        step_id: Optional[str] = None,
        task_id: Optional[str] = None,
        stage_id: Optional[str] = None
    ):
        """
        根据 step_id 或 task_id 或 stage_id 移除 step
        如果是 task_id 或 stage_id，会移除所有对应的step
        """
        if step_id:
            self.step_list = [step for step in self.step_list if step.step_id != step_id]
        elif task_id:
            self.step_list = [step for step in self.step_list if step.task_id != task_id]
        elif stage_id:
            self.step_list = [step for step in self.step_list if step.stage_id != stage_id]

    # 获取step
    def get_step(
        self,
        step_id: Optional[str] = None,
        stage_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Optional[StepState]:
        """
        从 step_list 中根据 step_id 获取 step
        如果是 task_id 或 stage_id，会返回所有匹配的 step
        """
        if step_id:
            return next((step for step in self.step_list if step.step_id == step_id), None)
        elif stage_id:
            return [step for step in self.step_list if step.stage_id == stage_id]
        elif task_id:
            return [step for step in self.step_list if step.task_id == task_id]
        return None

    # 更新step状态
    def update_step_status(self, step_id: str, new_state: str):
        """更新 step 执行状态"""
        step = self.get_step(step_id=step_id)
        if step:
            step.update_execution_state(new_state)

    # 打印所有step
    def print_all_steps(self):
        """打印所有 step 的详细信息"""
        for step in self.step_list:
            print(
                f"Task ID: {step.task_id}, Stage ID: {step.stage_id}, Step ID: {step.step_id}, "
                f"Execution State: {step.execution_state}, Type: {step.type}, Executor: {step.executor}, "
                f"Intention: {step.step_intention}, Text Content: {step.text_content}, "
                f"Instruction Content: {step.instruction_content}, Execute Result: {step.execute_result}"
            )
