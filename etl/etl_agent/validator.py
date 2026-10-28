"""Post-execution validation and warning reporting. Warnings are never silently hidden."""
import pandas as pd

def validate_output(fact,dimensions,plan,logs,relations,frames):
    checks=[]
    def record(name,passed,details,severity='error'):
        checks.append({'name':name,'passed':bool(passed),'details':details,'severity':severity})
    record('fact_not_empty',len(fact)>0,len(fact))
    record('fact_grain_preserved',len(fact)==len(frames[plan.base_table]),
           {'input_rows':len(frames[plan.base_table]),'fact_rows':len(fact)})
    for item in plan.derived_columns:
        record('derived_exists:'+item.name,item.name in fact,item.inputs)
        if item.name in fact:
            record('derived_not_all_null:'+item.name,fact[item.name].notna().any(),int(fact[item.name].isna().sum()),'warning')
    for rel in relations:
        dim=dimensions[rel['dimension_table']]
        parent_name=rel.get('source_table',plan.fact_table)
        parent=fact if parent_name==plan.fact_table else dimensions[parent_name]
        fk=parent[rel.get('source_column',rel.get('fact_column'))]
        pk=dim[rel['dimension_column']]
        record('dimension_pk_unique:'+rel['dimension_table'],pk.is_unique and pk.notna().all(),rel['dimension_column'])
        orphans=int((fk.notna() & ~fk.isin(pk)).sum());nnull=int(fk.isna().sum())
        record('fk_coverage:'+parent_name+'->'+rel['dimension_table'],orphans==0 and nnull==0,{'unmatched':orphans,'null_keys':nnull},'warning')
    record('high_null_observation',True,
           {c:round(float(fact[c].isna().mean()),3) for c in fact if fact[c].isna().mean()>.5},'warning')
    record('duplicate_row_observation',True,int(fact.duplicated().sum()),'warning')
    return {'passed':all(c['passed'] for c in checks if c['severity']=='error'),
            'has_warnings':any(not c['passed'] for c in checks if c['severity']=='warning'),
            'checks':checks}
