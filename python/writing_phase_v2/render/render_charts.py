"""Render the figure registry from a bundle.
Usage: python render_charts.py bundle.json outdir [render_data.json]

Every figure is BUILT or carries a real data reason (the completeness
ledger). Each chart runs ISOLATED (2026-09-08, after a highlight bug on one
chart sank a PASSED Ardenwald plan): an exception records the figure as
'RENDERER ERROR: ...' and the other charts still render. The completeness
gate treats a RENDERER ERROR as an UNEXPLAINED absence - a bug is not a
data reason, so the run still fails loudly - but nothing else is lost.
"""
import contextlib
import json, sys, os
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import numpy as np

bundle = json.load(open(sys.argv[1], encoding='utf-8')); out = sys.argv[2]; os.makedirs(out, exist_ok=True)
# renderer-only data (marketing periods etc.) - the writer's bundle excludes
# it, the renderer legitimately reads it (2026-09-08)
RD = {}
if len(sys.argv) > 3 and os.path.exists(sys.argv[3]):
    RD = json.load(open(sys.argv[3], encoding='utf-8'))
PERIODS = [p for p in (RD.get('marketing_periods') or []) if not p.get('is_stub')]
STATUS = {}
def built(fid): STATUS[fid] = {'built': True, 'reason': ''}
def absent(fid, why): STATUS[fid] = {'built': False, 'reason': why}

@contextlib.contextmanager
def guard(fid):
    try:
        yield
    except Exception as exc:
        absent(fid, 'RENDERER ERROR: %s: %s' % (type(exc).__name__, str(exc)[:160]))
        plt.close('all')

plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'axes.edgecolor':'#888'})
NAVY='#1F3A5F'; TEAL='#2A9D8F'; GREY='#9AA0A6'; AMBER='#C8811E'
money=FuncFormatter(lambda v,p: f'${v/1e6:.1f}M' if abs(v)>=1e6 else f'${v/1e3:.0f}K')
A=bundle['model']['annual']; years=[f'Year {r["year"]}' for r in A]
rev=[r['revenue'] for r in A]; ebitda=[r['ebitda'] for r in A]; ni=[r['net_income'] for r in A]
D=bundle['derived']
SIZES={}

with guard('revenue_ebitda_net_income'):
    fig,ax=plt.subplots(figsize=(7.2,3.6)); ax.bar(years,rev,color=NAVY,width=0.55)
    for i,v in enumerate(rev): ax.text(i,v*1.02,f'${v/1e6:.2f}M',ha='center',fontsize=9,color=NAVY)
    ax2=ax.twinx(); ax2.spines['top'].set_visible(False); ax2.plot(years,ebitda,color=TEAL,marker='o',lw=2); ax2.plot(years,ni,color=AMBER,marker='o',lw=2)
    ax2.text(4.1,ebitda[-1],'EBITDA',color=TEAL,va='center'); ax2.text(4.1,ni[-1],'Net income',color=AMBER,va='center')
    ax.yaxis.set_major_formatter(money); ax2.yaxis.set_major_formatter(money); ax.set_ylim(0,max(rev)*1.25); ax2.set_ylim(0,max(ebitda)*1.4)
    ax.set_title('Revenue, EBITDA and net income, Years 1–5',loc='left',fontsize=11,color='#222'); plt.tight_layout(); plt.savefig(f'{out}/revenue_ebitda_net_income.png',dpi=200); plt.close(); SIZES['revenue_ebitda_net_income']=3.6; built('revenue_ebitda_net_income')

# EVERY figure carries a data condition (Nick 2026-09-08): nothing empty
# renders, and annotations obey the same rule - no debt, no debt annotation.

with guard('revenue_by_line'):
    # Year-1 shares from derived, scaled to annual revenue (mix held constant
    # beyond Y1). CONDITION: two lines or more - a single-line stack repeats
    # the revenue chart and says nothing.
    lines=[k[:-len('_revenue_share_y1')] for k in D if k.endswith('_revenue_share_y1')]
    if len(lines)>=2:
        fig,ax=plt.subplots(figsize=(7.2,3.4)); bottom=np.zeros(5); cols=[NAVY,TEAL,AMBER,GREY]
        for j,l in enumerate(lines):
            vals=[r['revenue']*D[l+'_revenue_share_y1'] for r in A]; ax.bar(years,vals,bottom=bottom,color=cols[j%4],width=0.55,label=l.replace('_',' ').capitalize())
            for i,v in enumerate(vals):
                if v>0.08*max(rev): ax.text(i,bottom[i]+v/2,f'${v/1e3:.0f}K',ha='center',color='white',fontsize=8.5)
            bottom+=np.array(vals)
        ax.yaxis.set_major_formatter(money); ax.legend(frameon=False,loc='upper left',fontsize=9); ax.set_title('Revenue by line of business (Year-1 mix applied to annual revenue)',loc='left',fontsize=11,color='#222')
        plt.tight_layout(); plt.savefig(f'{out}/revenue_by_line.png',dpi=200); plt.close(); SIZES['revenue_by_line']=3.4; built('revenue_by_line')
    else:
        absent('revenue_by_line','single line of business - the figure would repeat the revenue chart')

with guard('cash_and_debt_quarterly'):
    q=[c[0] for c in bundle['model']['cash_by_quarter']]; cash=[c[2] for c in bundle['model']['cash_by_quarter']]
    debt=[r['closing_debt'] for r in bundle['model']['debt_schedule']][:20]
    has_debt=any(d>0 for d in debt)
    fig,ax=plt.subplots(figsize=(7.2,3.4)); ax.plot(q,cash,color=NAVY,lw=2)
    ax.text(20.3,cash[-1],'Cash',color=NAVY,va='center')
    if has_debt:
        ax.plot(q,debt,color=GREY,lw=2,ls='--'); ax.text(20.3,debt[-1]+max(cash)*0.03,'Term debt',color=GREY,va='center')
        if D.get('debt_retired_quarter'): ax.annotate(f'Term loan retired\n{D["debt_retired_date"][:7]}',xy=(D['debt_retired_quarter'],0),xytext=(D['debt_retired_quarter']+1.5,max(cash)*0.5),arrowprops=dict(arrowstyle='-',color=GREY),fontsize=9,color='#444')
    ti=D['cash_trough_quarter']; ax.annotate(f'Low point ${D["cash_trough_amount"]/1e3:.0f}K\n({D["cash_trough_date"][:7]})',xy=(ti,D['cash_trough_amount']),xytext=(ti+1.5,D['cash_trough_amount']*0.35),arrowprops=dict(arrowstyle='-',color=NAVY),fontsize=9,color=NAVY)
    ax.set_xticks([1,5,9,13,17,20]); ax.set_xticklabels(['Q1','Q5','Q9','Q13','Q17','Q20']); ax.yaxis.set_major_formatter(money); ax.set_ylim(0,max(cash)*1.15)
    ax.set_title('Cash balance and outstanding term debt by quarter' if has_debt else 'Cash balance by quarter',loc='left',fontsize=11,color='#222'); plt.tight_layout(); plt.savefig(f'{out}/cash_and_debt_quarterly.png',dpi=200); plt.close(); SIZES['cash_and_debt_quarterly']=3.4; built('cash_and_debt_quarterly')

with guard('cvp_year1'):
    be=bundle['model']['break_even']['y1_annualized']; fc=be['fixed_costs']; cm=be['cm_ratio']; planned=be['planned_revenue']; ber=be['be_revenue']; xmax=planned*1.35
    x=np.linspace(0,xmax,50); fig,ax=plt.subplots(figsize=(7.2,3.6))
    ax.plot(x,x,color=NAVY,lw=2); ax.plot(x,fc+(1-cm)*x,color=AMBER,lw=2); ax.axhline(fc,color=GREY,lw=1.2,ls='--'); ax.fill_between(x,x,fc+(1-cm)*x,where=x>ber,color=TEAL,alpha=0.15)
    ax.scatter([ber],[ber],color='black',zorder=5); ax.annotate(f'Break-even ${ber/1e6:.2f}M',xy=(ber,ber),xytext=(ber*0.35,ber*1.25),fontsize=9,arrowprops=dict(arrowstyle='-',color='#444'))
    ax.axvline(planned,color=NAVY,lw=1,ls=':'); ax.text(planned*1.01,xmax*0.08,f'Year-1 plan\n${planned/1e6:.2f}M',fontsize=9,color=NAVY)
    ax.text(xmax*0.82,xmax*0.86,'Revenue',color=NAVY,fontsize=9); ax.text(xmax*0.82,fc+(1-cm)*xmax*0.82-xmax*0.07,'Total cost',color=AMBER,fontsize=9); ax.text(xmax*0.02,fc-xmax*0.05,f'Fixed costs ${fc/1e3:.0f}K',color='#555',fontsize=9)
    ax.xaxis.set_major_formatter(money); ax.yaxis.set_major_formatter(money); ax.set_xlim(0,xmax); ax.set_ylim(0,xmax); ax.set_xlabel('Annual revenue'); ax.set_title('Cost–volume–profit, Year 1',loc='left',fontsize=11,color='#222')
    plt.tight_layout(); plt.savefig(f'{out}/cvp_year1.png',dpi=200); plt.close(); SIZES['cvp_year1']=3.6; built('cvp_year1')

with guard('industry_establishments_history'):
    bds=bundle['warehouse'].get('bds_2023') or {}
    hist=(next(iter(bds.values()),{}) or {}).get('estabs_history') or []
    if hist:
        fig,ax=plt.subplots(figsize=(7.2,3.0)); yrs=[h[0] for h in hist]; est=[h[1] for h in hist]; ax.plot(yrs,est,color=NAVY,lw=2,marker='o',ms=3); ax.fill_between(yrs,est,color=NAVY,alpha=0.08)
        ax.text(yrs[-1]+0.3,est[-1],f'{est[-1]/1e3:.0f}K',color=NAVY,va='center',fontsize=9); ax.text(yrs[0],est[0]*1.1,f'{est[0]/1e3:.0f}K',color=NAVY,fontsize=9)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v,p:f'{v/1e3:.0f}K')); ax.set_xlim(yrs[0],yrs[-1]+2)
        ax.set_title(f'U.S. establishments in the trade group, {yrs[0]}–{yrs[-1]}',loc='left',fontsize=10.5,color='#222'); plt.tight_layout(); plt.savefig(f'{out}/industry_establishments_history.png',dpi=200); plt.close(); SIZES['industry_establishments_history']=3.0; built('industry_establishments_history')
    else:
        absent('industry_establishments_history','no BDS establishment history for the trade group')

with guard('headcount_payroll'):
    # EVERY business has people (Nick 2026-09-08): needs only the payroll
    # schedule, no SOC codes, no wage slice.
    qt=bundle['model'].get('payroll',{}).get('quarter_totals') or []
    if qt:
        qi=[r['quarter_index'] for r in qt]; fte=[r.get('ending_fte') for r in qt]; pay=[r.get('payroll') for r in qt]
        if any(v is not None for v in fte):
            fig,ax=plt.subplots(figsize=(7.2,3.0))
            ax.bar(qi,pay,color=NAVY,alpha=0.25,width=0.7)
            ax.yaxis.set_major_formatter(money); ax.set_ylim(0,max(pay)*1.3)
            ax2=ax.twinx(); ax2.spines['top'].set_visible(False)
            ax2.step(qi,fte,where='post',color=AMBER,lw=2)
            ax2.set_ylim(0,max(fte)*1.5); ax2.set_ylabel('FTE',color=AMBER,fontsize=9)
            ax.text(qi[0]+0.2,max(pay)*1.18,'Quarterly payroll (bars)',color=NAVY,fontsize=9)
            ax2.text(qi[-1]-0.2,fte[-1]*1.08,f'{fte[-1]:.1f} FTE',color=AMBER,ha='right',fontsize=9)
            ax.set_xticks([1,5,9,13,17,20]); ax.set_xticklabels(['Q1','Q5','Q9','Q13','Q17','Q20'])
            ax.set_title('Headcount (FTE) and payroll by quarter',loc='left',fontsize=11,color='#222')
            plt.tight_layout(); plt.savefig(f'{out}/headcount_payroll.png',dpi=200); plt.close(); SIZES['headcount_payroll']=3.0; built('headcount_payroll')
        else:
            absent('headcount_payroll','payroll schedule carries no FTE series')
    else:
        absent('headcount_payroll','no payroll quarter totals on the model')

with guard('capacity_vs_plan_y1'):
    # What the data holds, precisely: per-line weekly capacity and Year-1
    # utilisation (financials_year1); TOTAL planned units per quarter for all
    # five years (the marketing schedule, renderer data); NO per-line paths
    # beyond Year 1. So: a five-year path of total planned weekly volume
    # against the total weekly ceiling, plus per-line Year-1 bars beneath.
    fy=bundle['record'].get('financials_year1') or {}
    cap_rows=[]
    for lob in fy.get('lobs') or []:
        for pr in lob.get('products') or []:
            wk=pr.get('units_per_week_capacity'); u=pr.get('utilization_rate')
            if wk and u:
                cap_rows.append((lob.get('lob_name') or 'Line', wk, wk*u))
    watermark=(bundle['record'].get('planning_context') or {}).get('stage_ramp_contract',{}).get('utilization_high_watermark')
    if cap_rows:
        total_cap=sum(r[1] for r in cap_rows)
        path=[(int(p['period_index']), float(p.get('units') or 0)/13.0) for p in PERIODS
              if p.get('units') is not None][:20]
        two=bool(path)
        if two:
            fig,(axp,ax)=plt.subplots(2,1,figsize=(7.2,2.6+0.9+0.75*len(cap_rows)),
                                      gridspec_kw={'height_ratios':[2.6,0.9+0.75*len(cap_rows)]})
            axp.plot([p[0] for p in path],[p[1] for p in path],color=NAVY,lw=2,marker='o',ms=3)
            axp.axhline(total_cap,color=GREY,lw=1.5,ls='--')
            axp.text(path[-1][0],total_cap*1.03,f'capacity {total_cap:.0f}/wk',color='#555',fontsize=8.5,ha='right')
            if watermark:
                axp.axhline(total_cap*watermark,color=AMBER,lw=1.5)
                axp.text(path[0][0],total_cap*watermark*1.03,f'{watermark:.0%} sustained ceiling',color=AMBER,fontsize=8.5)
            axp.set_xticks([1,5,9,13,17,20]); axp.set_xticklabels(['Q1','Q5','Q9','Q13','Q17','Q20'])
            axp.set_ylim(0,total_cap*1.2); axp.set_ylabel('Units/week',fontsize=9)
            axp.set_title('Planned weekly volume against capacity, five years',loc='left',fontsize=11,color='#222')
            axp.spines['top'].set_visible(False); axp.spines['right'].set_visible(False)
        else:
            fig,ax=plt.subplots(figsize=(7.2,0.9+0.75*len(cap_rows)))
        for i,(nm,wk,planned) in enumerate(cap_rows):
            y=len(cap_rows)-1-i
            ax.barh(y,wk,color=GREY,alpha=0.3,height=0.5)
            ax.barh(y,planned,color=NAVY,height=0.5)
            if watermark: ax.plot([wk*watermark,wk*watermark],[y-0.32,y+0.32],color=AMBER,lw=2)
            ax.text(wk*1.01,y,f'{wk:.0f}/wk capacity',va='center',fontsize=8.5,color='#555')
            ax.text(planned/2,y,f'{planned:.0f} planned',va='center',ha='center',fontsize=8.5,color='white')
            ax.text(-max(r[1] for r in cap_rows)*0.01,y,nm,ha='right',va='center',fontsize=8.5)
        if watermark and not two:
            ax.text(max(r[1] for r in cap_rows)*1.27,-0.52,f'| {watermark:.0%} sustained-utilisation ceiling',color=AMBER,fontsize=8,ha='right')
        ax.set_yticks([]); ax.set_xlim(0,max(r[1] for r in cap_rows)*1.28); ax.set_ylim(-0.65,len(cap_rows)-0.35); ax.spines['left'].set_visible(False)
        ax.set_xlabel('Units per week',fontsize=9)
        ax.set_title('Year 1, by line',loc='left',fontsize=10,color='#222') if two else \
            ax.set_title('Capacity against planned Year-1 volume, by line',loc='left',fontsize=11,color='#222')
        plt.tight_layout(); plt.savefig(f'{out}/capacity_vs_plan_y1.png',dpi=200); plt.close()
        SIZES['capacity_vs_plan_y1']=(2.6 if two else 0)+0.9+0.75*len(cap_rows); built('capacity_vs_plan_y1')
    else:
        absent('capacity_vs_plan_y1','no line carries weekly capacity and utilisation')

with guard('marketing_customers'):
    # new versus returning customers by year, with marketing spend - from the
    # marketing schedule (renderer data; the writer's bundle excludes periods)
    if PERIODS:
        yr_new=[]; yr_ret=[]; yr_spend=[]
        for y in range(5):
            grp=[p for p in PERIODS if y*4 < int(p['period_index']) <= (y+1)*4]
            if len(grp)<4: break
            yr_new.append(sum(float(p.get('new_customers') or 0) for p in grp))
            yr_ret.append(sum(float(p.get('retained_customers') or 0) for p in grp))
            yr_spend.append(sum(float(p.get('marketing_dollars') or 0) for p in grp))
        if yr_new:
            ylab=[f'Year {i+1}' for i in range(len(yr_new))]
            fig,ax=plt.subplots(figsize=(7.2,3.2))
            ax.bar(ylab,yr_new,color=NAVY,width=0.55,label='New customers')
            ax.bar(ylab,yr_ret,bottom=yr_new,color=TEAL,width=0.55,label='Returning customers')
            ax.legend(frameon=False,loc='upper left',fontsize=9)
            ax.yaxis.set_major_formatter(FuncFormatter(lambda v,p:f'{v/1e3:.0f}K' if v>=1000 else f'{v:.0f}'))
            ax2=ax.twinx(); ax2.spines['top'].set_visible(False)
            ax2.plot(ylab,yr_spend,color=AMBER,marker='o',lw=2)
            ax2.yaxis.set_major_formatter(money)
            ax2.text(len(ylab)-1,yr_spend[-1]*1.06,'Marketing spend',color=AMBER,ha='right',fontsize=9)
            ax.set_title('New and returning customers by year, with marketing spend',loc='left',fontsize=11,color='#222')
            plt.tight_layout(); plt.savefig(f'{out}/marketing_customers.png',dpi=200); plt.close(); SIZES['marketing_customers']=3.2; built('marketing_customers')
        else:
            absent('marketing_customers','marketing schedule has fewer than four projected quarters')
    else:
        absent('marketing_customers','no marketing-schedule periods in the renderer data')

with guard('competitor_size_bands'):
    # national firms by employee-size band, the primary trade code - places
    # the business in the field without naming anyone.
    fs=(bundle['warehouse'].get('bds_firm_size_2023') or {}).get('firms_by_size') or {}
    if fs:
        labels={'a) 1 to 4':'1–4','b) 5 to 9':'5–9','c) 10 to 19':'10–19','d) 20 to 49':'20–49','e) 50 to 99':'50–99','f) 100 to 249':'100–249','g) 250 to 499':'250–499','h) 500 to 999':'500–999','i) 1000 to 2499':'1,000+','j) 2500 to 4999':'1,000+','k) 5000 to 9999':'1,000+','l) 10000+':'1,000+'}
        agg={}
        for k,v in fs.items():
            lb=labels.get(k)
            if lb: agg[lb]=agg.get(lb,0)+v
        order=['1–4','5–9','10–19','20–49','50–99','100–249','250–499','500–999','1,000+']
        bands=[b for b in order if agg.get(b)]
        if bands:
            heads=(bundle['record'].get('financials') or {}).get('current_num_employees')
            qt0=bundle['model'].get('payroll',{}).get('quarter_totals') or [{}]
            size=heads or qt0[0].get('ending_fte')
            mine=None
            if size:
                for b_,(lo,hi) in zip(order,[(1,4),(5,9),(10,19),(20,49),(50,99),(100,249),(250,499),(500,999),(1000,10**9)]):
                    if lo<=size<=hi: mine=b_; break
            # the business's own band can be EMPTY in the data (zero firms in
            # the bucket, Ardenwald 2026-09-08) - highlight only when present
            if mine not in bands: mine=None
            fig,ax=plt.subplots(figsize=(7.2,3.0))
            vals=[agg[b_] for b_ in bands]
            cols=[AMBER if b_==mine else NAVY for b_ in bands]
            ax.bar(bands,vals,color=cols,width=0.6)
            for i,v in enumerate(vals): ax.text(i,v*1.02,f'{v/1e3:.1f}K' if v>=1000 else str(v),ha='center',fontsize=8.5,color='#333')
            if mine: ax.text(bands.index(mine),agg[mine]*1.16,'this business',color=AMBER,ha='center',fontsize=9)
            ax.yaxis.set_major_formatter(FuncFormatter(lambda v,p:f'{v/1e3:.0f}K'))
            ax.set_xlabel('Employees per firm',fontsize=9)
            ax.set_title('U.S. firms in the trade by employee size, 2023',loc='left',fontsize=11,color='#222')
            plt.tight_layout(); plt.savefig(f'{out}/competitor_size_bands.png',dpi=200); plt.close(); SIZES['competitor_size_bands']=3.0; built('competitor_size_bands')
        else:
            absent('competitor_size_bands','BDS firm-size buckets empty for the trade code')
    else:
        absent('competitor_size_bands','no bds_firm_size slice in the bundle')

with guard('wage_positioning'):
    wp=[r for r in bundle['warehouse'].get('wage_positioning',[])
        if r.get('p10') and r.get('median') and r.get('p90')]
    if wp:
        fig,ax=plt.subplots(figsize=(7.2,0.9+0.9*len(wp)))
        lo=min(r['p10'] for r in wp)*0.55; hi=max(max(r['p90'],r['client_wage']) for r in wp)*1.08
        for i,r in enumerate(wp):
            y=len(wp)-1-i
            ax.plot([r['p10'],r['p90']],[y,y],color=GREY,lw=6,solid_capstyle='round',alpha=0.5)
            if r.get('p25') and r.get('p75'): ax.plot([r['p25'],r['p75']],[y,y],color=GREY,lw=6,solid_capstyle='round')
            ax.plot([r['median']],[y],'|',color='black',ms=14,mew=2); ax.plot([r['client_wage']],[y],'o',color=AMBER,ms=9,zorder=5)
            ax.text(r['p10']-hi*0.01,y,r['occupation'],ha='right',va='center',fontsize=8.5); ax.text(r['client_wage'],y+0.25,r['client_label'],color=AMBER,fontsize=8,ha='center')
        ax.set_xlim(lo,hi); ax.set_ylim(-0.6,len(wp)-0.3); ax.set_yticks([]); ax.xaxis.set_major_formatter(FuncFormatter(lambda v,p:f'${v/1e3:.0f}K')); ax.spines['left'].set_visible(False)
        ax.text(hi,-0.55,f'Bars: 10th–90th and 25th–75th percentiles, {wp[0]["area"]}; tick = median',ha='right',fontsize=8,color='#666')
        ax.set_title("Stated and market wages against the area wage distribution",loc='left',fontsize=11,color='#222'); plt.tight_layout(); plt.savefig(f'{out}/wage_positioning.png',dpi=200); plt.close(); SIZES['wage_positioning']=0.9+0.9*len(wp); built('wage_positioning')
    else:
        absent('wage_positioning','no roster role could be matched to an occupation')

json.dump(SIZES,open(f'{out}/sizes.json','w'))
json.dump(STATUS,open(f'{out}/figures_report.json','w'),indent=1)
print('rendered',[k for k,v in STATUS.items() if v['built']])
for k,v in STATUS.items():
    if not v['built']: print('absent  ',k,'-',v['reason'])
