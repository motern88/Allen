'''
定义executor基础类，所有的skills与tools都继承自executor基类
Router类通过type与executor的str返回一个具体执行器，这个执行器具备executor基础类的通用实现方法
'''

from mas.agent.state.step_state import StepState

from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union
import yaml
import os



class Executor(ABC):
    '''
    抽象基类Executor，所有具体执行器继承此类，并实现execute方法
    用于维护执行器的注册表，并实现一些基础通用方法

    在 Executor 基类中维护注册表，并通过类型和名称注册子类，可以实现动态路由和解耦设计，
    好处是无需每次新增一个执行器，就去修改Router类的代码，添加新的条件分支，而只需添加新的执行器类并注册，不需要修改现有路由逻辑

    通过register方法注册执行器类，register方法接受两个参数，executor_type和executor_name，分别表示执行器的类型和名称
    使用方法：@Executor.register("skill", "planning")

    路由器Routor会通过这个注册表来查找并返回对应的执行器类
    '''

    #注册表：键为 (type, executor_name) 的元组，值为对应的执行器类
    _registry: Dict[tuple[str, str], type] = {}

    @classmethod
    def register(cls, executor_type: str, executor_name: str):
        """显式注册执行器类（替代装饰器）"""
        def wrapper(subclass: type):
            cls._registry[(executor_type, executor_name)] = subclass
            return subclass
        return wrapper

    @abstractmethod
    def execute(self, step_state: StepState) -> None:
        """由子类必须实现的具体execute方法"""
        pass

    # 上：基础方法
    # --------------------------------------------------------------------------------------------
    # 下：一些通用工具方法

    # 加载skill的 YAML 配置文件
    def load_skill_config(self, skill_name, config_dir="mas/skills"):
        """
        根据技能名称动态加载对应的 YAML 配置文件
        """
        # 生成对应的文件名
        config_file = os.path.join(config_dir, f"{skill_name}_config.yaml")
        if not os.path.exists(config_file):
            raise ValueError(f"配置文件 {config_file} 不存在！")
        # 加载YAML文件
        with open(config_file, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    # 加载tool指定的 YAML 配置文件
    def load_tool_config(self, tool_name, config_dir="mas/tools"):
        """
        根据工具名称动态加载对应的 YAML 配置文件
        """
        # 生成对应的文件名
        config_file = os.path.join(config_dir, f"{tool_name}_config.yaml")
        if not os.path.exists(config_file):
            raise ValueError(f"配置文件 {config_file} 不存在！")
        # 加载YAML文件
        with open(config_file, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    # 根据Agent的技能与工具权限 List[str]，组装相应skill与tool的使用说明提示词
    def get_skill_and_tool_prompt(self, agent_skills: List[str], agent_tools: List[str]):
        '''
        组装Agent工具与技能权限的提示词，该方法供子类使用

        根据Agent的技能与工具权限 List[str]，获取涉及到的技能与工具的配置文件中读取使用说明提示词

        返回markdown:
            ### 可用技能skills
            - **<skill_name>**: <skill_prompt>
            - **<skill_name>**: <skill_prompt>

            ### 可用工具tools
            - **<tool_name>**: <tool_prompt>
            - **<tool_name>**: <tool_prompt>
        '''
        md_output = []
        md_output.append("## available_skills_and_tools\n")
        # 获取技能说明
        if agent_skills:
            md_output.append("### 可用技能 skills\n")
            for skill in agent_skills:
                config = self.load_skill_config(f"{skill}_config.yaml")  # 读取 YAML
                skill_name = config["use_guide"].get("skill_name", skill)
                skill_prompt = config["use_guide"].get("description", "暂无描述")
                md_output.append(f"- **{skill_name}**: {skill_prompt}")

        # 处理工具
        if agent_tools:
            md_output.append("\n### 可用工具 tools\n")
            for tool in agent_tools:
                config = self.load_tool_config(f"{tool}_config.yaml")  # 读取 YAML
                tool_name = config["use_guide"].get("tool_name", tool)
                tool_prompt = config["use_guide"].get("description", "暂无描述")
                md_output.append(f"- **{tool_name}**: {tool_prompt}")
        return "\n".join(md_output)

    # TODO：实现组装Agent角色背景提示词
    def get_agent_role_prompt(self, agent_state):
        '''
        组装Agent角色背景提示词，该方法供子类使用
        '''
        md_output = []
        md_output.append("## agent_role\n")





    def add_step(
        self,
        agent_state,
        stage_id: str,
        step_intention: str,  # Step的目的
        step_type: str,  # Step的类型 'skill', 'tool'
        executor: str,  # Step的执行模块
        text_content: Optional[str] = None,  # Step的文本内容
        instruction_content: Optional[Dict[str, Any]] = None,  # Step的指令内容
    ):  # TODO:为planning reflection等技能实现通用add_step的方法
        '''
        为agent_step的列表中添加一个Step
        '''
        # 1. 构造一个完整的StepState
        step_state = StepState(
            task_id = task_id,
            stage_id = stage_id,
            agent_id = self.agent_state["agent_id"],
            step_intention = step_intention,
            step_type = step_type,
            executor = executor,
            execution_state = "init",  # 'init', 'pending', 'running', 'finished', 'failed'
            text_content = text_content,  # Optional[str]
            instruction_content = instruction_content,  # Optional[Dict[str, Any]]
            execute_result = None,  # Optional[Dict[str, Any]]
        )

        if step_type == "tool" and instruction_content is None:
            # 如果是工具调用且没有具体指令，则状态为待填充 pending
            step_state.update_execution_state = "pending"

        # 2. 添加一个该Step到agent_step中
        agent_step = self.agent_state["agent_step"]
        agent_step.add_step(step_state)

        # 3. 返回添加的step_id, 记录在工作记忆中  # TODO:实现工作记忆
        self.agent_state["working_memory"][task_id][stage_id].append(step_state.step_id)

