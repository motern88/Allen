'''

暂未使用到该类，当前MAS直接调用AgentBase。
TODO：
后续可以尝试AgentBase仅保留agent_state、基础工具方法、monitor装饰器
Agent类则放置执行线程和任务管理线程的方法

'''


from mas.agent.base.agent_base import AgentBase
from typing import Dict, Any, List





class LLMAgent(AgentBase):
    '''
    继承自AgentBase类的Agent，对AgentBase中方法的使用
    '''

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


