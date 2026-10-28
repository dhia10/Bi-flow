"""python main.py --example car_rental [--no-llm] or --input data/input"""
import argparse
import json
import os
from pathlib import Path
from etl_agent import ETLAgent

def main():
    parser=argparse.ArgumentParser(description='BI-FLOW Intelligent ETL Agent')
    parser.add_argument('--input','--input-dir',dest='input_dir',default='data/input',help='Folder containing CSV/XLSX/JSON tables')
    parser.add_argument('--output','--output-dir',dest='output_dir',default='data/output',help='Warehouse and image output folder')
    parser.add_argument('--example',choices=sorted(p.name for p in Path('data/examples').iterdir() if p.is_dir()),help='Run one of the included examples without copying files')
    parser.add_argument('--no-llm',action='store_true',help='Use deterministic safe fallback without Ollama')
    parser.add_argument('--schema',choices=['star','snowflake','auto'],default='auto',help='Data warehouse schema; star is original default, auto selects snowflake for validated dimension hierarchies')
    parser.add_argument('--model',help='Ollama model name, e.g. qwen2.5:1.5b')
    args=parser.parse_args()
    if args.model:os.environ['OLLAMA_MODEL']=args.model
    source=Path('data/examples')/args.example if args.example else args.input_dir
    output=Path(args.output_dir)
    if args.example and args.output_dir=='data/output':output=output/args.example
    result=ETLAgent(use_llm=not args.no_llm,schema=args.schema).run(source,output)
    print('\n=== INTELLIGENT ETL AGENT RESULT ===')
    print(json.dumps(result,indent=2,ensure_ascii=False,default=str))
    return result
if __name__=='__main__':main()
