'''
消息分发类，一般实例化在MAS类中，与SyncState和Agent同级，用于消息分发。
它会遍历所有 TaskState 的消息队列，捕获到消息后会调用agent.receive_message方法来处理消息。
'''
from mas.agent.state.sync_state import SyncState

from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union
import threading
import queue

class MessageDispatcher(threading.Thread):
    def __init__(self, sync_state: SyncState):
        self.sync_state = sync_state  # 可以访问所有 task_state

    def dispatch_messages(self, agent_dict):
        '''
        遍历所有 TaskState 的消息队列，将消息分发给对应的 Agent。
        agent_dict: agent_id -> agent 实例
        '''
        for task_id, task_state in self.sync_state.all_tasks.items():
            while not task_state.communication_queue.empty():
                try:
                    message = task_state.communication_queue.get_nowait()
                    # "receiver": ["<agent_id>", "<agent_id>", ...],
                    agent_id_list = message["receiver"]
                    # 分发消息给对应的 Agent
                    for agent_id in agent_id_list:
                        if agent_id in agent_dict:
                            agent = agent_dict[agent_id]
                            # 这里调用Agent的receive_message方法来处理消息
                            agent.receive_message(message)
                            print(f"[MessageDispatcher] 消息已分发给 Agent {agent_id}")
                        else:
                            print(f"[MessageDispatcher] Agent {agent_id} 不存在，无法分发消息。")

                except queue.Empty:
                    continue
