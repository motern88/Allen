'''
定义executor基础类，所有的skills与tools都继承自executor基类
Router类通过type与executor的str返回一个具体执行器，这个执行器具备executor基础类的通用实现方法
'''

from abc import ABC, abstractmethod
from typing import Dict
from mas.agent.state.step_state import StepState

class Executor(ABC):
    '''
    # 抽象基类Executor，所有具体执行器继承此类，并实现execute方法
    在 Executor 基类中维护注册表，并通过类型和名称注册子类，可以实现动态路由和解耦设计，
    好处是无需每次新增一个执行器，就去修改Router类的代码，添加新的条件分支，而只需添加新的执行器类并注册，不需要修改现有路由逻辑
    '''

    # # 注册表：键为 (type, executor_name) 的元组，值为对应的执行器类
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
        """执行步骤，需更新step_state的状态和结果"""
        pass