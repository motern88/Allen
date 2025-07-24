## MAS:Multi-Agent System

### 1. 总览

我们在该目录下完成MAS运行所需的具体实现：

```markdown
mas/ 
├──agent             # 单个Agent所需的基础组件实现
|
├──human_config      # HumanAgent的角色配置文件
├──role_config       # LLM-Agent的角色配置文件
|
├──skills            # 技能库
├──tools             # 工具库
|
├──utils             # MAS所需的其他基础组件实现
└──web               # 前端监控与操作界面

mas.py               # 实现了MAS核心类MultiAgentSystem，也是MAS的启动入口
```



- `mas/agent`：实现和单个Agent运行相关的组件

  

- `mas/human_config`：人类操作端Agent的配置文件

  定义人类操作端可用的工具权限等

- `mas/role_config`：LLM-Agent 的配置文件

  定义 LLM-Agent 的角色背景、技能与工具权限、LLM API等

  

- `mas/skills`：实现 MAS 中 LLM-Agent 所有可用的技能

  技能是指需要LLM调用的步骤类型

- `mas/tools`：实现 MAS 中 Agent 所有可用的工具

  工具是指不需要调用LLM，且能够与实际环境交互的步骤类型

  

- `mas/utils`：实现 MAS 中其他基础组件

- `mas/web`：前端服务和静态资源界面在该目录下实现

  

- `mas/mas.py`：实现 MAS 中核心类 `MultiAgentSystem` 



### 2. MultiAgentSystem类

> 详情见文档[Multi-Agent-System实现细节](https://github.com/motern88/Allen/blob/main/docs/Multi-Agent-System实现细节.md)中第**1.2**节。

该类是MAS中的主要类，也是多Agent系统的启动入口。

在 MultiAgentSystem 类 `agent_list` 属性中维护和管理所有的 Agent 实例， 同时也管理系统中唯一的状态同步器 SyncState 和消息分发器 MessageDispatcher 。



在MAS的运行过程中，`agent_list` 属性中管理的每个Agent会初始化自己的一个线程用于执行 `AgentBase.action()` 循环。整个MAS的结构是 **多线程并行 + 每个线程内部同步逻辑** 。



#### 2.1 启动方式

调用 `MultiAgentSystem.start_system()` 方法即可启动系统：

```python
mas = MultiAgentSystem()  # 实例化MAS系统
mas.start_system()  # 启动MAS系统
```

或者直接在Allen根目录下执行：

```cmd
python -m mas.mas
```



> 在调用 `MultiAgentSystem.start_system()` 方法时，MAS系统会先后进行如下操作：
>
> - 启动消息分发器的循环（在一个线程中异步运行）
>
> - 添加第一个Agent（管理者）
>
> - 创建MAS中第一个任务，并启动该任务
>
> - 启动人类操作端和状态监控（可视化 + 热更新）的统一服务端口

