'''
定义executor基础类，所有的skills与tools都继承自executor基类
Router类通过type与executor的str返回一个具体执行器，这个执行器具备executor基础类的通用实现方法
'''

from mas.agent.state.step_state import StepState

from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union
import yaml
import os
import re


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
    def execute(self, step_id: str, agent_state: Dict[str, Any]):
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
            ## 角色可用技能与工具 available_skills_and_tools
            ### 可用技能skills
            - **<skill_name>**: <skill_prompt>
            - **<skill_name>**: <skill_prompt>

            ### 可用工具tools
            - **<tool_name>**: <tool_prompt>
            - **<tool_name>**: <tool_prompt>
        '''
        md_output = []
        # 获取技能说明
        if agent_skills:
            md_output.append("### 可用技能 skills\n")
            for skill in agent_skills:
                config = self.load_skill_config(skill)  # 读取 YAML
                skill_name = config["use_guide"].get("skill_name", skill)
                skill_prompt = config["use_guide"].get("description", "暂无描述")
                md_output.append(f"- **{skill_name}**: {skill_prompt}")

        # 处理工具
        if agent_tools:
            md_output.append("\n### 可用工具 tools\n")
            for tool in agent_tools:
                config = self.load_tool_config(tool)  # 读取 YAML
                tool_name = config["use_guide"].get("tool_name", tool)
                tool_prompt = config["use_guide"].get("description", "暂无描述")
                md_output.append(f"- **{tool_name}**: {tool_prompt}")
        return "\n".join(md_output)

    # MAS系统的基础提示词
    def get_base_prompt(self, base_prompt="mas/agent/base/base_prompt.yaml", key="system_prompt"):
        '''
        获取MAS系统的基础提示词, 该方法供子类使用
        获取到yaml文件中以base_prompt为键的值：包含 # 一级标题的md格式文本
        '''
        with open(base_prompt, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)[key]

    # Role角色提示词
    def get_agent_role_prompt(self, agent_state):
        '''
        组装Agent角色背景提示词，该方法供子类使用
        '''
        md_output = []
        md_output.append(
            "**你是一个智能Agent，具有自己的角色和特点。这个章节agent_role是关于你的身份设定，请牢记它，你接下来任何事情都是以这个身份进行的:**\n"
        )
        md_output.append(
            f"**Name(你的名字)**: {agent_state['name']}\n"
            f"**Role(你的角色)**: {agent_state['role']}\n"
            f"**Profile(你的简介)**: {agent_state['profile']}"
        )

        return "\n".join(md_output)



    # Agent持续性记忆提示词
    def get_persistent_memory_prompt(self, agent_state):
        '''
        组装Agent持续性记忆提示词，该方法供子类使用
        '''
        md_output = []
        md_output.append(
            "**这里是你的持续性记忆，它完全由过去的你自己编写，记录了一些过去的你认为非常重要且现在的你可能需要及时查看或参考的信息**(如果是空的则说明过去你还未写入记忆):\n"
        )
        md_output.append(f"<persistent_memory>"
                         f"{agent_state['persistent_memory']}"
                         f"</persistent_memory>")

        return "\n".join(md_output)

    def extract_persistent_memory(self, response):
        '''
        从文本中解析持续性记忆，该方法供子类使用
        '''
        # 使用正则表达式提取 <persistent_memory> ... </persistent_memory> 之间的内容
        match = re.search(r"<persistent_memory>\s*(.*?)\s*</persistent_memory>", response, re.DOTALL)

        if match:
            step_content = match.group(1)  # 获取匹配内容
            return step_content
        else:
            return None

    # 组装Agent当前执行的skill_step的提示词
    def get_current_skill_step_prompt(self, step_id, agent_state):
        '''
        组装Agent当前执行的技能Step的提示词，该方法供子类使用

        1.当前步骤的简要意图
        2.从step.text_content获取的具体目标
        3.技能规则提示

        '''
        step_state = agent_state["agent_step"].get_step(step_id)[0]
        skill_config = self.load_skill_config(step_state.executor)

        md_output = []
        md_output.append(
            "**这是你当前需要执行的步骤！你将结合背景设定、你的角色agent_role、持续记忆persistent_memory、来遵从当前步骤(本小节'current_step')的提示完成具体目标**:\n"
        )

        skill_prompt = skill_config["use_prompt"].get("skill_prompt", "暂无描述")
        return_format = skill_config["use_prompt"].get("return_format", "暂无描述")
        md_output.append(f"**当前步骤的简要意图**: {step_state.step_id}\n")
        md_output.append(f"**需要用技能实现的具体目标**: {step_state.text_content}\n")

        md_output.append(f"{skill_prompt}\n")
        md_output.append(f"**return_format**: {return_format}\n")

        return "\n".join(md_output)

    # TODO:组装为的tool_step执行指令生成时的提示词
    def get_tool_instruction_generation_step_prompt(self, step_id, agent_state):
        '''
        组装Agent当前执行的工具Step的提示词，该方法供子类使用
        '''
        pass




    # 为planning、reflection等技能实现通用add_step的方法
    def add_step(
        self,
        planned_step: List[Dict[str, Any]],
        step_id: str,
        agent_state,
    ):
        '''
        为agent_step的列表中添加多个Step

        接受planned_step格式为：
        [
            {
                "step_intention": "获取当前时间",
                "type": "tool",
                "executor": "time_tool",
                "text_content": "获取当前时间"
            },
            ...
        ]
        '''
        agent_step = agent_state["agent_step"]
        current_step = agent_step.get_step(step_id)[0]  # 获取当前Planning step的信息
        for step in planned_step:
            # 构造新的StepState
            step_state = StepState(
                task_id=current_step.task_id,
                stage_id=current_step.stage_id,
                agent_id=current_step.agent_id,
                step_intention=step["step_intention"],
                step_type=step["type"],
                executor=step["executor"],
                text_content=step["text_content"]
            )
            # 添加到AgentStep中
            agent_step.add_step(step_state)
            # 记录在工作记忆中
            agent_state["working_memory"][current_step.task_id][current_step.stage_id,].append(step_state.step_id)


