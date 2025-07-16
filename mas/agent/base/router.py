'''
这里实现一个Router类:
Router类根据step_state.type和step_state.executor两个字符串。
访问Executor的注册表_registry，获取对应执行器类。
并返回实例化后的执行器类。
'''

from mas.agent.base.executor_base import Executor

class Router:

    @staticmethod
    def get_executor(type: str, executor: str) -> Executor:
        """
        根据 type 和 executor 返回对应的executor实例
        - 如果是技能，则找到对应名称executor的技能执行器
        - 如果是工具，则找到名称为mcp_tool的工具执行器（因为所有的工具均通过该mcp_tool executor来执行，所有的工具均以MCP标准实现）
        """
        # print("[DEBUG][Router] 注册表：", Executor._registry)
        executor_class = None
        if type == "skill":
            executor_class = Executor._registry.get((type, executor))
        elif type == "tool":
            executor_class = Executor._registry.get((type, "mcp_tool"))

        if not executor_class:
            raise ValueError(f"未找到对应的执行器: type={type}, executor={executor}")
        return executor_class()
