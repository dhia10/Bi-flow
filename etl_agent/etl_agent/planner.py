"""Decision planner: structural discovery, constrained LLM semantics, feedback retries, safe fallback."""
from __future__ import annotations
import json
import re
from pydantic import BaseModel,Field
from .models import ETLPlan,JoinStep,DimensionPlan,DerivedColumn,DateFeature
from .llm_client import OllamaClient
from .relationships import choose_base_table,build_join_tree
from .semantic import infer_domain,measure_candidates,make_semantic_context,numeric_columns
from .domain_detector import assessment

SYSTEM_PROMPT="""You are the reasoning component of a trustworthy domain-independent ETL agent.
You receive profiled tables and validated formula candidates. Identify business domain, or 'unknown'.
Propose up to 5 supported, meaningful derived measures. You may select a candidate formula, but NEVER
invent columns, operations, arbitrary multiplication or a business rule not supported by evidence.
Names must describe the computation, NOT a false promised total invoice. Rates may not include taxes.
Examine ALL tables under dataset_overview for domain detection. You may invent a NEW domain label for an unfamiliar industry.
Include a broad domain (e.g. retail), optional subdomain (e.g. ecommerce), and 2-5 domain_evidence entries that exactly match real table or column names.
Never mistake a narrower subdomain for a conflicting broad domain. Include business_processes if justified.
If evidence is insufficient, set domain=unknown, do not guess.
Respond as JSON with keys domain, subdomain, domain_evidence, business_processes, derived_columns, explanation. Each derived_columns element must
have name, operation, inputs (2 real columns), reason. Do not return relationships, joins, or SQL.
If no calculation is justified return derived_columns: []."""

class SemanticSuggestion(BaseModel):
    domain:str='unknown'
    subdomain:str=''
    domain_evidence:list[str]=Field(default_factory=list)
    business_processes:list[str]=Field(default_factory=list)
    derived_columns:list[DerivedColumn]=Field(default_factory=list)
    explanation:str=''

def clean(s):return re.sub('[^a-z0-9_]+','_',s.lower()).strip('_')
def dimension_name(s):
    for suffix in ('_registry','_catalog','_directory','_lookup','_reference','_master','_accounts','_dataset'):
        if s.lower().endswith(suffix):s=s[:-len(suffix)];break
    return 'dim_'+clean(s)

def structure_plan(profile,frames,schema="star"):
    if schema not in ("star", "snowflake", "auto"):
        raise ValueError("schema must be star, snowflake or auto")
    base=choose_base_table(frames,profile['relationship_candidates'])
    joins=build_join_tree(base,frames,profile['relationship_candidates'])
    dims=[];used=set()
    for j in joins:
        dn=dimension_name(j['right_table'])
        if dn in used:dn='dim_'+clean(j['right_table'])
        used.add(dn)
        dims.append(DimensionPlan(source_table=j['right_table'],dimension_name=dn,key=j['right_on']))
    hierarchy=[j for j in joins if j['source_table']!=base]
    if schema=='star':
        selected='star_schema';reason='Star Schema requested (backward-compatible default).'
    elif hierarchy:
        selected='snowflake_schema'
        reason='Validated lookup-to-lookup relationship(s) support normalized dimension hierarchy: '+', '.join(j['source_table']+' → '+j['right_table'] for j in hierarchy)
    else:
        selected='star_schema'
        reason='Snowflake requested but no validated multi-level dimension hierarchy detected; keeping a truthful Star/Fact model.' if schema=='snowflake' else 'No validated multi-level hierarchy; simpler Star Schema selected.'
    return ETLPlan(base_table=base,fact_table='fact_'+clean(base),schema_type=selected,
                   schema_reason=reason,joins=[JoinStep(**j) for j in joins],dimensions=dims)

def add_dates(plan,profile):
    dates=[]
    for c in profile['tables'][plan.base_table]['columns']:
        if c['semantic_type']=='date' and c['date_parse_ratio']>=.8:
            dates.append(c['name'])
    # use one primary transaction date dimension; log additional date columns in profile, avoid ambiguous date_key
    if dates:
        plan.date_features=[DateFeature(source_column=dates[0],features=['year','month','quarter'],reason='Type-validated transaction date')]
    return dates

def check_formula(item,plan,frames,candidates):
    if item.operation!='multiply':return 'unapproved operator (only verified rate × quantity supported)'
    if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',item.name):return 'invalid output name'
    if item.name in {c for t in frames for c in frames[t].columns} or item.name=='date_key':return 'output name already exists'
    acceptable={frozenset(v['inputs']) for v in candidates}
    if frozenset(item.inputs) not in acceptable:return 'formula not supported by compatible units and known joined columns'
    return None

def resolve_domain(suggestion,profile,*,subdomain='',domain_evidence=None,business_processes=None):
    """Return an evidence-checked, synonym-aware, open-vocabulary domain decision."""
    schema,reason=infer_domain(profile)
    return assessment(profile,suggestion,llm_subdomain=subdomain,
                      llm_evidence=domain_evidence,llm_business_processes=business_processes,
                      schema_label=schema,schema_reason=reason)


def _save_domain(plan, decision):
    plan.domain=decision['domain']
    plan.domain_source=decision['source']
    plan.domain_subdomain=decision['subdomain']
    plan.domain_confidence=decision['confidence_level']
    plan.domain_evidence=decision['evidence']
    plan.business_processes=decision['business_processes']
    plan.semantic_notes.append(decision['explanation'])

def _apply_candidates(plan,suggestions,candidates,frames):
    rejected=[];accepted=[]
    for item in suggestions:
        why=check_formula(item,plan,frames,candidates)
        if why:rejected.append({'formula':item.model_dump(),'reason':why});continue
        if any(set(x.inputs)==set(item.inputs) for x in accepted):continue
        if any(x.name==item.name for x in accepted):
            rejected.append({'formula':item.model_dump(),'reason':'duplicate derived name'});continue
        accepted.append(item)
    plan.derived_columns.extend(accepted)
    for x in accepted:plan.measure_sources[x.name]='llm_validated'
    return rejected

def _fallback(plan,candidates):
    repairs=[];existing={frozenset(x.inputs) for x in plan.derived_columns}
    names={x.name for x in plan.derived_columns}
    for c in candidates:
        if frozenset(c['inputs']) in existing:continue
        if c['name'] in names:continue
        plan.derived_columns.append(DerivedColumn(name=c['name'],operation='multiply',inputs=c['inputs'],reason='Validated unit-rate fallback: '+c['reason']))
        plan.measure_sources[c['name']]='validated_rule_fallback'
        repairs.append('Added validated fallback: '+c['name'])
        existing.add(frozenset(c['inputs']));names.add(c['name'])
    return repairs

def build_plan(profile,frames,use_llm=True,client=None,schema="star"):
    plan=structure_plan(profile,frames,schema=schema)
    repairs=[];debug=[];evidence,reason=infer_domain(profile)
    add_dates(plan,profile)
    candidates=measure_candidates(plan,profile,frames)
    _save_domain(plan,resolve_domain('unknown',profile))
    if not use_llm:
        repairs+=_fallback(plan,candidates)
        plan.planner_summary='Deterministic structure, profiled semantic types and validated rate/quantity suggestions. '+reason
        return plan,'validated_fallback',repairs,debug
    client=client or OllamaClient()
    context=make_semantic_context(profile,frames,plan)
    failure='';suggestion=None
    for attempt in range(1,4):
        user=json.dumps(context,ensure_ascii=False,default=str)
        if failure:user+='\n\nPREVIOUS PROPOSAL REJECTED: '+failure+'\nTry again using only valid candidate formulas. Return an empty derived_columns array if none are justified.'
        try:
            raw,trace=client.generate_json(SYSTEM_PROMPT,user,json_schema=SemanticSuggestion.model_json_schema(),retries=1,timeout=90)
            debug.extend([{**d,'semantic_attempt':attempt} for d in trace]);s=SemanticSuggestion.model_validate(raw)
        except Exception as exc:
            failure=f'{type(exc).__name__}: {exc}'
            debug.append({'semantic_attempt':attempt,'error':failure})
            # Ollama offline: do not waste three long requests
            if 'ConnectionError' in failure or 'ConnectTimeout' in failure:break
            continue
        if attempt==1:
            _save_domain(plan,resolve_domain(s.domain,profile,subdomain=s.subdomain,
                domain_evidence=s.domain_evidence,business_processes=s.business_processes))
        rejected=_apply_candidates(plan,s.derived_columns,candidates,frames)
        if rejected:
            repairs.extend('Rejected LLM proposal: '+x['reason'] for x in rejected)
            debug.append({'semantic_attempt':attempt,'validation_rejections':rejected})
            failure=json.dumps(rejected,ensure_ascii=False)
            if attempt<3:continue
        elif not s.derived_columns and candidates and attempt<2:
            failure='No calculated measures were suggested despite compatible candidate measures; reconsider.'
            continue
        suggestion=s;break
    repairs+=_fallback(plan,candidates)
    if suggestion is None:plan.semantic_notes.append('LLM unavailable or all proposals invalid; validated fallback used.')
    else:plan.semantic_notes.append(suggestion.explanation)
    plan.planner_summary='Intelligent ETL plan: structural inference + constrained semantic suggestions + validation. '+reason
    mode='llm_validated' if suggestion is not None else 'fallback_after_llm_error'
    debug.append({'stage':'final_decision','domain':plan.domain,'domain_source':plan.domain_source,
                  'domain_subdomain':plan.domain_subdomain,'domain_confidence':plan.domain_confidence,
                  'domain_evidence':plan.domain_evidence,
                  'measure_sources':plan.measure_sources,'repairs':repairs})
    return plan,mode,repairs,debug
