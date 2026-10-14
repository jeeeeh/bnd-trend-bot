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


# ───────── 2·3) 유튜브 영상·댓글 ─────────
def yt(path, **params):
    params["key"] = YT_KEY
    r = requests.get(f"https://www.googleapis.com/youtube/v3/{path}", params=params, timeout=20)
    if not r.ok:
        raise RuntimeError(f"{path} {r.status_code}: {r.text[:120]}")
    return r.json()


def to_date(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(KST)


def collect_videos():
    after = datetime.combine(WEEK_START, datetime.min.time(), KST).isoformat()
    vids = {}
    for q in CFG["yt_queries"]:
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
                    vids[v] = {"id": v, "title": html.unescape(sn["title"]), "channel": sn["channelTitle"],
                               "at": to_date(sn["publishedAt"])}
            token = j.get("nextPageToken")
            if not token:
                break
    ids = list(vids)
    for i in range(0, len(ids), 50):
        try:
            j = yt("videos", part="statistics", id=",".join(ids[i:i + 50]))
            for it in j.get("items", []):
                st = it.get("statistics", {})
                vids[it["id"]]["views"] = int(st.get("viewCount", 0))
                vids[it["id"]]["comments"] = int(st.get("commentCount", 0))
        except Exception as e:
            errors.append(f"조회수: {e}")
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


def collect_questions(videos):
    """(한국 질문, 영어 질문): [(날짜, 좋아요, 텍스트, 영상제목, 영상id)]"""
    ko, en, seen = [], [], set()
    targets = sorted([v for v in videos if v.get("comments", 0) > 0], key=lambda v: -v.get("views", 0))
    targets = targets[: CFG["yt_question_videos"]]
    for v in targets:
        for order in ("relevance", "time"):
            try:
                j = yt("commentThreads", part="snippet", videoId=v["id"], order=order,
                       maxResults=100, textFormat="plainText")
            except Exception:
                break  # 댓글 막힌 영상
            for it in j.get("items", []):
                c = it["snippet"]["topLevelComment"]["snippet"]
                text = re.sub(r"\s+", " ", c.get("textDisplay", "")).strip()
                key = NORM(text)[:60]
                if key in seen or len(text) < 8 or len(text) > 300 or SPAM.search(text):
                    continue
                d = to_date(c["publishedAt"]).date()
                if d < WEEK_START or d > YDAY:
                    continue
                row = (d, int(c.get("likeCount", 0)) + int(it["snippet"].get("totalReplyCount", 0)), text, v["title"], v["id"])
                if HANGUL.search(text):
                    if is_ko_question(text):
                        ko.append(row); seen.add(key)
                elif re.search(r"[A-Za-z]{3}", text) and EN_Q.search(text):
                    en.append(row); seen.add(key)
    print(f"질문 댓글: 한국 {len(ko)} / 영어 {len(en)} (영상 {len(targets)}개)")
    return ko, en


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


# ───────── 메시지 ─────────
def q_list(items, n):
    return " · ".join(esc(x) for x in items[:n]) if items else "없음"


def section_search(flag, cur, top, hist, lang):
    day_new = new_since(cur, hist, lang, 1, 1)
    week_new = new_since(cur, hist, lang, 2, 7)
    lines = [f"{flag} 많이 찾는: {q_list(top, 8)}"]
    if day_new is None:
        lines.append("   🆕 새 검색어: 내일부터 비교돼요 (오늘 첫 기록)")
    else:
        lines.append(f"   🆕 어제 대비 새로: {q_list(day_new, 8)}")
        if week_new is not None:
            lines.append(f"   🆕 이번 주 새로: {q_list(week_new, 8)}")
    return "\n".join(lines)


def section_questions(flag, rows, n):
    day = sorted((r for r in rows if r[0] == YDAY), key=lambda r: -r[1])[:n]
    shown = {r[2] for r in day}
    week = sorted((r for r in rows if r[2] not in shown), key=lambda r: -r[1])[:n]
    out = []
    for title, group in (("전일", day), ("최근 7일", week)):
        out.append(f"{flag} <b>{title}</b>")
        if not group:
            out.append("   (없음)")
        for d, likes, text, vt, vid in group:
            out.append(f"   • {esc(short(text, 70))} <i>👍{likes}</i> "
                       f"<a href=\"https://youtu.be/{vid}\">영상</a>")
    return "\n".join(out)


TITLE_OK = re.compile("|".join(re.escape(w) for w in CFG["title_words"]), re.I)


def is_english(t):
    letters = re.findall(r"[^\W\d_]", t)
    return letters and sum(c.isascii() for c in letters) / len(letters) > 0.8


def section_videos(videos, korean, n):
    pick = [v for v in videos if TITLE_OK.search(v["title"])
            and (HANGUL.search(v["title"]) if korean else is_english(v["title"]))]
    pick = sorted(pick, key=lambda v: -v["per_day"])[:n]
    if not pick:
        return "   (없음)"
    fmt = lambda x: f"{x / 10000:.1f}만" if x >= 10000 else f"{x:,.0f}"
    return "\n".join(f"   • <a href=\"https://youtu.be/{v['id']}\">{esc(short(v['title'], 45))}</a> "
                     f"<i>하루 {fmt(v['per_day'])}회</i>" for v in pick)


def build_messages(ko_s, en_s, hist, qs, videos):
    ko_cur, ko_top = ko_s
    en_cur, en_top = en_s
    m1 = "\n".join([
        f"🎧 <b>보넥도, 요즘 사람들은 뭘 궁금해할까?</b> · {YDAY.month}/{YDAY.day}({DOW[YDAY.weekday()]}) 기준",
        "",
        "🔎 <b>유튜브 검색어</b> (자동완성 기준)",
        section_search("🇰🇷", ko_cur, ko_top, hist, "ko"),
        section_search("🌏", en_cur, en_top, hist, "en"),
        "",
        "🔥 <b>뜨는 영상</b> (최근 7일, 하루 평균 조회수)",
        "🇰🇷", section_videos(videos, True, 3),
        "🌏", section_videos(videos, False, 3),
    ])
    m2 = "\n".join([
        "❓ <b>팬들이 궁금해하는 질문</b> (유튜브 댓글, 👍=좋아요+답글)",
        "",
        section_questions("🇰🇷", qs[0], CFG["questions_n"]),
        "",
        section_questions("🌏", qs[1], CFG["questions_n"]),
    ])
    return [m1, m2]


def send(text):
    for cid in CHAT_IDS:
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", timeout=30,
                          json={"chat_id": cid, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True})
        if not r.ok:
            print(f"텔레그램 전송 실패({cid}): {r.text}", file=sys.stderr)


def main():
    if not YT_KEY:
        sys.exit("YOUTUBE_API_KEY가 없어요.")
    ko_s = collect_suggestions(CFG["ko_suggest_seeds"], KO_PREFIX, "ko")
    en_s = collect_suggestions(CFG["en_suggest_seeds"], EN_PREFIX, "en")
    print(f"자동완성 검색어: 한국 {len(ko_s[0])} / 영어 {len(en_s[0])}")
    videos = collect_videos()
    qs = collect_questions(videos)
    hist = load_hist()
    msgs = build_messages(ko_s, en_s, hist, qs, videos)
    print("\n\n".join(msgs))
    for e in errors[:15]:
        print("!", e)
    hist[str(TODAY)] = {"ko": ko_s[0], "en": en_s[0]}
    save_hist(hist)
    if BOT_TOKEN and CHAT_IDS and os.environ.get("DRY_RUN") != "true":
        for m in msgs:
            send(m)


if __name__ == "__main__":
    main()
