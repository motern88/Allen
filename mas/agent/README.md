总览

```python
├──base
|   ├──agent_base.py  # agent基础类
|   ├──executor_base.py  # 执行器基础类(为skills与tools定义统一的方法)
|   └──llm_base.py  # LLM基础调用类
├──configs
|   └──llm_config.py  # LLM配置类 
├──state
|   ├──task_state.py
|   ├──stage_state.py
|   └──step_state.py
└──agent.py  # 实现通用agent类
```



25-3-25
实现LLM基础调用类

```python
configs.llm_config.LLMType  # LLM API 类型枚举
configs.llm_config.LLMConfig  # LLM 基础配置
base.llm_base.LLMContext  # 对话历史上下文
base.llm_base.LLMClient  # LLM API 调用封装，使用.call调用
```

