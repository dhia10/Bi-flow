"""Conservative FK→PK inference. Only unique dimension keys become automatic joins."""
from __future__ import annotations
import re
import pandas as pd
from collections import defaultdict

TRANSACTION_HINTS=('order','orders','transaction','sales','sale','booking','stay','invoice','event','movement','parcel','rental','contract','reading','usage','activity','fact','line','record','shipment','flight')
KEY_TOKENS={'id','key','code','ref','uuid','number','no'}
def tokens(s):return set(filter(None,re.split('[^a-z0-9]+',s.lower())))
def looks_like_date(s):
    t=tokens(s)
    if t & {'days','hours','minutes','nights','duration'} and not t & {'date','timestamp'}:return False
    return bool(t & {'date','timestamp','datetime'} or s.lower().endswith(('_at','_on')) or s.lower() in ('checkin','checkout'))
def key_like(s):return bool(tokens(s)&KEY_TOKENS)
def _values(s):return set(s.dropna().astype(str).head(20000))
def infer_relationships(frames):
    found=[];names=list(frames)
    for i,ln in enumerate(names):
        for rn in names[i+1:]:
            left,right=frames[ln],frames[rn]
            for lc in left:
                if not key_like(lc):continue
                for rc in right:
                    if not key_like(rc):continue
                    same=lc.lower()==rc.lower()
                    a,b=tokens(lc),tokens(rc)
                    similarity=len(a&b)/max(1,len(a|b))
                    if not same and similarity < .5:continue
                    lv,rv=_values(left[lc]),_values(right[rc])
                    if not lv or not rv:continue
                    shared=len(lv&rv)
                    # evidence of a valid link in at least one direction
                    coverage_l=shared/max(1,len(lv));coverage_r=shared/max(1,len(rv))
                    if max(coverage_l,coverage_r) < .65:continue
                    ul=left[lc].notna().all() and left[lc].is_unique
                    ur=right[rc].notna().all() and right[rc].is_unique
                    # A PK or unique dimension key is necessary; do not automatically perform M:N joins
                    if not (ul or ur):continue
                    score=round(.4*float(same)+.2*similarity+.4*max(coverage_l,coverage_r),4)
                    found.append({'left_table':ln,'left_column':lc,'right_table':rn,'right_column':rc,
                                  'score':score,'value_overlap':round(max(coverage_l,coverage_r),4),
                                  'left_key_unique':bool(ul),'right_key_unique':bool(ur),
                                  'coverage_left_to_right':round(coverage_l,4),
                                  'coverage_right_to_left':round(coverage_r,4),
                                  'reason':f'Key similarity with sample FK coverage {max(coverage_l,coverage_r):.0%}; unique key side verified.'})
    return sorted(found,key=lambda r:(r['score'],r['value_overlap']),reverse=True)
def choose_base_table(frames,relationships):
    degree=defaultdict(set)
    for r in relationships:
        degree[r['left_table']].add(r['left_column']);degree[r['right_table']].add(r['right_column'])
    maxrows=max(map(len,frames.values()))
    def score(item):
        name,df=item;low=name.lower()
        trans=sum(1 for t in TRANSACTION_HINTS if t in low)
        # multiple links + events + number of rows, but not solely a large lookup table
        return (min(2,trans)*4+len(degree[name])*2+len(df)/maxrows*2+
                sum(.5 for col in df.columns if looks_like_date(col)))
    return max(frames.items(),key=score)[0]
def build_join_tree(base_table,frames,relationships):
    """Build a safe, limited-depth dimension path, supporting snowflake inputs.

    Every lookup join must point to a unique key and have evidence of FK overlap.
    Fact-level FK projection is performed downstream for indirect dimensions.
    """
    joined={base_table};depth={base_table:0};joins=[]
    for _ in range(len(frames)-1):
        candidates=[]
        for r in relationships:
            if r['left_table'] in joined and r['right_table'] not in joined and r['right_key_unique']:
                src=r['left_table'];dest=r['right_table'];lc=r['left_column'];rc=r['right_column']
            elif r['right_table'] in joined and r['left_table'] not in joined and r['left_key_unique']:
                src=r['right_table'];dest=r['left_table'];lc=r['right_column'];rc=r['left_column']
            else:continue
            if depth[src]>=2:continue
            if lc not in frames[src].columns:continue
            # prefer direct star joins, then snowflake dimensions when necessary
            candidates.append((depth[src],-r['score'],src,dest,lc,rc,r))
        if not candidates:break
        _,_,src,dest,lc,rc,r=min(candidates,key=lambda x:(x[0],x[1],x[3]))
        joins.append({'source_table':src,'right_table':dest,'left_on':lc,'right_on':rc,
                      'how':'left','reason':r['reason']})
        joined.add(dest);depth[dest]=depth[src]+1
    return joins
