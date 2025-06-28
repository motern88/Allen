'''
该文件用于注释和理解MCP的使用方式
'''



#################### 服务端 ####################

from typing import Any
import httpx
from mcp.server.fastmcp import FastMCP

# 初始化 FastMCP 服务
mcp = FastMCP("weather")

# Constants
NWS_API_BASE = "https://api.weather.gov"
USER_AGENT = "weather-app/1.0"

'''
FastMCP 类使用 Python 类型提示和文档字符串自动生成工具定义，从而轻松创建和维护 MCP 工具
'''

'''
接下来，让我们添加用于查询和格式化 National Weather Service API 中的数据的帮助程序函数：
'''
async def make_nws_request(url: str) -> dict[str, Any] | None:
    """向 NWS API 发起请求，并处理可能的错误。"""
    headers = {
        "User-Agent": USER_AGENT,  # 自定义的用户代理标识（通常需注册）
        "Accept": "application/geo+json"  # 请求 NWS API 返回 GeoJSON 格式的数据
    }

    # 创建一个异步 HTTP 客户端
    async with httpx.AsyncClient() as client:
        try:
            # 发起 GET 请求，设置超时时间为 30 秒
            response = await client.get(url, headers=headers, timeout=30.0)

            # 如果响应状态码不是 2xx，会抛出异常
            response.raise_for_status()

            return response.json()
        except Exception:
            return None

def format_alert(feature: dict) -> str:
    """将一条警报特征信息格式化为可读字符串。"""
    props = feature["properties"]

    # 构造并返回格式化的字符串，使用 get() 防止字段缺失导致错误
    return f"""
        Event: {props.get('event', 'Unknown')}
        Area: {props.get('areaDesc', 'Unknown')}
        Severity: {props.get('severity', 'Unknown')}
        Description: {props.get('description', 'No description available')}
        Instructions: {props.get('instruction', 'No specific instructions provided')}
    """

'''
工具执行处理程序负责实际执行每个工具的逻辑。让我们添加它：
'''
@mcp.tool()
async def get_alerts(state: str) -> str:
    """获取指定美国州的天气警报信息。

    参数:
        state: 两位美国州缩写（例如 CA 表示加州，NY 表示纽约州）
    """

    # 构造 NWS API 的天气警报请求 URL（根据州代码）
    url = f"{NWS_API_BASE}/alerts/active/area/{state}"
    # 异步请求该 URL，获取天气警报数据
    data = await make_nws_request(url)

    if not data or "features" not in data:
        return "无法获取警报信息，或未找到任何警报。"

    if not data["features"]:
        return "该州目前没有活跃的天气警报。"

    # 遍历每个警报数据，使用 format_alert 函数进行格式化
    alerts = [format_alert(feature) for feature in data["features"]]
    # 将多个警报信息拼接成一个字符串，并使用 '---' 作为分隔符
    return "\n---\n".join(alerts)

@mcp.tool()
async def get_forecast(latitude: float, longitude: float) -> str:
    """获取指定位置的天气预报。

    参数:
        latitude: 位置的纬度
        longitude: 位置的经度
    """
    # 构造获取天气网格信息的 API URL
    points_url = f"{NWS_API_BASE}/points/{latitude},{longitude}"
    # 发送请求获取该位置的天气网格信息（包括后续用于获取天气预报的 URL）
    points_data = await make_nws_request(points_url)

    if not points_data:
        return "无法获取该位置的天气预报数据。"

    # 从返回的网格信息中提取天气预报的 URL
    forecast_url = points_data["properties"]["forecast"]
    # 发送请求获取详细天气预报信息
    forecast_data = await make_nws_request(forecast_url)

    if not forecast_data:
        return "无法获取详细的天气预报信息。"

    # 提取预报时段信息
    periods = forecast_data["properties"]["periods"]
    forecasts = []
    # 只展示前 5 个预报时段的信息
    for period in periods[:5]:
        forecast = f"""
            {period['name']}:
            温度: {period['temperature']}°{period['temperatureUnit']}
            风速: {period['windSpeed']} {period['windDirection']}
            天气预报: {period['detailedForecast']}
        """
        forecasts.append(forecast)

    # 将多段预报拼接为一个字符串，以 '---' 分隔
    return "\n---\n".join(forecasts)


if __name__ == "__main__":
    # 运行 FastMCP 服务
    mcp.run(transport='stdio')


