"""Orchestrates an isolated BI-FLOW ETL run and maintains explainable state."""
from pathlib import Path
from .executor import execute_plan
from .planner import build_plan
from .profiler import build_profile,load_data_directory
from .reporter import write_artifacts
from .schema_visualizer import generate_schema_image
from .state_manager import write_state
from .storage import save_outputs
from .validator import validate_output

class ETLAgent:
    def __init__(self,use_llm=True,client=None,schema="star"):
        if schema not in ("star", "snowflake", "auto"):
            raise ValueError("schema must be 'star', 'snowflake' or 'auto'")
        self.use_llm=use_llm;self.client=client;self.schema=schema
    def run(self,input_dir,output_dir):
        out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
        state_path=out/'state.json';write_state(state_path,'running',input_dir=str(input_dir))
        try:
            frames=load_data_directory(input_dir)
            profile=build_profile(frames)
            plan,mode,repairs,debug=build_plan(profile,frames,use_llm=self.use_llm,client=self.client,schema=self.schema)
            fact,dimensions,logs,relations,lineage=execute_plan(frames,plan)
            validation=validate_output(fact,dimensions,plan,logs,relations,frames)
            if not validation['passed']:
                from .reporter import write_json
                write_json(out/'validation_failed.json',validation)
                raise RuntimeError('Critical validation failed. Output not saved; see validation_failed.json')
            saved=save_outputs(out,plan.fact_table,fact,dimensions)
            diagram=generate_schema_image(out,plan.fact_table,fact,dimensions,relations,domain=plan.domain,schema_type=plan.schema_type)
            artifacts=write_artifacts(out,profile,plan,mode,repairs,logs,validation,saved,fact,dimensions,relations,lineage,diagram,debug)
            result={'status':'success_with_warnings' if validation['has_warnings'] else 'success',
                    'planner_mode':mode,'domain':plan.domain,'domain_source':plan.domain_source,
                    'domain_subdomain':plan.domain_subdomain,'domain_confidence':plan.domain_confidence,
                    'domain_evidence':plan.domain_evidence,'business_processes':plan.business_processes,
                    'schema_type':plan.schema_type,'schema_reason':plan.schema_reason,
                    'derived_columns':[m.model_dump() for m in plan.derived_columns],
                    'measure_sources':plan.measure_sources,'auto_repairs':repairs,
                    'fact_table':plan.fact_table,'fact_rows':len(fact),'fact_columns':list(fact.columns),
                    'dimension_tables':list(dimensions),'relationship_mapping':relations,
                    'validation':validation,'saved':saved,'schema_diagram':diagram,'star_schema':diagram,'artifacts':artifacts}
            write_state(state_path,result['status'],next_agent='BI Semantic & KPI Agent',
                        outputs=artifacts,schema_diagram=diagram,star_schema=diagram,schema_type=plan.schema_type)
            result['artifacts']['state']=str(state_path)
            return result
        except Exception as exc:
            write_state(state_path,'failed',error=f'{type(exc).__name__}: {exc}')
            raise
