'''
实现状态监控可视化，该脚本实现状态推送服务

技术方案：
| 后端   | Flask + `StateMonitor`
| 推送   | Flask + WebSocket (建议用 `flask-socketio`)
| 前端   | 可用简单的 HTML + JavaScript，或 Vue/React
| 后台线程 | `threading.Timer` 或 `while True + sleep` 周期推送

实现结构：
├── web/
│   ├── server.py         # Flask + SocketIO 服务端
│   └── templates/
│       └── index.html    # 前端界面

实现后端接口：
GET /api/states?type=task
GET /api/states?type=stage
GET /api/states?type=agent
GET /api/states?type=step

接口返回格式：
{
    "StateID_1": { "task_id": "...", "task_name": "...", ... },
    "StateID_2": { ... },
    ...
}
'''
# 引入 Flask 框架核心模块：Flask 用于搭建 Web 服务，render_template 渲染前端页面，request 获取请求参数，jsonify 返回 JSON 格式数据
from flask import Flask, render_template, request, jsonify
# 引入 SocketIO 支持，用于实现 WebSocket 推送功能
from flask_socketio import SocketIO
from typing import Dict
import threading
import time
import json

from mas.utils.monitor import StateMonitor

app = Flask(__name__)  # 创建 Flask 实例
socketio = SocketIO(app)  # 将 Flask 实例封装为支持 WebSocket 的 SocketIO 实例
monitor = StateMonitor()  # 实例化状态监控器，通常为单例对象


# 根路径，返回前端页面
@app.route('/')
def index():
    return render_template('index.html')  # 渲染 web/templates/index.html 文件

# 定义一个循环任务，用于周期性推送状态数据
def push_state_loop():
    while True:
        # 从状态监控器中获取所有状态数据
        states = monitor.get_all_states()
        socketio.emit('state_update', states)  # 广播名为 'state_update' 的事件
        time.sleep(2)  # 每 2 秒推送一次

# 启动状态监控服务，包括后端 HTTP 和 WebSocket 以及状态推送线程
def start_monitor_web():
    # 启动后台线程，负责状态数据的周期推送
    threading.Thread(target=push_state_loop, daemon=True).start()
    # 启动 Flask + SocketIO 服务，监听 5000 端口
    socketio.run(app, host='0.0.0.0', port=5000)

# 实现 REST API：GET /api/states?type=xxx
@app.route("/api/states", methods=['GET'])
def get_states():
    """
    假设状态类在注册时，state_id 是以 TaskState_...、AgentState_... 开头的

    实现统一接口，支持按类型筛选返回状态数据：
    - GET /api/states?type=task
    - GET /api/states?type=stage
    - GET /api/states?type=agent
    - GET /api/states?type=step

    返回以下格式：
    {
        "StateID_1": { "task_id": "...", "task_name": "...", ... },
        "StateID_2": { ... },
        ...
    }
    """
    # 获取 URL 参数 type（期望是 task / stage / agent / step）
    state_type = request.args.get("type", "").strip().lower()
    if state_type not in ("task", "stage", "agent", "step"):
        return jsonify({"error": f"Unsupported type '{state_type}'"}), 400

    # 统一获取全部状态（统一结构：{state_id: 内容dict}）
    all_states: Dict[str, dict] = monitor.get_all_states()
    # print("[DEBUG] all state ids:", list(all_states.keys()))  # Debug: 打印所有状态 ID
    # print("[DEBUG] all state ", all_states)

    # 过滤匹配类型:通过状态 ID 前缀匹配（如 TaskState_）
    result = {}
    for state_id, state_dict in all_states.items():
        if state_id.lower().startswith(f"{state_type}"):
            result[state_id] = state_dict
        # 增加HumanAgent筛选逻辑
        if state_type == "agent" and state_id.lower().startswith(f"human"):
            result[state_id] = state_dict

    # 返回 JSON 格式的结果
    return result



