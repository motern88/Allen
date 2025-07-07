'''
Multi-Agent System

该类用于管理几个上层组件：
- 状态同步器
    首先在MultiAgentSystem类中创建一个与Agent实例平级的sync_state，
    以确保sync_state是全局唯一一个状态同步器，同时保证sync_state中的task_state是所有Agent共享的。

- Agent智能体
    MAS类是唯一的 agent 生命周期管理者，所有agent映射由它统一提供。

- 消息分发器
    同时实现一个MAS中的消息转发组件，该组件不断地从sync_state.all_tasks中的每个task_state
    task_state.communication_queue中获取消息，并向指定的Agent发送消息。

同时该类决定MAS的启动方式：
    1.先启动消息分发器的循环（在一个线程中异步运行），后续任务的启动和创建均依赖此分发器
    2.添加第一个Agent（管理者），Agent在被实例化时就会启动自己的任务执行线程
    3.创建MAS中第一个任务，并指定MAS中第一个Agent为管理者，并启动该任务（启动其中的阶段）
    4.启动状态监控网页服务（可视化 + 热更新）
    5.主线程保持活跃，接受来自人类操作段的输入

'''
from mas.agent.state.stage_state import StageState
from mas.agent.state.task_state import TaskState
from mas.agent.state.sync_state import SyncState
from mas.agent.base.agent_base import AgentBase
from mas.agent.human_agent import HumanAgent  # 人类操作端Agent
from mas.utils.message_dispatcher import MessageDispatcher  # 消息分发器

from mas.utils.web.server import start_monitor_web  # 监控器网页服务
from mas.utils.web.human_interface import register_mas_instance, start_human_interface  # 人类操作端接口服务

import mas.skills.__init__  # 会自动触发所有注册器的装饰器调用
# import mas.tools.__init__  # 会自动触发所有注册器的装饰器调用  TODO:工具注册器暂时注释掉，等工具模块完善后再启用

import time
import yaml
import threading


class MultiAgentSystem:
    '''
    多Agent系统的核心类，负责管理所有Agent的生命周期和状态同步。

    属性:
        sync_state (SyncState): 全局状态同步器，用于协调所有Agent的状态
        agents_list (List[AgentBase]): 用于存放所有Agent的列表
        message_dispatcher (MessageDispatcher): 消息分发器，用于在Agent之间传递消息

    '''
    def __init__(self):
        self.sync_state = SyncState(self)  # 实例化局唯一的状态同步器，把self传进去，让SyncState能访问MultiAgentSystem
        self.agents_list = []  # 存储所有Agent实例的列表
        self.message_dispatcher = MessageDispatcher(self.sync_state)  # 实例化消息分发器


    def add_llm_agent(self, agent_config):
        '''
        添加新的LLM-Agent到系统中。（如果未解析yaml则解析）

        agent_config 是一个包含 Agent 配置的字典，包含 name、role、profile 等信息。
        所有Agent共享同一个状态同步器 SyncState。
        '''
        if isinstance(agent_config, str):  # 如果传进来是一个路径
            with open(agent_config, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)  # 解析成字典
        else:
            config_data = agent_config

        # 实例化AgentBase对象，并添加到agents_list中。在Agent实例化的同时就启动了Agent自己的任务执行线程。
        llm_agent = AgentBase(config=config_data, sync_state=self.sync_state)
        self.agents_list.append(llm_agent)

        return llm_agent.agent_id  # 返回新添加的Agent的ID，方便后续引用


    def add_human_agent(self, agent_config):
        '''
        添加新的人类操作端 Human-Agent到系统中。
        检查配置文件中是否包含了agent_id, 如果包含则直接传入该ID
        '''
        if isinstance(agent_config, str):  # 如果传进来是一个路径
            with open(agent_config, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)  # 解析成字典
        else:
            config_data = agent_config

        # 获取配置中的 agent_id，如果没有则为 None
        agent_id = config_data.get("human_config", {}).get("agent_id", None)
        if agent_id is not None:
            # 检查是否已经存在同名的Agent，如果存在则抛出异常
            for agent in self.agents_list:
                if agent.agent_id == agent_id:
                    raise ValueError(f"Agent ID '{agent_id}' 已经存在. 请使用唯一ID.")
            # 实例化指定AgentID的AgentBase对象
            human_agent = HumanAgent(agent_id=agent_id, config=config_data, sync_state=self.sync_state)
        else:
            # 实例化AgentBase对象，并添加到agents_list中。
            human_agent = HumanAgent(config=config_data, sync_state=self.sync_state)

        self.agents_list.append(human_agent)

        return human_agent.agent_id  # 返回新添加的Human-Agent的ID，方便后续引用


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


    def init_and_start_first_task(
        self,
        task_manager_id: str
    ):
        '''
        创建MAS中第一个任务，并指定MAS中第一个Agent为管理者。
        随后启动这个任务的阶段。
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
                            "根据人类的指示，管理者Agent将创建相应的新任务，确保系统开始有序地执行具体任务。\n"
                            "**请预先明确MAS系统中HumanAgent的Agent ID**\n"
                            "该阶段作为管理Agent的初始活动环境，不应当结束，请此阶段下的管理Agent通过不断追加reflection保持活跃。",
            agent_allocation={task_manager_id: "向人类询问具体需求，并根据需求创建相应的新任务，确保系统按需运作。"},
            execution_state="init",
        )
        # 添加阶段到第一个任务中
        task_state.add_stage(stage_state)
        # 通过sync_state将实例化的任务状态添加到MAS系统中
        self.sync_state.add_task(task_state)

        # 通过sync_state启动任务阶段
        self.sync_state.start_stage(
            task_id=task_state.task_id,
            stage_id=stage_state.stage_id,
            sender_id=task_manager_id
        )
        print(f"[SyncState] 任务{task_state.task_id}的阶段{stage_state.stage_id}已开启")

        return task_state.task_id  # 返回新创建的任务ID，方便后续引用


    def get_agent_from_id(self, agent_id: str):
        '''
        根据agent_id获取AgentBase实例。
        '''
        for agent in self.agents_list:
            if agent.agent_id == agent_id:
                return agent
        return None  # 没找到就返回 None，也可以抛出异常


if __name__ == "__main__":
    '''
    测试MAS系统 在在Allen根目录下执行 python -m mas.mas
    
    MAS系统的启动方式，
    1.先启动消息分发器的循环（在一个线程中异步运行），后续任务的启动和创建均依赖此分发器
    
    2.添加第一个Agent（管理者），Agent在被实例化时就会启动自己的任务执行线程
    
    3.创建MAS中第一个任务，并指定MAS中第一个Agent为管理者，并启动该任务（启动其中的阶段）
    
    4.启动状态监控网页服务（可视化 + 热更新）
    4.1 启动人类操作端接口服务
    
    5.主线程保持活跃，接受来自人类操作段的输入
    
    '''
    # TODO：将MAS启动写成一个函数

    # 1. 实例化MAS
    mas = MultiAgentSystem()

    # 2. 启动消息分发循环（用线程异步跑）
    dispatch_thread = threading.Thread(
        target=mas.run_message_dispatch_loop,
        daemon=True  # 守护线程，主程序退出时自动关闭
    )
    dispatch_thread.start()
    print(f"[MAS] 消息分发循环已启动。")

    # 3. 初始任务启动
    llm_agent_id = mas.add_llm_agent("mas/role_config/管理者_灰风.yaml")  # 添加第一个Agent（管理者）
    first_task_id = mas.init_and_start_first_task(llm_agent_id)  # 传入第一个agent（管理者）的ID

    # 4. 启动状态监控网页服务（可视化 + 热更新）
    threading.Thread(target=start_monitor_web, daemon=True).start()
    print(f"[MAS] 状态监控网页服务已启动，访问 http://localhost:5000 查看状态。")

    from mas.utils.monitor import StateMonitor  # Debug：查看监控器捕获信息时需要导入

    # 4.1 启动人类操作端接口服务
    register_mas_instance(mas)  # 注册MAS实例
    threading.Thread(target=start_human_interface, daemon=True).start()
    print(f"[MAS] 人类操作端接口服务已启动，访问 http://localhost:5001 发送消息。")


    # 5. 主线程可以执行其他逻辑，接受来自人类操作段的输入
    # TODO: 这里是临时的调试代码，写死人类操作端agent_id，写死发送对象为灰风，后续可以改为更友好的人类操作端交互方式
    human_agent_id = mas.add_human_agent("mas/human_config/人类操作端_测试.yaml")  # 添加一个HumanAgent
    human_agent = mas.get_agent_from_id(human_agent_id)  # 获取HumanAgent实例
    while True:
        # # Debug:打印系统任务状态，MAS是否正确创建任务
        # all_tasks = mas.sync_state.all_tasks
        # print(f"sync_state.all_tasks:\n{all_tasks}")

        # # Debug:打印监控状态，监控器是否成功捕获MAS的各种状态
        # print(f"monitor.get_all_states：\n{StateMonitor().get_all_states()}")

        user_input = input("[DEBUG][HumanAgent] 请输入指令 (输入 'send' 来向当前任务管理者发送消息)：")

        if user_input.strip() == "send":
            print("[DEBUG][HumanAgent] 请输入要发送的消息内容：")
            message_content = input("[DEBUG][HumanAgent] 消息内容：")
            # 调用 HumanAgent 的 send_message 方法发送消息
            human_agent.send_message(
                task_id=first_task_id,
                receiver=[llm_agent_id],  # 发送给管理者Agent
                context=message_content,
                stage_relative="no_relative",  # 与任务阶段无关
                need_reply=True,  # 需要回复
                waiting=None,  # 不等待回复
            )

        if user_input.strip() == "step_list":
            llm_agent = mas.get_agent_from_id(llm_agent_id)
            print(f"step_list:")
            llm_agent.agent_state["agent_step"].print_all_steps()

        # print(".")
        time.sleep(1)  # 主线程保持活跃
