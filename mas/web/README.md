## Web

### 1. 总览

我们在该目录下实现MAS架构的前端操作和展示界面

```python
mas/web
└──templates
    ├──assets			# 静态资源（CSS/JS）
    |   ├──xxx.js
    |   └──xxx.css
    └──index.html		# 前端界面
server.py               # 服务端
```



### 2. Server

#### 2.1 状态监控接口

```python
GET /api/states?type=task
GET /api/states?type=stage
GET /api/states?type=agent
GET /api/states?type=step
GET /api/state/<state_id>    # 查询指定状态 ID 的详情
```

可以查询某一种状态类型的全部状态信息。也可以指定状态ID查询某一个状态信息。



返回以下格式：

```python
{
    "StateID_1": { "task_id": "...", "task_name": "...", ... },
    "StateID_2": { ... },
    ...
}
```



#### 2.2 人类操作端接口

```python
POST /api/send_private_message       # 人类操作端发送私聊消息
POST /api/send_group_message         # 人类操作端发送群聊消息
POST /api/bind_human_agent           # 人类操作端登录
```



- 在私聊中发送消息

  `POST /api/send_private_message`

  请求参数（JSON）：

  ```python
  {
      "human_agent_id": "人类操作员ID",  # 这个ID是uuid.uuid4()的agent_id,而不是监控器中带"HumanAgent_"前缀的ID
      "task_id": "任务ID",
      "receiver": ["接收者ID1", "接收者ID2", ...],
      "content": "消息内容",
      "stage_relative": "相关阶段ID",   # 可选，默认为"no_relative"
      "need_reply": true,  		    # 可选，默认为true
      "waiting": true      			# 可选，默认为false
  }
  ```

  返回：

  ```python
  {
      "success": true,
      "message": "消息已发送"
  }
  ```



- 在群聊中发送消息

  `POST /api/send_group_message`

  请求参数（JSON）：

  ```python
  {
      "human_agent_id": "人类操作员ID",  # 这个ID是uuid.uuid4()的agent_id,而不是监控器中带"HumanAgent_"前缀的ID
      "task_id": "任务ID",
      "receiver": ["接收者ID1", "接收者ID2", ...],
      "content": "消息内容",
      "stage_relative": "相关阶段ID", // 可选，默认为"no_relative"
      "need_reply": true,  // 可选，默认为true
      "waiting": true      // 可选，默认为false
      "return_waiting_id": "唯一等待ID"  // 可选，默认为None
  }
  ```

  返回：

  ```python
  {
      "success": true,
      "message": "消息已发送"
  }
  ```



- 人类操作端登录

  > 用户从前端可以绑定一个Human-Agent，此后用户在MAS中从行为均以该HumanAgent的身份代为执行。即，用户操作HumanAgent在MAS中与环境/其他Agent进行交互。
  >
  > 访问密码在每个HumanAgent的配置文件中可以设置。

  `POST /api/bind_human_agent` 

  请求参数（JSON）：

  ```python
  {
      "human_agent_id": "<HumanAgent的ID>"
      "password": "<HumanAgent的密码>"
  }
  ```

  返回：

  ```python
  {
      "success": true,
      "human_agent_id": "<传入的HumanAgent的ID>"
      "message": "<调用成功或失败的消息>"
  }
  ```

  

### 3. 前端界面设计

> 前端设计图可见文档[MAS界面示意图](https://github.com/motern88/AI_Conversation_in_Motern/blob/main/-技术报告/多智能体系统-技术报告/操作界面示意图/MAS界面示意图.md)