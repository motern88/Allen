## Configs

### 1. LLM Config

在 `mas/agent/configs/llm_config.py` 中定义了Agent配置中的LLMConfig的结构，并实现加载文件配置的方法：

-  `LLMConfig.from_yaml` 即可从对应文件路径的 `.yaml` 文件中加载LLM配置。



### 2. 配置默认 LLM Config

请配置自己的 LLM API 到 `mas/agent/configs/default_llm_config.yaml` 以便MAS创建新Agent时能够顺利进行。

> MAS架构中创建未预先定义的Agent角色时，其LLM Config部分会使用此处的 `default_llm_config` 。
