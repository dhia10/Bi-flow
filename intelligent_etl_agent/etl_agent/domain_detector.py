"""Open-vocabulary, evidence-checked business domain reconciliation.

No finite industry allow-list: novel LLM labels can be accepted when backed by
real input column/table names. Unknown remains a valid outcome for ambiguous data.
"""
from __future__ import annotations

import re
from typing import Any

# Broad industries and their common expressions. These are synonyms, not the
# set of industries permitted for the LLM to discover.
ALIASES = {
    'retail': 'retail', 'online_retail': 'retail', 'online_retail_orders': 'retail',
    'ecommerce': 'retail', 'e_commerce': 'retail', 'electronic_commerce': 'retail',
    'online_shopping': 'retail', 'shopping': 'retail', 'sales': 'retail',
    'hospitality': 'hospitality', 'hotel': 'hospitality', 'hotels': 'hospitality',
    'lodging': 'hospitality', 'accommodation': 'hospitality',
    'logistics': 'logistics', 'shipping': 'logistics', 'parcel_delivery': 'logistics',
    'transportation': 'transportation', 'aviation': 'aviation', 'airline': 'aviation',
    'car_rental': 'car_rental', 'car_rentals': 'car_rental', 'vehicle_rental': 'car_rental',
    'vehicle_rentals': 'car_rental',
    'energy': 'energy', 'electricity': 'energy', 'renewable_energy': 'energy',
    'telecom': 'telecom', 'telecommunications': 'telecom',
    'restaurant': 'restaurant', 'restaurants': 'restaurant', 'food_service': 'restaurant',
    'manufacturing': 'manufacturing', 'industrial_production': 'manufacturing',
    'healthcare': 'healthcare', 'medical': 'healthcare', 'hospital': 'healthcare',
    'banking': 'banking', 'bank': 'banking', 'financial_services': 'finance',
    'finance': 'finance', 'insurance': 'insurance',
    'education': 'education', 'university': 'education', 'school': 'education',
    'real_estate': 'real_estate', 'property_management': 'real_estate',
    'agriculture': 'agriculture', 'farming': 'agriculture',
}
SUBDOMAINS = {
    'online_retail': 'ecommerce', 'online_retail_orders': 'ecommerce',
    'ecommerce': 'ecommerce', 'e_commerce': 'ecommerce',
    'electronic_commerce': 'ecommerce', 'online_shopping': 'ecommerce',
    'renewable_energy': 'renewable_energy',
}
GENERIC_LABELS = {'', 'unknown', 'none', 'other', 'general', 'data', 'dataset', 'business'}
GENERIC_WORDS = {'data','dataset','records','record','table','tables','system','management',
                 'business','online','information','id','date','time','value','name','type',
                 'details','detail','status','the','for','of','and'}


def normalize(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', str(value or '').lower()).strip('_')


def taxonomy(label: str, subdomain: str = '') -> tuple[str, str]:
    """Normalize synonyms, but preserve previously unseen, supported labels."""
    raw = normalize(label)
    normalized = ALIASES.get(raw, raw)
    # Common descriptive process suffixes should not make a domain look new.
    # The label remains open vocabulary for every other case.
    if normalized == raw:
        for prefix, broad in (('online_retail_', 'retail'), ('ecommerce_', 'retail'),
                              ('e_commerce_', 'retail'), ('retail_', 'retail')):
            if raw.startswith(prefix):
                normalized = broad
                break
    sub = normalize(subdomain) or SUBDOMAINS.get(raw, '')
    if not sub and normalized == 'retail' and (raw.startswith(('online_retail_', 'ecommerce_', 'e_commerce_'))):
        sub = 'ecommerce'
    if sub == normalized:
        sub = ''
    return normalized, sub


def _real_identifiers(profile: dict) -> dict[str, str]:
    available: dict[str, str] = {}
    for table, meta in profile.get('tables', {}).items():
        available[normalize(table)] = table
        for column in meta.get('columns', []):
            name = column['name']
            available[normalize(name)] = name
            available[normalize(table + '.' + name)] = table + '.' + name
    return available


def _validated_evidence(profile: dict, claims: list[str] | None) -> list[str]:
    identifiers = _real_identifiers(profile)
    accepted: list[str] = []
    for claim in claims or []:
        key = normalize(claim)
        if key in identifiers and identifiers[key] not in accepted:
            accepted.append(identifiers[key])
    return accepted[:16]


def _textual_evidence(profile: dict, label: str) -> list[str]:
    """Conservative lexical signals for a *new* domain without fixed keywords."""
    terms = [w for w in normalize(label).split('_') if len(w) >= 4 and w not in GENERIC_WORDS]
    if not terms:
        return []
    found = []
    for table, meta in profile.get('tables', {}).items():
        for candidate in [table] + [c['name'] for c in meta.get('columns', [])]:
            words = set(normalize(candidate).split('_'))
            if words.intersection(terms):
                if candidate not in found:
                    found.append(candidate)
    return found[:16]


def assessment(profile: dict, llm_label: str = 'unknown', *,
               llm_subdomain: str = '', llm_evidence: list[str] | None = None,
               llm_business_processes: list[str] | None = None,
               schema_label: str = 'unknown', schema_reason: str = '') -> dict[str, Any]:
    """Select a domain from schema and LLM evidence without false conflicts.

    Returns domain, subdomain, source, confidence_level, evidence, processes,
    and explanation. Confidence is qualitative rather than a made-up probability.
    """
    llm_domain, sub = taxonomy(llm_label, llm_subdomain)
    schema_domain, _ = taxonomy(schema_label)
    verified = _validated_evidence(profile, llm_evidence)
    lexical = _textual_evidence(profile, llm_label)
    evidence = list(dict.fromkeys(verified + lexical))[:16]
    processes = [normalize(p) for p in (llm_business_processes or [])
                 if isinstance(p, str) and normalize(p) not in GENERIC_LABELS][:12]
    note = ''
    source = 'unknown'
    confidence = 'low'
    result_domain = 'unknown'

    if llm_domain in GENERIC_LABELS:
        if schema_domain != 'unknown':
            result_domain = schema_domain
            source = 'schema_evidence'
            confidence = 'medium'
            note = 'LLM did not identify a supported domain; using schema evidence. '
        else:
            note = 'Insufficient evidence to identify the business domain. '
    elif schema_domain != 'unknown' and llm_domain == schema_domain:
        result_domain = schema_domain
        source = 'llm_schema_agreement'
        confidence = 'high' if evidence else 'medium'
        note = 'LLM label and schema evidence agree after synonym normalization. '
    elif schema_domain != 'unknown' and llm_domain != schema_domain:
        # Do not let two genuine, different domains silently override each other.
        result_domain = 'unknown'
        source = 'conflicting_evidence'
        note = f'LLM proposed {llm_domain} but schema suggests {schema_domain}; separate verification required. '
        if len(verified) >= 2 and len(lexical) >= 2:
            # A different, supported new domain is still uncertain in a mixed-domain dataset.
            note += 'The LLM label has supporting columns, but the conflict is unresolved. '
    elif len(verified) >= 2 or len(lexical) >= 2:
        result_domain = llm_domain
        source = 'llm_evidence_validated'
        confidence = 'medium'
        note = 'An open-vocabulary LLM domain is supported by actual input identifiers. '
    else:
        note = 'LLM proposed a domain but provided insufficient verifiable evidence. '

    # A more specific label only accompanies a supported domain.
    if result_domain == 'unknown':
        sub = ''
        processes = []
    return {
        'domain': result_domain,
        'subdomain': sub,
        'source': source,
        'confidence_level': confidence,
        'evidence': evidence,
        'business_processes': processes,
        'explanation': note + schema_reason,
    }
