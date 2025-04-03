from kimi_contract2table import KimiContract2Table 
import os

if __name__ == "__main__":  
        # 初始化处理器  
    processor = KimiContract2Table(  
        contract_config_path="mas/tools/kimi_ocr/contract2table.yaml",  
        api_key = "sk-GqiNrqNiJixxEcA6OYIRmu9EVopLuAMZlc071StzUfPScozm",
        base_url = "https://api.moonshot.cn/v1")  

    print("批量处理初始化完成")  

    # 待处理文件夹路径  
    input_folder = r"F:\市场合同\2023年合同\2023-12月合同扫描件\沐腾"  
    output_excel_file = r"C:\Users\Administrator\Desktop\contracts_summary.xlsx"  
    contract_type = "投放类合同"  

    # 遍历文件夹中的所有pdf文件  
    for root, dirs, files in os.walk(input_folder):  
        for file in files:  
            if file.lower().endswith(".pdf"):  # 只处理PDF文件  
                file_path = os.path.join(root, file)  
                try:  
                # 提取合同信息  
                    contract_info = processor.extract_contract_info(file_path, contract_type=contract_type)  
                        
                    # 增量保存到Excel文件  
                    processor.append_results_to_excel(contract_info, output_excel_file, file)  
                except Exception as e:  
                    print(f"处理文件 {file} 时发生错误: {e}")  

    # 清理Kimi文件缓存  
    processor.delete_all_files()  

