"""
보넥도 트렌드 봇 — "요즘 사람들이 보넥도에 대해 뭘 궁금해하나" (매일 아침 8시, 유튜브만, 무료)

1) 🔎 유튜브 검색어 자동완성: "보넥도 ㄱ", "boynextdoor a" … 에 뜨는 실제 검색어를 매일 저장해서
      어제 대비 / 지난주 대비 '새로 뜬 검색어' + 지금 가장 많이 찾는 검색어
2) ❓ 궁금해하는 질문: 최근 인기 영상 댓글 중 질문 댓글을 좋아요 순으로 (전일 / 최근 7일)
3) 🔥 뜨는 영상: 최근 7일 영상 중 하루 평균 조회수가 높은 영상
한국(한글) / 영어 따로
"""
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).parent
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
HIST = ROOT / "data" / "suggest_history.json"

YT_KEY = os.environ.get("YOUTUBE_API_KEY", "")
NAVER_ID = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_IDS = [c.strip() for c in os.environ.get("CHAT_ID", "").split(",") if c.strip()]

KST = timezone(timedelta(hours=9))
NOW = datetime.now(KST)
TODAY = NOW.date()
YDAY = TODAY - timedelta(days=1)
WEEK_START = YDAY - timedelta(days=6)
DOW = "월화수목금토일"
UA = {"User-Agent": "Mozilla/5.0"}
HANGUL = re.compile(r"[가-힣]")
errors = []

NORM = lambda w: re.sub(r"[\s\-_.·()&'!?]", "", w.lower())
EXCLUDE = {NORM(w) for w in CFG.get("exclude_artists", [])}


def esc(s):
    return html.escape(str(s), quote=False)


def short(s, n):
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


# ───────── 1) 유튜브 검색어 자동완성 ─────────
KO_PREFIX = ["", "ㄱ", "ㄴ", "ㄷ", "ㄹ", "ㅁ", "ㅂ", "ㅅ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"]
EN_PREFIX = [""] + list("abcdefghijklmnopqrstuvwxyz")


def suggest(q, lang):
    r = requests.get(
        "https://suggestqueries.google.com/complete/search",
        params={"client": "firefox", "ds": "yt", "q": q, "hl": lang, "gl": "KR" if lang == "ko" else "US"},
        headers=UA, timeout=15)
    r.raise_for_status()
    return json.loads(r.content.decode("utf-8", "ignore"))[1]


def remainder(full, seeds):
    """'보넥도 성호 안경' → '성호 안경' (그룹 이름 떼기)"""
    t = full.lower()
    for s in sorted(seeds, key=len, reverse=True):
        t = t.replace(s.lower(), " ")
    return re.sub(r"\s+", " ", t).strip()


def collect_suggestions(seeds, prefixes, lang):
    """{검색어(그룹명 뗀 것): 순위점수} — 접두어 없는 기본 검색 결과는 '많이 찾는 순서'로 사용"""
    out, top = {}, []
    for seed in seeds:
        for p in prefixes:
            try:
                items = suggest(f"{seed} {p}".strip() + (" " if p == "" else ""), lang)
            except Exception as e:
                errors.append(f"자동완성({seed} {p}): {str(e)[:60]}")
                continue
            for i, s in enumerate(items):
                rest = remainder(s, CFG["self_words"])
                if len(rest) < 2 or NORM(rest) in EXCLUDE:
                    continue
                if lang == "en" and rest in EN_FILLER:
                    continue
                if (lang == "ko") != bool(HANGUL.search(rest)):
                    continue  # 한국은 한글 검색어만, 영어는 한글 없는 검색어만
                out.setdefault(rest, 0)
                out[rest] += 10 - i
                if p == "" and rest not in top:
                    top.append(rest)
            time.sleep(0.25)
    return out, top


def member_suggestions():
    """멤버별 자동완성 상위 3개 (그룹·멤버 이름은 떼고)"""
    strip = CFG["self_words"] + CFG["member_names"]
    out = {}
    for m, seeds in CFG["member_seeds"].items():
        got = []
        for seed in seeds:
            try:
                items = suggest(seed + " ", "ko")
            except Exception as e:
                errors.append(f"멤버 자동완성({seed}): {str(e)[:60]}")
                continue
            for it in items:
                rest = remainder(it, strip)
                if (len(rest) >= 2 and rest not in got and NORM(rest) not in EXCLUDE
                        and not any(w in rest for w in CFG["member_block_words"])):
                    got.append(rest)
            time.sleep(0.25)
        out[m] = got
    # 모든 멤버에 공통으로 뜨는 검색어(예: 직캠)는 정보가 없어서 빼고 멤버별 특징만 3개
    from collections import Counter
    common = {q for q, n in Counter(q for v in out.values() for q in v).items() if n >= 4}
    return {m: [q for q in v if q not in common][:3] for m, v in out.items()}, sorted(common)


def combo_ranking():
    """조합명 네이버 검색량 (데이터랩). 5그룹씩만 비교돼서 '보넥도'를 기준점으로 같이 넣고 환산"""
    if not (NAVER_ID and NAVER_SECRET):
        errors.append("조합명: 네이버 키 없음")
        return []
    amb = set(CFG["combo_ambiguous"])
    groups = []
    for names, members in CFG["combos"]:
        kws = []
        for n in names.split("|"):
            kws += [f"보넥도 {n}"] if n in amb else [n, f"보넥도 {n}"]
        groups.append({"groupName": names.split("|")[0], "keywords": kws[:20], "members": members})
    start = YDAY - timedelta(days=6)
    anchor = {"groupName": "__anchor", "keywords": ["보넥도", "보이넥스트도어"]}
    res = []
    for i in range(0, len(groups), 4):
        batch = groups[i:i + 4]
        body = {"startDate": str(start), "endDate": str(YDAY), "timeUnit": "date",
                "keywordGroups": [anchor] + [{"groupName": g["groupName"], "keywords": g["keywords"]} for g in batch]}
        try:
            r = requests.post("https://naverapihub.apigw.ntruss.com/search-trend/v1/search", json=body, timeout=20,
                              headers={"X-NCP-APIGW-API-KEY-ID": NAVER_ID, "X-NCP-APIGW-API-KEY": NAVER_SECRET,
                                       "Content-Type": "application/json"})
            if not r.ok:
                raise RuntimeError(f"{r.status_code}: {r.text[:120]}")
            data = {x["title"]: {d["period"]: d["ratio"] for d in x["data"]} for x in r.json()["results"]}
        except Exception as e:
            errors.append(f"조합명 검색량: {e}")
            continue
        a_sum = sum(data.get("__anchor", {}).values()) or 1
        a_y = data.get("__anchor", {}).get(str(YDAY), 0) or 1
        for g in batch:
            d = data.get(g["groupName"], {})
            week = sum(d.values()) / a_sum * 1000
            yday = d.get(str(YDAY), 0) / a_y * 1000
            if week > 0:
                res.append({"name": g["groupName"], "members": g["members"], "week": week,
                            "rising": yday > week / 7 * 1.5 and yday > 0})
        time.sleep(0.2)
    res.sort(key=lambda x: -x["week"])
    print(f"조합명 검색량 있는 것: {len(res)}개")
    return res


# ───────── 2·3) 유튜브 영상·댓글 ─────────
def yt(path, **params):
    params["key"] = YT_KEY
    r = requests.get(f"https://www.googleapis.com/youtube/v3/{path}", params=params, timeout=20)
    if not r.ok:
        raise RuntimeError(f"{path} {r.status_code}: {r.text[:120]}")
    return r.json()


def to_date(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(KST)


VIDEO_CACHE = ROOT / "data" / "videos.json"


def collect_videos():
    """최근 7일 영상. REUSE_VIDEOS=true면 검색(한도 많이 씀) 없이 저장된 영상 목록만 다시 조회"""
    after = datetime.combine(WEEK_START, datetime.min.time(), KST).isoformat()
    vids = {}
    reuse = os.environ.get("REUSE_VIDEOS") == "true" and VIDEO_CACHE.exists()
    if reuse:
        for v in json.loads(VIDEO_CACHE.read_text(encoding="utf-8")):
            vids[v] = {"id": v}
    for q in ([] if reuse else CFG["yt_queries"]):
        token = None
        for _ in range(3):
            try:
                p = {"part": "snippet", "q": q, "type": "video", "order": "date",
                     "publishedAfter": after, "maxResults": 50}
                if token:
                    p["pageToken"] = token
                j = yt("search", **p)
            except Exception as e:
                errors.append(f"유튜브 검색: {e}")
                break
            for it in j.get("items", []):
                v = it["id"].get("videoId")
                if v and v not in vids:
                    sn = it["snippet"]
                    vids[v] = {"id": v}
            token = j.get("nextPageToken")
            if not token:
                break
    ids = list(vids)
    for i in range(0, len(ids), 50):
        try:
            j = yt("videos", part="snippet,statistics", id=",".join(ids[i:i + 50]))
            for it in j.get("items", []):
                st, sn = it.get("statistics", {}), it["snippet"]
                vids[it["id"]].update({
                    "title": sn["title"], "desc": sn.get("description", ""), "at": to_date(sn["publishedAt"]),
                    "views": int(st.get("viewCount", 0)), "comments": int(st.get("commentCount", 0))})
        except Exception as e:
            errors.append(f"조회수: {e}")
    vids = {k: v for k, v in vids.items() if "at" in v}
    VIDEO_CACHE.parent.mkdir(exist_ok=True)
    VIDEO_CACHE.write_text(json.dumps(list(vids)), encoding="utf-8")
    for v in vids.values():
        hours = max((NOW - v["at"]).total_seconds() / 3600, 6)
        v["per_day"] = v.get("views", 0) / hours * 24
    print(f"최근 7일 영상 {len(vids)}개")
    return list(vids.values())


# 감탄문("어떻게 저렇게 잘생김")은 빼고 진짜 질문만: 물음표, 또는 질문형 어미/표현
KO_Q = re.compile(r"[가-힣a-z0-9]\s*\?|궁금|알려주|아시는 ?분|아는 ?사람|제목 ?(이|좀|뭐)|"
                  r"(뭐예요|뭐에요|뭐야|뭐임|뭔가요|뭐죠|뭐지|나요|까요|가요|인가|건가|는지|냐|니|어요|아요|죠)(?=\s*($|[ㅋㅎㅠㅜ.!~^]))")
KO_WH = re.compile(r"언제|어디|누구|뭐|왜|몇|무슨|어떤|어느")
KO_END = re.compile(r"(요|나|까|니|냐|지|죠|가|래)[\sㅋㅎㅠㅜ.!~^]*$")


def is_ko_question(t):
    """물음표·질문형 어미, 또는 의문사(언제/뭐/왜…)가 있고 요/나/까… 로 끝나는 문장"""
    if KO_Q.search(t):
        return True
    t = re.sub(r"[^\w\sㅋㅎㅠㅜ.!~^]", "", t).strip()  # 이모지 제거
    return bool(KO_WH.search(t) and KO_END.search(t))


EN_Q = re.compile(r"[a-z0-9]\s*\?|anyone know|does anyone|can someone|i wonder|wondering", re.I)
EN_FILLER = {"what", "who", "how", "why", "when", "where", "is", "the", "and", "in", "on", "a", "an", "to", "of", "for", "with", "vs"}
SPAM = re.compile(r"https?://|www\.|구독|sub4sub|check out my|my channel", re.I)


def collect_comments(videos):
    """최근 7일 인기 영상 댓글 (한글): [(날짜, 좋아요+답글, 텍스트, 영상제목, 영상id)]"""
    rows, seen = [], set()
    targets = sorted([v for v in videos if v.get("comments", 0) > 0], key=lambda v: -v.get("views", 0))
    targets = targets[: CFG["yt_question_videos"]]
    for v in targets:
        for order in ("relevance", "time"):
            try:
                j = yt("commentThreads", part="snippet", videoId=v["id"], order=order,
                       maxResults=100, textFormat="plainText")
            except Exception as e:
                errors.append(f"댓글({v['id']}): {str(e)[:60]}")
                break
            for it in j.get("items", []):
                c = it["snippet"]["topLevelComment"]["snippet"]
                text = re.sub(r"\s+", " ", c.get("textDisplay", "")).strip()
                key = NORM(text)[:60]
                if key in seen or len(text) < 6 or len(text) > 300 or SPAM.search(text) or not HANGUL.search(text):
                    continue
                d = to_date(c["publishedAt"]).date()
                if d < WEEK_START or d > YDAY:
                    continue
                seen.add(key)
                rows.append((d, int(c.get("likeCount", 0)) + int(it["snippet"].get("totalReplyCount", 0)),
                             text, v["title"], v["id"]))
    print(f"한국어 댓글 {len(rows)}개 (영상 {len(targets)}개)")
    return rows


def combo_ranking_yt(videos, comments):
    """조합명 유튜브 기준: 최근 7일 영상 제목·설명·댓글 언급 수 + 유튜브 자동완성에 뜨는 개수"""
    amb = set(CFG["combo_ambiguous"])
    texts = [v["title"] + " " + v.get("desc", "") for v in videos] + [c[2] for c in comments]
    yday_texts = [c[2] for c in comments if c[0] == YDAY] + \
                 [v["title"] for v in videos if v["at"].date() == YDAY]
    res = []
    for names, members in CFG["combos"]:
        aliases = names.split("|")
        pats = [re.compile(re.escape(n), re.I) for n in aliases if n not in amb or len(n) >= 4]
        mention = sum(1 for t in texts if any(p.search(t) for p in pats)) if pats else 0
        y = sum(1 for t in yday_texts if any(p.search(t) for p in pats)) if pats else 0
        ac = 0
        for n in aliases[:2]:
            q = f"보넥도 {n}" if n in amb else n
            try:
                ac += sum(1 for x in suggest(q + " ", "ko") if NORM(n) in NORM(x))
            except Exception:
                pass
            time.sleep(0.2)
        score = mention * 3 + ac
        if score > 0:
            res.append({"name": aliases[0], "members": members, "mention": mention, "ac": ac,
                        "score": score, "rising": y >= 2 and y * 7 >= mention * 2})
    res.sort(key=lambda x: (-x["score"], -x["mention"]))
    print(f"조합명 유튜브 점수 있는 것: {len(res)}개")
    return res


# ───────── 기록 (자동완성 스냅샷) ─────────
def load_hist():
    try:
        return json.loads(HIST.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_hist(h):
    cutoff = str(TODAY - timedelta(days=21))
    h = {d: v for d, v in h.items() if d >= cutoff}
    HIST.parent.mkdir(exist_ok=True)
    HIST.write_text(json.dumps(h, ensure_ascii=False), encoding="utf-8")


def new_since(cur, hist, lang, days_from, days_to):
    """days_from~days_to일 전 스냅샷 어디에도 없던 검색어 (점수 높은 순)"""
    old = set()
    for k in range(days_from, days_to + 1):
        old |= set(hist.get(str(TODAY - timedelta(days=k)), {}).get(lang, {}))
    if not old:
        return None  # 비교할 기록이 아직 없음
    return sorted((q for q in cur if q not in old), key=lambda q: -cur[q])


# ───────── 메시지 (카카오톡에 그대로 복사하기 좋게: 서식 없는 텍스트, 항목마다 링크) ─────────
LINE = "━━━━━━━━━━━━━━"
CIRCLE = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def fmt_views(x):
    return f"{x / 10000:.1f}만" if x >= 10000 else f"{x:,.0f}"


def is_english(t):
    letters = re.findall(r"[^\W\d_]", t)
    return letters and sum(c.isascii() for c in letters) / len(letters) > 0.8


TITLE_OK = re.compile("|".join(re.escape(w) for w in CFG["title_words"]), re.I)


def korean_title(t):
    body = re.sub(r"#\S+", "", t)
    return bool(HANGUL.search(body)) if body.strip() else bool(HANGUL.search(t))


def build_messages(ko_cur, ko_top, hist, questions, videos, members, combos):
    N = CFG["list_n"]
    head = [f"🎧 보넥도, 요즘 사람들은 뭘 궁금해할까?",
            f"📅 {YDAY.month}/{YDAY.day}({DOW[YDAY.weekday()]}) 기준 · 유튜브·네이버"]
    secs = []

    # 1) 검색어
    s1 = [LINE, "🔎 유튜브에서 많이 찾는 검색어", LINE]
    s1 += [f"{i + 1}. {q}" for i, q in enumerate(ko_top[:N])] or ["(없음)"]
    day_new = new_since(ko_cur, hist, "ko", 1, 1)
    week_new = new_since(ko_cur, hist, "ko", 2, 7)
    s1.append("")
    if day_new is None:
        s1.append("🆕 새로 뜬 검색어는 내일부터 비교돼요")
    else:
        s1.append("🆕 어제보다 새로 뜬 검색어")
        s1 += [f"· {q}" for q in day_new[:N]] or ["· 없음"]
        if week_new is not None:
            s1 += ["", "🆕 이번 주 새로 뜬 검색어"]
            s1 += [f"· {q}" for q in week_new[:N]] or ["· 없음"]
    secs.append(s1)

    # 2) 멤버별
    members, common = members
    s2 = [LINE, "👤 멤버별 많이 찾는 검색어", LINE]
    if common:
        s2.append(f"(모든 멤버 공통: {' · '.join(common[:3])})")
    for m, qs in members.items():
        s2.append(f"[{m}] " + (" · ".join(qs) if qs else "-"))
    secs.append(s2)

    # 3) 조합명
    s3 = [LINE, "💞 요즘 많이 언급되는 조합명 (유튜브, 최근 7일)", LINE]
    for i, c in enumerate(combos[:N]):
        s3.append(f"{i + 1}. {c['name']} ({c['members']}){' 🔺' if c['rising'] else ''}")
    if not combos:
        s3.append("(데이터 없음)")
    else:
        s3.append("유튜브 영상·댓글 언급 + 검색 자동완성 기준 · 🔺 어제 급증")
    secs.append(s3)

    # 4) 뜨는 영상
    hot = [v for v in videos if TITLE_OK.search(v["title"]) and korean_title(v["title"])]
    hot = sorted(hot, key=lambda v: -v["per_day"])[:N]
    s4 = [LINE, "🔥 요즘 뜨는 영상 (최근 7일)", LINE]
    for i, v in enumerate(hot):
        s4 += [f"{CIRCLE[i]} {short(v['title'], 40)}", f"    └ 하루 평균 {fmt_views(v['per_day'])}회",
               f"    https://youtu.be/{v['id']}"]
    if not hot:
        s4.append("(없음)")
    secs.append(s4)

    # 5) 질문
    day = sorted((r for r in questions if r[0] == YDAY), key=lambda r: -r[1])[:N]
    shown = {r[2] for r in day}
    week = sorted((r for r in questions if r[2] not in shown), key=lambda r: -r[1])[:N]
    s5 = [LINE, "💬 요즘 핫한 댓글 (좋아요+답글 순)", LINE]
    for title, group in (("[어제]", day), ("[최근 7일]", week)):
        s5.append(title)
        for d, likes, text, vt, vid in group:
            s5 += [f"· \"{short(text, 60)}\"", f"    └ 👍{likes:,}", f"    https://youtu.be/{vid}"]
        if not group:
            s5.append("· 없음")
        s5.append("")
    secs.append(s5)

    # 텔레그램 한 메시지 4096자 제한 → 섹션 단위로 나눔
    msgs, cur = [], "\n".join(head)
    for sec in secs:
        block = "\n".join(sec).rstrip()
        if len(cur) + len(block) + 2 > 3900:
            msgs.append(cur)
            cur = block
        else:
            cur += "\n\n" + block
    msgs.append(cur)
    return msgs


def send(text):
    for cid in CHAT_IDS:
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", timeout=30,
                          json={"chat_id": cid, "text": text, "disable_web_page_preview": True})
        if not r.ok:
            print(f"텔레그램 전송 실패({cid}): {r.text}", file=sys.stderr)


def send_saved():
    """유튜브 호출 없이 data/saved_message_*.txt 를 그대로 보냄 (한도 초과 시 테스트용)"""
    files = sorted((ROOT / "data").glob("saved_message_*.txt"))
    if not files:
        sys.exit("저장된 메시지가 없어요.")
    for f in files:
        send(f.read_text(encoding="utf-8"))
    print(f"저장된 메시지 {len(files)}개 전송")


def main():
    if os.environ.get("SEND_SAVED") == "true":
        return send_saved()
    if not YT_KEY:
        sys.exit("YOUTUBE_API_KEY가 없어요.")
    ko_cur, ko_top = collect_suggestions(CFG["ko_suggest_seeds"], KO_PREFIX, "ko")
    print(f"자동완성 검색어: {len(ko_cur)}")
    videos = collect_videos()
    ko_q = collect_comments(videos)
    members = member_suggestions()
    combos = combo_ranking_yt(videos, ko_q)
    hist = load_hist()
    msgs = build_messages(ko_cur, ko_top, hist, ko_q, videos, members, combos)
    print("\n\n====\n\n".join(msgs))
    for e in errors[:15]:
        print("!", e)
    hist[str(TODAY)] = {"ko": ko_cur}
    save_hist(hist)
    if BOT_TOKEN and CHAT_IDS and os.environ.get("DRY_RUN") != "true":
        for m in msgs:
            send(m)


if __name__ == "__main__":
    main()
