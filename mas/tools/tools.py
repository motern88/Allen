
from mas.agent.base.executor_base import Executor
from mas.agent.state.step_state import StepState

# 显式注册谷歌搜索到类型 "tool", 名称 "google_search"
@Executor.register(executor_type="tool", executor_name="google_search")
class GoogleSearchTool(Executor):
    def execute(self, step_state: StepState) -> None:
        try:
            step_state.update_execution_state("running")
            query = step_state.instruction_content.get("query", "")
            # 模拟搜索逻辑
            step_state.update_execute_result({"results": [{"title": "示例结果"}]})
            step_state.update_execution_state("finished")
        except Exception as e:
            step_state.update_execute_result({"error": str(e)})
            step_state.update_execution_state("failed")