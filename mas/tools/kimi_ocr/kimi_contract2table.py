'''
实现调用kimi API提取的合同信息转换为表格
'''

import yaml
from openai import OpenAI
import pandas as pd
import json


class KimiContract2Table:
    '''
    调用Kimi API提取的合同信息转换为表格:
    1. 读取合同配置文件与API初始化
    2. 调用API上传pdf合同文件
    3. 遍历合同配置文件，构造字段提取的提示词
    4. 解析返回的JSON结果，转换为表格
    '''
    def __init__(self, contract_config_path: str, api_key: str, base_url):
        '''
        contract_config_path (str): 合同配置文件路径
        api_key (str): OpenAI API Key
        base_url (str): 调取LLM的 Base URL
        '''
        # 读取配置文件
        with open(contract_config_path, "r", encoding="utf-8") as file:
            self.contract_config = yaml.safe_load(file)
        # 初始化OpenAI客户端
        self.client = OpenAI(
            api_key = api_key,
            base_url = base_url,
        )

    def generate_prompt(self, contract_type: str) -> str:
        """
        生成智能提示词（支持动态表格定位和字段级规则）
        """
        # 获取合同配置
        contract_info = next(
            (c for c in self.contract_config['contracts'] if c['contract_type'] == contract_type), None
        )
        if not contract_info:
            return f"没有找到类型为{contract_type}的合同配置。"

        # 基础信息
        prompt = f"""## 高级合同信息提取指令（{contract_info['contract_type']}）

    ### 通用处理规则
    1. **表格定位**：
    - 柜体信息表格：查找包含【名称及配置】、【数量】、【单价】、【小计】的表头
    - 费用相关表格：查找包含【费用项】、【金额】的表头
    - 注意跨页表格的连续性

    2. **数据清洗**：
    - 金额处理：去除￥、元等符号，转换为浮点数
    - 日期格式：统一为YYYY-MM-DD格式
    - 单位处理：明确标注单位（如"3主2副"）

    3. **计算逻辑**：
    - 禁止直接使用"总计"行数据
    - 必须自行计算汇总值
    - 保留两位小数

    ### 字段级提取规范
    """

        # 生成字段级指令
        for field in contract_info['table_header']:
            field_prompt = f"\n【{field['field_name']}】"
            field_prompt += f"\n- 描述：{field['field_description']}"
            field_prompt += f"\n- 格式：{field['expect_format']}"

            # 动态添加处理规则
            if "柜子总价" in field['field_name']:
                field_prompt += """
    - 处理步骤：
    1. 定位柜体信息表格
    2. 筛选行条件：
        ✓ 必须包含：主柜、副柜
        ✗ 必须排除：运费、配件、安装
    3. 提取【小计】列数值
    4. 数据清洗：
        - 去除所有非数字字符（如￥12,500 → 12500）
    5. 累加所有有效数值
    """
            elif "柜子数" in field['field_name']:
                field_prompt += """
    - 处理步骤：
    1. 定位柜体信息表格
    2. 分类统计：
        - 主柜：名称包含"主柜"的条目
        - 副柜：名称包含"副柜"的条目
    3. 特殊类型处理：
        - 投放柜/改造柜需单独分类统计
    4. 累加【数量】列
    """
            elif "运费" in field['field_name']:
                field_prompt += """
    - 处理步骤：
    1. 定位费用相关表格
    2. 精确匹配行：
        - 名称包含：运费、运输费、物流费
    3. 提取【金额】列数值
    4. 若存在多笔运费需累加
    """

            # 添加示例
            examples = {
                "柜子总价": """
    示例表格：
    | 名称及配置       | 小计    |
    |------------------|---------|
    | 主柜A型         | ￥5,500 |
    | 副柜B型         | 13,500元|
    | 运输费          | 1,200   |
    正确结果：5500 + 13500 = 19000.00""",
                "柜子数": """
    示例表格：
    | 名称及配置        | 数量 |
    |-------------------|------|
    | 投放柜-主柜      | 2    |
    | 改造柜-主柜      | 1    |
    | 投放柜-副柜      | 3    |
    正确结果：投放柜2主3副，改造柜1主0副"""
            }
            if field['field_name'] in examples:
                field_prompt += f"\n- 示例：{examples[field['field_name']]}"

            prompt += field_prompt

        # 添加错误防范
        prompt += """
        
    ### 错误防范措施
    1. 金额验证：总价 = Σ(单价×数量)
    2. 逻辑校验：投入合计 = 柜子总价 + 运费 + 配件
    3. 格式检查：使用正则校验日期/百分比格式
    4. 排重处理：同一表格中重复条目取首次出现值

    请以严格JSON格式输出，确保数值精确到小数点后两位。"""

        return prompt

    def extract_contract_info(self, pdf_path: str, contract_type: str):
        """
        调用Kimi API提取合同信息并转换为表格
        """
        print("构建合同表格字段提示词中...")

        prompt = self.generate_prompt(contract_type=contract_type)

        print("上传合同文件中...")
        # 上传合同文件
        with open(pdf_path, "rb") as file:  # 使用 open() 打开 PDF 文件并传递给 API
            file_object = self.client.files.create(file=file, purpose="file-extract")
            file_content = self.client.files.content(file_id=file_object.id).text

        # 构建消息内容
        messages = [
            {"role": "system", "content": "你是 Kimi，由 Moonshot AI 提供的人工智能助手，专注于合同信息提取。"},
            {"role": "system", "content": file_content},
            {"role": "user", "content": prompt}
        ]

        # 调用API获取响应
        completion = self.client.chat.completions.create(
            model="moonshot-v1-32k",
            messages=messages,
            temperature=0.2,
            response_format={"type": "json_object"}
        )

        # 解析并打印结果
        result = json.loads(completion.choices[0].message.content)
        print("\n====== 提取结果 ======")
        print(json.dumps(result, indent=4, ensure_ascii=False))
        result = json.loads(completion.choices[0].message.content)
        return result


    def save_json2excel(self, result, excel_path):
        """
        保存JSON结果到Excel
        """
        # 将结果转换为 DataFrame
        try:
            # 假设 result 是一个字典，转换为 DataFrame
            df = pd.DataFrame([result])

            # 将 DataFrame 保存为 Excel 文件
            df.to_excel(excel_path, index=False, engine='openpyxl')

            print(f"JSON 数据成功保存为 Excel 文件：{excel_path}")

        except Exception as e:
            print(f"保存 JSON 到 Excel 失败: {e}")

    def delete_all_files(self):
        '''
        删除所有上传的文件，kimi有上传限制，不能无限上传文件，需要主动清理分配给每个用户的文件空间
        '''
        file_list = self.client.files.list()
        for file in file_list.data:
            print(f"删除文件中: {file.filename} (id: {file.id})")
            response = self.client.files.delete(file.id)  # 按 id 删除文件
            print(f"删除状态: {response}")
        print("所有文件已删除")

if __name__ == "__main__":
    '''
    执行 python mas/tools/kimi_ocr/kimi_contract2table.py
    '''
    processor = KimiContract2Table(
        contract_config_path = "mas/tools/kimi_ocr/contract2table.yaml",
        api_key = "sk-GqiNrqNiJixxEcA6OYIRmu9EVopLuAMZlc071StzUfPScozm",
        base_url = "https://api.moonshot.cn/v1",
    )
    print("KimiContract2Table 初始化完成")

        # 需要诊断的文件路径
    test_file = r"C:\Users\Administrator\Desktop\7-2023120101750101-沈阳时尚商业有限公司-沈阳时尚地下购物广场-何鑫山.pdf"

    contract_info = processor.extract_contract_info(test_file, contract_type="投放类合同")

    # 打印输出提取的合同信息
    print(json.dumps(contract_info, indent=4))

    # 将kimi的结果保存在Excel中
    processor.save_json2excel(
        contract_info,
        "C:/Users/Administrator/Desktop/7-2023120101750101-沈阳时尚商业有限公司-沈阳时尚地下购物广场-何鑫山.xlsx"
    )

    # 清空kimi云端文件空间缓存
    processor.delete_all_files()
