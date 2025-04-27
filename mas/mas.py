'''
Multi-Agent System

- 状态同步器
    首先在MultiAgentSystem类中创建一个与Agent实例平级的sync_state，
    以确保sync_state是全局唯一一个状态同步器，同时保证sync_state中的task_state是所有Agent共享的。

- Agent智能体
    MAS类是唯一的 agent 生命周期管理者，所有agent映射由它统一提供。

- 消息分发器
    同时实现一个MAS中的消息转发组件，该组件不断地从sync_state.all_tasks中的每个task_state
    task_state.communication_queue中获取消息，并向指定的Agent发送消息。

'''

from mas.agent.state.sync_state import SyncState
from mas.agent.base.agent_base import AgentBase
from mas.message_dispatcher import MessageDispatcher
import time


class MultiAgentSystem:
    '''
    多Agent系统的核心类，负责管理所有Agent的生命周期和状态同步。

    属性:
        sync_state (SyncState): 全局状态同步器，用于协调所有Agent的状态
        agents_list (List[AgentBase]): 用于存放所有Agent的列表

    '''
    def __init__(self):
        self.sync_state = SyncState()  # 实例化局唯一的状态同步器
        self.agents_list = []  # 存储所有Agent的列表
        self.message_dispatcher = MessageDispatcher()  # 实例化消息分发器

    def add_agent(self, agent_config):
        '''
        添加新的Agent到系统中。

        agent_config 是一个包含 Agent 配置的字典，包含 name、role、profile 等信息。
        所有Agent共享同一个状态同步器 SyncState。
        '''
        self.agents_list.append(
            AgentBase(config=agent_config, sync_state=self.sync_state)
        )

    def get_agent_dict(self):
        '''
        提供Agent ID -> AgentBase实例的映射字典
        '''
        return {agent.agent_id: agent for agent in self.agents_list}

    def run_message_dispatch_loop(self):
        '''
        启动消息分发组件的循环
        '''
        while True:
            self.message_dispatcher.dispatch_messages(agent_dict=self.get_agent_dict())  # 传入所有Agent的映射字典
            time.sleep(0.5)  # 每0.5秒检查一次消息队列
