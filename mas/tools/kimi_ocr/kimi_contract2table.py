'''
实现调用kimi API提取的合同信息转换为表格
'''

import yaml
from openai import OpenAI
import pandas as pd
import json
from pathlib import Path  


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
        生成智能提示词（支持动态表格定位、字段校验及反推规则）
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
    - 必须自行计算汇总值，保留两位小数  
    - 动态校验：数量字段应满足【数量 × 单价 ≈ 小计】  
    - 若数量缺失，基于【小计 ÷ 单价】反推补全；若金额缺失，反推小计；记录补全结果来源  

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
- 核心识别逻辑：
  1. 特征分析三步法：
    ✓ 步骤一：检查是否包含柜体结构描述（如"850mm宽 x 1950mm高 x 600mm深"）
    ✓ 步骤二：确认是否标注门数（如"5门"、"10门"）
    ✓ 步骤三：验证是否具备完整参数（尺寸/材质/门数）
  
  2. 金额计算优先级：
    (1) 首选：小计列数值（若存在）
    (2) 备选：单价 × 数量（需验证乘积关系）
    (3) 末选：从名称中解析（如"850-5门"对应标准价格）
  
  3. 错误检查与剔除：  
    ✗ 无完整柜体参数（尺寸、材质） → 剔除记录  
    ✗ 非柜体条目（如"AED除颤设备"） → 剔除记录  
    ✗ 冗余标注（如配件、运费） → 剔除  
    """
            elif "柜子数" in field['field_name']:
                field_prompt += """
- 数据提取规则：  
  1. 按字段名称查找包含【主柜】或【副柜】条目；  
  2. 对符合条件行的【数量】列进行分类汇总：  
      ✓ 主柜：包含“主柜”或等效关键词  
      ✓ 副柜：包含“副柜”或等效关键词  
  3. 若数量缺失，根据【小计 ÷ 单价】动态反推，并记录“修正来源”。  
  4. 排除不包含【柜】相关字样的条目或冗余记录。  
    """
            elif "运费" in field['field_name']:
                field_prompt += """
- 核心提取逻辑：  
  1. 定位表格中包含【费用项】和【金额/小计】的列；  
  2. 精确匹配行：  
      ✓ 包含关键词：运费、运输费、物流费  
  3. 累加金额列值，若无相关记录则返回0.0，并记录状态。
    """
            # 处理“销售(改造)与服务合同”的特定字段
            elif contract_type == "销售(改造)与服务合同":
                if "售卖类别" in field['field_name']:
                    field_prompt += """
    - 数据提取规则：
    1. 根据合同中的“货品名称”判断售卖类别：
     - 如果货品名称中包含“SaaS”、“云服务”、“行政管理平台”等关键词，则售卖类别为“智慧行政”。
     - 如果货品名称中包含“物料”、“配件”、“耗材”等关键词，则售卖类别为“寄存柜物料”。
     - 否则，默认售卖类别为“寄存柜”。
     - 示例：
        - 合同内容：资产营理柜主形现件L01-01，正确结果：智慧行政
        - 合同内容：提产管理相吸件L01-02，正确结果：智慧行政
        - 合同内容：33门室内标准主柜，正确结果：寄存柜
    2. 确保提取的类别与合同内容一致。
                    """
                elif "货品名称" in field['field_name']:
                    field_prompt += """
    - 数据提取规则：
    1. 提取合同中明确指出的商品名称
    2. 确保名称详细且准确，如“室内主柜5门”，“锁控系统”，“企业储物柜副柜”
                    """
                elif "数量" in field['field_name']:
                    field_prompt += """
    - 数据提取规则：
    1. 提取合同中货品名称所对应的明确数量值
    2. 确保数量值为整数，如“1”，“2”
                    """
                elif "单价" in field['field_name']:
                    field_prompt += """
    - 数据提取规则：
    1. 提取合同中货品名称所对应的明确单价
    2. 确保单价为数值，如“2800”，“2520”
                    """
                elif "合同金额" in field['field_name']:
                    field_prompt += """
    - 数据提取规则：
    1. 提取合同中全部货品的总价，计算规则为单价*数量
    2. 确保金额为数值，如“2800”，“5040”
                    """
            # 添加示例
            examples = {
                "柜子总价": """
    示例表格：
示例1（有效条目）：
| 名称及配置              | 规格参数                          | 小计 |
|-------------------------|-----------------------------------|------|
| 智能寄存柜(主)          | 800x2000x600mm 不锈钢 6门        | 8800 |
| 室内标准副柜B型-10门    | 550x1000x900mm                   | 3500 |
| 户外储物箱-副箱         | 1000x2000x800mm 镀锌板 8门       | 12500|
    正确结果：8800 + 3500 + 12500 = 24800
    """,
                "柜子数": """
    示例表格：
    | 名称及配置        | 数量 |
    |-------------------|------|
    | 投放柜-主柜      | 2    |
    | 寄存柜（主柜-10门）| 2    |
    | 改造柜-主柜      | 1    |
    | 投放柜-副柜      | 3    |
    正确结果：投放柜2主3副，改造柜1主0副"""
            }
            if field['field_name'] in examples:
                field_prompt += f"\n- 示例：{examples[field['field_name']]}"

            elif contract_type == "销售(改造)与服务合同":
                if "售卖类别" in field['field_name']:
                    field_prompt += """
    - 示例：
        合同内容：办公用品领用柜产品销售合同，包含“智慧行政SaaS平台”和“云服务器的租用”。
        正确结果：智慧行政"""
                elif "货品名称" in field['field_name']:
                    field_prompt += """
    - 示例：
        合同内容：小款称重柜（带10.1寸屏）
        正确结果：小款称重柜"""
                elif "数量" in field['field_name']:
                    field_prompt += """
    - 示例：
        合同内容：数量为1
        正确结果：1"""
                elif "单价" in field['field_name']:
                    field_prompt += """
    - 示例：
        合同内容：单价为28800元
        正确结果：28800"""
                elif "合同金额" in field['field_name']:
                    field_prompt += """
    - 示例：
        合同内容：总价（含税）47800元
        正确结果：47800"""

            prompt += field_prompt

        # 添加错误防范
        prompt += """
        
    ### 错误防范措施
    1. 金额验证：总价 = Σ(单价×数量)
    2. 动态补全规则：  
    - 若【数量】缺失，则：数量 = 小计 ÷ 单价；  
    - 若【小计】缺失，则：小计 = 单价 × 数量；  
    3. 逻辑校验：投入合计 = 柜子总价 + 运费 + 配件  
    4. 数据类型检查：金额保留两位小数，使用正则校验日期格式。  
    5. 冗余排除：剔除未关联柜体的条目。  

    请以严格JSON格式输出，确保数值精确到小数点后两位。"""

        return prompt

    def extract_contract_info(self, pdf_path: str, contract_type: str, preview_len: int = 100):
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

            # 打印关键内容预览
            print("\n=========关键内容预览=========")
            print(file_content[:preview_len] + ("..." if len(file_content)>preview_len else ""))

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
        print("\n====== 提取结果 ======")
        result = json.loads(completion.choices[0].message.content)
        # print(json.dumps(result, indent=4, ensure_ascii=False))
        
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

    def append_results_to_excel(self, result: dict, output_file: str, filename: str):  
                """  
                将提取的结果增量写入到一个Excel文件  
                result: 提取的JSON数据  
                output_file: 输出Excel文件路径  
                filename: 当前处理的文件名，用作标识  
                """  
                # 转换结果为DataFrame，并添加文件名字段  
                record = {**result, "filename": filename}  
                df_new = pd.DataFrame([record])  

                try:  
                    # 如果文件已存在，直接追加写入  
                    if Path(output_file).exists():  
                        df_old = pd.read_excel(output_file, engine="openpyxl")  
                        df_combined = pd.concat([df_old, df_new], ignore_index=True)  
                    else:  
                        df_combined = df_new  
                    
                    # 存储结果  
                    df_combined.to_excel(output_file, index=False, engine="openpyxl")  
                    print(f"文件 {filename} 的提取结果已保存至 {output_file}")  
                except Exception as e:  
                    print(f"增量写入Excel失败: {e}")  


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

    # 需要提取信息的文件路径
    test_file = r"C:\Users\Administrator\Desktop\18-2023110709180201-佛山市万城合一科技有限公司-骆远山.pdf"

    contract_info = processor.extract_contract_info(test_file, contract_type="销售(改造)与服务合同",preview_len=1500)
    print("contract_info: \n", contract_info)

    # 将kimi的结果保存在Excel中
    # processor.save_json2excel(
    #     contract_info,
    #     "C:\\Users\\Administrator\\Desktop\\18-2023110709180201-佛山市万城合一科技有限公司-骆远山.xlsx"
    # )

    # 清空kimi云端文件空间缓存
    processor.delete_all_files()
