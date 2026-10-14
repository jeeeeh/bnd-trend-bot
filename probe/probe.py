import requests, re, json
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36","Accept":"application/json, text/plain, */*","Referer":"https://nol.yanolja.com/","Origin":"https://nol.yanolja.com"}
G="26007159"
urls=[
 f"https://api-ticketfront.interpark.com/v1/goods/{G}/summary?goodsCode={G}&priceGrade=&seatGrade=",
 f"https://api-ticketfront.interpark.com/v1/goods/{G}/playSeq?endDate=20261231&goodsCode={G}&isBookableDate=true&page=1&pageSize=1550&startDate=20261201",
 f"https://api-ticketfront.interpark.com/v1/goods/{G}/playSeq?endDate=20261231&goodsCode={G}&isBookableDate=false&page=1&pageSize=1550&startDate=20261201",
 f"https://nol.yanolja.com/ticket/products/{G}",
 f"https://tickets.interpark.com/goods/{G}",
]
for u in urls:
    try:
        r=requests.get(u,headers=H,timeout=20)
        t=r.text
        print("=====",u,r.status_code,len(t))
        if "json" in r.headers.get("content-type",""):
            print(t[:2500])
        else:
            for m in sorted(set(re.findall(r"https?://[a-zA-Z0-9.\-]*(?:api|ticket)[a-zA-Z0-9.\-]*/[^\"'\s<>]{0,80}",t)))[:60]: print("  url:",m)
            nd=re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',t,re.S)
            if nd: print("  NEXT_DATA:",nd.group(1)[:3000])
            for k in ["playSeq","bookable","remainSeat","예매","판매","schedule"]:
                print("  has",k,k in t)
    except Exception as e: print("ERR",u,e)
