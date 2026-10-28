"""Produce polished star-schema PNG/SVG using Matplotlib (no Graphviz system install)."""
from __future__ import annotations
from pathlib import Path
import math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, PathPatch
from matplotlib.path import Path as MPath

FACT_BG = '#0f172a'
FACT_BORDER = '#334155'
DIM_COLORS = ['#0284c7', '#0f766e', '#4f46e5', '#7c3aed', '#d97706', '#0891b2']
TEXT = '#0f172a'
MUTED = '#64748b'
PAPER = '#f8fafc'
LINE = '#64748b'

def _dtype(dtype):
    dt = str(dtype).lower()
    if 'int' in dt: return 'BIGINT'
    if 'float' in dt or 'double' in dt: return 'DOUBLE'
    if 'datetime' in dt or 'date' in dt: return 'TIMESTAMP'
    if 'bool' in dt: return 'BOOLEAN'
    return 'VARCHAR'

def generate_star_schema_image(output_dir, fact_name, fact, dimensions, relations, domain='unknown'):
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)

    left_names = list(dimensions)[::2]
    right_names = list(dimensions)[1::2]
    side_count = max(1, len(left_names), len(right_names))

    row_unit = 0.40
    card_h = lambda df: min(5.4, 0.70 + min(len(df.columns), 12) * row_unit + 0.35)
    max_side_h = max([card_h(df) for df in dimensions.values()] + [2.2])
    space = max_side_h + 0.90
    total_height = max(11.0, side_count * space + 3.5, card_h(fact) + 5.5)
    total_width = 20.0

    fig, ax = plt.subplots(figsize=(total_width, total_height), dpi=180)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    ax.set_xlim(0, total_width)
    ax.set_ylim(0, total_height)
    ax.axis('off')

    ax.text(0.8, total_height - 0.55, 'BI-FLOW  *  INTELLIGENT ETL ARCHITECTURE', fontsize=11, color='#4f46e5', fontweight='bold')
    ax.text(0.8, total_height - 1.10, 'Enterprise Star Schema Architecture' if dimensions else 'Analytical Fact Model', fontsize=23, fontweight='black', color='#0f172a')
    ax.text(total_width - 0.8, total_height - 0.70, f'DOMAIN: {domain.upper().replace("_", " ")}', fontsize=10, fontweight='bold', color='#475569', ha='right')
    ax.text(0.8, 0.35, 'Notation:  1 = Dimension Primary Key (PK)   *   oo = Fact Foreign Key (FK)   *   * = Numeric Measure', fontsize=9.5, color='#64748b', fontweight='medium')

    fact_fk = {x['fact_column'] for x in relations}
    dim_pk = {x['dimension_table']: x['dimension_column'] for x in relations}
    fact_pk = next((c for c in fact if fact[c].notna().all() and fact[c].is_unique and
                    (c.lower().endswith(('_id', '_ref', '_no', '_key')) or c.lower() in ('sale_id', 'reading_id', 'order_id')) and c not in fact_fk), None)

    cards = {}
    col_coords = {}

    def draw_card(name, df, x, cy, w, is_fact, color_idx=0):
        h = card_h(df)
        y = cy - h / 2

        shadow = FancyBboxPatch((x + 0.09, y - 0.09), w, h, boxstyle='round,pad=0.03,rounding_size=0.18', facecolor='#cbd5e1', linewidth=0, zorder=1, alpha=0.6)
        ax.add_patch(shadow)
        card = FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.03,rounding_size=0.18', facecolor='#ffffff', edgecolor='#cbd5e1', linewidth=1.2, zorder=2)
        ax.add_patch(card)

        header_color = FACT_BG if is_fact else DIM_COLORS[color_idx % len(DIM_COLORS)]
        head = FancyBboxPatch((x, y + h - 0.62), w, 0.62, boxstyle='round,pad=0.03,rounding_size=0.18', facecolor=header_color, linewidth=0, zorder=3)
        ax.add_patch(head)
        ax.add_patch(plt.Rectangle((x, y + h - 0.62), w, 0.25, facecolor=header_color, zorder=3, linewidth=0))

        ax.text(x + 0.25, y + h - 0.36, name, fontsize=12.5 if is_fact else 12, color='#ffffff', fontweight='black', zorder=4)
        type_badge = 'FACT TABLE' if is_fact else 'DIMENSION'
        ax.text(x + w - 0.25, y + h - 0.36, type_badge, fontsize=8.5, color='#94a3b8' if is_fact else '#e0f2fe', fontweight='bold', ha='right', zorder=4)

        pk = dim_pk.get(name)
        for index, (col, dtype) in enumerate(df.dtypes.items()):
            if index >= 12:
                ax.text(x + 0.25, y + 0.20, f'+ {len(df.columns)-12} other attributes...', fontsize=8.5, color=MUTED, zorder=4)
                break
            yy = y + h - 0.95 - index * row_unit
            col_coords[(name, col)] = yy

            if index % 2 == 1:
                ax.add_patch(plt.Rectangle((x + 0.05, yy - row_unit/2.3), w - 0.10, row_unit, facecolor='#f8fafc', zorder=2.5, linewidth=0))

            is_col_pk = (col == pk or (is_fact and col == fact_pk))
            is_col_fk = (col in fact_fk and is_fact)
            is_measure = (is_fact and __import__('pandas').api.types.is_numeric_dtype(dtype) and not is_col_pk and not is_col_fk)

            if is_col_pk:
                ax.text(x + 0.18, yy, 'PK', fontsize=8.5, color='#b45309', fontweight='black', zorder=4,
                        bbox=dict(boxstyle='round,pad=0.15', facecolor='#fef3c7', edgecolor='#f59e0b', linewidth=0.7))
            elif is_col_fk:
                ax.text(x + 0.18, yy, 'FK', fontsize=8.5, color='#1d4ed8', fontweight='black', zorder=4,
                        bbox=dict(boxstyle='round,pad=0.15', facecolor='#dbeafe', edgecolor='#3b82f6', linewidth=0.7))
            elif is_measure:
                ax.text(x + 0.18, yy, '●', fontsize=9.5, color='#059669', fontweight='bold', zorder=4)

            maxletters = 28 if w > 4.5 else 22
            ax.text(x + 0.72, yy, str(col)[:maxletters], fontsize=9.2, color='#1e293b', fontweight='medium', zorder=4)
            ax.text(x + w - 0.22, yy, _dtype(dtype), fontsize=8.0, color='#64748b', fontfamily='monospace', ha='right', zorder=4)

        cards[name] = {'x': x, 'y': y, 'h': h, 'w': w, 'mid': cy}

    center_y = (total_height - 1.4) / 2
    draw_card(fact_name, fact, 7.55, center_y, 4.90, True, 0)

    top = total_height - 3.2
    bottom = max(2.8, max_side_h / 2 + 1.2)
    def positions(length):
        if length == 1: return [center_y]
        return [top - (top - bottom) * i / (length - 1) for i in range(length)]

    for idx, (name, y) in enumerate(zip(left_names, positions(len(left_names)))):
        draw_card(name, dimensions[name], 0.65, y, 5.60, False, idx)
    for idx, (name, y) in enumerate(zip(right_names, positions(len(right_names)))):
        draw_card(name, dimensions[name], 13.75, y, 5.60, False, idx + len(left_names))

    for rel in relations:
        dim_name = rel['dimension_table']
        fact_col = rel['fact_column']
        dim_col = rel['dimension_column']
        dest = cards.get(dim_name)
        if not dest:
            continue

        left = dest['x'] < 7.0
        a = cards[fact_name]

        y1 = col_coords.get((fact_name, fact_col), a['mid'])
        y2 = col_coords.get((dim_name, dim_col), dest['mid'])

        x1 = a['x'] if left else a['x'] + a['w']
        x2 = dest['x'] + dest['w'] if left else dest['x']

        mid_x = (x1 + x2) / 2
        vertices = [(x1, y1), (mid_x, y1), (mid_x, y2), (x2, y2)]
        codes = [MPath.MOVETO, MPath.LINETO, MPath.LINETO, MPath.LINETO]
        path = MPath(vertices, codes)

        ax.add_patch(PathPatch(path, facecolor='none', edgecolor='#64748b', linewidth=2.0, zorder=1.5, alpha=0.85))

        ax.text(x2 + (0.20 if left else -0.20), y2, '1', fontsize=9.0, fontweight='black', color='#0f766e',
                ha='left' if left else 'right', va='center',
                bbox=dict(boxstyle='round,pad=0.18', facecolor='#ccfbf1', edgecolor='#14b8a6', linewidth=0.8, zorder=6))

        ax.text(x1 + (-0.20 if left else 0.20), y1, 'N', fontsize=10.0, fontweight='black', color='#4338ca',
                ha='right' if left else 'left', va='center',
                bbox=dict(boxstyle='round,pad=0.18', facecolor='#e0e7ff', edgecolor='#6366f1', linewidth=0.8, zorder=6))

        ax.text(mid_x, (y1 + y2) / 2, f" {fact_col} ", fontsize=8.0, fontweight='bold', color='#1e293b',
                ha='center', va='center',
                bbox=dict(boxstyle='round,pad=0.22', facecolor='#ffffff', edgecolor='#cbd5e1', linewidth=1.0, zorder=7))

    png = folder / 'star_schema.png'
    svg = folder / 'star_schema.svg'
    fig.savefig(png, bbox_inches='tight', pad_inches=0.25, facecolor=fig.get_facecolor())
    fig.savefig(svg, bbox_inches='tight', pad_inches=0.25, facecolor=fig.get_facecolor())
    plt.close(fig)
    return {
        'png': str(png),
        'svg': str(svg),
        'schema_type': 'star_schema' if dimensions else 'fact_only',
        'fact': fact_name,
        'dimension_count': len(dimensions),
        'relationship_count': len(relations)
    }


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
