## 工具库

该目录下用于存放工具的配置文件 `{TOOLNAME}_config.yaml` 和工具具体实现 `{TOOLNAME}.py`

```python
mas/tools
├──rag.py  # 具体实现
├──rag_config.yaml  # 配置
├──ocr.py  # 具体实现
├──ocr_config.yaml  # 配置
...
```

### 1. tool config

`{TOOLNAME}_config.yaml` 工具配置文件标准：

```yaml
# 该文件用于描述工具的使用方法，以及工具包含的提示词
#（工具本身不调用LLM，但是为工具生成指令时要调用LLM。这里提示词是为instruction_generation准备的）。

# 工具的简要作用描述，Agent所有可选技能与工具的简要描述会被组装在available_skills_and_tools中
use_guide:
  tool_name: 
  description:  # 该工具的大致功能描述

# 为工具进行指令生成时调用的提示词
use_prompt:
  tool_name: 
  tool_prompt:  # 该工具对LLM指令生成时的实际引导提示词
  return_format:  # 定义LLM需要返回的，使用该工具的特定指令调用格式。建议要求llm将指令格式夹在<TOOLNAME></TOOLNAME>之间以便代码解析
```



### 2. tool executor

技能执行器实现需要继承基础执行器类，并且要向基础执行器类注册

```python
@Executor.register(executor_type="tool", executor_name="XXX") # 注册具体工具名到类型 "tool", 名称 "XXX"
class XXXTool(Executor):
    def __init__(self):
        super().__init__()  # 调用父类的构造方法
```

实现一个 `execute(self, step_id: str, agent_state: Dict[str, Any])` 方法来覆盖父类的 execute 方法，在该方法中实现这个工具的主要功能。

技能 executor 大致流程如下：

1. 从step中获取具体调用指令
2. 执行自己定义的工具实现逻辑
3. 返回用于指导状态同步的execute_result（如果有的话）





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

