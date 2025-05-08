'''
实现一个MAS中的StateMonitor监控器类，
通过装饰器，对TaskState，StageState，AgentState，StepState等状态类进行监控
并将监控信息呈现在网页中（通过web/server.py推送）

支持单例模式，示例注册机制，状态转字典，类型兼容性
'''

import functools
import threading
import uuid
from typing import Dict, Any, List, Optional, Type, TypeVar, Union


class StateMonitor:
    """
    状态监控器，负责装饰类、注册实例、提供状态查询

    实现为单例模式，确保在整个系统中只有一个监控器实例。
    可用于监控如 TaskState、StageState、AgentState、StepState 等状态类。
    """
    _instance = None  # 单例实例

    def __new__(cls):
        # 实现单例逻辑，只初始化一次
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._registry = {}  # 用于注册所有被追踪的类实例（状态实例）
            cls._instance._lock = threading.Lock()  # 多线程安全锁
        return cls._instance

    @classmethod
    def track(cls, user_cls):
        monitor = cls()
        return monitor._track(user_cls)

    def _track(self, cls):
        """
        装饰器：为类添加状态追踪功能
        - 替换原始构造方法，注册新创建的实例
        - 注入自定义 __setattr__ 和 as_dict 方法
        """
        original_init = cls.__init__   # 保存原始构造函数

        @functools.wraps(original_init)
        def new_init(instance, *args, **kwargs):
            # 替代构造方法：初始化原始类内容
            original_init(instance, *args, **kwargs)
            # 生成唯一 state_id（由类名和 UUID组成）
            state_id = f"{cls.__name__}_{uuid.uuid4()}"
            instance._state_id = state_id
            # 将该实例注册到监控器的注册表中
            with self._lock:
                self._registry[state_id] = instance

        # 自定义属性设置逻辑（保留普通设置行为，可扩展为触发事件或记录）
        def custom_setattr(instance, name, value):
            object.__setattr__(instance, name, value)
            # 可选：这里可以加回调或事件钩子
            # print(f"[{instance._state_id}] 属性更新: {name} = {value}")

        # 将对象转为字典形式，排除私有变量
        def as_dict(instance):
            return {
                k: v for k, v in instance.__dict__.items()
                if not k.startswith("_")
            }

        # 注入新的方法和属性
        cls.__init__ = new_init
        cls.__setattr__ = custom_setattr
        cls.as_dict = as_dict
        return cls

    def get_all_states(self) -> Dict[str, Any]:
        """
        获取所有被追踪的实例的状态，返回字典：{state_id: 属性字典}
        """
        with self._lock:
            return {sid: inst.as_dict() for sid, inst in self._registry.items()}

    def get_state(self, state_id: str) -> Any:
        """
        获取指定 state_id 的状态内容（属性字典）
        """
        with self._lock:
            inst = self._registry.get(state_id)
            return inst.as_dict() if inst else None
































