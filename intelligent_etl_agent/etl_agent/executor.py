"""Guarded ETL: only join lookup attributes required by accepted measures.
All dataset rows are preserved; no implicit deduplication or imputation of source facts.
"""
from __future__ import annotations
import pandas as pd
from .models import ETLPlan

class ETLExecutionError(RuntimeError):pass

def _number(s):return pd.to_numeric(s,errors='coerce')
def execute_plan(frames:dict[str,pd.DataFrame],plan:ETLPlan):
    fact=frames[plan.base_table].copy()
    initial_rows=len(fact);base_columns=list(fact.columns);logs=[];lineage=[]
    required={c for m in plan.derived_columns for c in m.inputs}
    indirect_fk={step.left_on for step in plan.joins if step.source_table != plan.base_table}
    required |= indirect_fk  # dimension-to-dimension keys become fact FKs when safe
    for step in plan.joins:
        table=step.right_table;lookup=frames[table]
        if step.left_on not in fact or step.right_on not in lookup:
            raise ETLExecutionError(f'Missing join key {step.left_on} => {table}.{step.right_on}')
        if lookup[step.right_on].isna().any() or lookup[step.right_on].duplicated().any():
            raise ETLExecutionError(f'{table}.{step.right_on} is not a unique non-null dimension key; unsafe join blocked')
        missing=fact[step.left_on].notna() & ~fact[step.left_on].isin(lookup[step.right_on])
        logs.append({'operation':'fk_integrity_check','dimension_table':table,'left_on':step.left_on,
                     'unmatched_rows':int(missing.sum()),'null_fk_rows':int(fact[step.left_on].isna().sum())})
        need=[c for c in lookup if c in required and c not in fact.columns]
        if not need:
            logs.append({'operation':'skip_unnecessary_join','dimension_table':table,'reason':'Relationships retained logically; no dimensional attributes required for calculation.'})
            continue
        before=len(fact)
        fact=fact.merge(lookup[[step.right_on]+need],how='left',left_on=step.left_on,right_on=step.right_on,
                        validate='many_to_one',suffixes=('','_'+table))
        if len(fact)!=before:raise ETLExecutionError('Join unexpectedly changed fact row count')
        logs.append({'operation':'selective_join','table':table,'lookup_columns':need,'rows_before':before,'rows_after':len(fact)})
    derived_names=[]
    for m in plan.derived_columns:
        a,b=m.inputs
        if not {a,b}.issubset(set(fact.columns)):raise ETLExecutionError('Unknown formula inputs '+m.name)
        if m.operation!='multiply':raise ETLExecutionError('Unapproved formula operator '+m.operation)
        fact[m.name]=_number(fact[a])*_number(fact[b]);derived_names.append(m.name)
        lineage.append({'output_column':m.name,'operation':'multiply','source_columns':list(m.inputs),
                        'source_tables':{c:next((t for t in [plan.base_table]+[j.right_table for j in plan.joins] if c in frames[t].columns),'unknown') for c in m.inputs},
                        'source':plan.measure_sources.get(m.name),'reason':m.reason})
        logs.append({'operation':'derived_column','name':m.name,'inputs':m.inputs,'missing_results':int(fact[m.name].isna().sum())})
    dimensions={};relations=[]
    for dim in plan.dimensions:
        df=frames[dim.source_table].copy()
        if not df[dim.key].is_unique or df[dim.key].isna().any():
            raise ETLExecutionError(f'Unsafe PK for {dim.dimension_name}: {dim.key}')
        dimensions[dim.dimension_name]=df
        join=next(j for j in plan.joins if j.right_table==dim.source_table)
        if plan.schema_type=='snowflake_schema' and join.source_table!=plan.base_table:
            source_dim=next((d.dimension_name for d in plan.dimensions if d.source_table==join.source_table),None)
            if not source_dim:
                raise ETLExecutionError('Snowflake dimension parent missing for '+dim.dimension_name)
            relations.append({'source_table':source_dim,'source_column':join.left_on,
                              'dimension_table':dim.dimension_name,'dimension_column':dim.key,
                              'relationship_type':'dimension_to_dimension'})
        else:
            relations.append({'fact_table':plan.fact_table,'fact_column':join.left_on,
                              'source_table':plan.fact_table,'source_column':join.left_on,
                              'dimension_table':dim.dimension_name,'dimension_column':dim.key,
                              'relationship_type':'fact_to_dimension'})
    if plan.date_features:
        source=plan.date_features[0].source_column
        parsed=pd.to_datetime(fact[source],errors='coerce')
        numeric_date=pd.to_numeric(parsed.dt.strftime('%Y%m%d'),errors='coerce').astype('Int64')
        if 'date_key' in fact.columns:raise ETLExecutionError('date_key already exists; cannot add date dimension safely')
        fact['date_key']=numeric_date
        unique=parsed.dropna().drop_duplicates().sort_values()
        dimensions['dim_date']=pd.DataFrame({'date_key':pd.to_numeric(unique.dt.strftime('%Y%m%d')).astype('Int64'),
            'date':unique.dt.strftime('%Y-%m-%d'),'year':unique.dt.year,'month':unique.dt.month,
            'day':unique.dt.day,'quarter':unique.dt.quarter,'month_name':unique.dt.month_name()}).reset_index(drop=True)
        dimensions['dim_date']=dimensions['dim_date'].drop_duplicates(subset=['date_key'])
        relations.append({'fact_table':plan.fact_table,'fact_column':'date_key',
                          'source_table':plan.fact_table,'source_column':'date_key',
                          'dimension_table':'dim_date','dimension_column':'date_key',
                          'relationship_type':'fact_to_dimension'})
        logs.append({'operation':'date_dimension','date_column':source,'rows':len(dimensions['dim_date'])})
    extra_fks=[k for k in sorted(indirect_fk) if k not in base_columns and k in fact.columns] if plan.schema_type=='star_schema' else []
    keep=base_columns+extra_fks+derived_names+(['date_key'] if 'date_key' in fact else [])
    result=fact[keep].copy()
    if len(result)!=initial_rows:raise ETLExecutionError('Fact grain changed unexpectedly')
    logs.append({'operation':'final_projection','fact_rows':len(result),'fact_columns':result.columns.tolist(),
                 'removed_temporary_lookup_columns':sorted(set(fact)-set(result))})
    return result,dimensions,logs,relations,lineage
