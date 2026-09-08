"""Render the figure registry from a bundle. Usage: python render_charts.py bundle.json outdir"""
import json, sys, os
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import numpy as np

bundle = json.load(open(sys.argv[1])); out = sys.argv[2]; os.makedirs(out, exist_ok=True)
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'axes.edgecolor':'#888'})
NAVY='#1F3A5F'; TEAL='#2A9D8F'; GREY='#9AA0A6'; AMBER='#C8811E'
money=FuncFormatter(lambda v,p: f'${v/1e6:.1f}M' if abs(v)>=1e6 else f'${v/1e3:.0f}K')
A=bundle['model']['annual']; years=[f'Year {r["year"]}' for r in A]
rev=[r['revenue'] for r in A]; ebitda=[r['ebitda'] for r in A]; ni=[r['net_income'] for r in A]
SIZES={}

fig,ax=plt.subplots(figsize=(7.2,3.6)); ax.bar(years,rev,color=NAVY,width=0.55)
for i,v in enumerate(rev): ax.text(i,v*1.02,f'${v/1e6:.2f}M',ha='center',fontsize=9,color=NAVY)
ax2=ax.twinx(); ax2.spines['top'].set_visible(False); ax2.plot(years,ebitda,color=TEAL,marker='o',lw=2); ax2.plot(years,ni,color=AMBER,marker='o',lw=2)
ax2.text(4.1,ebitda[-1],'EBITDA',color=TEAL,va='center'); ax2.text(4.1,ni[-1],'Net income',color=AMBER,va='center')
ax.yaxis.set_major_formatter(money); ax2.yaxis.set_major_formatter(money); ax.set_ylim(0,max(rev)*1.25); ax2.set_ylim(0,max(ebitda)*1.4)
ax.set_title('Revenue, EBITDA and net income, Years 1–5',loc='left',fontsize=11,color='#222'); plt.tight_layout(); plt.savefig(f'{out}/revenue_ebitda_net_income.png',dpi=200); plt.close(); SIZES['revenue_ebitda_net_income']=3.6

# revenue by line: Year-1 shares from derived, scaled to annual revenue (mix held constant beyond Y1 unless model gives per-line annuals)
D=bundle['derived']; lines=[k[:-len('_revenue_share_y1')] for k in D if k.endswith('_revenue_share_y1')]
fig,ax=plt.subplots(figsize=(7.2,3.4)); bottom=np.zeros(5); cols=[NAVY,TEAL,AMBER,GREY]
for j,l in enumerate(lines):
    vals=[r['revenue']*D[l+'_revenue_share_y1'] for r in A]; ax.bar(years,vals,bottom=bottom,color=cols[j%4],width=0.55,label=l.replace('_',' ').capitalize())
    for i,v in enumerate(vals):
        if v>0.08*max(rev): ax.text(i,bottom[i]+v/2,f'${v/1e3:.0f}K',ha='center',color='white',fontsize=8.5)
    bottom+=np.array(vals)
ax.yaxis.set_major_formatter(money); ax.legend(frameon=False,loc='upper left',fontsize=9); ax.set_title('Revenue by line of business (Year-1 mix applied to annual revenue)',loc='left',fontsize=11,color='#222')
plt.tight_layout(); plt.savefig(f'{out}/revenue_by_line.png',dpi=200); plt.close(); SIZES['revenue_by_line']=3.4

q=[c[0] for c in bundle['model']['cash_by_quarter']]; cash=[c[2] for c in bundle['model']['cash_by_quarter']]
debt=[r['closing_debt'] for r in bundle['model']['debt_schedule']][:20]
fig,ax=plt.subplots(figsize=(7.2,3.4)); ax.plot(q,cash,color=NAVY,lw=2); ax.plot(q,debt,color=GREY,lw=2,ls='--')
ax.text(20.3,cash[-1],'Cash',color=NAVY,va='center'); ax.text(20.3,debt[-1]+max(cash)*0.03,'Term debt',color=GREY,va='center')
if D.get('debt_retired_quarter'): ax.annotate(f'Term loan retired\n{D["debt_retired_date"][:7]}',xy=(D['debt_retired_quarter'],0),xytext=(D['debt_retired_quarter']+1.5,max(cash)*0.5),arrowprops=dict(arrowstyle='-',color=GREY),fontsize=9,color='#444')
ti=D['cash_trough_quarter']; ax.annotate(f'Low point ${D["cash_trough_amount"]/1e3:.0f}K\n({D["cash_trough_date"][:7]})',xy=(ti,D['cash_trough_amount']),xytext=(ti+1.5,D['cash_trough_amount']*0.35),arrowprops=dict(arrowstyle='-',color=NAVY),fontsize=9,color=NAVY)
ax.set_xticks([1,5,9,13,17,20]); ax.set_xticklabels(['Q1','Q5','Q9','Q13','Q17','Q20']); ax.yaxis.set_major_formatter(money); ax.set_ylim(0,max(cash)*1.15)
ax.set_title('Cash balance and outstanding term debt by quarter',loc='left',fontsize=11,color='#222'); plt.tight_layout(); plt.savefig(f'{out}/cash_and_debt_quarterly.png',dpi=200); plt.close(); SIZES['cash_and_debt_quarterly']=3.4

be=bundle['model']['break_even']['y1_annualized']; fc=be['fixed_costs']; cm=be['cm_ratio']; planned=be['planned_revenue']; ber=be['be_revenue']; xmax=planned*1.35
x=np.linspace(0,xmax,50); fig,ax=plt.subplots(figsize=(7.2,3.6))
ax.plot(x,x,color=NAVY,lw=2); ax.plot(x,fc+(1-cm)*x,color=AMBER,lw=2); ax.axhline(fc,color=GREY,lw=1.2,ls='--'); ax.fill_between(x,x,fc+(1-cm)*x,where=x>ber,color=TEAL,alpha=0.15)
ax.scatter([ber],[ber],color='black',zorder=5); ax.annotate(f'Break-even ${ber/1e6:.2f}M',xy=(ber,ber),xytext=(ber*0.35,ber*1.25),fontsize=9,arrowprops=dict(arrowstyle='-',color='#444'))
ax.axvline(planned,color=NAVY,lw=1,ls=':'); ax.text(planned*1.01,xmax*0.08,f'Year-1 plan\n${planned/1e6:.2f}M',fontsize=9,color=NAVY)
ax.text(xmax*0.82,xmax*0.86,'Revenue',color=NAVY,fontsize=9); ax.text(xmax*0.82,fc+(1-cm)*xmax*0.82-xmax*0.07,'Total cost',color=AMBER,fontsize=9); ax.text(xmax*0.02,fc-xmax*0.05,f'Fixed costs ${fc/1e3:.0f}K',color='#555',fontsize=9)
ax.xaxis.set_major_formatter(money); ax.yaxis.set_major_formatter(money); ax.set_xlim(0,xmax); ax.set_ylim(0,xmax); ax.set_xlabel('Annual revenue'); ax.set_title('Cost–volume–profit, Year 1',loc='left',fontsize=11,color='#222')
plt.tight_layout(); plt.savefig(f'{out}/cvp_year1.png',dpi=200); plt.close(); SIZES['cvp_year1']=3.6

bds=bundle['warehouse']['bds_2023']; code=list(bds.keys())[0]; hist=bds[code]['estabs_history']
fig,ax=plt.subplots(figsize=(7.2,3.0)); yrs=[h[0] for h in hist]; est=[h[1] for h in hist]; ax.plot(yrs,est,color=NAVY,lw=2,marker='o',ms=3); ax.fill_between(yrs,est,color=NAVY,alpha=0.08)
ax.text(yrs[-1]+0.3,est[-1],f'{est[-1]/1e3:.0f}K',color=NAVY,va='center',fontsize=9); ax.text(yrs[0],est[0]*1.1,f'{est[0]/1e3:.0f}K',color=NAVY,fontsize=9)
ax.yaxis.set_major_formatter(FuncFormatter(lambda v,p:f'{v/1e3:.0f}K')); ax.set_xlim(yrs[0],yrs[-1]+2)
ax.set_title(f'U.S. establishments in the trade group, {yrs[0]}–{yrs[-1]}',loc='left',fontsize=10.5,color='#222'); plt.tight_layout(); plt.savefig(f'{out}/industry_establishments_history.png',dpi=200); plt.close(); SIZES['industry_establishments_history']=3.0

wp=bundle['warehouse'].get('wage_positioning',[])
if wp:
    fig,ax=plt.subplots(figsize=(7.2,0.9+0.9*len(wp)))
    lo=min(r['p10'] for r in wp)*0.55; hi=max(max(r['p90'],r['client_wage']) for r in wp)*1.08
    for i,r in enumerate(wp):
        y=len(wp)-1-i
        ax.plot([r['p10'],r['p90']],[y,y],color=GREY,lw=6,solid_capstyle='round',alpha=0.5); ax.plot([r['p25'],r['p75']],[y,y],color=GREY,lw=6,solid_capstyle='round')
        ax.plot([r['median']],[y],'|',color='black',ms=14,mew=2); ax.plot([r['client_wage']],[y],'o',color=AMBER,ms=9,zorder=5)
        ax.text(r['p10']-hi*0.01,y,r['occupation'],ha='right',va='center',fontsize=8.5); ax.text(r['client_wage'],y+0.25,r['client_label'],color=AMBER,fontsize=8,ha='center')
    ax.set_xlim(lo,hi); ax.set_ylim(-0.6,len(wp)-0.3); ax.set_yticks([]); ax.xaxis.set_major_formatter(FuncFormatter(lambda v,p:f'${v/1e3:.0f}K')); ax.spines['left'].set_visible(False)
    ax.text(hi,-0.55,f'Bars: 10th–90th and 25th–75th percentiles, {wp[0]["area"]}; tick = median',ha='right',fontsize=8,color='#666')
    ax.set_title("Client wages against the metro wage distribution",loc='left',fontsize=11,color='#222'); plt.tight_layout(); plt.savefig(f'{out}/wage_positioning.png',dpi=200); plt.close(); SIZES['wage_positioning']=0.9+0.9*len(wp)
json.dump(SIZES,open(f'{out}/sizes.json','w')); print('rendered',list(SIZES))
