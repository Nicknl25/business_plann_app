import json,sys
from collections import Counter
o=json.load(open(sys.argv[1]+"/old.json")); n=json.load(open(sys.argv[1]+"/new.json"))
new_only=[]; lost=[]; order=0; same=0
for s in o:
  of=Counter(round(x,4) for x in o[s][0]); nf=Counter(round(x,4) for x in n[s][0])
  add=nf-of; rem=of-nf
  if not add and not rem: same+=1; continue
  if add: new_only.append((s,sorted(add.elements()),o[s][0],n[s][0]))
  if rem and not add: lost.append((s,sorted(rem.elements()),n[s][0]))
print("same",same,"with-new-figures",len(new_only),"only-lost",len(lost))
# classify new figures: is new figure == some old figure *1000/*1e6 etc (magnitude fix) or brand new
def explained(x, old):
  return any(abs(x-y*k)<0.01 for y in old for k in (1,1000,1e6,1e9,100))
sus=[r for r in new_only if not all(explained(x,r[2]) for x in r[1])]
print("new figures not a rescale of an old one:",len(sus))
for s,a,of,nf in sus: print(repr(s[:220]),"\n   ADD",a,"\n   OLD",of,"\n   NEW",nf)
print("==== LOST-ONLY sample")
for s,r,nf in lost[:40]: print(repr(s[:200]),"LOST",r,"NEW",nf)
