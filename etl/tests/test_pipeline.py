"""End-to-end and adversarial regression suite. No external Ollama server required."""
import json
from pathlib import Path
import pandas as pd
import pytest
from etl_agent import ETLAgent
from etl_agent.profiler import load_data_directory,build_profile
from etl_agent.planner import build_plan
from etl_agent.relationships import infer_relationships
from etl_agent.executor import execute_plan

ROOT=Path(__file__).resolve().parents[1]
EXAMPLES=ROOT/'data'/'examples'

@pytest.mark.parametrize('domain,expected,measure,rows',[('car_rental','car_rental','estimated_rental_amount',28),
 ('logistics','logistics','estimated_shipping_charge',12),
 ('hotel','hospitality','estimated_booking_value',5),
 ('restaurant','restaurant','estimated_revenue',30),
 ('energy','energy','estimated_energy_cost',32),
 ('retail','retail','estimated_revenue',8)])
def test_end_to_end_multi_domain(tmp_path,domain,expected,measure,rows):
    result=ETLAgent(use_llm=False).run(EXAMPLES/domain,tmp_path/domain)
    assert result['status']=='success'
    assert result['domain']==expected
    assert result['fact_rows']==rows
    assert measure in result['fact_columns']
    assert result['measure_sources'][measure]=='validated_rule_fallback'
    assert (tmp_path/domain/'star_schema.png').read_bytes()[:8]==b'\x89PNG\r\n\x1a\n'
    assert '<svg' in (tmp_path/domain/'star_schema.svg').read_text(encoding='utf-8')
    assert (tmp_path/domain/'handoff_manifest.json').exists()
    assert json.load((tmp_path/domain/'state.json').open())['status']=='success'
    assert result['validation']['passed']

@pytest.mark.parametrize('domain', ['car_rental','logistics','hotel','restaurant','energy','retail'])
def test_no_bad_dates_and_same_grain(tmp_path,domain):
    result=ETLAgent(use_llm=False).run(EXAMPLES/domain,tmp_path/domain)
    plan=json.load((tmp_path/domain/'etl_plan.json').open())
    assert all(x['source_column']!='rental_days' for x in plan['date_features'])
    frames=load_data_directory(EXAMPLES/domain)
    assert result['fact_rows']==len(frames[plan['base_table']])
    assert all(c.get('name')!='fact_grain_preserved' or c['passed'] for c in result['validation']['checks'])

def test_indirect_fk_reaches_tariff_table(tmp_path):
    result=ETLAgent(False).run(EXAMPLES/'energy',tmp_path)
    assert 'dim_tariff' in result['dimension_tables']
    assert 'tariff_code' in result['fact_columns']
    j=json.load((tmp_path/'etl_plan.json').open())
    assert any(x['source_table']=='meter_registry' and x['right_table']=='tariff_catalog' for x in j['joins'])
    df=pd.read_csv(result['saved']['fact_csv'])
    assert (df['estimated_energy_cost']>=0).all()

def test_reject_many_to_many_no_row_explosion(tmp_path):
    folder=tmp_path/'in';folder.mkdir()
    pd.DataFrame({'order_id':['A','A','B'],'quantity':[2,4,1]}).to_csv(folder/'line_items.csv',index=False)
    pd.DataFrame({'order_id':['A','A','B'],'description':['x','y','z']}).to_csv(folder/'events.csv',index=False)
    result=ETLAgent(False).run(folder,tmp_path/'out')
    assert result['fact_rows'] in (3,3)
    assert all(x['dimension_table'] not in ('dim_events','dim_line_items') for x in result['relationship_mapping'])

def test_unknown_domain_no_invented_measure(tmp_path):
    folder=tmp_path/'in';folder.mkdir()
    pd.DataFrame({'key':['AA','BB'],'x':[2,3],'y':[8,9]}).to_csv(folder/'random_matrix.csv',index=False)
    result=ETLAgent(False).run(folder,tmp_path/'out')
    assert result['domain']=='unknown'
    assert result['derived_columns']==[]
    assert result['fact_rows']==2

def test_orphan_fk_reported_without_row_loss(tmp_path):
    folder=tmp_path/'in';folder.mkdir()
    pd.DataFrame({'purchase_id':[1,2,3],'sku_code':['X','X','MISSING'],'quantity':[1,2,3]}).to_csv(folder/'purchase_events.csv',index=False)
    pd.DataFrame({'sku_code':['X','Y'],'unit_price':[4,7]}).to_csv(folder/'inventory_catalog.csv',index=False)
    result=ETLAgent(False).run(folder,tmp_path/'out')
    # Inference can reject relationships with low coverage; if inferred, FK warnings must be explicit.
    assert result['fact_rows']==3
    for check in result['validation']['checks']:
        if check['name'].startswith('fk_coverage:') and check['details']['unmatched']:
            assert not check['passed']

def test_file_inputs_json_and_excel(tmp_path):
    folder=tmp_path/'mixed';folder.mkdir()
    pd.DataFrame({'log_id':[1,2],'status':['ok','error']}).to_json(folder/'logs.json',orient='records')
    pd.DataFrame({'person_code':['A','B'],'name':['Ana','Bo']}).to_excel(folder/'people.xlsx',index=False)
    f=load_data_directory(folder)
    assert set(f)=={'logs','people'}

def test_validated_llm_repair_loop(tmp_path):
    class FakeLLM:
        def __init__(self):self.calls=0
        def generate_json(self,*a,**kw):
            self.calls+=1
            if self.calls==1:return {'domain':'car_rental','derived_columns':[{'name':'unrelated','operation':'multiply','inputs':['rental_days','customer_ref'],'reason':'bad'}]},[{'attempt':1}]
            return {'domain':'car_rental','derived_columns':[{'name':'estimated_rental_amount','operation':'multiply','inputs':['rental_days','daily_rate'],'reason':'duration and daily rate'}]},[{'attempt':1}]
    fake=FakeLLM()
    result=ETLAgent(use_llm=True,client=fake).run(EXAMPLES/'car_rental',tmp_path)
    assert fake.calls==2
    assert result['measure_sources']['estimated_rental_amount']=='llm_validated'
    assert any('Rejected LLM proposal' in x for x in result['auto_repairs'])

def test_offline_llm_graceful_fallback(tmp_path):
    class Offline:
        def generate_json(self,*a,**kw):raise ConnectionError('offline')
    result=ETLAgent(use_llm=True,client=Offline()).run(EXAMPLES/'car_rental',tmp_path)
    assert result['planner_mode']=='fallback_after_llm_error'
    assert result['measure_sources']['estimated_rental_amount']=='validated_rule_fallback'

def test_dont_overwrite_source_files(tmp_path):
    folder=tmp_path/'in';folder.mkdir()
    p=folder/'orders.csv';p.write_text('order_id,quantity\n1,3\n2,4\n',encoding='utf-8')
    original=p.read_bytes()
    ETLAgent(False).run(folder,tmp_path/'out')
    assert p.read_bytes()==original

def test_state_failure_record(tmp_path):
    out=tmp_path/'out'
    with pytest.raises(FileNotFoundError):ETLAgent(False).run(tmp_path/'missing',out)
    assert json.loads((out/'state.json').read_text())['status']=='failed'


def test_snowflake_energy_physical_hierarchy_and_diagram(tmp_path):
    """Physical normalization: tariff_code must be in dim_meter, not copied into fact."""
    out=tmp_path/'snow'
    result=ETLAgent(use_llm=False,schema='snowflake').run(EXAMPLES/'energy',out)
    assert result['schema_type']=='snowflake_schema'
    assert result['star_schema']['schema_type']=='snowflake_schema'
    assert (out/'snowflake_schema.png').read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
    assert '<svg' in (out/'snowflake_schema.svg').read_text(encoding='utf-8')
    assert 'tariff_code' not in result['fact_columns']
    assert 'estimated_energy_cost' in result['fact_columns']
    assert 'tariff_code' in pd.read_csv(out/'dim_meter.csv').columns
    assert 'tariff_code' in pd.read_csv(out/'dim_tariff.csv').columns
    hierarchical=[r for r in result['relationship_mapping'] if r['relationship_type']=='dimension_to_dimension']
    assert len(hierarchical)==1
    assert hierarchical[0]['source_table']=='dim_meter'
    assert hierarchical[0]['source_column']=='tariff_code'
    assert hierarchical[0]['dimension_table']=='dim_tariff'
    checks={c['name']:c for c in result['validation']['checks']}
    assert checks['fk_coverage:dim_meter->dim_tariff']['passed']
    assert result['validation']['passed']
    assert json.loads((out/'etl_plan.json').read_text())['schema_type']=='snowflake_schema'
    assert json.loads((out/'handoff_manifest.json').read_text())['schema_type']=='snowflake_schema'


def test_star_default_unchanged_energy(tmp_path):
    out=tmp_path/'star'
    result=ETLAgent(use_llm=False).run(EXAMPLES/'energy',out)
    assert result['schema_type']=='star_schema'
    assert (out/'star_schema.png').exists()
    assert not (out/'snowflake_schema.png').exists()
    assert 'tariff_code' in result['fact_columns']
    assert not any(r['relationship_type']=='dimension_to_dimension' for r in result['relationship_mapping'])


def test_auto_schema_selects_snowflake_only_when_hierarchy(tmp_path):
    a=ETLAgent(use_llm=False,schema='auto').run(EXAMPLES/'energy',tmp_path/'energy')
    b=ETLAgent(use_llm=False,schema='auto').run(EXAMPLES/'car_rental',tmp_path/'car')
    assert a['schema_type']=='snowflake_schema'
    assert b['schema_type']=='star_schema'


def test_forced_snowflake_falls_back_when_no_hierarchy(tmp_path):
    out=tmp_path/'car'
    result=ETLAgent(use_llm=False,schema='snowflake').run(EXAMPLES/'car_rental',out)
    assert result['schema_type']=='star_schema'
    assert 'no validated multi-level dimension hierarchy' in result['schema_reason']
    assert (out/'star_schema.png').exists()


def test_dimension_to_dimension_orphans_are_reported(tmp_path):
    folder=tmp_path/'source';folder.mkdir()
    pd.DataFrame({'reading_id':['A','B','C','D'],'meter_id':['M1','M2','M3','M4'],
                  'kwh_consumed':[2,3,4,5]}).to_csv(folder/'meter_readings.csv',index=False)
    pd.DataFrame({'meter_id':['M1','M2','M3','M4'],'tariff_code':['T1','T1','T2','T_BAD']}).to_csv(folder/'meter_registry.csv',index=False)
    pd.DataFrame({'tariff_code':['T1','T2'],'price_per_kwh':[.1,.2]}).to_csv(folder/'tariff_catalog.csv',index=False)
    result=ETLAgent(use_llm=False,schema='snowflake').run(folder,tmp_path/'out')
    # If uncertain relationship inference does not validate the hierarchy, it should honestly stay star.
    if result['schema_type']=='snowflake_schema':
        checks=[c for c in result['validation']['checks'] if c['name']=='fk_coverage:dim_meter->dim_tariff']
        assert checks and checks[0]['details']['unmatched']==1
        assert not checks[0]['passed'] and result['validation']['has_warnings']
    else:
        assert 'no validated multi-level dimension hierarchy' in result['schema_reason']


def test_schema_name_validated():
    with pytest.raises(ValueError):ETLAgent(schema='galaxy')
