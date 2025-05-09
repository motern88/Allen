'''
工具名称：Browser Use
期望作用：Agent通过browser_use工具能够执行自动化的网络浏览任务，包括访问网站、提取网页内容、填写表单、点击按钮等复杂的网页交互操作。

Browser Use工具允许MAS系统直接与网络世界进行交互，扩展其信息获取和任务执行能力。工具使用底层的browser-use库，该库通过Playwright提供浏览器自动化能力，结合LLM的理解能力实现复杂网页任务的自动化完成。

具体实现:

从步骤状态获取指令:
1.1 从step_state.instruction_content获取由instruction_generation技能生成的浏览器操作指令
1.2 尝试提取指令生成中提取到的任务描述

执行浏览器操作任务:
2.1 根据LLM配置初始化兼容的LLM (OpenAI或Ollama)
2.2 设置浏览器环境配置(Browser、Controller)
2.3 创建并运行browser-use 第三方Agent执行任务，限制最大步骤数为100
2.4 确保资源正确关闭(浏览器、playwright实例)

处理执行结果:
3.1 提取任务执行的最终结果(final_result)
3.2 记录访问的URL列表(urls_visited)和提取的内容数量(content_count)
3.3 构建结果摘要用于状态更新

更新步骤状态:
4.1 成功执行时将步骤状态更新为finished
4.2 失败时将步骤状态更新为failed并记录错误信息

返回用于指导状态同步的execute_output:
5.1 通过update_stage_agent_state指导更新agent状态为working
5.2 通过send_shared_message添加步骤执行结果到task共享消息池

错误处理:
指令完全为空: 更新步骤状态为failed并返回错误信息
浏览器操作失败：捕获并记录详细的异常信息，更新步骤状态为failed
LLM配置缺失：检查是否有可用的LLM配置，不存在则报错并更新状态

浏览器任务结果包含:
final_result: 任务执行的最终结果文本
urls_visited: 访问过的网页URL列表
extracted_content: 从网页中提取的内容列表
content_count: 提取内容的数量统计

适用场景:
网络信息采集：从多个网站收集特定信息
自动化表单填写：完成注册、申请等需要填写表单的任务
市场调研：收集产品信息、价格比较等
自动化测试：验证网站功能和内容的有效性
预约和订购: 自动化完成在线预约和订购流程

注意事项:
必须由instruction_generation技能先生成明确的浏览器操作指令
指令应详细描述所需的浏览任务，包括目标网站、操作步骤和期望结果
默认以非无头模式运行浏览器(headless=False)，便于观察和调试
操作过程中的截图会保存到screenshots目录
'''

from typing import Any, Dict
from mas.agent.base.executor_base import Executor 
import os
import asyncio  
from mas.agent.configs.llm_config import LLMConfig
from mas.agent.base.llm_base import LLMClient, LLMContext 
from browser_use import Agent, Controller  
from browser_use.browser.browser import Browser, BrowserConfig  
import traceback 
import re

@Executor.register(executor_type="tool", executor_name="browser_use")  
class BrowserUseTool(Executor):  
    def __init__(self, llm_config=None):  
        super().__init__()  
        self.llm_config = llm_config 
        # 创建存储截图的目录  
        os.makedirs("screenshots", exist_ok=True)
        
    def execute(self, step_id: str, agent_state: Dict[str, Any]) -> Dict[str, Any]: 
        """  
        BrowserUseTool工具的具体执行方法:  
        1. 从step_state获取指令文本
        2. 提取浏览器任务描述  
        3. 执行browser-use任务  
        4. 解析结果并更新执行结果  
        5. 构造并返回execute_output   
        """  
        # 更新步骤状态为运行中 
        agent_state["agent_step"].update_step_status(step_id, "running")  
        # 获取当前步骤状态
        step_state = agent_state["agent_step"].get_step(step_id)[0]  

        # 如果没有传入llm_config，就从agent_state获取  
        if self.llm_config is None and "llm_config" in agent_state:  
            self.llm_config = agent_state["llm_config"]  

        # 检查是否有可用的LLM配置  
        if self.llm_config is None:  
            error_msg = "缺少LLM配置，无法执行浏览器任务"  
            agent_state["agent_step"].update_step_status(step_id, "failed")  
            return self.get_execute_output(  
                step_id,   
                agent_state,   
                update_agent_situation="failed",  
                shared_step_situation="failed: 缺少LLM配置",  
            )

        try:
            # 1. 从step_state获取指令文本
            task_description  = step_state.instruction_content.strip()
            print(f"从step_state获取的原始指令文本:\n{task_description}")

            # 2. 提取浏览器任务描述   
            browser_task = self.extract_browser_task(task_description)
            print(f"浏览器操作任务描述:\n{browser_task}")    

            # 如果无法提取有效的任务描述  
            if not browser_task:  
                # 如果没有找到标签包裹的任务，尝试使用整个文本作为任务
                browser_task = task_description
                # 如果任务描述仍然为空，则报错
                if not browser_task:
                    error_msg = "无法从指令中提取有效的浏览器任务描述"  
                    agent_state["agent_step"].update_step_status(step_id, "failed")  
                    # 记录错误并返回  
                    execute_result = {"browser_use_error": error_msg}  
                    step_state.update_execute_result(execute_result)  
                    return self.get_execute_output(  
                        step_id,  
                        agent_state,  
                        update_agent_situation="failed",  
                        shared_step_situation=f"失败: {error_msg}",  
                    )  
                
            # 3. 使用任务描述执行browser-use操作  
            result = self.run_browser_use_task(browser_task)  

            # 4. 记录执行结果到step的execute_result  
            execute_result = {  
                "browser_use_result": {  
                    "final_result": result.get("final_result", ""),  
                    "urls_visited": result.get("urls", []),  
                    "content_count": len(result.get("extracted_content", [])),  
                }  
            }  
            step_state.update_execute_result(execute_result)  

            # 构建摘要信息用于状态更新  
            summary = self._build_result_summary(result)   

            # 5. 步骤状态更新为 finished  
            agent_state["agent_step"].update_step_status(step_id, "finished")  

            # 6. 构造execute_output  
            execute_output = self.get_execute_output(  
                step_id,  
                agent_state,  
                update_agent_situation="working", 
                shared_step_situation=f"完成: {summary}",  
            )  
            
            return execute_output  
        
        except Exception as e:  
            # 获取详细的错误信息  
            error_details = traceback.format_exc()  
            agent_state["agent_step"].update_step_status(step_id, "failed")  
            error_msg = f"浏览器操作失败: {str(e)}"    
            print(f"BrowserUseTool错误: {error_details}")  

            # 记录错误到执行结果  
            execute_result = {  
                "browser_use_error": error_msg  
            }  
            step_state.update_execute_result(execute_result)  
            
            # 构造并返回错误状态的execute_output  
            return self.get_execute_output(  
                step_id,  
                agent_state,  
                update_agent_situation="failed",  
                shared_step_situation=f"失败: {error_msg[:100]}",  
            )  

    def get_execute_output(  
        self,  
        step_id: str,  
        agent_state: Dict[str, Any],  
        update_agent_situation: str,  
        shared_step_situation: str,  
    ) -> Dict[str, Any]:  
        '''  
        构造BrowserUseTool工具的execute_output。  
        1. update_agent_situation:  
            通过update_stage_agent_state字段指导sync_state更新stage_state.every_agent_state中自己的状态  
            (一般情况下，只有Summary技能完成时，该字段传入finished，其他步骤完成时，该字段都传入working)  
        2. shared_step_situation:  
            添加步骤信息到task共享消息池  
        '''  
        execute_output = {}  

        # 1. 通过update_stage_agent_state字段指导sync_state更新stage_state.every_agent_state中自己的状态  
        # 获取当前步骤的task_id与stage_id  
        step_state = agent_state["agent_step"].get_step(step_id)[0]  
        task_id = step_state.task_id  
        stage_id = step_state.stage_id  
        # 构造execute_output  
        execute_output["update_stage_agent_state"] = {  
            "task_id": task_id,  
            "stage_id": stage_id,  
            "agent_id": agent_state["agent_id"],  
            "state": update_agent_situation,  
        }  

        # 2. 添加步骤信息到task共享消息池  
        execute_output["send_shared_message"] = {  
            "agent_id": agent_state["agent_id"],  
            "role": agent_state["role"],  
            "stage_id": stage_id,  
            "content": f"执行browser_use步骤: {shared_step_situation}"  
        }  
        return execute_output  

    def _build_result_summary(self, result: Dict[str, Any]) -> str:  
        """构建结果摘要"""  
        if "urls" in result:  
            urls_visited = result.get("urls", [])  
            content_count = len(result.get("extracted_content", []))  
            
            summary = f"访问了{len(urls_visited)}个网页，提取了{content_count}项内容"  
            if urls_visited:  
                summary += f"，包括网站：{', '.join(urls_visited[:2])}"  
                if len(urls_visited) > 2:  
                    summary += f"等{len(urls_visited)}个站点"  
        else:  
            summary = "完成浏览器操作"  
            if result.get("final_result"):  
                final_result = result.get("final_result", "")  
                if len(final_result) > 100:  
                    summary += f": {final_result[:100]}..."  
                else:  
                    summary += f": {final_result}"  
        
        return summary  
    
    def run_browser_use_task(self, task_description: str) -> Dict[str, Any]:  
        """  
        使用browser-use库执行高级任务  
        """  
        # 1. 使用LLMConfig获取LLM    
        llm = self._get_llm(self.llm_config)  

        # 在异步上下文中创建资源 
        async def main():  
            # 2. 设置browser-use组件  
            browser_config = BrowserConfig(
            headless=False, # 设置为False可以显示浏览器窗口，便于调试  
            viewport_size={"width": 1280, "height": 800}  
            )  
            browser = Browser(config=browser_config)  
            controller = Controller()  

            try:
                agent = Agent(  
                    task=task_description,  
                    llm=llm,  
                    browser=browser,  
                    controller=controller,  
                    generate_gif=False,  
                    enable_memory=False  
                )  
                result = await agent.run(max_steps=100)  
                return {  
                    "final_result": result.final_result(),  
                    "extracted_content": result.extracted_content(),  
                    "urls": result.urls(),  
                    "browser_use_result": result  
                } 
            finally:
                # 在异步上下文中正确关闭资源  
                # 关闭浏览器  
                if hasattr(browser, 'close') and callable(browser.close):  
                    if asyncio.iscoroutinefunction(browser.close):  
                        await browser.close()  
                    else:  
                        browser.close()  
                        
                # 获取并关闭playwright实例  
                if hasattr(browser, '_browser') and hasattr(browser._browser, '_playwright'):  
                    playwright = browser._browser._playwright  
                    if hasattr(playwright, 'stop') and callable(playwright.stop):  
                        if asyncio.iscoroutinefunction(playwright.stop):  
                            await playwright.stop()  
                        else:  
                            playwright.stop()  
        return asyncio.run(main())     


    def _get_llm(self, llm_config: LLMConfig):  
        """  
        创建LangChain兼容的LLM
        """  
        if llm_config is None:  
            raise ValueError("LLM配置不能为空")  
        try:
            # 获取配置参数  
            api_type = llm_config.api_type  
            api_type_str = api_type.lower() if isinstance(api_type, str) else str(api_type).lower() 
            model = llm_config.model  
            api_key = llm_config.api_key 
            base_url = llm_config.base_url  
            temperature = llm_config.temperature 
            # 处理不同的LLM类型  
            if "openai" in api_type_str:  
                from langchain_openai import ChatOpenAI  
                
                params = {  
                    "model": model or "gpt-3.5-turbo",  
                    "temperature": temperature,  
                    "api_key": api_key  
                }  
                return ChatOpenAI(**params)  
            elif "ollama" in api_type_str or "local" in api_type_str:  
                from langchain_ollama import ChatOllama  
                # 去掉 /api 部分，不然会报错
                if base_url.endswith("/api"):  
                    base_url = base_url[:-len("/api")]  
                params = {  
                    "base_url": base_url,  
                    "model": model,  
                    "temperature": temperature,  
                    "num_ctx": 32000  
                }  
                return ChatOllama(**params)
        except ImportError as e:  
            # 如果缺少依赖，提供有用的错误消息  
            if "langchain_openai" in str(e):  
                raise ImportError("使用OpenAI需要安装: pip install langchain_openai")  
            elif "langchain_ollama" in str(e):  
                raise ImportError("使用Ollama需要安装: pip install langchain_ollama")  
            else:  
                raise ImportError(f"LLM初始化失败: {e}")  
            
# Debug
if __name__ == "__main__":
    '''
    测试browser use需在Allen根目录下执行 python -m mas.tools.browser_use
    '''
    from mas.agent.configs.llm_config import LLMConfig
    from mas.agent.state.step_state import StepState, AgentStep
    from mas.skills.Instruction_generation import InstructionGenerationSkill

    print("测试BrowserUseTool工具的调用")  
    llm_config = LLMConfig.from_yaml("mas/role_config/qwen235b.yaml")
    agent_state = {  
        "agent_id": "0001",  
        "name": "网络助手",  
        "role": "网络调研专员",  
        "profile": "负责在网络上搜集信息，提取网页内容，完成各种网络任务",  
        "working_state": "idle",  
        "llm_config": llm_config,  
        "working_memory": {},  
        "persistent_memory": "我是一个网络调研专员，帮助用户完成网络任务。",  
        "agent_step": AgentStep("0001"),  
        "skills": ["planning", "reflection", "summary", "instruction_generation"],  
        "tools": ["browser_use"],  
    }  
    # 由于tool需要依赖instruction_generation这个Skill生成指令，所以这里需要构造一个类型为skill的StepState
    step0 = StepState(
        task_id="task_001",
        stage_id="stage_001",
        agent_id="0001",
        step_intention="为浏览器操作工具生成指令",
        step_type="skill",
        executor="instruction_generation",
        text_content="需要访问Python官网(https://www.python.org)，提取首页的主要新闻内容和Python的最新版本号。",
        execute_result={},
    )

    # 创建一个简单的浏览器任务  
    browser_task_step = StepState(  
        task_id="task_001",  
        stage_id="stage_001",  
        agent_id="0001",  
        step_intention="搜索Python相关信息",  
        step_type="tool",  
        executor="browser_use",  
        text_content="",
        execute_result={},  
    )  

    # 添加步骤到agent_state  
    agent_state["agent_step"].add_step(step0)
    agent_state["agent_step"].add_step(browser_task_step)  

    instuct_step_id = agent_state["agent_step"].step_list[0].step_id  # 指令生成为第0个step  
    browser_task_step_id = agent_state["agent_step"].step_list[1].step_id  # 浏览器操作为第1个step
    instruction_generation_skill = InstructionGenerationSkill()
    gen_result = instruction_generation_skill.execute(instuct_step_id, agent_state)

    print("指令生成结果:", gen_result)  # 打印指令生成结果
        # 检查生成的指令格式  
    if gen_result.get("update_stage_agent_state", {}).get("state") == "failed":  
        print("失败原因追踪:")  
        print("LLM响应内容:", agent_state["agent_step"].step_list[0].execute_result.get("raw_response"))  
        print("提取的指令:", agent_state["agent_step"].step_list[0].execute_result.get("instruction_generation"))  

    # 验证指令生成结果  
    if gen_result.get("update_stage_agent_state", {}).get("state") == "finished":  
        # 获取生成的浏览器操作指令
        store_instruction = agent_state["agent_step"].step_list[1].instruction_content  
        store_step_id = agent_state["agent_step"].step_list[1].step_id
        print(f"生成的浏览器操作指令: {store_instruction}，浏览器操作步骤ID: {store_step_id}")  

    # 创建工具实例  
    print("初始化BrowserUseTool...")  
    browser_tool = BrowserUseTool(llm_config)  
    
    print("执行浏览器任务...")  
    result = browser_tool.execute(browser_task_step_id, agent_state)  
    
    print("\n==== 执行结果 ====")  
    print(f"状态: {agent_state['agent_step'].get_step(browser_task_step_id)[0].execution_state}")  
    print("\n==== 执行输出 ====")  
    for key, value in result.items():  
        print(f"{key}: {value}")  
    
    # 显示执行结果详情  
    execute_result = agent_state["agent_step"].get_step(browser_task_step_id)[0].execute_result  
    print("\n==== 详细结果 ====")  
    if execute_result:  
        if "browser_use_result" in execute_result:  
            print("浏览器结果摘要:")  
            browser_result = execute_result["browser_use_result"]  
            
            # 显示访问的URL  
            if "urls_visited" in browser_result and browser_result["urls_visited"]:  
                print(f"访问的网站: {', '.join(browser_result['urls_visited'])}")  
            
            # 显示提取的内容数量  
            if "content_count" in browser_result:  
                print(f"提取的内容项数: {browser_result['content_count']}")  
            
            # 显示最终结果  
            if "final_result" in browser_result and browser_result["final_result"]:  
                print(f"最终结果: {browser_result['final_result'][:200]}")  
                if len(browser_result["final_result"]) > 200:  
                    print("...")  
        
        # 如果存在错误  
        if "browser_use_error" in execute_result:  
            print(f"错误信息: {execute_result['browser_use_error']}")  
    else:  
        print("没有执行结果")  

    # 打印所有步骤信息  
    print("\n==== 所有步骤信息 ====")  
    agent_state["agent_step"].print_all_steps()  