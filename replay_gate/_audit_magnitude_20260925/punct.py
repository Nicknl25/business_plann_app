import json,sys,re
o=json.load(open(sys.argv[1]+"/old.json")); n=json.load(open(sys.argv[1]+"/new.json"))
pat=re.compile(r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)[- ]?\w*\s+(hundred|thousand|million|billion)[.!?;:]", re.I)
hits=[s for s in o if pat.search(s.replace(",",""))]
print("real messages with a spoken amount ending in punctuation:",len(hits))
for s in hits:
  m=pat.search(s.replace(",",""))
  seg=s.replace(",","")[max(0,m.start()-60):m.end()+5]
  print(repr(seg)); print("   OLD",o[s][0][:8]); print("   NEW",n[s][0][:8])
