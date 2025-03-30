
from mas.agent.base.executor_base import Executor
from mas.agent.state.step_state import StepState

# 注册规划技能到类型 "skill", 名称 "planning"
@Executor.register(executor_type="skill", executor_name="planning")
class PlanningSkill(Executor):
    def execute(self, step_state: StepState) -> None:
        try:
            # TODO:待完善规划过程，后续可通过配置文件的方式读取提示词等
            step_state.update_execution_state("running")
            # 示例：生成规划文本
            prompt = f"规划目标：{step_state.text_content}"
            step_state.update_execute_result({"plan": "1. 分析需求\n2. 制定步骤"})
            step_state.update_execution_state("finished")
        except Exception as e:
            step_state.update_execute_result({"error": str(e)})
            step_state.update_execution_state("failed")


# 注册反思技能到类型 "skill", 名称 "reflection"
@Executor.register(executor_type="skill", executor_name="reflection")
class ReflectionSkill(Executor):
    def execute(self, step_state: StepState) -> None:
        try:
            # TODO: 待完善反思过程
            step_state.update_execution_state("running")
            step_state.update_execute_result({"insight": "任务执行顺利"})
            step_state.update_execution_state("finished")
        except Exception as e:
            step_state.update_execute_result({"error": str(e)})
            step_state.update_execution_state("failed")