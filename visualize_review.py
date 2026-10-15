from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np
import json
import csv
BASE=Path(__file__).resolve().parent
DATA={'cross':list(csv.DictReader(open(BASE/'docs/review_v2/의미구분별_감성표.csv',encoding='utf-8-sig'))),'meta':json.loads((BASE/'docs/review_v2/재검토_요약.json').read_text()),'metrics':json.loads((BASE/'docs/review_v2/metrics.json').read_text())}
META=DATA["meta"];METRICS=DATA["metrics"]
from zipfile import ZipFile
F=FontProperties(fname='/System/Library/Fonts/AppleSDGothicNeo.ttc')
plt.rcParams.update({'font.family':F.get_name(),'axes.unicode_minus':False,'font.size':16,'svg.fonttype':'path'})
OUT=BASE/'docs/review_v2';OUT.mkdir(exist_ok=True);BG='#FFFFFF';INK='#172638';MUT='#5A6878';COL=['#277F70','#CB625D','#94A5BA','#D4AD52','#78658F']
def page(title,subtitle):
 fig=plt.figure(figsize=(16,9),facecolor=BG);fig.text(.055,.92,title,fontsize=29,fontweight='bold',color=INK);fig.text(.055,.865,subtitle,fontsize=15,color=MUT);return fig
def footer(fig,s):fig.text(.055,.045,s,fontsize=11,color=MUT)
def save(fig,name):
 for ext in ['png','svg']:fig.savefig(OUT/f'{name}.{ext}',dpi=180,facecolor=BG)
 plt.close(fig)
# 1 overall
fig=page('전체 댓글의 감정 분포','전체 2,983개 댓글의 AI 참조 라벨 집계 · 원댓글과 답글 포함')
ax=fig.add_axes([.12,.22,.75,.56]);labs=['긍정','부정','중립','혼합','판단 불가'];vals=[META['sentiment_counts'][k] for k in labs];p=np.array(vals)/2983*100
bars=ax.barh(labs,p,color=COL,height=.6);ax.invert_yaxis()
for b,n,v in zip(bars,vals,p):ax.text(v+.65,b.get_y()+b.get_height()/2,f'{n:,}개  ·  {v:.1f}%',va='center',fontsize=20,color=INK)
ax.set_xlim(0,53);ax.set_xticks([0,10,20,30,40,50],[f'{n}%' for n in [0,10,20,30,40,50]]);ax.spines[['top','right','left']].set_visible(False);ax.spines['bottom'].set_color('#D8DEE5');ax.tick_params(axis='y',length=0,pad=15,labelsize=20);ax.tick_params(axis='x',colors=MUT);ax.set_axisbelow(True);ax.grid(axis='x',color='#EBEEF2')
fig.text(.12,.12,'중립 댓글이 가장 많음 → 질문·정보성 반응을 긍정·부정과 구분할 필요',fontsize=20,fontweight='bold',color=INK)
footer(fig,'수집: 2026.10.15 | AI 라벨 집계이며 TF-IDF·로지스틱 회귀 모델의 예측 분포가 아님')
save(fig,'01_전체댓글_감정분포')
# 2 category
fig=page('반응 대상별 감정 분포','전체 2,983개 원문·답글 문맥 재검토 · 의미 기준 주대상 1개씩 분류')
a=np.array([[int(r[k]) for k in labs] for r in DATA['cross']]);tot=a.sum(axis=1);pc=a/tot[:,None]*100
names=[r['댓글구분'] for r in DATA['cross']];ax=fig.add_axes([.30,.26,.64,.54]);left=np.zeros(len(names))
for j in range(5):
 ax.barh(range(len(names)),pc[:,j],left=left,height=.67,color=COL[j],label=labs[j])
 for i in range(len(names)):
  if pc[i,j]>=9:ax.text(left[i]+pc[i,j]/2,i,f'{pc[i,j]:.1f}%',ha='center',va='center',fontsize=15,color='white',fontweight='bold')
 left+=pc[:,j]
ax.set_yticks(range(len(names)),[f'{n} (n={v:,})' for n,v in zip(names,tot)],fontsize=15);ax.invert_yaxis();ax.set_xlim(0,100);ax.set_xticks([0,25,50,75,100],['0%','25%','50%','75%','100%']);ax.spines[['top','right','left']].set_visible(False);ax.tick_params(axis='y',length=0,pad=12);ax.legend(ncol=5,loc='upper center',bbox_to_anchor=(.5,-.06),frameon=False,fontsize=15)
fig.text(.055,.115,'영상·제작자: 긍정 284개 / 부정 77개     포스터: 긍정 3개 / 부정 59개',fontsize=18,fontweight='bold',color=INK)
footer(fig,'AI 2차 의미 라벨 기준 | 8개 주대상 합계 2,983개 | 기타는 잡담·대인 대화·대상불명이며 키워드 미일치와 다름')
save(fig,'02_댓글구분별_감정분포')
# 3 pipeline
fig=page('TF-IDF와 로지스틱 회귀 기반 감정 이진 분류','명확한 긍정·부정 댓글 1,287개를 학습·검증·테스트로 분할')
ax=fig.add_axes([0,0,1,1]);ax.set_xlim(0,1);ax.set_ylim(0,1);ax.axis('off')
steps=[('댓글 입력','원문과 답글 문맥'),('TF-IDF','단어와 연속 단어쌍을 수치화'),('로지스틱 회귀','특징과 감정 라벨의 관계 학습'),('감정 예측','긍정 또는 부정')]
xs=[.055,.292,.529,.766]
for i,((t,s),x) in enumerate(zip(steps,xs)):
 ax.add_patch(FancyBboxPatch((x,.51),.179,.205,boxstyle='round,pad=0.013,rounding_size=.015',facecolor='#F0F5F9' if i!=3 else '#E8F3EF',edgecolor='#D9E3EB',linewidth=1.3))
 ax.text(x+.0895,.645,t,ha='center',fontsize=22,fontweight='bold',color=INK)
 ax.text(x+.0895,.565,s.replace('특징과 감정 라벨의 관계 학습','특징과 감정 라벨의\n관계 학습').replace('단어와 연속 단어쌍을 수치화','단어와 연속 단어쌍을\n수치화'),ha='center',va='center',fontsize=14,color=MUT)
 if i<3:ax.add_patch(FancyArrowPatch((x+.195,.61),(xs[i+1]-.02,.61),arrowstyle='-|>',mutation_scale=21,color='#6B8195',linewidth=2))
ax.text(.055,.375,'학습용 라벨',fontsize=18,fontweight='bold',color=INK);ax.text(.205,.375,'AI 참조 라벨 중 명확한 긍정·부정만 사용',fontsize=18,color=INK)
for x,title,n in [(.055,'학습',767),(.37,'검증',264),(.685,'테스트',256)]:
 ax.add_patch(FancyBboxPatch((x,.16),.26,.135,boxstyle='round,pad=.012',facecolor='#F6F8FA',edgecolor='none'))
 ax.text(x+.13,.244,f'{title}  {n}개',ha='center',fontsize=23,fontweight='bold',color=INK)
 ax.text(x+.13,.19,{'학습':'단어장·IDF·모델 학습','검증':'후보 모델 비교 및 선택','테스트':'선택 후 최종 성능 평가'}[title],ha='center',fontsize=14,color=MUT)
footer(fig,'원댓글·답글 및 동일 본문은 같은 그룹으로 분할 | 포스터·관람환경·중립·혼합·판단 불가 등은 이진 학습에서 제외')
save(fig,'03_감정분류모델_처리과정')
# 4 confusion
fig=page('감정 이진 분류 모델의 테스트 결과','학습에 사용하지 않은 댓글 256개 · AI 참조 라벨과 모델 예측 비교')
ax=fig.add_axes([.10,.22,.39,.54]);a=np.array(METRICS["test_confusion_matrix_labels_0_1"]);ax.imshow(a,cmap='Blues',vmin=0,vmax=140)
for i in range(2):
 for j in range(2):ax.text(j,i,str(a[i,j]),ha='center',va='center',fontsize=37,fontweight='bold',color='white' if a[i,j]>75 else INK)
ax.set_xticks([0,1],['부정','긍정'],fontsize=19);ax.set_yticks([0,1],['부정','긍정'],fontsize=19);ax.set_xlabel('모델 예측',fontsize=17,labelpad=12);ax.set_ylabel('AI 참조 라벨',fontsize=17,labelpad=12);ax.tick_params(length=0)
fig.text(.57,.71,'204 / 256개 일치',fontsize=30,fontweight='bold',color=INK);fig.text(.57,.59,'Accuracy',fontsize=18,color=MUT);fig.text(.79,.59,'0.7969',fontsize=28,fontweight='bold',color=INK);fig.text(.57,.48,'Macro-F1',fontsize=18,color=MUT);fig.text(.79,.48,'0.7961',fontsize=28,fontweight='bold',color=INK)
fig.text(.57,.32,'부정 → 긍정 오류: 28개\n긍정 → 부정 오류: 24개',fontsize=20,linespacing=1.7,color=INK)
footer(fig,'선택 모델: Unigram + Bigram TF-IDF + 로지스틱 회귀 | AI 참조 라벨과의 일치도이며 사람 합의 정답에 대한 정확도가 아님')
save(fig,'04_모델성능_혼동행렬')
# 5 actual test examples
fig=page('실제 테스트 댓글의 분류 사례','AI 참조 라벨과 로지스틱 회귀 예측을 함께 비교')
ax=fig.add_axes([0,0,1,1]);ax.set_xlim(0,1);ax.set_ylim(0,1);ax.axis('off')
examples=[('진짜 보면 볼 수록 마블영화들 잘 만들어졌다','긍정','긍정',True),('마블은 엔드게임을 마지막으로 버블이 되었다.','부정','부정',True),('또 봐도 울컥하네.. 10년뒤에 보고 또 울컥하겠지','긍정','부정',False)]
ax.text(.065,.77,'댓글 원문',fontsize=17,color=MUT);ax.text(.66,.77,'AI 참조',fontsize=17,color=MUT);ax.text(.79,.77,'모델 예측',fontsize=17,color=MUT);ax.text(.91,.77,'결과',fontsize=17,color=MUT)
for y,(t,label,pred,correct) in zip([.65,.49,.33],examples):
 ax.add_patch(FancyBboxPatch((.055,y-.065),.89,.13,boxstyle='round,pad=.012',facecolor='#F4F7FA' if correct else '#FFF0ED',edgecolor='none'))
 ax.text(.07,y,t,fontsize=20,va='center',color=INK);ax.text(.68,y,label,fontsize=21,ha='center',va='center',color=COL[0] if label=='긍정' else COL[1]);ax.text(.82,y,pred,fontsize=21,ha='center',va='center',color=COL[0] if pred=='긍정' else COL[1]);ax.text(.925,y,'일치' if correct else '오류',fontsize=18,ha='center',va='center',color=INK)
ax.text(.055,.15,'감동을 표현하는 문맥 의존 댓글에서도 분류 오류가 나타남',fontsize=22,fontweight='bold',color=INK)
footer(fig,'실제 test_predictions.csv / test_errors.csv의 사례 | 마지막 사례: AI 긍정, 모델 부정(긍정 확률 0.4533)')
save(fig,'05_실제댓글_모델분류사례')
# zip user-facing assets only
with ZipFile(OUT/'PPT_시각자료_재검토_5종.zip','w') as z:
 for p in sorted([p for p in OUT.iterdir() if p.suffix in {'.png','.svg'}]):z.write(p,p.name)
print('Created 5 PNG and 5 SVG files')
