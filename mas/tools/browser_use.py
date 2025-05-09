'''
工具名称：Browser Use
期望作用：Agent通过browser_use工具能够执行自动化的网络浏览任务，包括访问网站、提取网页内容、填写表单、点击按钮等复杂的网页交互操作。

Browser Use工具允许MAS系统直接与网络世界进行交互，扩展其信息获取和任务执行能力。工具使用底层的browser-use库，该库通过Playwright提供浏览器自动化能力，结合LLM的理解能力实现复杂网页任务的自动化完成。

具体实现:

组装提示词:
1.1 MAS系统提示词（# 一级标题）
1.2 Agent角色:（# 一级标题）
1.2.1 Agent角色背景提示词（## 二级标题）
1.2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
1.3 browser_use_task step:（# 一级标题）
1.3.1 step.step_intention 当前步骤的简要意图
1.3.2 step.text_content 具体目标
1.3.3 技能规则提示
1.4 持续性记忆:（# 一级标题）
1.4.1 Agent持续性记忆说明提示词（## 二级标题）
1.4.2 Agent持续性记忆内容提示词（## 二级标题）

LLM调用生成浏览器任务描述
2.1 调用LLM生成明确的浏览器操作任务描述
2.2 从LLM响应中提取<BROWSER_USE>标签中的内容作为任务描述

执行浏览器操作任务
3.1 初始化浏览器环境（Browser、Controller和Agent组件）
3.2 执行任务并收集结果（访问的URL、提取的内容、最终结果）
3.3 确保资源正确关闭（浏览器、playwright实例）

处理执行结果
4.1 解析执行结果并构建结果摘要
4.2 更新步骤状态与执行结果
4.3 处理可能出现的错误情况

返回用于指导状态同步的execute_output
5.1 通过update_stage_agent_state指导更新agent状态
5.2 通过send_shared_message添加步骤信息到task共享消息池

错误处理:
LLM任务生成失败：当无法从LLM响应中提取有效的浏览器任务描述时，更新步骤状态为failed
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
数据提取：从特定网站提取结构化数据
自动化测试：验证网站功能和内容的有效性
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

    def extract_browser_task(self, text: str):  
        """从文本中解析browser_use任务描述"""  
        match = re.findall(r"<BROWSER_USE>\s*(.*?)\s*</BROWSER_USE>", text, re.DOTALL)  
        if match:  
            browser_task = match[-1]  # 获取最后一个匹配内容  
            return browser_task  
        else:  
            return None  
        
    
    def get_browser_task_generation_prompt(self, step_id: str, agent_state: Dict[str, Any]) -> str:
        '''
        组装提示词
        1 MAS系统提示词（# 一级标题）
        2 Agent角色提示词:（# 一级标题）
            2.1 Agent角色背景提示词（## 二级标题）
            2.2 Agent可使用的工具与技能权限提示词（## 二级标题）
        3 browser_use_task step:（# 一级标题）
            3.1 step.step_intention 当前步骤的简要意图
            3.2 step.text_content 具体目标
            3.3 技能规则提示(browser_use_config["use_prompt"])
        4. 持续性记忆:（# 一级标题）
            4.1 Agent持续性记忆说明提示词（## 二级标题）
            4.2 Agent持续性记忆内容提示词（## 二级标题）
        '''
        md_output = []

        # 1. 获取MAS系统的基础提示词
        md_output.append("# 系统提示 system_prompt\n")
        system_prompt = self.get_base_prompt(key="system_prompt")  # 已包含 # 一级标题的md
        md_output.append(f"{system_prompt}\n")

        # 2. 组装角色提示词
        md_output.append("# Agent角色\n")
        # 角色背景
        agent_role_prompt = self.get_agent_role_prompt(agent_state)  # 不包含标题的md格式文本
        md_output.append(f"## 你的角色信息 agent_role\n"
                         f"{agent_role_prompt}\n")
        # 工具与技能权限
        available_skills_and_tools = self.get_skill_and_tool_prompt(agent_state["skills"],
                                                                    agent_state["tools"])  # 包含 # 三级标题的md
        md_output.append(f"## 角色可用技能与工具 available_skills_and_tools\n"
                         f"{available_skills_and_tools}\n")

        # 3. browser_use_task step提示词
        md_output.append(f"# 当前需要执行的步骤 current_step\n")
        current_step = self.get_current_tool_step_prompt(step_id, agent_state)  # 不包含标题的md格式文本
        md_output.append(f"{current_step}\n")

        # 4. 持续性记忆提示词
        md_output.append("# 持续性记忆 persistent_memory\n")
        # 获取persistent_memory的使用说明
        base_persistent_memory_prompt = self.get_base_prompt(key="persistent_memory_prompt")  # 不包含标题的md格式文本
        md_output.append(f"## 持续性记忆使用规则说明：\n"
                         f"{base_persistent_memory_prompt}\n")
        # persistent_memory的具体内容
        persistent_memory = self.get_persistent_memory_prompt(agent_state)  # 不包含标题的md格式文本
        md_output.append(f"## 你已有的持续性记忆内容：\n"
                         f"{persistent_memory}\n")

        return "\n".join(md_output)
        
    def execute(self, step_id: str, agent_state: Dict[str, Any]) -> Dict[str, Any]: 
        """  
        BrowserUseTool工具的具体执行方法:  
        1. 使用LLM生成浏览器任务描述  
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
            # 1. 从step_state获取指令文本-----------------已弃用
            # task_description  = step_state.text_content.strip()    

            # 1. 组装浏览器任务生成提示词  
            browser_task_prompt = self.get_browser_task_generation_prompt(step_id, agent_state)  
            print(f"浏览器操作任务生成提示词:\n{browser_task_prompt}")  

            # 2. LLM调用  
            llm_client = LLMClient(self.llm_config)  
            chat_context = LLMContext(context_size=15)  
            
            chat_context.add_message("assistant", "我将根据你的需求生成浏览器自动化任务描述。"  
                                                 "我会在<BROWSER_USE>和</BROWSER_USE>标签之间提供明确的任务描述。")  
            
            response = llm_client.call(  
                browser_task_prompt,  
                context=chat_context  
            )  
            print(f"LLM响应:\n{response}")  
            
            # 3. 提取浏览器任务描述  
            browser_task = self.extract_browser_task(response)  

            # 如果无法提取有效的任务描述  
            if not browser_task:  
                error_msg = "无法从LLM响应中提取有效的浏览器任务描述"  
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

            # 4. 使用任务描述执行browser-use操作  
            result = self.run_browser_use_task(browser_task)  

            # 5. 记录执行结果到step的execute_result  
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

            new_persistent_memory = self.extract_persistent_memory(response)
            if new_persistent_memory:  # 当有新的记忆内容时追加持续性记忆
                agent_state["persistent_memory"] += "\n" + new_persistent_memory

            # 6. 步骤状态更新为 finished  
            agent_state["agent_step"].update_step_status(step_id, "finished")  

            # 7. 构造execute_output  
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
                # 去掉 /api 部分  
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

    # 创建一个简单的浏览器任务  
    browser_task_step = StepState(  
        task_id="task_001",  
        stage_id="stage_001",  
        agent_id="0001",  
        step_intention="搜索Python相关信息",  
        step_type="tool",  
        executor="browser_use",  
        text_content="请访问Python官网(https://www.python.org)，提取首页的主要新闻内容和Python的最新版本号。",  
        execute_result={},  
    )  

    # 添加步骤到agent_state  
    agent_state["agent_step"].add_step(browser_task_step)  
    step_id = agent_state["agent_step"].step_list[0].step_id  # 获取步骤ID  

    # 创建工具实例  
    print("初始化BrowserUseTool...")  
    browser_tool = BrowserUseTool(llm_config)  
    
    print("执行浏览器任务...")  
    result = browser_tool.execute(step_id, agent_state)  
    
    print("\n==== 执行结果 ====")  
    print(f"状态: {agent_state['agent_step'].get_step(step_id)[0].execution_state}")  
    print("\n==== 执行输出 ====")  
    for key, value in result.items():  
        print(f"{key}: {value}")  
    
    # 显示执行结果详情  
    execute_result = agent_state["agent_step"].get_step(step_id)[0].execute_result  
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