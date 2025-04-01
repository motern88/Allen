'''
这里实现一个Router类:
Router类根据step_state.type和step_state.executor两个字符串。
访问Executor的注册表_registry，获取对于执行器类。
并返回实例化后的执行器类。
'''

from mas.agent.base.executor_base import Executor

class Router:

    @staticmethod
    def get_executor(type: str, executor: str) -> Executor:
        """根据 type 和 executor 返回对应的excutor实例"""
        executor_class = Executor._registry.get((type, executor))
        if not executor_class:
            raise ValueError(f"未找到对应的执行器: type={type}, executor={executor}")
        return executor_class()
