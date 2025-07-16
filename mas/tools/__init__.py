import os
import importlib

# 自动导入当前目录下的所有工具模块，确保所有工具触发向executor注册
def auto_import_tools():
    current_dir = os.path.dirname(__file__)
    target_files = {"mcp_tool.py"}  # 与Skill不同Tool模块只需要导入mcp_tool，说有的tool均以mcp_tool的executor执行

    for filename in os.listdir(current_dir):
        if filename in target_files:
            module_name = f"mas.tools.{filename[:-3]}"
            importlib.import_module(module_name)

# 在模块导入时自动触发
auto_import_tools()