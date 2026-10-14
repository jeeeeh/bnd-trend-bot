"""
보넥도 트렌드 봇 (매일 아침 8시, GitHub Actions, 완전 무료)

- 한국: 네이버 블로그·뉴스(NAVER API HUB)에서 보이넥스트도어 관련 글을 모아
        같이 언급된 키워드 TOP 10 (전일 / 최근 7일) + 네이버 데이터랩 검색량 변화
- 영어: 구글 뉴스 RSS + Bluesky 에서 같이 언급된 키워드 TOP 10 (전일 / 최근 7일)
- 🔥 = 지난주 평소보다 전일에 2배 이상 많이 언급된 키워드
"""
import html
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))

NAVER_ID = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_IDS = [c.strip() for c in os.environ.get("CHAT_ID", "").split(",") if c.strip()]

KST = timezone(timedelta(hours=9))
NOW = datetime.now(KST)
YDAY = (NOW - timedelta(days=1)).date()          # 전일
WEEK_START = YDAY - timedelta(days=6)            # 최근 7일 = 전일 포함 7일
PREV_START = WEEK_START - timedelta(days=7)      # 비교용 그 전 7일
DOW = "월화수목금토일"
UA = {"User-Agent": "Mozilla/5.0 (bnd-trend-bot; personal telegram bot)"}

SELF = {w.lower() for w in CFG["self_words"]}
KO_STOP = set(CFG["ko_stopwords"]) | SELF
EN_STOP = set(CFG["en_stopwords"]) | SELF
errors = []


def clean(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


# ───────── 한국: 네이버 ─────────
def naver_get(path, **params):
    r = requests.get(
        f"https://naverapihub.apigw.ntruss.com/search/v1/{path}", params=params,
        headers={"X-NCP-APIGW-API-KEY-ID": NAVER_ID, "X-NCP-APIGW-API-KEY": NAVER_SECRET}, timeout=20)
    if r.status_code == 429:
        time.sleep(2)
        return naver_get(path, **params)
    if not r.ok:
        raise RuntimeError(f"{path} {r.status_code}: {r.text[:150]}")
    time.sleep(0.12)
    return r.json().get("items", [])


def collect_korean():
    """(날짜, 텍스트) 목록. 최근 14일치 (지난 7일 + 비교용 이전 7일)"""
    docs, seen = [], set()
    for kind in ("blog", "news"):
        for q in CFG["ko_queries"]:
            for start in range(1, 1000, 100):
                try:
                    items = naver_get(kind, query=q, display=100, start=start, sort="date")
                except Exception as e:
                    errors.append(f"네이버 {kind}: {e}")
                    break
                if not items:
                    break
                oldest = None
                for it in items:
                    try:
                        if kind == "blog":
                            d = datetime.strptime(it["postdate"], "%Y%m%d").date()
                        else:
                            d = parsedate_to_datetime(it["pubDate"]).astimezone(KST).date()
                    except Exception:
                        continue
                    oldest = d
                    key = it.get("link")
                    if key in seen or not (PREV_START <= d <= YDAY):
                        continue
                    seen.add(key)
                    docs.append((d, clean(it["title"]) + " " + clean(it.get("description", ""))))
                if oldest and oldest < PREV_START:
                    break  # 더 오래된 글까지 내려왔으면 그만
    print(f"한국 글 {len(docs)}건")
    return docs


def datalab():
    """전일 vs 그 전날, 최근 7일 평균 vs 이전 7일 평균 (검색량 변화 %)"""
    body = {
        "startDate": str(PREV_START), "endDate": str(YDAY), "timeUnit": "date",
        "keywordGroups": [{"groupName": CFG["name"], "keywords": CFG["datalab_keywords"][:20]}],
    }
    try:
        r = requests.post(
            "https://naverapihub.apigw.ntruss.com/search-trend/v1/search", json=body, timeout=20,
            headers={"X-NCP-APIGW-API-KEY-ID": NAVER_ID, "X-NCP-APIGW-API-KEY": NAVER_SECRET,
                     "Content-Type": "application/json"})
        if not r.ok:
            raise RuntimeError(f"{r.status_code}: {r.text[:150]}")
        data = {x["period"]: x["ratio"] for x in r.json()["results"][0]["data"]}
    except Exception as e:
        errors.append(f"데이터랩: {e}")
        return None
    day = lambda d: data.get(str(d), 0.0)
    y, y2 = day(YDAY), day(YDAY - timedelta(days=1))
    wk = sum(day(WEEK_START + timedelta(days=i)) for i in range(7)) / 7
    pw = sum(day(PREV_START + timedelta(days=i)) for i in range(7)) / 7
    pct = lambda a, b: None if b == 0 else (a - b) / b * 100
    return {"day": pct(y, y2), "week": pct(wk, pw)}


# 한국어 명사 추출 (kiwipiepy 형태소 분석기, 없으면 간단 규칙)
try:
    from kiwipiepy import Kiwi
    KIWI = Kiwi()
except Exception:
    KIWI = None
JOSA = re.compile(r"(으로|에서|에게|까지|부터|이랑|하고|처럼|보다|이라|라는|이다|입니다|했다|한다|해서|하며|하는|했던|됐다|되는|된|한|은|는|이|가|을|를|의|에|도|와|과|로|만)$")
ALIASES = sorted({q for q in CFG["ko_queries"] + CFG["en_queries"] + CFG["datalab_keywords"] + CFG["self_words"]}, key=len, reverse=True)
ALIAS_RE = re.compile("|".join(re.escape(a) for a in ALIASES), re.I)


def ko_terms(text):
    text = ALIAS_RE.sub(" ", text)  # 그룹 이름 자체는 키워드에서 제외
    terms = set()
    if KIWI:
        for t in KIWI.tokenize(text):
            if t.tag in ("NNP", "NNG", "SL", "SH") and len(t.form) >= 2:
                terms.add(t.form.lower() if t.tag == "SL" else t.form)
    else:
        for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", text):
            w = JOSA.sub("", w)
            if len(w) >= 2:
                terms.add(w.lower())
    return {t for t in terms if t not in KO_STOP and not t.isdigit()}


# ───────── 영어: 구글 뉴스 + Reddit ─────────
def collect_english():
    docs, seen = [], set()
    for q in CFG["en_queries"]:
        url = f"https://news.google.com/rss/search?q={quote(q)}+when:14d&hl=en-US&gl=US&ceid=US:en"
        try:
            root = ET.fromstring(requests.get(url, headers=UA, timeout=20).content)
            for it in root.iter("item"):
                title = it.findtext("title") or ""
                title = re.sub(r"\s+-\s+[^-]+$", "", title)  # 끝의 " - 언론사명" 제거
                d = parsedate_to_datetime(it.findtext("pubDate")).astimezone(KST).date()
                if title in seen or not (PREV_START <= d <= YDAY):
                    continue
                seen.add(title)
                docs.append((d, title))
        except Exception as e:
            errors.append(f"구글 뉴스: {e}")
    for q in ("boynextdoor", "#boynextdoor"):
        cursor = None
        for _ in range(5):
            try:
                params = {"q": q, "sort": "latest", "limit": 100, "lang": "en"}
                if cursor:
                    params["cursor"] = cursor
                r = requests.get("https://api.bsky.app/xrpc/app.bsky.feed.searchPosts", params=params, headers=UA, timeout=20)
                r.raise_for_status()
                j = r.json()
            except Exception as e:
                errors.append(f"Bluesky: {str(e)[:80]}")
                break
            oldest = None
            for p in j.get("posts", []):
                rec = p.get("record", {})
                try:
                    d = datetime.fromisoformat(rec["createdAt"].replace("Z", "+00:00")).astimezone(KST).date()
                except Exception:
                    continue
                oldest = d
                if p["uri"] in seen or not (PREV_START <= d <= YDAY):
                    continue
                seen.add(p["uri"])
                docs.append((d, rec.get("text", "")))
            cursor = j.get("cursor")
            if not cursor or (oldest and oldest < PREV_START):
                break
            time.sleep(0.5)
    print(f"영어 글 {len(docs)}건")
    return docs


def en_terms(text):
    text = ALIAS_RE.sub(" ", text)
    words = re.findall(r"[a-z][a-z0-9'\-]{1,}", text.lower())
    return {w.strip("'-") for w in words if w.strip("'-") not in EN_STOP and len(w.strip("'-")) >= 3}


# ───────── 집계 ─────────
def rank(docs, terms_fn):
    """전일 / 최근 7일 키워드 문서빈도 TOP N, 전일에 평소보다 급증한 키워드는 🔥"""
    day, week, prev = Counter(), Counter(), Counter()
    nd = nw = npv = 0
    for d, text in docs:
        ts = terms_fn(text)
        if d == YDAY:
            day.update(ts); nd += 1
        if WEEK_START <= d <= YDAY:
            week.update(ts); nw += 1
        else:
            prev.update(ts); npv += 1
    def surge(t, c):
        base = (week[t] - day[t] + prev[t] + 1) / max(nw - nd + npv, 1)  # 전일을 뺀 13일 평균 비율
        return (c / max(nd, 1)) / base
    top = CFG["top_n"]
    min_c = 2
    cand = [(t, c) for t, c in day.most_common(top * 3) if c >= min_c][:top]
    ranked = sorted((x for x in cand if x[1] >= 5 and surge(*x) >= CFG["hot_ratio"]), key=lambda x: -surge(*x))
    hot = {t for t, _ in ranked[: CFG["hot_max"]]}
    day_top = [(t, c, t in hot) for t, c in cand]
    week_top = [(t, c, False) for t, c in week.most_common(top * 3) if c >= min_c][:top]
    return day_top, week_top, nd, nw


def fmt_list(items):
    if not items:
        return "   (데이터 부족)"
    return "\n".join(f"   {i + 1}. {html.escape(t)} <i>{c}</i>{' 🔥' if h else ''}" for i, (t, c, h) in enumerate(items))


def pct_text(p):
    if p is None:
        return "-"
    arrow = "🔺" if p > 0 else ("🔻" if p < 0 else "➖")
    return f"{arrow}{abs(p):.0f}%"


def build_message(ko, en, dl):
    kd, kw, knd, knw = ko
    ed, ew, end, enw = en
    lines = [f"🎧 <b>{CFG['name']} 트렌드</b> · {YDAY.month}/{YDAY.day}({DOW[YDAY.weekday()]}) 기준"]
    if dl:
        lines.append(f"🔎 네이버 검색량  전일 {pct_text(dl['day'])} · 최근 7일 {pct_text(dl['week'])} (직전 기간 대비)")
    lines += [
        "",
        f"🇰🇷 <b>한국 · 전일</b> (글 {knd}건)", fmt_list(kd),
        "",
        f"🇰🇷 <b>한국 · 최근 7일</b> (글 {knw}건)", fmt_list(kw),
        "",
        f"🌏 <b>영어 · 전일</b> (글 {end}건)", fmt_list(ed),
        "",
        f"🌏 <b>영어 · 최근 7일</b> (글 {enw}건)", fmt_list(ew),
        "",
        "<i>숫자 = 그 단어가 함께 나온 글 수 · 🔥 = 평소보다 2배↑</i>",
    ]
    return "\n".join(lines)


def send(text):
    for cid in CHAT_IDS:
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", timeout=30,
                          json={"chat_id": cid, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True})
        if not r.ok:
            print(f"텔레그램 전송 실패({cid}): {r.text}", file=sys.stderr)


def main():
    if not (NAVER_ID and NAVER_SECRET):
        sys.exit("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET이 없어요.")
    ko = rank(collect_korean(), ko_terms)
    en = rank(collect_english(), en_terms)
    dl = datalab()
    text = build_message(ko, en, dl)
    print(text)
    for e in errors:
        print("!", e)
    if BOT_TOKEN and CHAT_IDS and os.environ.get("DRY_RUN") != "true":
        send(text)


if __name__ == "__main__":
    main()
