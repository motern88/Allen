'''
这里实现 LLMAgent ，继承Agent基础类，拥有和AgentBase相同的构造与接口。

1. Agent唯一的LLM Client
    我们在LLMAgent初始化时，向AgentState中添加了Agent唯一的LLM Client和Context。
    此后在Skill Executor调用时，均会使用该LLM Client和Context实例而不再重新组装

TODO：后续可以尝试AgentBase仅保留agent_state、基础工具方法、monitor装饰器；
    LLMAgent类则放置执行线程和任务管理线程的方法。

'''
from typing import Dict, Any, List

from mas.agent.base.agent_base import AgentBase
from mas.agent.base.llm_base import LLMContext, LLMClient
from mas.utils.monitor import StateMonitor


@StateMonitor.track  # 注册状态监控器，主要监控agent_state
class LLMAgent(AgentBase):
    '''
    继承自AgentBase类的LLMAgent，对AgentBase中方法的使用

    相比于基础类：
    - 在AgentState中初始化并维护Agent唯一的LLM Client和LLM Context。
    '''

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 在父类（AgentBase）初始化后，初始化LLM客户端和上下文
        self.init_llm_client_and_context()

    # TODO：这里实现的LLMClient / Context未同步到 base_prompt系统提示词中，
    #   不过几乎没有影响，Agent本身也感知不到AgentState中这两个字段
    def init_llm_client_and_context(self):
        '''
        向AgentState中存储唯一的LLM客户端和上下文。
        {
            "llm_client": LLMClient,
            "llm_context": LLMContext,
        }
        '''
        # 通过配置文件初始化LLMClient
        self.agent_state["llm_client"] = LLMClient(self.agent_state["llm_config"])
        # 初始化LLMContext
        self.agent_state["llm_context"] = LLMContext(context_size=15)  # 限制最大轮数为15
