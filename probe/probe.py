import requests, re
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36","Accept-Language":"ko-KR,ko;q=0.9"}
G="26007159"
t=requests.get(f"https://nol.yanolja.com/ticket/products/{G}",headers=H,timeout=20).text
srcs=sorted(set(re.findall(r'(?:src|href)="([^"]+\.js)"',t)) | set(re.findall(r'"(/_next/static/[^"]+\.js)"',t.replace('\\"','"'))))
print("JS files",len(srcs))
hosts=set()
for c in srcs:
    u=c if c.startswith("http") else "https://nol.yanolja.com"+c
    try: js=requests.get(u,headers=H,timeout=20).text
    except Exception: continue
    for h in re.findall(r'https://[a-zA-Z0-9.\-]+(?:yanolja|interpark|nol)[a-zA-Z0-9.\-]*\.(?:com|kr)[^"\'`\s]{0,60}',js): hosts.add(h)
    for k in ["ticketDates","playSeqs","play-seq","playseq","/dates","schedules","bookableDates","remain"]:
        for m in list(re.finditer(re.escape(k),js))[:2]:
            print(f"JS {u[-40:]} [{k}]", js[max(0,m.start()-300):m.end()+300].replace("\n"," "))
            print("--")
print("HOSTS"); [print(" ",h) for h in sorted(hosts)[:80]]
