'''
该脚本专门用于处理人机交互相关的功能。
主要为HumanAgent类开放一些API接口，使得前端操作可以通过该接口来调用相应HumanAgent的功能
'''

from flask import Flask, request, jsonify
from mas.agent.human_agent import HumanAgent
import gc

app = Flask(__name__)  # 创建Flask实例

# 全局变量，用于存储MAS实例的引用
_mas_instance = None

def register_mas_instance(mas_instance):
    """
    注册MAS实例的引用，这个函数会在MAS初始化时被调用
    """
    global _mas_instance
    _mas_instance = mas_instance
    print("[HumanInterface] MAS实例已注册到人类操作端接口")

@app.route("/api/send_message", methods=['POST'])
def send_human_message():
    """
    API接口，用于调用HumanAgent的send_message方法发送消息

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
        human_agent.send_message(
            task_id=task_id,
            receiver=receiver,
            context=content,
            stage_relative=stage_relative,
            need_reply=need_reply,
            waiting=waiting
        )

        return jsonify({"success": True, "message": "消息已发送"})
    except Exception as e:
        return jsonify({"success": False, "message": f"发送消息失败: {str(e)}"}), 500

# TODO: 实现人类操作员登录接口
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
        required_fields = ["agent_id", "password"]
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



def start_human_interface(host='0.0.0.0', port=5001):
    """
    启动人类操作端接口服务
    """
    app.run(host=host, port=port, debug=False, use_reloader=False)










