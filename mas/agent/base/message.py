'''
这里定义一个Message的基本格式，包含 TODO

    task_id (str): 任务ID
    sender_id (str): 发送者ID
    receiver (List[str]): 接收者ID列表
    message (str): 消息内容
        如果其中包含指令，则用<instruction>和</instruction>包裹指令字典

    stage_relative (str): 是否与任务阶段相关
    need_reply (bool): 是否需要回复

    TODO 步骤锁机制说明
    waiting (Optional[List[str]]): 等待回复的唯一ID列表
    return_waiting_id (Optional[str]): 返回的唯一等待ID
'''


from typing import TypedDict, List, Union, Optional

class Message(TypedDict):
    task_id: str  # 任务ID,
    sender_id: str
    receiver: List[str]  # 用列表包裹的接收者agent_id
    message: str  # 消息文本
    stage_relative: str  # 表示是否与任务阶段相关，是则填对应阶段Stage ID，否则为no_relative的字符串
    need_reply: bool  # 需要回复则为True，否则为False
    waiting: Optional[List[str]]  # 如果发送者需要等待回复，则为所有发送对象填写唯一等待ID。不等待则为 None
    return_waiting_id: Optional[str]  # 如果消息发送者需要等待回复，则返回消息时填写接收到的消息中包含的来自发送者的唯一等待ID