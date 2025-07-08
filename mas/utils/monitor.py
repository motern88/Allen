'''
实现一个MAS中的StateMonitor监控器类，
通过装饰器，对TaskState，StageState，AgentState，StepState等状态类进行监控
并将监控信息呈现在网页中（通过web/server.py推送）

说明：
服务获取监控内容时，该监控器需要处理不可序列化的字段为特殊含义的可表示形式

支持单例模式，示例注册机制，状态转字典，类型兼容性
'''

import functools
import threading
import uuid
from typing import Dict, Any, List, Optional, Type, TypeVar, Union

# 导入相关包以方便该类的序列化操作
import queue
from collections import deque

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
            # 生成唯一 state_id（由类名和 该类属性中的id组成）
            state_id = generate_state_id(instance)
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

        # 生成状态 ID 的方法
        def generate_state_id(cls_instance):
            cls_name = cls_instance.__class__.__name__
            if cls_name == 'TaskState' and hasattr(cls_instance, 'task_id'):
                return f"{cls_name}_{cls_instance.task_id}"
            elif cls_name == 'StageState' and hasattr(cls_instance, 'stage_id'):
                return f"{cls_name}_{cls_instance.stage_id}"
            elif cls_name == 'StepState' and hasattr(cls_instance, 'step_id'):
                return f"{cls_name}_{cls_instance.step_id}"
            elif cls_name == 'AgentBase' and hasattr(cls_instance, 'agent_id'):
                return f"{cls_name}_{cls_instance.agent_id}"
            elif cls_name == 'HumanAgent' and hasattr(cls_instance, 'agent_id'):
                return f"{cls_name}_{cls_instance.agent_id}"
            else:
                raise AttributeError(f"{cls_name} 未定义合适的 ID 属性")

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
            # return {sid: inst.as_dict() for sid, inst in self._registry.items()}
            return {
                state_id: self._safe_serialize(state)
                for state_id, state in self._registry.items()
            }

    def get_state(self, state_id: str) -> Any:
        """
        获取指定 state_id 的状态内容（属性字典）
        """
        with self._lock:
            inst = self._registry.get(state_id)
            return inst.as_dict() if inst else None


    # 在状态监控器（StateMonitor）获取状态内容时，就把不可序列化字段转换成特殊可表示形式
    def _safe_serialize(self, obj: Any):
        '''递归地将对象转换为 JSON 可序列化格式'''

        if isinstance(obj, (int, float, str, bool)) or obj is None:
            return obj
        elif isinstance(obj, list):
            return [self._safe_serialize(v) for v in obj]
        elif isinstance(obj, dict):
            return {k: self._safe_serialize(v) for k, v in obj.items()}

        # queue.Queue 特殊序列化, 例如task_state.communication_queue
        elif isinstance(obj, queue.Queue):
            return f"通讯队列未分发数：{obj.qsize()}"
        # list[StageState] 特殊序列化, 例如task_state.stage_list
        elif isinstance(obj, list) and all(
                type(item).__name__ == "StageState" for item in obj):  # 不依赖导入类而通过名字判断
            '''
            转换成 list[Dict[str,str]],将StageState的几个特殊属性序列化为字典
            {
                "stage_id": StageState.stage_id,
                "stage_intention": StageState.stage_intention,
                "execution_state": StageState.execution_state,
            }
            '''
            return [
                {
                    "stage_id": getattr(item, "stage_id", None),
                    "stage_intention": getattr(item, "stage_intention", None),
                    "execution_state": getattr(item, "execution_state", None),
                }
                for item in obj
            ]
        # list[StepState] 特殊序列化, 例如agent_state.step_list
        elif isinstance(obj, list) and all(
                type(item).__name__ == "StepState" for item in obj):
            '''
            List[StepState] 中的每个step仅展示
            {
                "step_id": StepState.step_id,
                "step_intention": StepState.step_intention,
                "execution_state": StepState.execution_state,
            }
            '''
            return [
                {
                    "step_id": getattr(step, "step_id", None),
                    "step_intention": getattr(step, "step_intention", None),
                    "execution_state": getattr(step, "execution_state", None),
                }
                for step in obj
            ]
        # deque() 特殊序列化, 例如agent_step.todo_list
        elif isinstance(obj, deque):
            # 将deque转换为列表
            return [self._safe_serialize(item) for item in obj]

        # Message 特殊序列化, 例如 task_state.shared_conversation_pool 中的消息
        elif isinstance(obj, Dict) and all(
            type(value).__name__ == "Message" for value in obj.values()):# 不依赖导入类而通过名字判断
            '''
            每个 Message 展示：
            {
                "task_id": Message.task_id,                      # 任务ID
                "sender_id": Message.sender_id,                  # 发送者ID
                "receiver": Message.receiver,                    # 接收者ID的列表
                "message": Message.message,                      # 消息文本
                "stage_relative": Message.stage_relative,        # 是否与任务阶段相关
                "need_reply": Message.need_reply,                # 是否需要回复
                "waiting": Message.waiting,                      # 等待回复的唯一ID列表
                "return_waiting_id": Message.return_waiting_id,  # 返回的唯一等待标识ID
            }
            '''
            return {
                "task_id": getattr(obj, "task_id", None),
                "sender_id": getattr(obj, "sender_id", None),
                "receiver": getattr(obj, "receiver", []),  # 接收者ID的列表
                "message": getattr(obj, "message", None),
                "stage_relative": getattr(obj, "stage_relative", None),
                "need_reply": getattr(obj, "need_reply", None),
                "waiting": getattr(obj, "waiting", None),  # 等待回复的唯一ID列表
                "return_waiting_id": getattr(obj, "return_waiting_id", None),  # 返回的唯一等待标识ID
            }


        # 1. TaskState
        elif type(obj).__name__ == "TaskState":
            return {
                "task_id": getattr(obj, "task_id", None),
                "task_name": getattr(obj, "task_name", None),
                "task_intention": getattr(obj, "task_intention", None),
                "task_manager": getattr(obj, "task_manager", None),
                "task_group": getattr(obj, "task_group", None),
                "shared_message_pool": self._safe_serialize(getattr(obj, "shared_message_pool", [])),  # 注意内部是 dict
                "communication_queue": self._safe_serialize(getattr(obj, "communication_queue", None)),
                "shared_conversation_pool": self._safe_serialize(getattr(obj, "shared_conversation_pool", [])),  # 注意内部是 Dict[str, Message]
                "stage_list": self._safe_serialize(getattr(obj, "stage_list", [])),  # 注意内部是 StageState
                "execution_state": getattr(obj, "execution_state", None),
                "task_summary": getattr(obj, "task_summary", None),
            }

        # 2. StageState
        elif type(obj).__name__ == "StageState":
            return {
                "stage_id": getattr(obj, "stage_id", None),
                "task_id": getattr(obj, "task_id", None),
                "stage_intention": getattr(obj, "stage_intention", None),
                "agent_allocation": self._safe_serialize(getattr(obj, "agent_allocation", {})),  # 注意内部是 dict
                "execution_state": getattr(obj, "execution_state", None),
                "every_agent_state": self._safe_serialize(getattr(obj, "every_agent_state", {})),  # 注意内部是 dict
                "completion_summary": self._safe_serialize(getattr(obj, "completion_summary", {})),  # 注意内部是 dict
            }

        # 3. StepState
        elif type(obj).__name__ == "StepState":
            return {
                "step_id": getattr(obj, "step_id", None),
                "task_id": getattr(obj, "task_id", None),
                "stage_id": getattr(obj, "stage_id", None),
                "agent_id": getattr(obj, "agent_id", None),
                "step_intention": getattr(obj, "step_intention", None),

                "type": getattr(obj, "type", None),
                "executor": getattr(obj, "executor", None),
                "execution_state": getattr(obj, "execution_state", None),

                "text_content": getattr(obj, "text_content", None),
                "instruction_content": self._safe_serialize(getattr(obj, "instruction_content", None)),  # 注意内部是 dict
                "execute_result": self._safe_serialize(getattr(obj, "execute_result", None)),  # 注意内部是 dict

            }

        # 4. AgentBase.agent_state
        # 如果是AgentBase实例(或人类操作端HumanAgent实例)，且AgentBase.agent_state是字典
        elif type(obj).__name__ == "AgentBase": # 不依赖导入类而通过名字判断
            '''
            只保留AgentBase.agent_state （Dict[str,any]）的特殊字段
            agent_state 中 LLM Config 与 step_lock 不展示
            '''
            agent_state = getattr(obj, "agent_state", None)

            # print("[DEBUG] agent_state type:", type(agent_state))
            # print("[DEBUG] agent_state content:", agent_state)

            return {
                "agent_id": getattr(obj, "agent_id", None),
                "name": agent_state.get("name"),
                "role": agent_state.get("role"),
                "profile": agent_state.get("profile"),
                "working_state": agent_state.get("working_state"),
                "working_memory": self._safe_serialize(agent_state.get("working_memory")),
                "persistent_memory": agent_state.get("persistent_memory"),
                "agent_step": {
                    "step_list": self._safe_serialize(agent_state.get("agent_step").step_list),
                    "todo_list": self._safe_serialize(agent_state.get("agent_step").todo_list),
                } if isinstance(agent_state, dict) else None,
                "tools": self._safe_serialize(agent_state.get("tools")),
                "skills": self._safe_serialize(agent_state.get("skills")),
            }
        # 5. HumanAgent.agent_state
        # 如果是人类操作端HumanAgent实例
        elif type(obj).__name__ == "HumanAgent": # 不依赖导入类而通过名字判断
            '''
            只保留HumanAgent.agent_state （Dict[str,any]）的特殊字段
            agent_state 中 Human Config不展示
            '''
            agent_state = getattr(obj, "agent_state", None)

            return {
                "agent_id": getattr(obj, "agent_id", None),
                "name": agent_state.get("name"),
                "role": agent_state.get("role"),
                "profile": agent_state.get("profile"),
                "working_state": agent_state.get("working_state"),
                "working_memory": self._safe_serialize(agent_state.get("working_memory")),
                "persistent_memory": agent_state.get("persistent_memory"),
                "agent_step": {
                    "step_list": self._safe_serialize(agent_state.get("agent_step").step_list),
                    "todo_list": self._safe_serialize(agent_state.get("agent_step").todo_list),
                } if isinstance(agent_state, dict) else None,
                "tools": self._safe_serialize(agent_state.get("tools")),
                "skills": self._safe_serialize(agent_state.get("skills")),
                "conversation_pool": self._safe_serialize(agent_state.get("conversation_pool", {})),
            }

        else:
            print(f"[WARN] [StateMonitor] _safe_serialize: Unhandled object type {type(obj)}")
            return f"<Unserializable {type(obj).__name__}>"






























