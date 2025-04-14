## 技能库

该目录下用于存放技能的配置文件 `{SKILLNAME}_config.yaml` 和技能具体实现 `{SKILLNAME}.py`

```python
mas/skills
├──planning.py  # 具体实现
├──planning_config.yaml  # 配置
├──reflection.py  # 具体实现
├──reflection_config.yaml  # 配置
...
```

### 1. skill config

`{SKILLNAME}_config.yaml` 技能配置文件标准：

```yaml
# 该文件用于描述技能的使用方法，以及技能包含的提示词。

# 技能的简要作用描述，Agent所有可选技能与工具的简要描述会被组装在available_skills_and_tools中
use_guide:
  skill_name: 
  description:  # 该技能的大致功能描述

# 技能实际调用的提示词
use_prompt:
  skill_name: 
  skill_prompt:  # 该技能对LLM的实际引导提示词
  return_format:  # 定义解析该技能结果的特定返回格式，建议要求llm将一些需要代码读取的特定返回结果夹在<SKILLNAME></SKILLNAME>之间
```



### 2. skill executor

技能执行器实现需要继承基础执行器类，并且要向基础执行器类注册

```python
@Executor.register(executor_type="skill", executor_name="XXX") # 注册规划技能到类型 "skill", 名称 "XXX"
class XXXSkill(Executor):
    def __init__(self):
        super().__init__()  # 调用父类的构造方法
```

实现一个 `execute(self, step_id: str, agent_state: Dict[str, Any])` 方法来覆盖父类的 execute 方法，在该方法中实现这个技能的主要功能。

技能 executor 大致流程如下：

1. 组装提示词（系统 → 角色 → (目标 → 规则) → 记忆）

   1.1 MAS系统提示词

   1.2 Agent角色提示词（角色背景与可使用的工具/技能权限）

   1.3 当前技能步骤提示词（步骤目标，技能规则）

   1.4 持续性记忆提示词（持续性记忆规则说明，持续性记忆内容提示）

2. LLM调用

3. 解析LLM调用的技能返回结果，完成技能的实际操作

4. 解析LLM调用返回的持续性记忆信息，追加到Agent持续性记忆中

5. 返回用于指导状态同步的execute_result（如果有的话）



#### 2.1 执行器状态更新

默认执行器必须传递的状态更新有：

1. 更新step状态为 running

   ```python
   agent_state["agent_step"].update_step_status(step_id, "running")
   ```

2. 完成具体执行内容后更新step状态

   如果执行成功则更新为 finished

   ```python
   agent_state["agent_step"].update_step_status(step_id, "finished")
   ```

   如果执行失败则更新为 failed

   ```python
   agent_state["agent_step"].update_step_status(step_id, "failed")
   ```

3. 更新stage中agent自身状态 update_agent_situation

   借用execute_output传递，finished 或 failed

   ```python
   execute_output["update_stage_agent_state"] = {
               "task_id": task_id,
               "stage_id": stage_id,
               "agent_id": agent_state["agent_id"],
               "state": update_agent_situation,
           }
   ```

4. 添加task中共享消息 shared_step_situation

   借用execute_output传递，finished 或 failed

   ```python
   execute_output["send_shared_message"] = {
       "agent_id": agent_state["agent_id"],
       "role": agent_state["role"],
       "stage_id": stage_id,
       "content": f"执行XXX步骤:{shared_step_situation}，"
   }
   ```

