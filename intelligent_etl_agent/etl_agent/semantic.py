"""Open-vocabulary semantic hints and guarded dimensionally-consistent rate calculations.

Domain labels are hints, not switches that determine whether a calculation is allowed.
No unverified LLM arithmetic is executed.
"""
from __future__ import annotations
import re
import pandas as pd
from .models import ETLPlan

DOMAIN_CUES={
 'car_rental': ('rental','vehicle','daily_rate','rental_days','car_hire','fleet'),
 'logistics': ('parcel','courier','shipment','delivery','tracking','shipping'),
 'hospitality': ('hotel','stay','guest','room','nightly','booking'),
 'energy': ('electricity','kwh','meter','tariff','energy','power'),
 'telecom': ('subscriber','network','data_gb','call','bandwidth','session'),
 'restaurant': ('menu','dish','dining','table_code','ordered_at'),
 'retail': ('sale','store','sku','products','basket','item','orders'),
 'manufacturing': ('factory','production','machine','workorder','assembly'),
}

def infer_domain(profile):
    terms=[table.lower() for table in profile['tables']]
    for t in profile['tables'].values():terms.extend(c['name'].lower() for c in t['columns'])
    scores={domain:sum(any(cue in x for cue in cues) for x in terms) for domain,cues in DOMAIN_CUES.items()}
    ordered=sorted(scores.items(),key=lambda kv:kv[1],reverse=True)
    if ordered[0][1]<2 or ordered[0][1]==ordered[1][1]:return 'unknown','Insufficient or ambiguous schema indicators'
    return ordered[0][0],f'Candidate domain from schema terms: {ordered[0][0]} (score {ordered[0][1]})'

def norm(s):return re.sub('[^a-z0-9]+','_',s.lower()).strip('_')
def quantity_unit(name):
    s=norm(name)
    if any(x in s for x in ('rate','price','fee','cost','per_')):return None
    if any(t in s for t in ('rental_days','days_rented','duration_days','number_of_days')):return 'day'
    if any(t in s for t in ('nights','night_count','nights_booked')):return 'night'
    if any(t in s for t in ('operating_hours','usage_hours','duration_hours','hours_used')):return 'hour'
    if any(t in s for t in ('kwh_consumed','consumption_kwh','energy_kwh','kwh_used')):return 'kwh'
    if any(t in s for t in ('data_gb','usage_gb','gb_used','volume_gb')):return 'gb'
    if 'weight_kg' in s or s.endswith('_kg'):return 'kg'
    if any(t in s for t in ('quantity','qty','units_sold','unit_count','items_sold','pieces')):return 'unit'
    if any(t in s for t in ('volume_l','liters','litres')):return 'liter'
    # days / hours can be generic but are durations, not dates
    if s in ('days','duration_days'):return 'day'
    if s in ('hours','duration_hours'):return 'hour'
    return None

def rate_unit(name):
    s=norm(name)
    if not any(x in s for x in ('price','rate','cost','fee','charge','tariff')):return None
    synonyms={'kg':'kg','kilogram':'kg','kilograms':'kg','hours':'hour','day':'day','days':'day',
      'night':'night','nights':'night','kwh':'kwh','gb':'gb','gigabyte':'gb',
      'unit':'unit','items':'unit','item':'unit','piece':'unit','liter':'liter','litre':'liter'}
    m=re.search(r'(?:^|_)per_([a-z]+)(?:_|$)',s)
    if m:return synonyms.get(m.group(1))
    if s in ('daily_rate','daily_price','price_daily','day_rate','rate_daily'):return 'day'
    if s.startswith('nightly_') or s in ('night_rate','room_rate_per_night'):return 'night'
    if s in ('hourly_rate','hourly_cost'):return 'hour'
    if s in ('unit_price','price_per_unit','price_each','price_unit','selling_price','unit_cost'):return 'unit'
    return None

def numeric_columns(frames):
    return {t:{c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])} for t,df in frames.items()}

def candidate_name(unit,rate,domain):
    if unit=='day' and domain=='car_rental':return 'estimated_rental_amount'
    if unit=='night' and domain=='hospitality':return 'estimated_booking_value'
    if unit=='kg' and domain=='logistics':return 'estimated_shipping_charge'
    if unit=='unit':return 'estimated_revenue'
    if unit=='kwh':return 'estimated_energy_cost'
    if unit=='gb':return 'estimated_usage_cost'
    if unit=='hour':return 'estimated_operating_cost'
    return 'estimated_amount'

def measure_candidates(plan:ETLPlan,profile,frames):
    domain,_=infer_domain(profile);base=plan.base_table
    reachable=[base]+[j.right_table for j in plan.joins]
    numbers=numeric_columns(frames)
    counts={col:sum(col in frames[t].columns for t in reachable) for col in set().union(*[set(frames[t].columns) for t in reachable])}
    found=[]
    for qty in numbers[base]:
        unit=quantity_unit(qty)
        if not unit or counts[qty]!=1:continue
        for table in reachable:
            for rate in numbers[table]:
                if qty==rate or counts[rate]!=1 or rate_unit(rate)!=unit:continue
                # Positive unit/rate values are expected; flag suspicious values rather than silently changing them.
                found.append({'name':candidate_name(unit,rate,domain),'operation':'multiply',
                     'inputs':[qty,rate], 'reason':f'{qty} has units of {unit}; {rate} is a rate per {unit}. This is only an estimated amount; pricing terms may vary.',
                     'rate_source_table':table,'unit':unit,'confidence':0.85})
    found.sort(key=lambda v:(v['inputs'][0],v['inputs'][1]))
    unique=[];names=set();pairs=set()
    for v in found:
        p=tuple(v['inputs'])
        if p in pairs:continue
        if v['name'] in names:v['name']+='_'+norm(v['inputs'][0])
        names.add(v['name']);pairs.add(p);unique.append(v)
    return unique[:12]

def make_semantic_context(profile,frames,plan):
    reachable=[plan.base_table]+[j.right_table for j in plan.joins]
    return {'tables':{n:{'rows':profile['tables'][n]['rows'],
           'columns':[{'name':c['name'],'dtype':c['dtype'],'meaning_hint':c['semantic_type'],
                       'examples':c['sample_values'][:3]} for c in profile['tables'][n]['columns']]} for n in reachable},
       'base_table':plan.base_table,
       'dataset_overview':{n:{'rows':meta['rows'],
           'columns':[{'name':c['name'],'semantic_type':c['semantic_type'],
                       'example':c['sample_values'][:1]} for c in meta['columns'][:40]]}
           for n,meta in profile['tables'].items()},
       'validated_relationship_candidates':profile['relationship_candidates'][:25],
       'validated_candidate_formulas':measure_candidates(plan,profile,frames),
       'instruction':'Infer a domain from ALL tables in dataset_overview, not only joined tables. Cite actual table/column names as domain_evidence. Propose only defensible calculations; do not output joins or arbitrary Python.'}
