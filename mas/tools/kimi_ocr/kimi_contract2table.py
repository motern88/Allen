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

    def generate_prompt(self, contract_type: str):
        """
        根据合同类型，从合同配置文件生成提示词
        """
        # 查找对应合同类型
        contract_info = next(
            (contract for contract in self.contract_config['contracts'] if contract['contract_type'] == contract_type),None
        )
        if contract_info is None:
            return f"没有找到类型为{contract_type}的合同配置。"

        contract_type = contract_info['contract_type']
        contract_description = contract_info['contract_description']
        table_header = contract_info['table_header']

        prompt = f"合同类型: {contract_type}\n描述: {contract_description}\n\n请根据以下字段提取信息：\n"

        # 遍历字段信息，生成提示词
        for field in table_header:
            field_name = field['field_name']
            field_description = field['field_description']
            expect_format = field['expect_format']

            # 动态生成提示词
            prompt += f"\n- {field_name}：{field_description}\n期望格式：{expect_format}\n"

        prompt += "\n请以 JSON 格式输出结果，无法提取的信息请记为 null，切勿捏造信息。"

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

        # 解析返回的JSON结果
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
    kimi_contract2table = KimiContract2Table(
        contract_config_path = "mas/tools/kimi_ocr/contract2table.yaml",
        api_key = "sk-GqiNrqNiJixxEcA6OYIRmu9EVopLuAMZlc071StzUfPScozm",
        base_url = "https://api.moonshot.cn/v1",
    )
    print("KimiContract2Table 初始化完成")

    pdf_path = "example/1-2023120103870101-广州市汉唐区双盛饮食娱乐管理有限公司-INSIDECLUB-王富容.pdf"
    contract_info = kimi_contract2table.extract_contract_info(pdf_path, contract_type="投放类合同")

    # 打印输出提取的合同信息
    print(json.dumps(contract_info, indent=4))

    # 将kimi的结果保存在Excel中
    kimi_contract2table.save_json2excel(
        contract_info,
        "example/1-2023120103870101-广州市汉唐区双盛饮食娱乐管理有限公司-INSIDECLUB-王富容.xlsx"
    )

    # 清空kimi云端文件空间缓存
    kimi_contract2table.delete_all_files()
