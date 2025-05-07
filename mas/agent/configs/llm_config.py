'''
LLM基础调用类的配置管理类，实现LLM的初始化和管理LLM的API配置
'''

import yaml
from enum import Enum  # 导入枚举类型 Enum
from typing import Optional

class LLMType(Enum):  # 定义 LLMType 枚举，表示支持的 LLM 类型
    '''
    当前仅支持OLLAMA与openai
    '''
    OPENAI = "openai"  # OpenAI API
    # ANTHROPIC = "anthropic"  # Anthropic 提供的模型
    # CLAUDE = "claude"  # Claude 模型的别名
    # SPARK = "spark"  # Spark 提供的模型
    # ZHIPUAI = "zhipuai"  # 智谱 AI 提供的模型
    # FIREWORKS = "fireworks"  # Fireworks 提供的模型
    # OPEN_LLM = "open_llm"  # 开放 LLM 模型
    # GEMINI = "gemini"  # Google Gemini 模型
    # METAGPT = "metagpt"  # Meta 提供的 GPT 模型
    # AZURE = "azure"  # Microsoft Azure 提供的 LLM
    OLLAMA = "ollama"  # Ollama 提供的模型
    # OLLAMA_GENERATE = "ollama.generate"  # Ollama 的 /generate 接口
    # OLLAMA_EMBEDDINGS = "ollama.embeddings"  # Ollama 的 /embeddings 接口
    # OLLAMA_EMBED = "ollama.embed"  # Ollama 的 /embed 接口
    # QIANFAN = "qianfan"  # 百度提供的 Qianfan 模型
    # DASHSCOPE = "dashscope"  # 阿里云 LingJi DashScope 提供的模型
    # MOONSHOT = "moonshot"  # Moonshot 模型
    # MISTRAL = "mistral"  # Mistral 提供的模型
    # YI = "yi"  # Lingyiwanwu 提供的模型
    # OPEN_ROUTER = "open_router"  # OpenRouter 路由模型
    # DEEPSEEK = "deepseek"  # DeepSeek 模型
    # SILICONFLOW = "siliconflow"  # SiliconFlow 模型
    # OPENROUTER = "openrouter"  # OpenRouter 模型（别名）
    # OPENROUTER_REASONING = "openrouter_reasoning"  # OpenRouter 推理模型
    # BEDROCK = "bedrock"  # 亚马逊提供的 Bedrock 模型
    # ARK = "ark"  # 火山引擎提供的 Ark 模型  # https://www.volcengine.com/docs/82379/1263482#python-sdk

    def __missing__(self, key):
        """如果未匹配到类型，默认返回 OLLAMA。"""
        return self.OLLAMA

class LLMConfig:
    """LLM 基础配置类"""

    def __init__(
        self,
        api_key: str,  # API 密钥，用于身份验证
        api_type: LLMType, # API 类型
        base_url: str = "",  # API 基础 URL，默认为 OpenAI 官方 API
        model: str = "",  # 选择的 LLM 模型，默认 "gpt-3.5-turbo"
        max_tokens: int = 4096,  # 生成文本的最大 token 数，默认 4096
        temperature: float = 0.7,  # 生成文本的温度（影响随机性），默认 0.7
        timeout: int = 600,  # 请求超时时间（秒），默认 600 秒
    ):
        self.api_key = api_key  # 存储 API 密钥
        self.api_type = api_type  # 存储 API 类型
        self.base_url = base_url  # 存储 API 基础 URL
        self.model = model  # 存储模型名称
        self.max_tokens = max_tokens  # 存储最大 token 数
        self.temperature = temperature  # 存储温度参数
        self.timeout = timeout  # 存储超时时间

    def __repr__(self):  # 返回对象的字符串表示，便于调试和打印输出
        return (
            f"LLMConfig(api_type={self.api_type.value}, model={self.model}, "
            f"max_tokens={self.max_tokens}, temperature={self.temperature})"
        )

    @classmethod
    def from_yaml(cls, file_path: str) -> "LLMConfig":
        """从 YAML 文件加载配置"""
        with open(file_path, "r", encoding="utf-8") as file:
            config_data = yaml.safe_load(file)

        return cls(
            api_key=config_data.get("api_key", ""),
            api_type=config_data.get("api_type", ""),
            base_url=config_data.get("base_url", ""),
            model=config_data.get("model", ""),
            max_tokens=config_data.get("max_tokens", 4096),
            temperature=config_data.get("temperature", 0.7),
            timeout=config_data.get("timeout", 600),
        )