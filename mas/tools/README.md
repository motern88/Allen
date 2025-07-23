## Tools

### 1. 总览

我们MAS中的工具调用均以MCP的标准实现；该目录下用于存放MAS中接入MCP Server的具体实现：

```python
mas/tools
├──mcp_local_server      		# 本地部署的MCP Server实现
|   └──XXX_server.py
└──mcp_server_config			# MCP Server启动配置
    └──XXX_mcp_config.json
mcp_client.py         			# MAS中全局唯一的MCP Client，负责提供session连接和管理
mcp_tool.py           			# Executor的工具子类，也是tool step的具体执行器
mcp_base_prompt.yaml  			# MCP使用方式的基础提示词
```



- `mas/tools/mcp_local_server`：用于存放自己实现的本地 MCP Server

- `mas/tools/mcp_server_config`：用于存放 MAS 中支持的 MCP Server 启动配置

  对于每个 MCP Server，都由一个以 `{server_name}_mcp_config.json` 命名的文件

  

- `mas/tools/mcp_client.py`：实现 MCP Client 以支持连接标准 MCP Server

- `mas/tools/mcp_tool.py`：实现用于调用 MCP Server 的 Executor

  对于技能而言，每个技能有各自不同的 Executor 子类。对于工具而言，因为我们使用 MCP 标准，因此只需要实现一个 Executor 子类，该 MCP 工具调用 Executor 即可调用任何一种 MCP 工具。



- `mas/tools/mcp_base_prompt.yaml`：包含MCP使用方式的基础提示词

  Agent已经知晓如何调用MAS中的工具，只是不了解MCP协议。我们在该基础提示词中详细描述了如何生成各种MCP调用指令，以及如何理解MCP调用返回结果。

  注：这里的MCP调用指令是我们自己定义的如何在MAS中操作和调用MCP。与此同时，我们在 MCP Tool Executor 中实现了相应指令的解析逻辑。



#### 1.1 MCP Server Config

`mas/tools/mcp_server_config` 下的 `{server_name}_mcp_config.json` 配置文件中实现了对MCP Server 的启动配置和简要描述。

这里展示其中一个示例：

```yaml
# 该文件用于描述MCP Server的描述，以及记录MCP Server的启动配置。

# 技能的简要作用描述，Agent所有可选技能与工具的简要描述会被组装在available_skills_and_tools中
use_guide:
  tool_name: "everything"  # 工具名称需要与mcpServer启动配置中的名称一致
  description: |
    此 MCP 服务器尝试执行 MCP 协议的所有功能。
    它不是为了成为一个有用的服务器，而是一个 MCP 客户端构建者的测试服务器。
    它实施提示、工具、资源、采样等来展示 MCP 功能。

# MCP Server 启动配置
config: |
  {
    "mcpServers": {
      "everything": {
        "command": "npx",
        "args": [
          "-y",
          "@modelcontextprotocol/server-everything"
        ]
      }
    }
  }
```



#### 1.2 MCP Base Prompt

`mas/tools/mcp_server_config/mcp_base_prompt.yaml` 中 `mcp_base_prompt` 字段记录了 MCP 调用的基础提示词。

在MAS中Agent已经知晓如何调用MAS中的工具，只是不了解MCP协议。

该提示词主要内容为 Agent能直接看到的涉及到MCP协议执行过程的交互提示 而非工具调用方式提示。

其中包含：

- 如何生成获取MCP Server能力列表的具体指令
- 如何理解MCP Server能力列表
- 如何生成MCP Server能力具体调用的参数
- 如何理解MCP Server对能力调用的具体返回结果

该提示一般在涉及到工具步骤的时候才会调用，例如 Instruction Generation 和 Tool Decision 。





### 2. MCP Client

> MCP客户端实现详情见文档[Multi-Agent-System实现细节](https://github.com/motern88/Allen/blob/main/docs/Multi-Agent-System实现细节.md)中**4.1**节

我们在 `mas/tools/mcp_client.py` 中实现了标准MCP客户端。MCPClient 类负责连接多个 MCP Server，而每个 MCP Server 可用有多个 MCP Tool :

```python
MCP Client
    ├── MCP Server 1
    │      ├── MCP Tool A
    │      └── MCP Tool B
    └── MCP Server 2
           ├── MCP Tool C
           └── MCP Tool D
```

因此我们对于MCP 连接管理自下而上有四个层级：

- **第一级** 静态启动配置：`MCPClient.server_config`

  存放了MAS中所有支持的MCP Server的启动配置

- **第二级** Agent调用权限：`AgentState.tools`

  Agent并不能直接调用MAS支持的所有MCP Server，会受到Agent配置中的工具权限的限制。 `AgentState.tools`中存放了Agent可调用的外部工具（MCP服务）的权限。

- **第三级** 活跃的连接：`MCPClient.server_sessions`

  存放了活跃的MCP Server连接实例，key 为MCP Server名称，value 为 `requests.Session` 实例。

  `MCPClient.server_sessions` 会动态连接第二级权限包含的MCP Server，并保证MAS中所有Agent的工具权限所涉及到的MCP Server都处于活跃连接状态。

- **第四级** 缓存调用描述：`MCPClient.server_descriptions`

  我们不希望每次调用具体MCP Server的能力时都发起获取描述的请求，我们会在本第四层级中做缓存。`MCPClient.server_descriptions` 存放了MCP Server中可用工具的详细描述，key 为工具名称，value 为工具描述。

  `MCPClient.server_descriptions` 会从第三级中活跃session连接中调用工具名称、描述和使用方式并记录。在Agent获取全部工具和技能提示词时，`server_descriptions` 提供相应支持；在Agent执行/组装工具Step提示词时，`server_descriptions` 也会提供具体工具的描述和调用格式信息。



我们在MCP Client中实现了三个主要方法：

- `connect_to_server` ：连接指定MCP服务器，并记录到 `MCPClient.server_sessions` 中

- `get_server_descriptions` ：获取指定MCP Server的详细描述
- `use_capability` ：传入参数使用MCP Server提供的能力





### 3. MCP Tool

> MCP Tool Executor实现详情见文档[Multi-Agent-System实现细节](https://github.com/motern88/Allen/blob/main/docs/Multi-Agent-System实现细节.md)中**4.2**节

我们在 `mas/tools/mcp_tool.py` 中实现用于调用 MCP Server 的 Executor。与技能Executor一样，该MCP Tool Executor依然继承自Executor基础类，共享所有基类的方法。与技能Executor的区别在于：

- 每个技能都实现一个单独的Executor子类用于隔离各个技能不同的调用逻辑
- 所有的工具都共享同一个Executor子类（`MCPTool(Executor)`）







### 4. 如何实现一个新的Tool

要在 MAS 中新增可以调用的 MCP Server 只需要在 `mas/tools/mcp_server_config` 中创建新的 MCP Server 配置即可。

- 对于一些已有的公开的MCP Server，你只需要填写 `{server_name}_mcp_config.json` ：

  ```yaml
  # 技能的简要作用描述
  use_guide:
    tool_name: # 填写{server_name}工具名称需要与mcpServer启动配置中的名称一致
    description: # 填写简要描述，让Agent知道什么时候该调用该MCP Server
  
  # MCP Server 启动配置
  config: # 填写一般公开MCP Server都会给出的启动配置字典
  ```

  

- 对于你自己实现的MCP Server，你可以在 `mas/tools/mcp_local_server` 下实现你本地自定义MCP Server的具体构造，随后在 `mas/tools/mcp_server_config`  中同样新增该 MCP Server 的启动配置即可。
