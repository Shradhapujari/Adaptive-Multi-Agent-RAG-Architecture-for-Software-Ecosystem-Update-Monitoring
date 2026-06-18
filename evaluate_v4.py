import json,time,sys,requests
from pathlib import Path
from datetime import datetime
from collections import defaultdict

RELEASES_API="https://releasetrain.io/api/v/"
REDDIT_API="https://releasetrain.io/api/reddit/query/positive"
CVE_API="https://releasetrain.io/api/reddit/query/cve"
QUESTIONS_API="https://releasetrain.io/api/reddit/query/questions"
LOCAL_DATA=Path(__file__).parent/"data"/"enhanced_automated_sentiment_results.json"
QUESTIONS_FILE="reddit_questions.json"
RESULTS_FILE="evaluation_results_v4.json"

SYNONYMS={"linux":["linux","ubuntu","debian","kernel","fedora"],"security":["security","vulnerability","cve","patch","exploit","advisory"],"bug":["bug","defect","issue","error","crash","regression"],"fix":["fix","patch","resolve","resolved","hotfix"],"update":["update","upgrade","release","version","changelog"],"critical":["critical","severe","high","urgent","major"],"python":["python","pip","pypi"],"chrome":["chrome","chromium","browser"],"windows":["windows","microsoft"],"macos":["macos","mac","apple"],"nodejs":["nodejs","node","npm"]}
EXPANSIONS={"bug":"bug fix resolved defect error","update":"software update release changelog","security":"security vulnerability CVE patch","fix":"bug fix resolved patch","crash":"crash bug error fix","issue":"issue bug error problem","latest":"latest version release changelog","broken":"bug broken fix resolved","help":"bug issue error fix","why":"bug issue error cause","how":"update release notes changelog","what":"update release notes changelog","anyone":"community issue bug fix","still":"update fix patch resolved"}

def load_local():
    if LOCAL_DATA.exists():
        with open(LOCAL_DATA) as f:
            posts=json.load(f).get("all_analyzed_posts",[])
        return [{"title":p["title"],"subreddit":p["subreddit"],"sentiment":p["title_sentiment"]["label"],"source":"local"} for p in posts]
    return []
LOCAL_POSTS=load_local()

def categorize(title):
    t=title.lower()
    if any(w in t for w in ["cve","vulnerability","security","patch","exploit","hack"]): return "security"
    if any(w in t for w in ["bug","crash","broken","error","fix","issue","not working"]): return "bugs"
    if any(w in t for w in ["release","version","changelog","update","upgrade"]): return "releases"
    if any(w in t for w in ["community","opinion","feel","think","anyone","users"]): return "community"
    return "general"

def fetch_questions(target=50):
    print(f"\n  Fetching real Reddit questions from releasetrain.io/api/reddit/query/questions...")
    all_q,seen=[],set()
    try:
        r=requests.get(QUESTIONS_API,timeout=30)
        if r.status_code==200:
            posts=r.json().get("data",[])
            print(f"  Got {len(posts)} questions from API")
            for p in posts:
                title=p.get("title","").strip()
                sub=p.get("subreddit","")
                if title and title not in seen:
                    seen.add(title)
                    all_q.append({"query":title,"source":"questions_api","subreddit":sub,"url":p.get("url",""),"date":p.get("created_utc","")[:10],"category":categorize(title)})
                if len(all_q)>=target: break
    except Exception as e:
        print(f"  Questions API error: {e}")
    if len(all_q)<target:
        try:
            r2=requests.get(CVE_API,params={"q":"CVE-","limit":20},timeout=30)
            if r2.status_code==200:
                for p in r2.json().get("data",[]):
                    title=p.get("title","").strip()
                    if title and title not in seen:
                        seen.add(title)
                        all_q.append({"query":title,"source":"cve_api","subreddit":p.get("subreddit",""),"url":p.get("url",""),"date":p.get("created_utc","")[:10],"category":"security"})
        except: pass
    if len(all_q)<target and LOCAL_DATA.exists():
        print(f"  Supplementing with local dataset...")
        for p in LOCAL_POSTS:
            title=p["title"].strip()
            if title and title not in seen and "?" in title:
                seen.add(title)
                all_q.append({"query":title,"source":"local","subreddit":p["subreddit"],"url":"","date":"2025-10-07","category":categorize(title)})
            if len(all_q)>=target: break
    print(f"  Total: {len(all_q)} questions")
    for q in all_q[:5]: print(f"    [{q['category']:10}] {q['query'][:65]}")
    return all_q[:target]

def expand(terms):
    exp=set(terms)
    for t in terms:
        for base,syns in SYNONYMS.items():
            if t in syns or t==base: exp.update(syns)
    return exp

def fetch_releases(query,limit=8,min_overlap=2):
    try:
        r=requests.get(RELEASES_API,timeout=30)
        all_v=r.json().get("versions",[]) if r.status_code==200 else []
        exp=expand(set(query.lower().split()))
        scored=[]
        for v in all_v:
            txt=(" ".join(v.get("versionSearchTags",[]))+v.get("versionProductName","")+v.get("versionReleaseNotes","")).lower()
            overlap=sum(1 for t in exp if t in txt)
            if overlap>=min_overlap: scored.append((overlap,v))
        scored.sort(key=lambda x:x[0],reverse=True)
        return [v for _,v in scored[:limit]]
    except: return []

def fetch_community(query,limit=5):
    exp=expand(set(query.lower().split()))
    try:
        r=requests.get(REDDIT_API,timeout=15)
        if r.status_code==200:
            all_p=r.json().get("data",[])
            scored=[(sum(1 for t in exp if t in (p.get("title","")+p.get("subreddit","")).lower()),p) for p in all_p]
            scored=sorted([(s,p) for s,p in scored if s>0],key=lambda x:x[0],reverse=True)
            results=[p for _,p in scored[:limit]]
            if results: return results,"live"
    except: pass
    scored=[(sum(1 for t in exp if t in (p["title"]+p["subreddit"]).lower()),p) for p in LOCAL_POSTS]
    scored=sorted([(s,p) for s,p in scored if s>0],key=lambda x:x[0],reverse=True)
    return [p for _,p in scored[:limit]],"local"

def fetch_cve(query,limit=3):
    try:
        r=requests.get(CVE_API,params={"q":query,"limit":limit},timeout=30)
        return r.json().get("data",[]) if r.status_code==200 else []
    except: return []

def auto_keywords(query):
    stop={"a","an","the","is","are","was","be","have","has","do","does","did","will","would","could","should","may","might","can","i","my","we","our","you","your","they","it","in","on","at","by","for","with","about","from","to","of","and","or","but","if","any","all","not","after","before","since","just","get","why","how","what","when","where","who","that","this"}
    return list(set([w.strip("?!.,") for w in query.lower().split() if len(w.strip("?!.,"))>2 and w.strip("?!.,") not in stop]))[:8]

def score(releases,community,cve,keywords):
    exp=list(expand(set(keywords))); s=0.0
    total=len(releases)+len(community)+len(cve)
    s+=0.20*min(total/8.0,1.0)
    if releases:
        txt=" ".join([v.get("versionProductName","")+v.get("versionReleaseNotes","")+" ".join(v.get("versionSearchTags",[])) for v in releases]).lower()
        s+=0.40*min(sum(1 for k in exp if k in txt)/max(len(keywords),1),1.0)
    if community:
        txt=" ".join([p.get("title","")+p.get("subreddit","") for p in community]).lower()
        s+=0.25*min(sum(1 for k in exp if k in txt)/max(len(keywords),1),1.0)
    if cve:
        txt=" ".join([c.get("title","")+(c.get("author_description") or "") for c in cve]).lower()
        s+=0.15*min(sum(1 for k in exp if k in txt)/max(len(keywords),1),1.0)
    return round(min(s,1.0),3)

def sig(q): return "excellent" if q>=0.7 else "positive" if q>=0.5 else "acceptable" if q>=0.3 else "negative"

def rewrite(query):
    rw=query.lower()
    for k,v in EXPANSIONS.items():
        if k in rw: rw=rw.replace(k,v)
    return rw

def run_baseline(qobj):
    q=qobj["query"]; kw=auto_keywords(q)
    r=fetch_releases(q,3,2); c,src=fetch_community(q,3)
    qual=score(r,c,[],kw)
    return {"query":q,"system":"baseline","category":qobj["category"],"source":qobj["source"],"releases":len(r),"community":len(c),"community_src":src,"cve":0,"quality":qual,"signal":sig(qual)}

def run_marag(qobj,mem):
    q=qobj["query"]; kw=auto_keywords(q)
    rw=rewrite(q)
    best=sorted(mem.items(),key=lambda x:x[1],reverse=True)[:3]
    if best: rw+=" "+" ".join(t for t,_ in best if t not in rw)
    r=fetch_releases(rw,8,2); c,src=fetch_community(rw,5); cv=fetch_cve(q,3)
    qual=score(r,c,cv,kw); retried=False
    if sig(qual)=="negative":
        r2=fetch_releases(q+" software update security patch release fix",8,1)
        c2,src2=fetch_community(q+" software update security patch release",5)
        q2=score(r2,c2,cv,kw)
        if q2>qual: r,c,src,qual,retried=r2,c2,src2,q2,True
    for t in set(rw.lower().split())-set(q.lower().split()):
        if len(t)>3 and t.isalpha(): mem[t]=mem.get(t,0.0)+(qual-0.3)
    return {"query":q,"system":"marag","category":qobj["category"],"source":qobj["source"],"rewritten":rw[:80],"releases":len(r),"community":len(c),"community_src":src,"cve":len(cv),"quality":qual,"signal":sig(qual),"retried":retried}

def run_eval(queries):
    print(f"\n{'='*64}\n  Multi-Agent RAG System v4 — {len(queries)} Real Reddit Questions — {datetime.now().strftime('%H:%M')}\n{'='*64}")
    br,ar,curve,mem=[],[],[],{}
    for i,q in enumerate(queries,1):
        print(f"\n  [{i:02d}/{len(queries)}] [{q['source'][:8]}] {q['query'][:55]}\n  {'-'*60}")
        b=run_baseline(q); br.append(b)
        print(f"  Baseline : {b['quality']:.3f} | {b['signal']:10} | r={b['releases']} c={b['community']}({b['community_src']})")
        a=run_marag(q,mem); ar.append(a)
        print(f"  Multi-Agent RAG System    : {a['quality']:.3f} | {a['signal']:10} | r={a['releases']} c={a['community']}({a['community_src']}) cve={a['cve']}" + (" ↺" if a.get("retried") else ""))
        imp=round(a["quality"]-b["quality"],3)
        print(f"  Change   : {imp:+.3f}  {'✅' if imp>0.01 else '➖' if abs(imp)<=0.01 else '⚠️'}")
        curve.append({"n":i,"query":q["query"],"category":q["category"],"source":q["source"],"baseline":b["quality"],"marag":a["quality"],"improvement":imp,"memory_size":len(mem)})
        time.sleep(0.2)
    return br,ar,curve,mem

def report(br,ar,curve,mem):
    b_avg=sum(r["quality"] for r in br)/len(br); a_avg=sum(r["quality"] for r in ar)/len(ar)
    imp=round(((a_avg-b_avg)/max(b_avg,0.001))*100,1)
    retried=sum(1 for r in ar if r.get("retried"))
    better=sum(1 for b,a in zip(br,ar) if a["quality"]-b["quality"]>0.01)
    cats=defaultdict(list)
    for b,a in zip(br,ar): cats[a["category"]].append((b["quality"],a["quality"]))
    early=curve[:max(len(curve)//3,1)]; late=curve[-max(len(curve)//3,1):]
    ea=sum(c["marag"] for c in early)/len(early); la=sum(c["marag"] for c in late)/len(late)
    lc=round(((la-ea)/max(ea,0.001))*100,1)
    print(f"\n{'='*64}\n  RESULTS — Real Reddit Questions\n{'='*64}")
    print(f"  Total queries     : {len(br)}")
    print(f"  Source            : releasetrain.io/api/reddit/query/questions")
    print(f"  Baseline avg      : {b_avg:.3f} ({b_avg:.1%})")
    print(f"  Multi-Agent RAG System avg         : {a_avg:.3f} ({a_avg:.1%})")
    print(f"  Improvement       : +{imp}%")
    print(f"  Queries improved  : {better}/{len(br)} ({round(better/len(br)*100)}%)")
    print(f"  RLAIF retries     : {retried}/{len(ar)} ({round(retried/len(ar)*100)}%)")
    print(f"  Memory terms      : {len(mem)} (Zero Human Feedback)")
    print(f"  Learning gain     : +{lc}%")
    print(f"\n  Per category:")
    for cat,scores in sorted(cats.items()):
        ba=sum(s[0] for s in scores)/len(scores); aa=sum(s[1] for s in scores)/len(scores)
        i2=round(((aa-ba)/max(ba,0.001))*100,1)
        print(f"    {cat:12} n={len(scores):2d} base={ba:.3f} marag={aa:.3f} +{i2}%  {'█'*int(aa*20)}")
    print(f"\n  Top learned terms:")
    for t,s in sorted(mem.items(),key=lambda x:x[1],reverse=True)[:6]:
        print(f"    {t:20} {s:+.3f}")
    print(f"\n{'='*64}\n  PAPER NUMBERS\n{'='*64}")
    print(f"  Dataset : {len(br)} real Reddit questions from releasetrain.io")
    print(f"  Baseline: {b_avg:.1%} | Multi-Agent RAG System: {a_avg:.1%} | +{imp}%")
    print(f"  {better}/{len(br)} improved | {round(retried/len(ar)*100)}% RLAIF retries | {len(mem)} Zero-HF terms")
    return {"baseline_avg":round(b_avg,3),"marag_avg":round(a_avg,3),"improvement_pct":imp,"queries_improved":better,"rlaif_retry_rate":round(retried/len(ar)*100),"memory_terms":len(mem),"learning_gain":lc,"total_queries":len(br),"categories":{k:{"n":len(v),"baseline":round(sum(s[0] for s in v)/len(v),3),"marag":round(sum(s[1] for s in v)/len(v),3)} for k,v in cats.items()}}

if __name__=="__main__":
    fetch_only="--fetch" in sys.argv; quick="--quick" in sys.argv
    if fetch_only or not Path(QUESTIONS_FILE).exists():
        questions=fetch_questions(target=50)
        with open(QUESTIONS_FILE,"w") as f: json.dump(questions,f,indent=2)
        print(f"\n  Saved {len(questions)} questions → {QUESTIONS_FILE}")
        if fetch_only: sys.exit(0)
    else:
        with open(QUESTIONS_FILE) as f: questions=json.load(f)
        print(f"\n  Loaded {len(questions)} questions from {QUESTIONS_FILE}")
    qs=questions[:10] if quick else questions[:50]
    cats=defaultdict(int); srcs=defaultdict(int)
    for q in qs: cats[q["category"]]+=1; srcs[q["source"]]+=1
    print(f"  Mode: {'QUICK' if quick else 'FULL'} ({len(qs)}) | Categories: {dict(cats)} | Sources: {dict(srcs)}")
    br,ar,curve,mem=run_eval(qs)
    s=report(br,ar,curve,mem)
    with open(RESULTS_FILE,"w") as f:
        json.dump({"timestamp":datetime.now().isoformat(),"questions":qs,"summary":s,"baseline":br,"marag":ar,"curve":curve,"memory":mem},f,indent=2)
    print(f"\n  Saved → {RESULTS_FILE}")
