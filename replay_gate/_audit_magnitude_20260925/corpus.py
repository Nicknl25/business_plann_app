import sys, json; sys.path.insert(0, sys.argv[1])
from db import conn
c=conn(); cur=c.cursor()
cur.execute("SELECT messages_json FROM intake_consult_drafts WHERE updated_at >= '2026-08-01'")
seen=set(); out=[]
for (m,) in cur.fetchall():
  try: msgs=json.loads(m or "[]")
  except Exception: continue
  for x in msgs:
    if isinstance(x,dict) and x.get("role")=="user":
      t=str(x.get("content") or "")
      if t and t not in seen: seen.add(t); out.append(t)
adv=["since April twenty sixteen","we started in twenty nineteen","nine fabricators and fitters","one of our customers","a couple of years","a hundred percent","about a third","one or two jobs a week","two to three thousand","between five and six thousand a month","twenty-four months left","twenty four seven","one hundred and one","nineteen ninety-five","in two thousand nineteen","two thousand and nineteen","a thousand","a million bucks","half a million","one and a half million","three to four hundred thousand","twelve fifty an hour","thirty-five an hour","forty hours a week","fifty-two weeks","twenty twenty-four","the year two thousand","eleven people","seven days a week","one point five","two point five percent","one to two percent","six or seven thousand a month","sixty-forty split","an hour and a half","a dozen","nine to five","one-off","one time","a few hundred dollars","several thousand","tens of thousands","hundreds of jobs","twenty-somethings","first", "twenty thousand one hundred", "one thousand nine hundred ninety five", "ninety nine", "sixty five thousand to seventy thousand", "5 hundred", "2 thousand", "10 million", "1.2 million", "twenty 5", "four point two five percent", "zero", "point five", "eight hundred thousand and fifty"]
json.dump(out+adv, open(sys.argv[2],"w"))
print(len(out), len(adv))
