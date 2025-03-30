
'''
Router类根据StepState的类型和名称查找对应的执行器，并触发执行
'''
from mas.agent.state.step_state import StepState
from mas.agent.base.executor_base import Executor

class Router:
    def __init__(self):
        pass  # TODO 路由初始化配置或上下文
    def route(self, step_state: StepState):
        # 组合键：type + executor，根据类型和名称获取执行器类
        key = (step_state.type, step_state.executor)
        executor_cls = Executor.registry.get(key)  # 直接查表
        if not executor_cls:
            raise ValueError(f"未注册的执行器：类型={key[0]}, 名称={key[1]}")
        # 实例化并执行
        executor = executor_cls()
        executor.execute(step_state)