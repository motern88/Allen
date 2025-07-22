'''
该脚本基于端口 5000 实现：

实现结构：
├── web/
│   ├── server.py         # Flask + SocketIO 服务端
│   └── templates/
│       ├── index.html    # 前端界面
│       └── assets/       # 静态资源（CSS/JS）
│           ├── index-xxxx.js
│           └── index-xxxx.css

1. 状态监控可视化服务
    技术方案：
        | 后端   | Flask + `StateMonitor`
        | 推送   | Flask + WebSocket (建议用 `flask-socketio`)
        | 前端   | 可用简单的 HTML + JavaScript，或 Vue/React
        | 后台线程 | `threading.Timer` 或 `while True + sleep` 周期推送

    实现接口：
        GET /api/states?type=task
        GET /api/states?type=stage
        GET /api/states?type=agent
        GET /api/states?type=step
        GET /api/state/<state_id>    # 查询指定状态 ID 的详情

    接口返回格式：
        {
            "StateID_1": { "task_id": "...", "task_name": "...", ... },
            "StateID_2": { ... },
            ...
        }

2. 人类操作端 Agent 服务

    实现接口：
        POST /api/send_message       # 人类操作端发送消息
        POST /api/bind_human_agent   # 人类操作端登录

'''
# 引入 Flask 框架核心模块：Flask 用于搭建 Web 服务，render_template 渲染前端页面，request 获取请求参数，jsonify 返回 JSON 格式数据
from flask import Flask, render_template, request, jsonify, send_from_directory
# 引入 SocketIO 支持，用于实现 WebSocket 推送功能
from flask_socketio import SocketIO
from typing import Dict
import threading
import time

from mas.utils.monitor import StateMonitor
from mas.agent.human_agent import HumanAgent

app = Flask(__name__, static_folder="templates", static_url_path="")  # 创建 Flask 实例
socketio = SocketIO(app)  # 将 Flask 实例封装为支持 WebSocket 的 SocketIO 实例
monitor = StateMonitor()  # 实例化状态监控器，通常为单例对象

# 全局变量，用于存储MAS实例的引用
_mas_instance = None

def register_mas_instance(mas_instance):
    """
    注册MAS实例的引用，这个函数会在MAS初始化时被调用
    我们实现人类操作端接口时需要能够直接操作MAS中的HumanAgent实例，因此需要这里注册引用
    """
    global _mas_instance
    _mas_instance = mas_instance
    print("[server] MAS实例已注册到人类操作端接口")

# ===================== 监控服务路由 =====================
# 根路径，返回前端页面
@app.route('/')
def index():
    return render_template('index.html')  # 渲染 web/templates/index.html 文件

@app.route('/assets/<path:filename>')
def serve_assets(filename):
    return send_from_directory('templates/assets', filename)

@app.route('/favicon.ico')
def favicon():
    return send_from_directory('templates', 'favicon.ico')

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

# 实现指定 ID 的状态详情查询接口
@app.route("/api/state/<state_id>", methods=['GET'])
def get_state_detail(state_id):
    """
    查询指定 ID 的状态详情（不校验类型）

    示例：
    - GET /api/state/TaskState_123d352a5d5
    - GET /api/state/AgentState_4f14f41a2k4

    返回：
    {
        "StateID_1": { "task_id": "...", "task_name": "...", ... }
    }
    """
    all_states: Dict[str, dict] = monitor.get_all_states()

    if state_id not in all_states:
        return jsonify({"error": f"State ID '{state_id}' not found"}), 404

    return jsonify({
        state_id: all_states[state_id]
    })

# ===================== 人类操作端路由 =====================

@app.route("/api/send_private_message", methods=['POST'])
def human_send_private_message():
    """
    API接口，用于调用HumanAgent的send_message方法发送消息（在私聊中发送消息）

    请求参数(JSON):
    {
        "human_agent_id": "人类操作员ID",  # 这个ID是uuid.uuid4()的agent_id,而不是监控器中带"HumanAgent_"前缀的ID
        "task_id": "任务ID",
        "receiver": ["接收者ID1", "接收者ID2", ...],
        "content": "消息内容",
        "stage_relative": "相关阶段ID", // 可选，默认为"no_relative"
        "need_reply": true,  // 可选，默认为true
        "waiting": true      // 可选，默认为false
    }

    返回:
    {
        "success": true,
        "message": "消息已发送"
    }
    """
    try:
        # 获取请求中的JSON数据
        data = request.json

        # 必需参数验证
        required_fields = ["human_agent_id", "task_id", "receiver", "content"]
        for field in required_fields:
            if field not in data:
                return jsonify({"success": False, "message": f"缺少必需参数: {field}"}), 400

        # 检查MAS实例是否已注册
        if _mas_instance is None:
            return jsonify({"success": False, "message": "MAS实例未注册"}), 500

        # 获取HumanAgent实例
        human_agent = _mas_instance.get_agent_from_id(data["human_agent_id"])
        if not human_agent or not isinstance(human_agent, HumanAgent):
            return jsonify({"success": False, "message": "找不到指定的HumanAgent"}), 404

        # 准备参数
        task_id = data["task_id"]
        receiver = data["receiver"]
        content = data["content"]
        stage_relative = data.get("stage_relative", "no_relative")
        need_reply = data.get("need_reply", True)
        waiting = data.get("waiting", False)

        # 调用send_message方法
        human_agent.send_private_message(
            task_id=task_id,
            receiver=receiver,
            context=content,
            stage_relative=stage_relative,
            need_reply=need_reply,
            waiting=waiting,
        )

        return jsonify({"success": True, "message": "消息已发送"})
    except Exception as e:
        return jsonify({"success": False, "message": f"发送消息失败: {str(e)}"}), 500

@app.route("/api/send_group_message", methods=['POST'])
def human_send_group_message():
    """
    API接口，用于调用HumanAgent的send_group_message方法发送消息（在群聊中发送消息）

    请求参数(JSON):
    {
        "human_agent_id": "人类操作员ID",  # 这个ID是uuid.uuid4()的agent_id,而不是监控器中带"HumanAgent_"前缀的ID
        "task_id": "任务ID",
        "receiver": ["接收者ID1", "接收者ID2", ...],
        "content": "消息内容",
        "stage_relative": "相关阶段ID", // 可选，默认为"no_relative"
        "need_reply": true,  // 可选，默认为true
        "waiting": true      // 可选，默认为false
        "return_waiting_id": "唯一等待ID"  // 可选，默认为None
    }

    返回:
    {
        "success": true,
        "message": "消息已发送"
    }
    """
    try:
        # 获取请求中的JSON数据
        data = request.json

        # 必需参数验证
        required_fields = ["human_agent_id", "task_id", "receiver", "content"]
        for field in required_fields:
            if field not in data:
                return jsonify({"success": False, "message": f"缺少必需参数: {field}"}), 400

        # 检查MAS实例是否已注册
        if _mas_instance is None:
            return jsonify({"success": False, "message": "MAS实例未注册"}), 500

        # 获取HumanAgent实例
        human_agent = _mas_instance.get_agent_from_id(data["human_agent_id"])
        if not human_agent or not isinstance(human_agent, HumanAgent):
            return jsonify({"success": False, "message": "找不到指定的HumanAgent"}), 404

        # 准备参数
        task_id = data["task_id"]
        receiver = data["receiver"]
        content = data["content"]
        stage_relative = data.get("stage_relative", "no_relative")
        need_reply = data.get("need_reply", True)
        waiting = data.get("waiting", False)
        return_waiting_id = data.get("return_waiting_id", None)

        # 调用send_message方法
        human_agent.send_group_message(
            task_id=task_id,
            receiver=receiver,
            context=content,
            stage_relative=stage_relative,
            need_reply=need_reply,
            waiting=waiting,
            return_waiting_id=return_waiting_id
        )

        return jsonify({"success": True, "message": "消息已发送"})
    except Exception as e:
        return jsonify({"success": False, "message": f"发送消息失败: {str(e)}"}), 500


@app.route("/api/bind_human_agent", methods=['POST'])
def bind_human_agent():
    '''
    该接口用于人类操作员登录，返回HumanAgent的ID
    输入参数:
    {
        "human_agent_id": "<HumanAgent的ID>"
        "password": "<HumanAgent的密码>"
    }
    返回:
    {
        "success": true,
        "human_agent_id": "<传入的HumanAgent的ID>"
        "message": "<调用成功或失败的消息>"
    }

    首先判定agent_id是否在系统中存在，如果存在则获取该HumanAgent的agent_state[human_config][password]进行比对
    '''
    # 获取请求中的JSON数据
    data = request.json

    try:
        # 必需参数验证
        required_fields = ["human_agent_id", "password"]
        for field in required_fields:
            if field not in data:
                return jsonify({"success": False, "message": f"缺少必需参数: {field}", "human_agent_id": data["human_agent_id"]}), 400

        # 检查MAS实例是否已注册
        if _mas_instance is None:
            return jsonify({"success": False, "message": "MAS实例未注册", "human_agent_id": data["human_agent_id"]}), 500

        # 获取HumanAgent实例
        human_agent = _mas_instance.get_agent_from_id(data["human_agent_id"])
        if not human_agent or not isinstance(human_agent, HumanAgent):
            return jsonify({"success": False, "message": "找不到指定的HumanAgent", "human_agent_id": data["human_agent_id"]}), 404

        # 检查密码是否正确
        input_password = data["password"]
        stored_password = human_agent.agent_state.get("human_config", {}).get("password", "")
        if input_password != stored_password:
            return jsonify({"success": False, "message": "密码不正确", "human_agent_id": data["human_agent_id"]}), 401
        else:
            # 返回HumanAgent的ID
            return jsonify({"success": True, "message": "验证通过", "human_agent_id": data["human_agent_id"]}), 200
    except Exception as e:
        return jsonify({"success": False, "message": e, "human_agent_id": data["human_agent_id"]}), 500

# ===================== 后台服务 =====================

# 定义一个循环任务，用于周期性推送状态数据
def push_state_loop():
    while True:
        # 从状态监控器中获取所有状态数据
        states = monitor.get_all_states()
        socketio.emit('state_update', states)  # 广播名为 'state_update' 的事件
        time.sleep(2)  # 每 2 秒推送一次

# 启动服务，人类操作端 和 状态监控（后端 HTTP 和 WebSocket 以及状态推送线程）
def start_interface():
    # 启动后台线程，负责状态数据的周期推送
    threading.Thread(target=push_state_loop, daemon=True).start()
    # 启动 Flask + SocketIO 服务，监听 5000 端口
    socketio.run(app, host='0.0.0.0', port=5000)