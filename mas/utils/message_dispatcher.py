'''
消息分发类，一般实例化在MAS类中，与SyncState和Agent同级，用于消息分发。
它会遍历所有 TaskState 的消息队列，捕获到消息后会调用agent.receive_message方法来处理消息。
当成功发送消息后，消息会被记录在 task_state.shared_conversation_pool 中。
'''
from mas.agent.state.sync_state import SyncState

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union
import threading
import queue

class MessageDispatcher(threading.Thread):
    def __init__(self, sync_state: SyncState):
        self.sync_state = sync_state  # 可以访问所有 task_state

    def dispatch_messages(self, agent_dict):
        '''
        遍历所有 TaskState 的消息队列，
        对找到的消息执行：
            1.分发给对应的 Agent。
            2.将分发成功的 message 记录在 task_state.shared_conversation_pool 中。
        agent_dict: agent_id -> agent 实例
        '''
        for task_id, task_state in self.sync_state.all_tasks.items():
            while not task_state.communication_queue.empty():
                try:
                    message = task_state.communication_queue.get_nowait()
                    # "receiver": ["<agent_id>", "<agent_id>", ...],
                    agent_id_list = message["receiver"]
                    delivered = False  # 标记消息是否成功分发给至少一个接收者

                    # 分发消息给对应的 Agent
                    for agent_id in agent_id_list:
                        if agent_id in agent_dict:
                            agent = agent_dict[agent_id]
                            # 这里调用Agent的receive_message方法来处理消息
                            agent.receive_message(message)
                            delivered = True
                            print(f"[MessageDispatcher] 消息已分发给 Agent {agent_id}")
                        else:
                            print(f"[MessageDispatcher] Agent {agent_id} 不存在，无法分发消息。")

                    # 如果消息成功分发给至少一个接收者，则记录在共享会话池中
                    if delivered:
                        # 获取当前时间戳
                        timestamp = datetime.now().isoformat()
                        task_state.shared_conversation_pool.append({timestamp:message})  # Dict[str, Message]
                        print(f"[MessageDispatcher] 消息已记录到任务 {task_id} 的共享会话池")

                except queue.Empty:
                    continue
