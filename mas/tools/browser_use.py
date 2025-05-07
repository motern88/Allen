from typing import Any, Dict, Optional, List
from mas.agent.base.executor_base import Executor 
from playwright.sync_api import sync_playwright
import json 
import re 
import os
import time

@Executor.register(executor_type="tool", executor_name="BrowserUseTool")  
class BrowserUseTool(Executor):  
    def __init__(self):  
        super().__init__()  
        self.playwright = None  
        self.browser = None  
        self.context = None  
        self.page = None  
        # 创建存储截图的目录  
        os.makedirs("screenshots", exist_ok=True)  

    def execute(self, step_id: str, agent_state: Dict[str, Any]) -> Dict[str, Any]: 
        """执行浏览器自动化任务"""  
        agent_step = agent_state["agent_step"]  
        agent_step.update_step_status(step_id, "running")  

        execute_output = {}  
        task_id = step_state.task_id
        stage_id = step_state.stage_id
        agent_id = agent_state.get("agent_id", "unknown")  
        role = agent_state.get("role", "unknown") 

        try:
             # 1. 从step_state获取指令文本  
            step_state = agent_state["agent_step"].get_step(step_id)[0]  
            # step_state.text_content 是本步骤为该技能准备的执行文本（含LLM生成的带<BROWSER_USE>标签的内容）  
            instruction = step_state.text_content  

            # 2. 解析指令获取浏览器操作列表  
            actions = self.extract_browser_use_step(instruction)  
            result = self.run_browser_actions(actions)  

             # 4. 更新步骤状态为完成  
            agent_step.update_step_status(step_id, "finished")  
            execute_output["result"] = result  

                        # 5. a. 构建结果摘要用于状态更新和消息分享  
            urls_visited = [act.get("url") for act in actions if act.get("type") == "goto" and "url" in act]  
            content_count = len(result.get("extracted_content", []))  
            
            summary = f"访问了{len(urls_visited)}个网页，提取了{content_count}项内容"  
            if urls_visited:  
                summary += f"，包括网站：{', '.join(urls_visited[:2])}"  
                if len(urls_visited) > 2:  
                    summary += f"等{len(urls_visited)}个站点"  
            
            # 5. b. 如果有截图，添加到摘要中  
            screenshot_count = len(result.get("screenshots", []))  
            if screenshot_count > 0:  
                summary += f"，保存了{screenshot_count}张截图"  
            
            # 6. 更新Agent状态  
            execute_output["update_stage_agent_state"] = {  
                "task_id": task_id,  
                "stage_id": stage_id,  
                "agent_id": agent_id,  
                "state": f"完成浏览器操作: {summary}"  
            }  
            
            # 7. 发送共享消息  
            execute_output["send_shared_message"] = {  
                "agent_id": agent_id,  
                "role": role,  
                "stage_id": stage_id,  
                "content": f"执行browser_use步骤: {summary}"  
            }  
            
            return execute_output  
        
        except Exception as e:  
            # 处理执行失败的情况  
            agent_step.update_step_status(step_id, "failed")  
            error_msg = f"浏览器操作失败: {str(e)}"  
            execute_output["error"] = error_msg  
            
            # 更新失败状态和共享消息  
            execute_output["update_stage_agent_state"] = {  
                "task_id": task_id,  
                "stage_id": stage_id,  
                "agent_id": agent_id,  
                "state": error_msg  
            }  
            
            execute_output["send_shared_message"] = {  
                "agent_id": agent_id,  
                "role": role,  
                "stage_id": stage_id,  
                "content": f"执行browser_use步骤失败: {error_msg}"  
            }  
            return execute_output  
        finally:
            # 确保资源被正确释放 
            self._close_browser()


    def extract_browser_use_step(self, text: str) -> List[Dict[str, Any]]:
        """从指令文本中解析浏览器操作序列"""  
        match = re.search(r"<BROWSER_USE>(.*?)</BROWSER_USE>", text, re.S)  
        if not match:  
            
            raise ValueError("未找到有效 browser_use 指令")  
        try:  
            json_text = match.group(1).strip()  
            actions_data = json.loads(json_text)  
            
            # 支持两种格式：直接的actions列表或包含actions键的对象  
            if isinstance(actions_data, list):  
                return actions_data  
            elif isinstance(actions_data, dict) and "actions" in actions_data:  
                return actions_data["actions"]  
            else:  
                raise ValueError("无效的actions格式，应为列表或包含actions键的对象")  
        except json.JSONDecodeError as e:  
            raise ValueError(f"指令中的JSON格式无效: {str(e)}\n原始JSON: {match.group(1)}")  
        
    def run_browser_actions(self, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """执行浏览器操作序列并返回结果"""  

        result = {  
            "extracted_content": [],  
            "screenshots": []  
        }  

        try:  
            # 设置浏览器  
            self.playwright = sync_playwright().start()  
            self.browser = self.playwright.chromium.launch(headless=True)  
            self.context = self.browser.new_context()  
            self.page = self.context.new_page()  
            
            for action in actions:  
                action_type = action.get("type", "")  
                
                if action_type == "goto":  
                    self._goto_url(action.get("url", ""))  
                
                elif action_type == "click":  
                    self._click_element(action.get("selector", ""), action.get("text", None))  
                
                elif action_type == "fill":  
                    self._fill_form(action.get("selector", ""), action.get("value", ""))  
                
                elif action_type == "extract_content":  
                    content = self._extract_content(action.get("selector", ""))  
                    result["extracted_content"].append({  
                        "content": content,  
                        "selector": action.get("selector", ""),  
                        "url": self.page.url if self.page else ""  
                    })  
                
                elif action_type == "wait_for":  
                    self._wait_for(  
                        action.get("selector", ""),   
                        action.get("timeout", 30000)  
                    )  
                
                elif action_type == "screenshot":  
                    screenshot_path = self._take_screenshot(action.get("name", "screenshot"))  
                    result["screenshots"].append(screenshot_path)  
                
                elif action_type == "wait":  
                    time.sleep(action.get("seconds", 1))  
                
                # 可以添加其他操作类型  
                else:  
                    print(f"警告: 未知的操作类型 '{action_type}'")  
                
            return result  
        except Exception as e:
            # 捕获并记录详细错误
            import traceback
            error_details = traceback.format_exc()
            print(f"浏览器操作错误: {error_details}")  
            raise  
        finally:
            self._close_browser()  # 确保浏览器在操作完成后关闭

    def _close_browser(self):
        """关闭浏览器和Playwright实例"""  
        try:
            if self.page:  
                self.page.close()  
                self.page = None  
            
            if self.context:  
                self.context.close()  
                self.context = None  
            
            if self.browser:  
                self.browser.close()  
                self.browser = None  
                
            if self.playwright:  
                self.playwright.stop()  
                self.playwright = None  

        except Exception as e:
            print(f"关闭浏览器时发生错误: {str(e)}")

    def _goto_url(self, url: str):  
        """访问指定URL"""  
        if not url:  
            raise ValueError("URL不能为空")  
        
        # 确保URL格式正确  
        if not url.startswith(("http://", "https://")):  
            url = "https://" + url  
            
        self.page.goto(url, wait_until="domcontentloaded")  
        # 给页面一点加载时间  
        self.page.wait_for_load_state("networkidle")  

    
    def _click_element(self, selector: str, text: Optional[str] = None):  
        """点击元素"""  
        try:  
            if text:  
                # 如果提供了文本，寻找包含该文本的元素  
                locator = self.page.get_by_text(text)  
                if selector:  
                    locator = self.page.locator(selector).filter(has_text=text)  
                locator.click()  
            else:  
                self.page.click(selector)  
        except Exception as e:  
            raise ValueError(f"点击元素失败: {selector} {text if text else ''}, 错误: {str(e)}")  
        
    def _fill_form(self, selector: str, value: str):  
        """填写表单"""  
        try:  
            self.page.fill(selector, value)  
        except Exception as e:  
            raise ValueError(f"填写表单失败: {selector}, 错误: {str(e)}")  

    def _extract_content(self, selector: str) -> str:  
        """提取内容"""  
        try:  
            if not selector:  
                # 如果没有指定选择器，提取页面全部文本  
                return self.page.content()  
            
            elements = self.page.query_selector_all(selector)  
            content = []  
            for element in elements:  
                text = element.inner_text()  
                if text:  
                    content.append(text)  
            
            return "\n".join(content)  
        except Exception as e:  
            raise ValueError(f"提取内容失败: {selector}, 错误: {str(e)}")  
        
    def _take_screenshot(self, name: str = "screenshot") -> str:  
        """截图并保存"""  
        from datetime import datetime  
        
        # 生成带时间戳的文件名  
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")  
        filename = f"screenshots/{name}_{timestamp}.png"  
        
        # 保存截图  
        try:  
            self.page.screenshot(path=filename)  
            return filename  
        except Exception as e:  
            raise ValueError(f"截图失败: {name}, 错误: {str(e)}")  