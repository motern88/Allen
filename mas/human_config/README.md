## Human Config

该路径下 `mas/human_config` 放置预定义的Human-Agent配置。代表人类操作端Agent的配置文件。

你可以按照相同的标准增加新的预定义的人类操作员配置。



### 1. 配置文件标准

以角色名字命名的 `.yaml` 文件记录了HumanAgent的配置，其中包含：

```yaml
name: ""
role: "人类操作员"
profile: |
  **简要介绍**：...
  **人格特质**：...

skills: ["planning", "reflection", "summary",...]  # 管理技能
tools: []

human_config:
  agent_id: ""
  password: ""
  level: 1
```



- `name`：HumanAgent名字
- `role`：自定义Agent角色，例如人类管理者、人类工程师等等
- `profile`：HumanAgent角色简介，主要在这里介绍该人类操作员



- `skills`：HumanAgent人类操作端配置必须给予全部的基础技能和通讯技能权限。

  同时给予 `ask_info` 等信息获取权限。管理技能 `task_manager` 和  `agent_manager`视情况赋予。

- `tools`：我们希望MAS架构中的MCP Server也可以被HumanAgent手动调用，因此这里也可以像LLM-Agent一样配置对应的工具权限。



- `human_config/agent_id`：在首次创建HumanAgent之后会自动生成该HumanAgent的唯一UUID，可以将其记录并填入该字段，此后每次MAS系统重新唤起该HumanAgent的时候就会固定使用该字段值作为HumanAgent的 `agent_id` 而不再新随机生成一个id。

- `human_config/password`：可以填入HumanAgent的访问密码。

  我们希望每个使用者都只能操作自己的HumanAgent。

  如果password不为空，则前端界面中的用户需要绑定该HumanAgent时需要验证密码一致。

  > 见 `mas/web/server.py` 中实现的接口 `POST /api/bind_human_agent`

- `human_config/level`：后续区分HumanAgent级别时可能会使用到，**暂未实现相关功能**