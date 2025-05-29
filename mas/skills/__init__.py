import os
import importlib

# 自动导入当前目录下的所有技能模块，确保所有技能触发向executor注册
def auto_import_skills():
    current_dir = os.path.dirname(__file__)
    for filename in os.listdir(current_dir):
        if filename.endswith(".py") and filename != "__init__.py":
            module_name = f"mas.skills.{filename[:-3]}"
            importlib.import_module(module_name)

# 在模块导入时自动触发
auto_import_skills()