import requests, re
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36","Accept-Language":"ko-KR,ko;q=0.9"}
G="26007159"
t=requests.get(f"https://nol.yanolja.com/ticket/products/{G}",headers=H,timeout=20).text
t2=t.replace('\\"','"')
for k in ["goodsStatus","saleStatus","salesStatus","bookingStatus","goodsSaleStatus","playDate","playSeq","bookable","isSale","ticketOpen","bookingOpen","goodsName","playStartDate","playEndDate","bookingEndDate","onSale","soldOut","예매대기","예매하기","판매예정","판매종료","api-ticketfront","/v1/","ticket-api","apiBase","gateway"]:
    for m in list(re.finditer(re.escape(k),t2))[:3]:
        print(f"[{k}]", t2[max(0,m.start()-150):m.end()+250].replace("\n"," "))
        print("--")
chunks=sorted(set(re.findall(r'/_next/static/chunks/[^"\'\s]+\.js',t)))
print("CHUNKS",len(chunks))
base="https://nol.yanolja.com"
for c in chunks:
    try:
        js=requests.get(base+c,headers=H,timeout=20).text
    except Exception: continue
    for k in ["playSeq","remainSeat","PlaySeq","bookableDate","playDate"]:
        for m in list(re.finditer(k,js))[:2]:
            print(f"JS {c} [{k}]", js[max(0,m.start()-250):m.end()+250].replace("\n"," "))
            print("--")
