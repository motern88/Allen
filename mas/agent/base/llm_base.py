'''
- LLMContext：一个LLM上下文类，用于维护对话历史。
- LLMClient：一个LLM基础调用类，来封装API请求逻辑

在LLMClient.call中传入单独维度的LLMContext
'''
from mas.agent.configs.llm_config import LLMConfig

import requests
from typing import Dict, Any, Union, List


class LLMContext:
    """
    负责维护对话历史，包括追加、删除、获取历史等功能。
    """

    def __init__(self, context_size: int = 30):
        self.context_size = context_size  # 控制上下文轮数，这里应当由Agent_state传入指定，而非LLM config传入指定，因为LLMContext就是为每个Agent单独维护的
        self.history: List[Dict[str, str]] = []  # 维护对话历史

    def add_message(self, role: str, content: str):
        """追加新的对话记录"""
        if role not in ["user", "assistant"]:
            raise ValueError("角色必须是 'user' 或 'assistant'")
        self.history.append({"role": role, "content": content})
        self.trim_history()  # 控制历史长度

    def remove_last_message(self):
        """删除最后一条消息"""
        if self.history:
            self.history.pop()

    def trim_history(self):
        """仅保留最近 `context_size` 轮对话"""
        self.history = self.history[-(self.context_size * 2):]

    def set_history(self, messages: List[Dict[str, str]]):
        """直接替换整个对话历史"""
        self.history = messages[-(self.context_size * 2):]

    def get_history(self) -> List[Dict[str, str]]:
        """获取当前的对话历史"""
        return self.history

    def clear(self):
        """清空对话历史"""
        self.history = []


class LLMClient:
    """
    LLM API 调用封装类，不直接维护对话历史，而是使用 LLMContext。
    该类实现两种API调用方式：Ollama 和 OpenAI。在不同分支中
    """

    def __init__(self, config: LLMConfig):
        self.config = config

    def _get_headers(self) -> Dict[str, str]:
        """生成 HTTP 头部信息"""
        headers = {"Content-Type": "application/json",}
        # 如果有 API 密钥，则添加 Authorization 头
        if hasattr(self.config, "api_key") and self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        return headers

    def _get_payload(
        self,
        prompt: str,
        context:LLMContext,
        stream: bool,
        **kwargs
    ) -> Dict[str, Any]:
        """生成 API 请求的 JSON 载荷，使用传入的上下文"""
        context.add_message("user", prompt)  # 追加新的 user 消息

        payload = {
            "model": self.config.model,
            "messages": context.get_history(),  # 使用上下文中的对话历史
            "stream": stream,  # 使用流模式参数
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "temperature": kwargs.get("temperature", self.config.temperature),
        }

        return payload

    def call(
        self,
        prompt: str,
        context: LLMContext,
        stream: bool = False,
        **kwargs
    ) -> Union[str, None]:
        """
        调用 LLM API 生成文本，固定以对话模式生成回复。
        该方法根据 `api_type` 选择不同的 API（Ollama 或 OpenAI），并处理相应的响应格式。

        参数:
            prompt (str): 用户输入的文本。
            context (LLMContext): 对话上下文对象，存储历史对话信息。
            stream (bool, 可选): 是否使用流式输出，默认为 False。
            **kwargs: 额外的 API 参数（如 `max_tokens`、`temperature` 等）。

        返回:
            Union[str, None]: 生成的文本回复，如果请求失败则返回 None。
        """
        # 1. 选择 API 端点
        if self.config.api_type == "ollama":
            url = self.config.base_url + "/chat"  # 使用生成对话模式
        elif self.config.api_type == "openai":
            url = self.config.base_url + "/chat/completions"  # 使用生成对话模式
        else:
            raise ValueError(f"不支持的 API 类型: {self.config.api_type}")

        # 2. 生成 HTTP 请求头
        headers = self._get_headers()

        # 3. 生成请求载荷
        payload = self._get_payload(prompt, context, stream, **kwargs)

        try:
            # 4. 发送 HTTP 请求
            response = requests.post(url, headers=headers, json=payload, timeout=self.config.timeout)
            response.raise_for_status()  # 检查 HTTP 错误
            data = response.json()

            # 5. 解析 API 响应
            if self.config.api_type == "ollama":
                # Ollama API 响应格式
                if "message" in data and "content" in data["message"]:
                    reply = data["message"]["content"]
                else:
                    print("Ollama API 响应中没有预期的字段")
                    return None
            elif self.config.api_type == "openai":
                # OpenAI API 响应格式
                if "choices" in data and len(data["choices"]) > 0:
                    reply = data["choices"][0]["message"]["content"]
                else:
                    print("OpenAI API 响应中没有预期的字段")
                    return None
            else:
                raise ValueError(f"不支持的 API 类型: {self.config.api_type}")

            # 6. 将 AI 生成的回复追加到上下文，并返回
            context.add_message("assistant", reply)
            return reply

        except requests.exceptions.RequestException as e:
            # 7. 处理请求异常
            print(f"API 请求失败: {e}")
            return None


# Debug
if __name__ == "__main__":
    '''
    运行脚本需在Allen根目录下执行 python -m mas.agent.base.llm_base
    '''

    print("尝试初始化llm并调用")
    config = LLMConfig.from_yaml("mas/role_config/qwq32b.yaml")  # 创建 LLM 配置  # mas/role_config/qwq32b.yaml mas/role_config/openai.yaml
    llm_client = LLMClient(config)  # 创建 LLM 客户端
    chat_context = LLMContext(context_size=3)  # 创建一个对话上下文

    # 追加自定义历史记录
    chat_context.add_message("user", "你好")
    chat_context.add_message("assistant", "你好！我是 AI 助手")

    # 调用 LLM
    response = llm_client.call("请介绍一下自己", context=chat_context)
    print(response)

    # 获取当前的对话历史
    print(chat_context.get_history())

    # 清空对话历史
    chat_context.clear()
