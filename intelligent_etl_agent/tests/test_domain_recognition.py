"""Domain detector regression tests for Olist and novel domains."""
import json
import pandas as pd
from etl_agent.agent import ETLAgent
from etl_agent.domain_detector import assessment
from etl_agent.profiler import build_profile
from etl_agent.planner import resolve_domain, make_semantic_context, structure_plan


def sample_olist():
    return {
        'olist_orders_dataset': pd.DataFrame({'order_id':['o1','o2'],'customer_id':['c1','c2'],
                                              'order_purchase_timestamp':['2021-01-02','2021-01-03']}),
        'olist_customers_dataset':pd.DataFrame({'customer_id':['c1','c2'],'customer_city':['X','Y']}),
        'olist_order_items_dataset':pd.DataFrame({'order_id':['o1','o1','o2'],'order_item_id':[1,2,1],
                                                  'product_id':['p1','p2','p1'],'price':[10.,12.,13.]}),
        'olist_order_payments_dataset':pd.DataFrame({'order_id':['o1','o2'],'payment_type':['card','cash']}),
        'olist_order_reviews_dataset':pd.DataFrame({'order_id':['o1','o2'],'review_score':[5,4]}),
        'olist_products_dataset':pd.DataFrame({'product_id':['p1','p2'],'product_category_name':['a','b']}),
        'olist_sellers_dataset':pd.DataFrame({'seller_id':['s1'],'seller_city':['X']}),
        'olist_geolocation_dataset':pd.DataFrame({'geolocation_zip_code_prefix':['12'],'geolocation_city':['X']}),
        'product_category_name_translation':pd.DataFrame({'product_category_name':['a','b'],
                                                            'product_category_name_english':['a','b']}),
    }


def test_olist_synonyms_not_conflict():
    profile=build_profile(sample_olist())
    out=resolve_domain('online_retail_orders',profile,
                       domain_evidence=['olist_order_items_dataset','order_id','product_id'],
                       business_processes=['order_management','sales'])
    assert out['domain']=='retail'
    assert out['subdomain']=='ecommerce'
    assert out['source']=='llm_schema_agreement'
    assert 'order_id' in out['evidence']


def test_llm_sees_all_nine_tables_even_when_plan_omits_some():
    frames=sample_olist();profile=build_profile(frames)
    plan=structure_plan(profile,frames)
    context=make_semantic_context(profile,frames,plan)
    assert len(context['dataset_overview'])==9
    assert 'olist_order_payments_dataset' in context['dataset_overview']
    assert 'olist_products_dataset' in context['dataset_overview']


def test_new_domain_accepts_verified_real_column_evidence():
    frames={'wind_farms':pd.DataFrame({'turbine_id':['t1','t2'],
                                        'wind_speed_mps':[4,7],
                                        'blade_angle_degrees':[20,22]}),
            'turbine_telemetry':pd.DataFrame({'turbine_id':['t1','t2'],
                                              'rotor_speed_rpm':[30,40]})}
    p=build_profile(frames)
    # Domain not listed in old semantic.py DOMAIN_CUES; accepted from verified input evidence.
    d=assessment(p,'wind_farm_operations',llm_evidence=['turbine_id','wind_speed_mps'],
                 schema_label='unknown')
    assert d['domain']=='wind_farm_operations'
    assert d['source']=='llm_evidence_validated'


def test_unsupported_new_domain_stays_unknown():
    frames={'random_matrix':pd.DataFrame({'id':['x','y'],'a':[1,2],'b':[9,8]})}
    p=build_profile(frames)
    d=assessment(p,'medical_diagnostics',llm_evidence=['patient_diagnosis','blood_pressure'],
                 schema_label='unknown')
    assert d['domain']=='unknown'


def test_report_and_plan_contain_domain_explanation(tmp_path):
    class FakeLLM:
        def generate_json(self,*args,**kwargs):
            return {'domain':'online_retail_orders','subdomain':'ecommerce',
                    'domain_evidence':['olist_orders_dataset','olist_order_items_dataset','order_id'],
                    'business_processes':['sales','orders'],
                    'derived_columns':[],'explanation':'Orders and order items describe sales.'}, []
    directory=tmp_path/'input';directory.mkdir()
    for name, df in sample_olist().items():
        df.to_csv(directory/(name+'.csv'),index=False)
    out=tmp_path/'output'
    result=ETLAgent(use_llm=True,client=FakeLLM()).run(directory,out)
    assert result['domain']=='retail'
    assert result['domain_subdomain']=='ecommerce'
    assert len(json.loads((out/'profile.json').read_text())['tables'])==9
    report=json.loads((out/'etl_report.json').read_text())
    assert report['domain_source']=='llm_schema_agreement'
    assert report['business_processes']==['sales','orders']
    assert report['domain_confidence']=='high'
    assert json.loads((out/'etl_plan.json').read_text())['domain_evidence']
