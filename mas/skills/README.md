## Skills

### 1. 总览

该目录下用于存放技能的配置文件 `{SKILLNAME}_config.yaml` 和技能具体实现 `{SKILLNAME}.py`

```python
mas/skills
{SKILLNAME}.py                  # 具体实现
{SKILLNAME}_config.yaml         # 配置
...
```



#### 1.1 Skill Config

`{SKILLNAME}_config.yaml` 技能配置文件中实现了对于技能（调用LLM步骤类型）的提示词，实现格式：

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

其中：

- `use_guide` 字段用于在任何决策时候提示LLM其可用的技能/工具及其简要功能描述。
- `use_prompt` 字段记录更为详细的调用引导和返回格式提示词，仅在发生决策后的实际调用中使用。



#### 1.2 Skill Executor

> 每种技能的实现详情见文档[Muti-Agent-System实现细节](https://github.com/motern88/Allen/blob/main/docs/Muti-Agent-System实现细节.md)中第**3**节。

技能执行器具体实现有关技能步骤Skill Step被执行时的具体逻辑。

MAS下所有的技能执行器 Skill Executor 均继承基础执行器类，其共享基础执行器方法，因此每个Skill Executor子类只需要专注实现差异化的决策逻辑。

每个Skill Executor子类均实现了一个子类的 `execute(self, step_id: str, agent_state: Dict[str, Any])` 方法。该方法会在Agent执行具体Step时被执行（路由Router会根据Step信息选择相应的执行器的 `execute()` 方法来执行）。



### 2. 如何实现一个新的Skill

> 首先你需要了解Skill是特指需要调用LLM进行决策的步骤类型，如果是不需要调用LLM的新功能，你应当实现的是一个工具Tool而不是技能。
>
> 其次需要明确尽量不要实现两个功能接近或功能重合的技能，请确保每个技能都是独一无二且必要的。模糊重复的技能定位容易让LLM调用时产生不必要的混乱。
>
> 最终当你确定MAS中已有的技能实现均无法满足你的特定需求时，你可以根据以下说明，同时参考已有的技能实现来制作一个新的Skill。

技能执行器实现需要继承基础执行器类，并且要向基础执行器类注册（以便路由Router能够在具体Step执行时找到相应的执行器Executor）

```python
@Executor.register(executor_type="skill", executor_name="XXX") # 注册规划技能到类型 "skill", 名称 "XXX"
class XXXSkill(Executor):
    def __init__(self):
        super().__init__()  # 调用父类的构造方法
```



同时必须实现一个 `execute(self, step_id: str, agent_state: Dict[str, Any])` 方法来覆盖父类的 execute 方法，并在该方法中实现这个技能的主要功能。

> 传入 `agent_state` 的主要作用是让 `execute()` 方法具备改变Agent自身状态的能力。
>
> 例如Planning技能需要为自身规划接下来的步骤，解析后的规划结果则可以在 `execute()` 方法的执行过程中直接将新增步骤添加到 `agent_state["agent_step"]` 中。



`Executor.execute()` 的大致实现功能如下：

- 组装需要送入LLM的提示词

  在MAS中的提示词顺序一般为（系统 → 角色 → (目标 → 规则) → 记忆）

- 进行实际LLM调用

  - 创建一个对话上下文 `LLMContext` 用来添加你组装好的提示词。
  - 调用 `LLMClient.call()` 方法来获取LLM的推理结果。

  >  LLMContext 和 LLMClient 实现于 mas.agent.base.llm_base 中

- 解析LLM调用的技能返回结果，完成技能的实际操作

  你的提示词一般会要求其以特殊标记（例如`<xxx_instruction>`）包裹指令内容以方便区分LLM生成的指令和其他思考过程。

  随后按照你定义的方式解析指令内容即可让 `Executor.execute()` 能够执行特定的逻辑行为（例如添加步骤，修改状态等）。

  > 你需要在该 `execute()` 方法中实现具体操作行为，例如：
  >
  > - 当解析出的指令包含XXX时，则执行XXX...
  >
  > 这一切都是你需要在 `execute()` 中定义好的，并且配合提示词来实现（提示词在 `{skill_name}_config.yaml` 中实现）。

- 解析LLM调用返回的持续性记忆信息，追加到Agent持续性记忆中

  持续性记忆是本系统中Agent的一个重要记忆机制，因为我们在每个Step中重组提示词，每个Step执行时并不一定知晓此前的Step发生了什么。因此我们维护了一个可以跨步骤Step、跨阶段Stage和跨任务Task的持续性记忆帮助Agent自我管理重要的上下文信息。

  > 持续性记忆机制详情见文档[Muti-Agent-System实现细节](https://github.com/motern88/Allen/blob/main/docs/Muti-Agent-System实现细节.md)中第**9.3**节。

  这一部分的实现请参考/照搬已有技能的实现即可，不需要额外做出改变。

- 返回用于指导状态同步的 `execute_output` ：

  每个步骤的 `Executor.execute()` 执行完毕后会返回 `execute_output` 。

  `execute_output` 是 `Executor` 操作/影响非自身Agent的重要途经。

  > `Executor.execute()` 能够直接访问传入的 `agent_state` Agent状态以改变自身，但如果执行器想要影响非自身Agent状态（例如阶段Stage、任务Task或其他Agent），则需要通过 `Executor.execute()` 返回的 `execute_output` 。

  > `Executor.execute()` 返回的 `execute_output` 会用于指导 `SyncState.sync_state()` 的更新。状态同步器的 `sync_state()` 方法会解析 `execute_output` 的指令，并根据指令内容触发相应的操作。
  >
  > 状态同步器 `mas.agent.state.sync_state.SyncState` 能够访问到MAS下的所有Agent和所有Task，故而所有 `Executor` 所无法影响的状态均可以通过传递 `execute_output` 指令的方式由 `SyncState` 代为执行。

  如果你实现的技能需要改变MAS系统中其他状态，请通过 `execute_output` 指导 `SyncState` 完成。

  此时你需要同步在 `mas.agent.state.sync_state` 中的 `SyncState.sync_state()` 方法中增加相应的触发判定和具体操作实现。


  一般来说 `Executor.execute()` 会使用在当前类中的 `get_execute_output()` 方法来构造 `execute_output`。其中必须构造的 `execute_output` 字段有 `execute_output["update_stage_agent_state"]` 和 `execute_output["send_shared_message"]` （见下 **2.1 执行器状态更新** 小节）。

  如果你的该技能需要影响MAS中的其他状态，则在 `Executor.get_execute_output()` 中构造新的字段即可（需同时在 `SyncState.sync_state()` 中增加对应的字段解析逻辑）。

  > 具体可用参考已有的技能实现，已有技能的 `Executor.get_execute_output()`  出于各自实现目的的需要均不相同。



#### 2.1 执行器状态更新

所有执行器必须遵从一定标准进行状态更新，这在自定义实现中需要注意。其中必须包含有：

1. 在`Executor.execute()`开始时更新step状态为 running

   ```python
   agent_state["agent_step"].update_step_status(step_id, "running")
   ```

2. 在`Executor.execute()`结束时更新step状态：

   如果执行成功则更新为 finished

   ```python
   agent_state["agent_step"].update_step_status(step_id, "finished")
   ```

   如果执行失败则更新为 failed

   ```python
   agent_state["agent_step"].update_step_status(step_id, "failed")
   ```

3. 将执行结果更新到step.execute_result中：

   ```python
   step = agent_state["agent_step"].get_step(step_id)[0]
   execute_result = {"{skill_name}": extracted_instruction}
   step.update_execute_result(execute_result)
   ```

   构造自己的执行结果 `execute_result` ，如果成功执行，一般该执行结果包含解析后的指令内容。

   如果失败，则 `execute_result` 一般为LLM原始回复：

   ```python
   execute_result = {"llm_response": response}
   ```

4. 在`Executor.execute()`结束时更新stage中agent自身状态

   一般在标准 `Executor.get_execute_output()` 实现中传入 `update_agent_situation` 为 `finished` 或 `failed` 。

   在 `Executor.get_execute_output()` 会构造完成指令以指导状态同步器：

   ```python
   execute_output["update_stage_agent_state"] = {
       "task_id": task_id,
       "stage_id": stage_id,
       "agent_id": agent_state["agent_id"],
       "state": update_agent_situation,
   }
   ```

5. 在`Executor.execute()`结束时更新执行信息

   向 Task 中共享信息池 `shared_info_pool` 中添加执行信息

   一般在标准 `Executor.get_execute_output()` 实现中传入 `shared_step_situation` 为 `finished` 或 `failed` 。

   在 `Executor.get_execute_output()` 会构造完成指令以指导状态同步器：

   ```python
   execute_output["send_shared_message"] = {
       "agent_id": agent_state["agent_id"],
       "role": agent_state["role"],
       "stage_id": stage_id,
       "content": f"执行XXX步骤:{shared_step_situation}，"
   }
   ```

