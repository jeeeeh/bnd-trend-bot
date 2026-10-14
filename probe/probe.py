import requests, json
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36","Referer":"https://nol.yanolja.com/ticket/products/26007159","Accept":"application/json"}
for a,b in [("2026-11-25","2026-11-29"),("2026-12-01","2026-12-10")]:
    r=requests.get("https://nol.yanolja.com/ticket/products/api/schedules",params={"goodsKey":"26007159:15711202","playStartDate":a,"playEndDate":b},headers=H,timeout=20)
    print("=====",a,b,r.status_code); print(r.text[:3000])
    try:
        c=r.json().get("content",[])
        if c:
            s=c[0]; print("KEYS",list(s.keys()))
            r2=requests.get("https://nol.yanolja.com/ticket/products/api/remaining-seats",params={"goodsCode":"26007159","playSeq":s.get("playSeq")},headers=H,timeout=20)
            print("REMAIN",r2.status_code,r2.text[:800])
    except Exception as e: print("ERR",e)
