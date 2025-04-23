'''
这里定义一个Message的基本格式，
在MAS中跨Agent的消息传递一般均使用该格式。

Message字典包含Key及含义:
    task_id (str): 任务ID
    sender_id (str): 发送者ID
    receiver (List[str]): 接收者ID列表
    message (str): 消息内容
        如果其中包含指令，则用<instruction>和</instruction>包裹指令字典

    stage_relative (str): 是否与任务阶段相关
        用于方便清除机制判断是否要随任务阶段
    need_reply (bool): 是否需要回复
        如果需要回复，则接收者被追加一个指向发送者的Send Message step，
        如果不需要回复，则接收者被追加一个Process Message step，Process Message 不需要向其他实体传递消息或回复

    waiting (Optional[List[str]]): 等待回复的唯一ID列表
        如果发送者需要等待回复，则为所有发送对象填写唯一等待标识ID。不等待则为 None
        如果等待，则发起者将在回收全部等待标识前不会进行任何步骤执行
    return_waiting_id (Optional[str]): 返回的唯一等待标识ID
        如果这个消息是用于回复消息发起者的，且消息发起时带有唯一等待标识ID，则回复时也需要返回这个唯一等待标识ID
        ！如果不返回，则会导致消息发起者无法回收这个唯一等待标识ID，发起者将陷入无尽等待中。
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