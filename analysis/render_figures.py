"""Rebuild publication figures using only the bundled aggregate study tables."""
import csv
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[1]
RESULTS=ROOT/'results'
OUT=ROOT/'figures'


def read(name):return list(csv.DictReader((RESULTS/name).open(encoding='utf-8-sig')))


def margin():
    data=read('margin_removal_walkforward.csv');fig,axes=plt.subplots(1,2,figsize=(10.5,4.6))
    for ax,group,title in zip(axes,['earlier_selection','later_primary'],['Earlier games: choose method','Later games: frozen choice']):
        g=[r for r in data if r['group']==group]
        for i,r in enumerate(g):
            y,lo,hi=[float(r[k]) for k in ['yes_underprediction_cents','bias_ci_low_cents','bias_ci_high_cents']]
            ax.errorbar(i,y,yerr=[[y-lo],[hi-y]],fmt='o',capsize=4,color='#087e8b' if r['margin_method']=='power' else '#64748b')
            ax.annotate(f'{y:+.1f}c',(i,y),xytext=(7,0),textcoords='offset points',fontsize=9)
        ax.axhline(0,color='#64748b',lw=1);ax.set_xticks(range(len(g)),[r['margin_method'].capitalize() for r in g]);ax.set_xlim(-.5,len(g)-.1)
        ax.set_title(title+f'\n{g[0]["checkpoints"]} checkpoints / {g[0]["games"]} games');ax.grid(axis='y',alpha=.15)
    axes[0].set_ylabel('Actual YES frequency minus model (cents)\nPositive = YES underpriced / NO overvalued')
    fig.suptitle('Margin removal with the frozen correlation model',fontsize=14)
    fig.text(.5,.02,'Original 50–80% cohort held fixed · paired cases · whole-game 95% intervals · retrospective temporal test',ha='center',fontsize=8)
    fig.tight_layout(rect=(0,.06,1,.93));fig.savefig(OUT/'margin_walkforward.png',dpi=160);plt.close(fig)


def reliability():
    data=read('synthetic_reliability_bins.csv');fig,axes=plt.subplots(2,2,figsize=(10,8),sharex=True,sharey=True)
    for ax,q in zip(axes.flat,range(1,5)):
        g=[r for r in data if r['direction']=='cover_over' and r['quarter']==str(q) and int(r['checkpoints'])>=20 and int(r['games'])>=10]
        ax.plot([0,1],[0,1],'--',color='#64748b',lw=1)
        ax.plot([float(r['independent_yes']) for r in g],[float(r['observed_yes']) for r in g],'x-',color='#94a3b8',label='Without correlation',lw=1)
        ax.plot([float(r['predicted_yes']) for r in g],[float(r['observed_yes']) for r in g],color='#087e8b',lw=1)
        for r in g:
            x,y=float(r['predicted_yes']),float(r['observed_yes'])
            if r['bias_ci_low_cents']:
                lo=x-float(r['bias_ci_high_cents'])/100;hi=x-float(r['bias_ci_low_cents'])/100
                ax.errorbar(x,y,yerr=[[max(0,y-lo)],[max(0,hi-y)]],fmt='o',ms=3,color='#087e8b',capsize=2)
            else:ax.scatter(x,y,facecolors='none',edgecolors='#087e8b')
        ax.set_title(f'Quarter {q}');ax.set_xlim(0,1);ax.set_ylim(0,1);ax.grid(alpha=.15);ax.set_xlabel('Predicted YES probability');ax.set_ylabel('Actual frequency')
    from matplotlib.lines import Line2D
    fig.legend(handles=[Line2D([0],[0],color='#94a3b8',marker='x',label='Independent product'),Line2D([0],[0],color='#087e8b',marker='o',label='Frozen correlated model')],loc='upper center',ncol=2,bbox_to_anchor=(.5,.945),frameon=False)
    fig.suptitle('Synthetic spread cover + total over',fontsize=14,y=.99)
    fig.text(.5,.02,'Real 2025–26 sportsbook lines and outcomes · mid-quarter checkpoints · whole-game intervals\nExploratory bins; sparse bins omitted from figure and retained in the CSV.',ha='center',fontsize=8)
    fig.tight_layout(rect=(0,.07,1,.9));fig.savefig(OUT/'spread_total_reliability.png',dpi=160);plt.close(fig)


def premiums():
    data=read('premium_sensitivity.csv')
    g=[r for r in data if r['base_premium_cents']=='3' and r['policy'].startswith('uniform_') and r['policy']!='uniform_add_observed_miss']
    g.sort(key=lambda r:float(r['affected_total_premium_cents']))
    x=[float(r['affected_total_premium_cents']) for r in g]
    fig,axes=plt.subplots(1,2,figsize=(10.5,4.5))
    axes[0].plot(x,[100-float(r['competitive_prints_lost_pct']) for r in g],'o-',color='#087e8b')
    axes[0].set_ylabel('Competitive opportunities retained (%)');axes[0].set_ylim(0,105);axes[0].set_title('Higher premiums lose historical opportunities')
    for r in g:
        y,lo,hi=[float(r[k]) for k in ['no_overvaluation_cents','no_error_ci_low','no_error_ci_high']]
        axes[1].errorbar(float(r['affected_total_premium_cents']),y,yerr=[[y-lo],[hi-y]],fmt='o',color='#087e8b',capsize=3)
    axes[1].axhline(0,color='#64748b',lw=1);axes[1].set_ylabel('NO overvaluation on remaining fills (cents)');axes[1].set_title('The remaining sample has a different error')
    for ax in axes:ax.set_xlabel('Total moneyline × total premium (cents)');ax.grid(alpha=.15)
    fig.suptitle('Actual-trade premium sensitivity: 3c baseline branch',fontsize=13)
    fig.text(.5,.02,'Actual sizes and historical fees · shared $500/game cash cap · other families retain 3c\nHistorical price-comparison proxy, not observed live RFQ acceptance. Scenarios are retrospective.',ha='center',fontsize=8)
    fig.tight_layout(rect=(0,.08,1,.92));fig.savefig(OUT/'premium_sensitivity.png',dpi=160);plt.close(fig)


if __name__=='__main__':
    OUT.mkdir(exist_ok=True);margin();reliability();premiums();print('Rendered three figures from bundled aggregates.')
