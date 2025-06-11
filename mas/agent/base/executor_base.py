'''
定义executor基础类，所有的skills与tools都继承自executor基类
Router类通过type与executor的str返回一个具体执行器，这个执行器具备executor基础类的通用实现方法
'''

from mas.agent.state.step_state import StepState

from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union
import yaml
import json
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
            f"**Agent ID(你的ID)**: {agent_state['agent_id']}\n"
            f"**Name(你的名字)**: {agent_state['name']}\n"
            f"**Role(你的角色)**: {agent_state['role']}\n"
            f"**Profile(你的简介)**: {agent_state['profile']}"
        )
        md_output.append("**你的行为做事逻辑必须严格按照以上角色设定来执行，不能随意更改角色设定。**")


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
        TODO:是否修改为获取最后一个匹配内容 排除是在<think></think>思考期间的内容，使用re.findall
        '''
        # 使用正则表达式提取 <persistent_memory> ... </persistent_memory> 之间的内容
        match = re.search(r"<persistent_memory>\s*(.*?)\s*</persistent_memory>", response, re.DOTALL)

        if match:
            persistent_memory = match.group(1)  # 获取匹配内容
            return persistent_memory
        else:
            return ""

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
        md_output.append(f"**当前步骤的简要意图 step_intention**: {step_state.step_intention}\n")
        md_output.append(f"**当前步骤的文本描述 text_content**: {step_state.text_content}\n")

        md_output.append(f"{skill_prompt}\n")
        md_output.append(f"**return_format**: {return_format}\n")

        return "\n".join(md_output)
    
        # 组装Agent当前执行的tool_step的提示词
    def get_current_tool_step_prompt(self, step_id, agent_state):
        '''
        组装Agent当前执行的工具Step的提示词，该方法供子类使用

        1.当前步骤的简要意图
        2.从step.text_content获取的具体目标
        3.工具规则提示

        '''
        step_state = agent_state["agent_step"].get_step(step_id)[0]
        tool_config = self.load_tool_config(step_state.executor)

        md_output = []
        md_output.append(
            "**这是你当前需要执行的步骤！你将结合背景设定、你的角色agent_role、持续记忆persistent_memory、来遵从当前步骤(本小节'current_step')的提示完成具体目标**:\n"
        )

        tool_prompt = tool_config["use_prompt"].get("tool_prompt", "暂无描述")
        return_format = tool_config["use_prompt"].get("return_format", "暂无描述")
        md_output.append(f"**当前步骤的简要意图 step_intention**: {step_state.step_intention}\n")
        md_output.append(f"**当前步骤的文本描述 text_content**: {step_state.text_content}\n")

        md_output.append(f"{tool_prompt}\n")
        md_output.append(f"**return_format**: {return_format}\n")

        return "\n".join(md_output)

    # 组装历史步骤信息提示词
    def get_history_steps_prompt(self, step_id, agent_state):
        '''
        获取当前stage_id下所有step信息，并将其结构化组装。
        通常本方法应用于reflection，summary技能中
        这里读取step的信息一般都会以str呈现，使用json.dumps()来处理步骤中execute_result与instruction_content
        '''
        # 获取当前阶段的所有步骤
        agent_step = agent_state["agent_step"]
        current_step = agent_step.get_step(step_id)[0]
        history_steps = agent_step.get_step(stage_id=current_step.stage_id) # 根据当前步骤的stage_id查找所有步骤

        # 结构化组装历史step信息
        md_output = [f"当前阶段的历史step信息如下:\n"]
        for idx, step in enumerate(history_steps, 1):
            step_info = [
                f"[step {idx}]**\n",
                f"- 属性: {step.type}-{step.step_intention}\n",
                f"- 意图: {step.step_intention}\n",
                f"- 文本内容(skills): {step.text_content}\n",
                f"- 指令内容: {json.dumps(step.instruction_content, ensure_ascii=False) if step.instruction_content else '无'}\n",
                f"- 执行结果: {json.dumps(step.execute_result, ensure_ascii=False) if step.execute_result else '无'}\n",
                f"- 执行状态: {step.execution_state}\n",
            ]
            md_output.append(f"{step_info}")
        md_output.append(f"\n以上是已执行step信息（共 {len(history_steps)} 步）")

        return "\n".join(md_output)

    # 组装指定长尾工具的历史调用信息
    def get_tool_history_prompt(self, step_id, agent_state, tool_name):
        '''
        接收tool_name，向前提取当前stage_id下最新的长尾工具连续调用步骤链
        根据筛选的连续调用步骤链，结构化组装其提示信息：
            - 该工具的历次调用结果
            - 该工具的历次工具决策
            - 该工具最初的执行意图

        本方法应用于tool_decision中用于获取该工具的历史执行结果、历史调用决策与最初执行意图

        执行步骤如下：

        1 获取当前阶段的所有步骤
        2 从后向前遍历所有步骤获取executor来比较，为了避免获取到该阶段下前一段长尾工具的调用：
            从最近一次 [Tool] 开始，尝试向前“恢复”出成对的 [Tool] -> [ToolDecision]，直到不能再恢复。
            2.1 从末尾倒序遍历 steps 找到第一个 Tool（匹配工具名），作为起点
            2.2 从该 Tool 向前寻找最近的 ToolDecision
                （中间允许跳过 InstructionGeneration 和 SendMessage，但如果存在其他步骤则视为非法，终止这轮）
            2.3 一旦找到了 ToolDecision，说明前面是一个完整调用：
                一定会存在 Tool -> ToolDecision 成对的步骤。
                继续寻找 ToolDecision 前的 Tool ，把这一对 Tool -> ToolDecision 都加入结果，
                随后以这一对调用的开头 Tool 为新的起点。
            2.4 在新的 Tool 作为起点，继续重复2.2向前查找，直到中途出现非法步骤（如遇到不是 tool_decision 又不是 gap 的步骤）
            2.5 如果向前找 [Tool] 的前一个有效步骤（排除[InstructionGeneration]和[SendMessage]）非[ToolDecision]
                则终止查找。
        3 获取最初工具调用步骤意图
        4 将恢复的历史 Tool / ToolDecision 步骤组装为结构化提示词（Markdown格式）
        '''
        # 1 获取当前阶段的所有步骤
        agent_step = agent_state["agent_step"]
        current_step = agent_step.get_step(step_id)[0]
        history_steps = agent_step.get_step(stage_id=current_step.stage_id)  # 根据当前步骤的stage_id查找所有步骤

        # 2 提取当前阶段最近一段连续的 Tool -> ToolDecision 调用链
        valid_steps = []
        i = len(history_steps) - 1
        break_loop = False  # 标记遍量，方便内循环的条件判断不仅打破内循环，且能够打破外循环
        got_first_tool = False   # 标记是否获取到第一个Tool

        while i >= 0 and not break_loop:
            step = history_steps[i]
            # print(f"[DEBUG] 获取到最近的第一个Tool: idx={i}, executor={step.executor}")

            # 2.1 从最近的 Tool 开始（匹配工具名t ool_name）
            if step.type == "tool" and step.executor == tool_name:
                valid_steps.insert(0, step)
                got_first_tool = True   # 标记已经获取到第一个Tool
                j = i - 1

                # 2.2 向前寻找 ToolDecision
                # （跳过允许的 gap 步骤）
                while j >= 0:
                    td_candidate = history_steps[j]
                    # print(f"[DEBUG] 当前步骤: idx={j}, executor={td_candidate.executor}")

                    if td_candidate.executor == "tool_decision":
                        valid_steps.insert(0, td_candidate)

                        # 2.3 ToolDecision 前面一定存在配对的 Tool，直接向前找到最近的一个 Tool 并加入
                        k = j - 1
                        while k >= 0:
                            maybe_tool = history_steps[k]
                            if maybe_tool.type == "tool" and maybe_tool.executor == tool_name:
                                valid_steps.insert(0, maybe_tool)
                                i = k - 1  # 在外循环中继续向前查找下一个 Tool -> ToolDecision 配对
                                break
                            else:
                                k -= 1
                        else:
                            # 理论上不该触发：ToolDecision 前没找到 Tool
                            # print(f"[executor][get_tool_history_prompt]没有找到 ToolDecision 前的 Tool，终止")

                            break_loop = True
                            i = -1
                        break

                    elif td_candidate.executor in ["instruction_generation", "send_message"]:
                        j -= 1  # 跳过 gap 步骤继续找 ToolDecision
                    else:
                        # 2.4 遇到非法步骤，说明该工具的连续调用被打断，终止所有循环
                        break_loop = True
                        break
                else:
                    # 2.5 没有找到更早的 ToolDecision，终止
                    break_loop = True
                    break
            else:
                # 继续往前找最近一个 Tool 步骤
                if got_first_tool:
                    # 如果已经找到第一个 Tool，则不需要再继续往前找了
                    break_loop = True
                i -= 1

        # 4 将找到的工具链结构化组装成提示词
        md_output = []
        for i, step in enumerate(valid_steps):
            # 3 获取工具最初调用意图
            if i == 0:
                md_output.append(
                    f"{tool_name}工具最初调用意图：\n"
                    f"- 步骤意图：{step.step_intention}\n"
                    f"- 详细说明：{step.text_content}\n"
                )
            # 获取工具和工具决策的步骤执行结果
            md_output.append(
                f"step：\n"
                f"- 步骤名称: {step.executor}\n"
                f"- 执行结果: {json.dumps(step.execute_result, ensure_ascii=False) if step.execute_result else '无'}\n"
            )
        # print(f"[DEBUG] 最终组装提示信息，共 {len(md_output)} 段")

        return "\n".join(md_output)


    # 组装为tool_step执行指令生成时的提示词
    def get_tool_instruction_generation_step_prompt(self, step_id, agent_state):
        '''
        组装Agent指令生成步骤的目标工具Step的提示词，该方法供子类使用
        （这里传入的step_id是前一步指令生成step的id）

        1.获取tool_step
        2.当前工具步骤的简要意图
        3.从step.text_content获取的具体目标
        4.工具规则提示
        '''
        md_output = []
        md_output.append(
            "**这是你需要生成具体工具指令的提示！你将结合背景设定、你的角色agent_role、持续记忆persistent_memory、来遵从当前工具步骤(本小节'tool_step')的提示来生成具体的调用指令**:\n"
        )

        # 1.获取instruction_generation的下一个工具step
        tool_step = self.get_next_tool_step(step_id, agent_state)
        tool_config = self.load_tool_config(tool_step.executor)

        tool_prompt = tool_config["use_prompt"].get("tool_prompt", "暂无描述")
        return_format = tool_config["use_prompt"].get("return_format", "暂无描述")

        # 2.当前工具步骤的简要意图
        md_output.append(f"**当前工具步骤的简要意图**: {tool_step.step_intention}\n")

        # 3.从step.text_content获取的具体目标
        md_output.append(f"**需要调用工具实现的具体目标**: {tool_step.text_content}\n")

        # 4.工具规则提示
        md_output.append(f"{tool_prompt}\n")
        md_output.append(f"**return_format**: {return_format}\n")

        return "\n".join(md_output)

    # 指令生成技能获取下一个工具step提示词
    def get_next_tool_step(self, current_step_id, agent_state) -> Optional[StepState]:
        '''
        获取当前步骤之后的下一个工具步骤。
        这个方法查找当前步骤所属阶段（stage_id）的所有工具步骤，并返回下一个工具步骤。
        '''
        # 1. 获取当前步骤
        current_step = agent_state["agent_step"].get_step(current_step_id)[0]
        # 2. 获取当前步骤所属阶段的所有步骤
        all_stage_steps = agent_state["agent_step"].get_step(stage_id=current_step.stage_id)
        # 3. 找到当前步骤在所有步骤中的位置，并从该位置开始寻找下一个工具步骤
        current_step_found = False
        for step in all_stage_steps:
            if current_step_found:
                # 找到第一个工具步骤并返回
                if step.type == 'tool':
                    return step
            elif step.step_id == current_step_id:
                # 标记当前步骤已经找到，开始查找下一个工具步骤
                current_step_found = True
        return None  # 如果没有找到下一个工具步骤，返回 None


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
        current_step = agent_step.get_step(step_id)[0]  # 获取当前step的信息
        for step in planned_step:
            # 构造新的StepState
            step_state = StepState(
                task_id=current_step.task_id,
                stage_id=current_step.stage_id,
                agent_id=current_step.agent_id,
                step_intention=step["step_intention"],
                type=step["type"],
                executor=step["executor"],
                text_content=step["text_content"]
            )
            # 添加到AgentStep中
            agent_step.add_step(step_state)
            # 记录在工作记忆中
            agent_state["working_memory"].setdefault(current_step.task_id, {}).setdefault(current_step.stage_id, []).append(step_state.step_id)

    # 为tool_decision技能实现通用add_next_step的方法
    def add_next_step(
        self,
        planned_step: List[Dict[str, Any]],
        step_id: str,
        agent_state,
    ):
        '''
        为agent_step的列表中插入多个Step (插入在下一个待执行的步骤之前)

        接受planned_step格式为：
        [
            {
                "step_intention": str,
                "type": str,
                "executor": str,
                "text_content": str,
            },
            ...
        ]
        '''
        agent_step = agent_state["agent_step"]
        current_step = agent_step.get_step(step_id)[0]  # 获取当前step的信息
        # 倒序获取
        for step in reversed(planned_step):
            # 构造新的StepState
            step_state = StepState(
                task_id=current_step.task_id,
                stage_id=current_step.stage_id,
                agent_id=current_step.agent_id,
                step_intention=step["step_intention"],
                type=step["type"],
                executor=step["executor"],
                text_content=step["text_content"]
            )
            # 插入到AgentStep中
            agent_step.add_next_step(step_state)
            # 记录在工作记忆中
            agent_state["working_memory"].setdefault(current_step.task_id, {}).setdefault(current_step.stage_id, []).append(step_state.step_id)
