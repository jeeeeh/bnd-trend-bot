"""
보넥도 트렌드 봇 (매일 아침 8시, GitHub Actions, 완전 무료)

- 한국: 네이버 블로그(NAVER API HUB) + 유튜브(한글 제목·설명·댓글)에서 보이넥스트도어 관련 글을 모아
        같이 언급된 키워드 TOP 10 (전일 / 최근 7일) + 네이버 데이터랩 검색량 변화
- 영어: 유튜브(영어 제목·설명·댓글) + Bluesky 에서 같이 언급된 키워드 TOP 10 (전일 / 최근 7일)
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
YT_KEY = os.environ.get("YOUTUBE_API_KEY", "")
CHAT_IDS = [c.strip() for c in os.environ.get("CHAT_ID", "").split(",") if c.strip()]

KST = timezone(timedelta(hours=9))
NOW = datetime.now(KST)
YDAY = (NOW - timedelta(days=1)).date()          # 전일
WEEK_START = YDAY - timedelta(days=6)            # 최근 7일 = 전일 포함 7일
PREV_START = WEEK_START - timedelta(days=7)      # 비교용 그 전 7일
DOW = "월화수목금토일"
UA = {"User-Agent": "Mozilla/5.0 (bnd-trend-bot; personal telegram bot)"}

SELF = {w.lower() for w in CFG["self_words"]}
NORM = lambda w: re.sub(r"[\s\-_.·()&']", "", w.lower())
ARTISTS = {NORM(w) for w in CFG.get("exclude_artists", [])} - {NORM(m) for m in CFG.get("members", [])}


def is_excluded(term):
    """다른 가수·그룹 이름, 음악방송·시상식 이름이면 제외 (조합이 이름 일부여도 제외: 제로 베이스 → 제로베이스원)"""
    n = NORM(term)
    return n in ARTISTS or any(len(a) >= 4 and (a in n or (len(n) >= 4 and n in a)) for a in ARTISTS)
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
    for kind in ("blog",):
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
    print(f"네이버 블로그 {len(docs)}건")
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
    """(단어 집합, 2단어 조합 집합). 조합 = 문장 안에서 바로 이어지는 명사 두 개 (조사 사이에 껴도 OK)"""
    text = ALIAS_RE.sub(" | ", text)  # 그룹 이름 자리는 끊어서 조합이 넘어가지 않게
    ok = lambda t: (len(t) >= 2 and t not in KO_STOP and t not in EN_STOP and not t.isdigit()
                    and not is_excluded(t) and not (t.isascii() and len(t) < 3))
    words, pairs = set(), set()
    if KIWI:
        prev, gap = None, 0
        for t in KIWI.tokenize(text):
            if t.tag in ("NNP", "NNG", "SL", "SH"):
                w = t.form.lower() if t.tag == "SL" else t.form
                if ok(w):
                    words.add(w)
                    if prev and gap <= 1 and prev != w and not is_excluded(prev + w):
                        pairs.add(f"{prev} {w}")
                    prev, gap = w, 0
                else:
                    prev = None
            elif t.tag.startswith("J") or t.tag in ("XSN",):
                gap += 1   # 조사는 건너뜀 (예: 일본의 투어 → 일본 투어)
            else:
                prev = None
    else:
        prev = None
        for raw in re.findall(r"[가-힣A-Za-z0-9]+|[^\s가-힣A-Za-z0-9]", text):
            w = JOSA.sub("", raw).lower()
            if ok(w):
                words.add(w)
                if prev and prev != w:
                    pairs.add(f"{prev} {w}")
                prev = w
            else:
                prev = None
    return words, pairs


# ───────── 영어: 구글 뉴스 + Reddit ─────────
def collect_english():
    docs, seen = [], set()
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
    print(f"Bluesky {len(docs)}건")
    return docs


def en_terms(text):
    text = ALIAS_RE.sub(" | ", text).lower()
    for a in CFG.get("exclude_artists", []):  # 여러 단어로 된 이름(stray kids, music bank 등) 먼저 제거
        if " " in a:
            text = text.replace(a.lower(), " | ")
    ok = lambda w: len(w) >= 3 and w not in EN_STOP and not is_excluded(w)
    words, pairs, prev = set(), set(), None
    for raw in re.findall(r"[a-z][a-z0-9'\-]*|[^\sa-z]", text):
        w = raw.strip("'-")
        if ok(w):
            words.add(w)
            if prev and prev != w:
                pairs.add(f"{prev} {w}")
            prev = w
        else:
            prev = None
    return words, pairs



# ───────── 유튜브 (YouTube Data API v3, 무료 하루 1만 단위 중 약 1천 사용) ─────────
HANGUL = re.compile(r"[가-힣]")


def yt_get(path, **params):
    params["key"] = YT_KEY
    r = requests.get(f"https://www.googleapis.com/youtube/v3/{path}", params=params, timeout=20)
    if not r.ok:
        raise RuntimeError(f"{path} {r.status_code}: {r.text[:150]}")
    return r.json()


def collect_youtube():
    """(한국 docs, 영어 docs). 영상 제목+설명, 그리고 조회수 상위 영상의 최근 댓글"""
    ko, en = [], []
    if not YT_KEY:
        errors.append("유튜브: YOUTUBE_API_KEY가 없어요")
        return ko, en

    def add(d, text):
        if not (PREV_START <= d <= YDAY) or not text.strip():
            return
        if HANGUL.search(text):
            ko.append((d, text))
        elif len(re.findall(r"[A-Za-z]", text)) >= 10:
            en.append((d, text))

    after = datetime.combine(PREV_START, datetime.min.time(), KST).isoformat()
    videos = {}
    for q in CFG["yt_queries"]:
        token = None
        for _ in range(3):
            try:
                params = {"part": "snippet", "q": q, "type": "video", "order": "date",
                          "publishedAfter": after, "maxResults": 50}
                if token:
                    params["pageToken"] = token
                j = yt_get("search", **params)
            except Exception as e:
                errors.append(f"유튜브 검색: {e}")
                break
            for it in j.get("items", []):
                vid = it["id"].get("videoId")
                if vid and vid not in videos:
                    sn = it["snippet"]
                    d = datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00")).astimezone(KST).date()
                    videos[vid] = d
                    add(d, clean(sn.get("title", "")) + " " + clean(sn.get("description", "")))
            token = j.get("nextPageToken")
            if not token:
                break
    print(f"유튜브 영상 {len(videos)}개")

    # 최근 7일 영상 중 조회수 상위 N개의 댓글
    recent = [v for v, d in videos.items() if d >= WEEK_START]
    views = {}
    for i in range(0, len(recent), 50):
        try:
            j = yt_get("videos", part="statistics", id=",".join(recent[i:i + 50]))
            for it in j.get("items", []):
                views[it["id"]] = int(it.get("statistics", {}).get("viewCount", 0))
        except Exception as e:
            errors.append(f"유튜브 조회수: {e}")
    top = sorted(views, key=views.get, reverse=True)[: CFG["yt_top_videos"]]
    nc = 0
    for vid in top:
        try:
            j = yt_get("commentThreads", part="snippet", videoId=vid, order="time",
                       maxResults=CFG["yt_comments_per_video"], textFormat="plainText")
        except Exception:
            continue  # 댓글 막힌 영상
        for it in j.get("items", []):
            c = it["snippet"]["topLevelComment"]["snippet"]
            d = datetime.fromisoformat(c["publishedAt"].replace("Z", "+00:00")).astimezone(KST).date()
            add(d, c.get("textDisplay", ""))
            nc += 1
    print(f"유튜브 댓글 {nc}개 (영상 {len(top)}개) → 한국 {len(ko)} / 영어 {len(en)}")
    return ko, en


# ───────── 집계 ─────────
def rank(docs, terms_fn):
    """전일 / 최근 7일: 2단어 조합 TOP N + 단어 TOP M. 🔥 = 전일에 평소보다 급증"""
    C = lambda: {"w": Counter(), "p": Counter()}
    day, week, prev = C(), C(), C()
    nd = nw = npv = 0
    for d, text in docs:
        ws, ps = terms_fn(text)
        bucket = []
        if d == YDAY:
            bucket.append(day); nd += 1
        if WEEK_START <= d <= YDAY:
            bucket.append(week); nw += 1
        else:
            bucket.append(prev); npv += 1
        for b in bucket:
            b["w"].update(ws); b["p"].update(ps)

    def top_of(cnt, n, with_hot, kind):
        cand = [(t, c) for t, c in cnt.most_common(n * 4) if c >= 2]
        # 조합에 이미 들어간 단어는 단어 목록에서 생략해 중복을 줄임
        cand = cand[:n]
        if not with_hot:
            return [(t, c, False) for t, c in cand]
        def surge(t, c):
            base = (week[kind][t] - day[kind][t] + prev[kind][t] + 1) / max(nw - nd + npv, 1)
            return (c / max(nd, 1)) / base
        hot = sorted((x for x in cand if x[1] >= 4 and surge(*x) >= CFG["hot_ratio"]), key=lambda x: -surge(*x))
        hot = {t for t, _ in hot[: CFG["hot_max"]]}
        return [(t, c, t in hot) for t, c in cand]

    n, m = CFG["top_n"], CFG["top_words"]
    return {
        "day_pairs": top_of(day["p"], n, True, "p"), "day_words": top_of(day["w"], m * 4, True, "w")[: m * 4],
        "week_pairs": top_of(week["p"], n, False, "p"), "week_words": top_of(week["w"], m * 4, False, "w")[: m * 4],
        "nd": nd, "nw": nw,
    }


def fmt_list(items):
    if not items:
        return "   (데이터 부족)"
    return "\n".join(f"   {i + 1}. {html.escape(t)} <i>{c}</i>{' 🔥' if h else ''}" for i, (t, c, h) in enumerate(items))


def pct_text(p):
    if p is None:
        return "-"
    arrow = "🔺" if p > 0 else ("🔻" if p < 0 else "➖")
    return f"{arrow}{abs(p):.0f}%"


def words_line(items):
    return "   단어: " + " · ".join(f"{html.escape(t)}{'🔥' if h else ''}" for t, c, h in items) if items else ""


def section(flag, title, r, key, n):
    pairs, words = r[f"{key}_pairs"], r[f"{key}_words"]
    in_pairs = {w for t, _, _ in pairs for w in t.split()}
    words = [x for x in words if x[0] not in in_pairs]  # 조합에 이미 나온 단어는 생략
    out = [f"{flag} <b>{title}</b> (글·영상·댓글 {n}건)", fmt_list(pairs)]
    if words:
        out.append(words_line(words[: CFG["top_words"]]))
    return "\n".join(out)


def build_message(ko, en, dl):
    lines = [f"🎧 <b>{CFG['name']} 트렌드</b> · {YDAY.month}/{YDAY.day}({DOW[YDAY.weekday()]}) 기준"]
    if dl:
        lines.append(f"🔎 네이버 검색량  전일 {pct_text(dl['day'])} · 최근 7일 {pct_text(dl['week'])} (직전 기간 대비)")
    lines += [
        "", section("🇰🇷", "한국 · 전일", ko, "day", ko["nd"]),
        "", section("🇰🇷", "한국 · 최근 7일", ko, "week", ko["nw"]),
        "", section("🌏", "영어 · 전일", en, "day", en["nd"]),
        "", section("🌏", "영어 · 최근 7일", en, "week", en["nw"]),
        "", "<i>숫자 = 함께 나온 글 수 · 🔥 = 평소보다 2배↑</i>",
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
    yt_ko, yt_en = collect_youtube()
    ko = rank(collect_korean() + yt_ko, ko_terms)
    en = rank(collect_english() + yt_en, en_terms)
    dl = datalab()
    text = build_message(ko, en, dl)
    print(text)
    for e in errors:
        print("!", e)
    if BOT_TOKEN and CHAT_IDS and os.environ.get("DRY_RUN") != "true":
        send(text)


if __name__ == "__main__":
    main()
