"""Produce polished star-schema PNG/SVG using Matplotlib (no Graphviz system install)."""
from __future__ import annotations
from pathlib import Path
import math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, PathPatch
from matplotlib.path import Path as MPath

BLUE='#2464a4'; GREEN='#27846a'; TEXT='#233044';MUTED='#6a778b';PAPER='#f5f8fc'; LINE='#91a5bb'

def _dtype(dtype):
    dt=str(dtype)
    if dt.startswith('int') or dt=='Int64':return 'INTEGER'
    if dt.startswith('float'):return 'DECIMAL'
    if 'datetime' in dt:return 'DATETIME'
    if dt=='bool':return 'BOOLEAN'
    return 'TEXT'

def generate_star_schema_image(output_dir,fact_name,fact,dimensions,relations,domain='unknown'):
    """Generate every label from actual output frames and validated relation metadata."""
    folder=Path(output_dir);folder.mkdir(parents=True,exist_ok=True)
    left_names=list(dimensions)[::2];right_names=list(dimensions)[1::2]
    side_count=max(1,len(left_names),len(right_names))
    row_unit=0.38
    max_rows=max([len(df.columns) for df in dimensions.values()]+[len(fact.columns),6])
    card_h=lambda df: min(4.2,0.60+min(len(df.columns),11)*row_unit+.30)
    max_side_h=max([card_h(df) for df in dimensions.values()]+[2.0])
    space=max_side_h+.75
    total_height=max(10.0,side_count*space+3.2,card_h(fact)+5.0)
    total_width=19
    fig,ax=plt.subplots(figsize=(total_width,total_height),dpi=165)
    fig.patch.set_facecolor(PAPER);ax.set_facecolor(PAPER)
    ax.set_xlim(0,19);ax.set_ylim(0,total_height);ax.axis('off')
    ax.text(.7,total_height-.55,'BI-FLOW  /  INTELLIGENT ETL',fontsize=11,color=BLUE,fontweight='bold')
    ax.text(.7,total_height-1.05,'Generated Star Schema' if dimensions else 'Analytical Fact Table (No Validated Dimensions)',fontsize=24 if dimensions else 17,fontweight='bold',color=TEXT)
    ax.text(18.3,total_height-.70,f'DOMAIN   {domain.upper().replace("_"," ")}',fontsize=10,color=MUTED,ha='right')
    ax.text(.7,.32,'Generated from validated ETL output  •  PK = Primary Key  •  FK = Foreign Key  •  ● = Measure',fontsize=10,color=MUTED)
    fact_fk={x['fact_column'] for x in relations}
    dim_pk={x['dimension_table']:x['dimension_column'] for x in relations}
    fact_pk=next((c for c in fact if fact[c].notna().all() and fact[c].is_unique and
       (c.lower().endswith(('_id','_ref','_no','_key')) or c.lower() in ('sale_id','contract_id','tracking_no')) and c not in fact_fk),None)
    cards={}
    def draw_card(name,df,x,cy,w,is_fact):
        h=card_h(df);y=cy-h/2
        shadow=FancyBboxPatch((x+.08,y-.08),w,h,boxstyle='round,pad=0.02,rounding_size=0.15',facecolor='#e2e8f2',linewidth=0,zorder=1)
        ax.add_patch(shadow)
        card=FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.02,rounding_size=0.15',facecolor='white',edgecolor='#d7dfeb',linewidth=1,zorder=2)
        ax.add_patch(card)
        color=BLUE if is_fact else GREEN
        head=FancyBboxPatch((x,y+h-.55),w,.55,boxstyle='round,pad=0.02,rounding_size=0.15',facecolor=color,linewidth=0,zorder=3)
        ax.add_patch(head)
        # white patch square-off bottom header corners
        ax.add_patch(plt.Rectangle((x,y+h-.55),w,.20,facecolor=color,zorder=3,linewidth=0))
        ax.text(x+.2,y+h-.34,name,fontsize=12 if not is_fact else 13,color='white',fontweight='bold',zorder=4)
        ax.text(x+w-.2,y+h-.34,'FACT' if is_fact else 'DIMENSION',fontsize=9,color='white',ha='right',zorder=4)
        pk=dim_pk.get(name)
        for index,(col,dtype) in enumerate(df.dtypes.items()):
            if index>=11:
                ax.text(x+.2,y+.18,f'+ {len(df.columns)-11} more columns',fontsize=9,color=MUTED,zorder=4);break
            yy=y+h-.84-index*row_unit
            tag='PK' if (col==pk or (is_fact and col==fact_pk)) else ('FK' if col in fact_fk and is_fact else ('●' if is_fact and __import__('pandas').api.types.is_numeric_dtype(dtype) else ''))
            ax.text(x+.17,yy,tag,fontsize=9,color=color,fontweight='bold',zorder=4)
            maxletters=30 if w>4.2 else 23
            ax.text(x+.7,yy,str(col)[:maxletters],fontsize=9.4,color=TEXT,zorder=4)
            ax.text(x+w-.18,yy,_dtype(dtype),fontsize=8.2,color=MUTED,ha='right',zorder=4)
        cards[name]={'x':x,'y':y,'h':h,'w':w,'mid':cy}
    center_y=(total_height-1.3)/2
    draw_card(fact_name,fact,7.25,center_y,4.55,True)
    top=total_height-3.0;bottom=max(2.7,max_side_h/2+1.1)
    def positions(length):
        if length==1:return [center_y]
        return [top-(top-bottom)*i/(length-1) for i in range(length)]
    for name,y in zip(left_names,positions(len(left_names))):draw_card(name,dimensions[name],.55,y,5.4,False)
    for name,y in zip(right_names,positions(len(right_names))):draw_card(name,dimensions[name],13.1,y,5.35,False)
    for rel in relations:
        dest=cards.get(rel['dimension_table'])
        if not dest:continue
        left=dest['x']<7
        a=cards[fact_name]
        x1=a['x'] if left else a['x']+a['w']
        x2=dest['x']+dest['w'] if left else dest['x']
        y1=a['mid'];y2=dest['mid']
        mid=x1-.55 if left else x1+.55
        vertices=[(x1,y1),(mid,y1),(mid,y2),(x2,y2)]
        path=MPath(vertices,[MPath.MOVETO,MPath.LINETO,MPath.LINETO,MPath.LINETO])
        ax.add_patch(PathPatch(path,facecolor='none',edgecolor=LINE,linewidth=2,zorder=.5))
        ax.scatter([x1,x2],[y1,y2],s=40,c=[BLUE,GREEN],zorder=5)
        ax.text((x1+x2)/2,(y1+y2)/2+.16,rel['fact_column'][:24],fontsize=7.8,color=MUTED,ha='center')
    png=folder/'star_schema.png';svg=folder/'star_schema.svg'
    fig.savefig(png,bbox_inches='tight',pad_inches=.20,facecolor=fig.get_facecolor())
    fig.savefig(svg,bbox_inches='tight',pad_inches=.20,facecolor=fig.get_facecolor())
    plt.close(fig)
    return {'png':str(png),'svg':str(svg),'schema_type':'star_schema' if dimensions else 'fact_only','fact':fact_name,
            'dimension_count':len(dimensions),'relationship_count':len(relations)}


def generate_schema_image(output_dir, fact_name, fact, dimensions, relations, domain='unknown', schema_type='star_schema'):
    """Draw validated *physical* relationships. Snowflake links connect dimensions to dimensions."""
    if schema_type != 'snowflake_schema':
        result=generate_star_schema_image(output_dir, fact_name, fact, dimensions, relations, domain)
        outdated=('snowflake_schema.png','snowflake_schema.svg')
    else:
        result=generate_snowflake_schema_image(output_dir, fact_name, fact, dimensions, relations, domain)
        outdated=('star_schema.png','star_schema.svg')
    # Runs can reuse the same output directory. Remove only obsolete diagram formats,
    # avoiding confusion between the current physical model and a previous run.
    for name in outdated:
        old=Path(output_dir)/name
        if old.exists():old.unlink()
    return result


def generate_snowflake_schema_image(output_dir, fact_name, fact, dimensions, relations, domain='unknown'):
    """Generate PNG/SVG from normalized dimension relationships (never invent links)."""
    folder=Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    import pandas as pd
    from collections import defaultdict
    nodes={fact_name:fact,**dimensions}
    parents={r['dimension_table']:r.get('source_table',fact_name) for r in relations}
    if not any(p!=fact_name for p in parents.values()):
        # Structural guard: no dimension-to-dimension hierarchy means it isn't a snowflake.
        raise ValueError('Snowflake image requested but no normalized dimension hierarchy exists')
    depth={fact_name:0}
    def node_depth(name,seen=None):
        if name in depth:return depth[name]
        if seen is None:seen=set()
        if name in seen:raise ValueError('Circular dimension relationships cannot be visualized')
        seen.add(name)
        par=parents.get(name)
        if par is None or par not in nodes:raise ValueError('Unmapped dimension parent: '+name)
        depth[name]=node_depth(par,seen)+1
        return depth[name]
    for n in dimensions:node_depth(n)
    levels=defaultdict(list)
    for n,d in depth.items():levels[d].append(n)
    for items in levels.values():items.sort(key=lambda n:(n!=fact_name,n))
    maxlevel=max(levels)
    ncols=maxlevel+1
    card_width=5.65
    card_gap=1.25
    width=1.1+ncols*card_width+maxlevel*card_gap+.5
    rowstep=.32
    def box_h(df):return .85+min(len(df.columns),10)*rowstep+.35
    max_h=max(box_h(df) for df in nodes.values())
    max_items=max(len(levels[level]) for level in levels)
    vertical_step=max_h+.85
    height=max(8.0,3.5+max_items*vertical_step)
    fig,ax=plt.subplots(figsize=(width,height),dpi=150)
    fig.patch.set_facecolor(PAPER);ax.set_facecolor(PAPER)
    ax.set_xlim(0,width);ax.set_ylim(0,height);ax.axis('off')
    ax.text(.65,height-.54,'BI-FLOW  /  INTELLIGENT ETL',fontsize=12,color=BLUE,fontweight='bold')
    ax.text(.65,height-1.11,'Generated Snowflake Schema',fontsize=24,color=TEXT,fontweight='bold')
    ax.text(width-.65,height-.65,'DOMAIN  '+domain.upper().replace('_',' '),fontsize=9.5,ha='right',color=MUTED)
    ax.text(.65,.40,'Actual physical links  •  PK = Primary Key  •  FK = Foreign Key  •  ● = Numeric measure',fontsize=10,color=MUTED)
    ax.text(.65,.17,'Each link points from a foreign key to a unique dimension key; a dimension may reference another dimension.',fontsize=9,color=MUTED)
    positions={}
    pk_by_dim={r['dimension_table']:r['dimension_column'] for r in relations}
    fk_by_node=defaultdict(set)
    for rel in relations:
        fk_by_node[rel.get('source_table',fact_name)].add(rel.get('source_column',rel.get('fact_column')))
    # Place nodes in vertical columns according to their actual distance from the fact.
    content_top=height-2.1
    content_bottom=1.3
    middle=(content_bottom+content_top)/2
    for level in range(ncols):
        names=levels.get(level,[])
        total_span=(len(names)-1)*vertical_step
        for index,name in enumerate(names):
            cx=.7+level*(card_width+card_gap)
            cy=middle+total_span/2-index*vertical_step
            df=nodes[name]
            h=box_h(df);y=cy-h/2
            positions[name]=(cx,y,card_width,h,cy)
    # Links must be under the cards, so render them first.
    for rel in relations:
        source=rel.get('source_table',fact_name)
        target=rel['dimension_table']
        if source not in positions or target not in positions:continue
        sx,sy,sw,sh,scy=positions[source]
        tx,ty,tw,th,tcy=positions[target]
        x1=sx+sw;x2=tx;y1=scy;y2=tcy
        midpoint=(x1+x2)/2
        ax.add_patch(PathPatch(MPath([(x1,y1),(midpoint,y1),(midpoint,y2),(x2,y2)],
                                      [MPath.MOVETO,MPath.LINETO,MPath.LINETO,MPath.LINETO]),
                               facecolor='none',edgecolor=LINE,linewidth=2,zorder=1))
        ax.scatter([x1,x2],[y1,y2],s=46,c=[BLUE,GREEN],zorder=4)
        ax.text(midpoint,y2+.14,str(rel.get('source_column',rel.get('fact_column')))[:17],
                ha='center',fontsize=8,color=MUTED,zorder=5)
    # Draw cards from actual DataFrames (not assumptions).
    for name,(x,y,w,h,cy) in positions.items():
        df=nodes[name];is_fact=name==fact_name;color=BLUE if is_fact else GREEN
        ax.add_patch(FancyBboxPatch((x+.065,y-.07),w,h,boxstyle='round,pad=0.015,rounding_size=0.14',
                                     facecolor='#e1e8f2',edgecolor='none',zorder=2))
        ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.015,rounding_size=0.14',
                                     facecolor='white',edgecolor='#d7dfeb',linewidth=1,zorder=3))
        ax.add_patch(FancyBboxPatch((x,y+h-.53),w,.53,boxstyle='round,pad=0.015,rounding_size=0.14',
                                     facecolor=color,edgecolor='none',zorder=4))
        ax.add_patch(plt.Rectangle((x,y+h-.53),w,.18,facecolor=color,edgecolor='none',zorder=4))
        display_name=name if len(name)<=30 else name[:27]+'...'
        ax.text(x+.18,y+h-.33,display_name,fontsize=11.5,color='white',fontweight='bold',zorder=5)
        ax.text(x+w-.17,y+h-.33,'FACT' if is_fact else 'DIMENSION',fontsize=8.5,color='white',ha='right',zorder=5)
        pk=pk_by_dim.get(name)
        if is_fact:
            pk=next((c for c in df.columns if df[c].notna().all() and df[c].is_unique and
                     (c.endswith(('_id','_ref','_key')) or c in ('tracking_no','run_id')) and c not in fk_by_node[name]),None)
        for row,(col,dtype) in enumerate(df.dtypes.items()):
            if row>=10:
                ax.text(x+.2,y+.17,f'+ {len(df.columns)-10} more columns',fontsize=8.5,color=MUTED,zorder=5)
                break
            yy=y+h-.77-row*rowstep
            tag='PK' if col==pk else ('FK' if col in fk_by_node[name] else
                 ('●' if is_fact and pd.api.types.is_numeric_dtype(dtype) else ''))
            ax.text(x+.14,yy,tag,fontsize=8.8,color=color,fontweight='bold',zorder=5)
            ax.text(x+.65,yy,str(col)[:26],fontsize=9,color=TEXT,zorder=5)
            ax.text(x+w-.15,yy,_dtype(dtype),fontsize=8.0,color=MUTED,ha='right',zorder=5)
    png=folder/'snowflake_schema.png';svg=folder/'snowflake_schema.svg'
    fig.savefig(png,bbox_inches='tight',pad_inches=.18,facecolor=fig.get_facecolor())
    fig.savefig(svg,bbox_inches='tight',pad_inches=.18,facecolor=fig.get_facecolor())
    plt.close(fig)
    return {'png':str(png),'svg':str(svg),'schema_type':'snowflake_schema','fact':fact_name,
            'dimension_count':len(dimensions),'relationship_count':len(relations),
            'dimension_to_dimension_links':sum(r.get('relationship_type')=='dimension_to_dimension' for r in relations)}
