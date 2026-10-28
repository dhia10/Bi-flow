"""Explainable audit artifacts and downstream KPI agent contract."""
import json
from pathlib import Path
from datetime import datetime,timezone
import pandas as pd

def write_json(path,data):
    p=Path(path);p.write_text(json.dumps(data,indent=2,ensure_ascii=False,default=str),encoding='utf-8')
    return str(p)
def write_artifacts(output_dir,profile,plan,planner_mode,repairs,execution_logs,validation,saved,fact,dimensions,relations,lineage,diagram,llm_debug):
    dest=Path(output_dir);dest.mkdir(parents=True,exist_ok=True)
    paths={}
    paths['profile']=write_json(dest/'profile.json',profile)
    paths['plan']=write_json(dest/'etl_plan.json',plan.model_dump())
    paths['llm_debug']=write_json(dest/'llm_debug.json',llm_debug)
    paths['lineage']=write_json(dest/'lineage.json',{'derived_columns':lineage,'relationships':relations})
    report={'agent':'intelligent_etl_agent','timestamp_utc':datetime.now(timezone.utc).isoformat(),
            'status':'success' if validation['passed'] and not validation['has_warnings'] else 'completed_with_warnings',
            'domain_subdomain':plan.domain_subdomain,'domain_confidence':plan.domain_confidence,
            'domain_evidence':plan.domain_evidence,'business_processes':plan.business_processes,
            'planner_mode':planner_mode,'domain':plan.domain,'domain_source':plan.domain_source,
            'schema_type':plan.schema_type,'schema_reason':plan.schema_reason,
            'semantic_notes':plan.semantic_notes,'repairs':repairs,'measure_sources':plan.measure_sources,
            'base_table':plan.base_table,'fact_table':plan.fact_table,'input_tables':list(profile['tables']),
            'execution_log':execution_logs,'validation':validation,'relationship_mapping':relations,
            'rows':len(fact),'columns':list(fact.columns),'outputs':saved,'diagram':diagram}
    paths['report']=write_json(dest/'etl_report.json',report)
    handoff={'next_agent':'BI Semantic & KPI Agent','producer':'intelligent_etl_agent',
             'status':report['status'],'warehouse':saved['database'],'database_engine':saved['database_engine'],
             'fact_table':plan.fact_table,'schema_type':plan.schema_type,'schema_reason':plan.schema_reason,'fact_grain':'one row per source '+plan.base_table+' row',
             'fact_columns':list(fact.columns),'measures':[m.name for m in plan.derived_columns],
             'dimension_tables':list(dimensions),'relationships':relations,
             'domain':plan.domain,'domain_source':plan.domain_source,
             'domain_subdomain':plan.domain_subdomain,'domain_confidence':plan.domain_confidence,
             'domain_evidence':plan.domain_evidence,'business_processes':plan.business_processes,'quality':validation,
             'schema_image':diagram,'lineage_json':paths['lineage'],'report_json':paths['report']}
    paths['handoff']=write_json(dest/'handoff_manifest.json',handoff)
    return paths
