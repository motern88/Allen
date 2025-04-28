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
from mas.agent.state.stage_state import StageState
from mas.agent.state.task_state import TaskState
from mas.agent.state.sync_state import SyncState
from mas.agent.base.agent_base import AgentBase
from mas.message_dispatcher import MessageDispatcher
import time
import yaml

from develop开发中.MetaGPT.tests.metagpt.actions.di.test_ask_review import test_ask_review


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
        添加新的Agent到系统中。（如果未解析yaml则解析）

        agent_config 是一个包含 Agent 配置的字典，包含 name、role、profile 等信息。
        所有Agent共享同一个状态同步器 SyncState。
        '''
        if isinstance(agent_config, str):  # 如果传进来是一个路径
            with open(agent_config, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)  # 解析成字典
        else:
            config_data = agent_config

        self.agents_list.append(
            AgentBase(config=config_data, sync_state=self.sync_state)
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

    # TODO: 未实现
    def init_and_start_first_task(
        self,
        task_manager_id: str
    ):
        '''
        创建MAS中第一个任务，并指定MAS中第一个Agent为管理者。
        随后启动这个任务。
        '''
        # 构造第一个任务
        task_state = TaskState(
            task_name="MAS基础任务进程",
            task_intention="（MAS中第一个任务，用于承载管理者Agent的初始活动）"
                           "至此，管理者Agent可以在该任务进程下产生活动。\n"
                           "**该任务进程专门用于接受来自人类的指令，并根据这些指令创建新的任务。**\n"
                           "通过该任务，管理者Agent需要协调系统内其他任务的创建和分配，确保整个系统的有序运行。"
                           "在此任务下，管理者Agent需要根据不同的需求灵活调整任务优先级和资源分配，进一步提高系统效率。\n",
            task_manager=task_manager_id,
            task_group=[task_manager_id],
        )
        # 构造第一个任务中的阶段
        stage_state = StageState(
            task_id=task_state.task_id,
            stage_intention="（MAS中第一个任务的第一个阶段）"
                            "在MAS刚刚初始化，尚未分配任何实际任务时，此阶段将等待或主动向人类询问指令。"
                            "根据人类的指示，管理者Agent将创建相应的新任务，确保系统开始有序地执行具体任务。",
            agent_allocation={task_manager_id: "向人类询问具体需求，并根据需求创建相应的新任务，确保系统按需运作。"},
            execution_state="init",
        )
        # 添加阶段到第一个任务中
        task_state.add_stage(stage_state)
        # 将实例化的任务状态添加到MAS系统中
        self.sync_state.add_task(task_state)
        
        # 启动第一个任务 TODO




if __name__ == "__main__":
    '''
    测试MAS系统 在在Allen根目录下执行 python -m mas.mas
    '''
    import threading
    # 1. 实例化MAS
    mas = MultiAgentSystem()

    # 2. 添加一个Agent
    mas.add_agent("mas/role_config/管理者_灰风.yaml")

    # 3. 获取Agent（比如取第一个）
    agent = mas.agents_list[0]

    # 4. 给Agent手动分配一个任务
    mas.init_and_start_first_task()

    # 5. 启动消息分发循环（用线程异步跑）
    dispatch_thread = threading.Thread(
        target=mas.run_message_dispatch_loop,
        daemon=True  # 守护线程，主程序退出时自动关闭
    )
    dispatch_thread.start()

    # 6. 主线程可以执行其他逻辑，或者等待
    while True:
        time.sleep(1)  # 主线程保持活跃
