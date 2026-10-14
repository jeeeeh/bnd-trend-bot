# 보넥도 트렌드 봇

매일 아침 8시, 보이넥스트도어(보넥도) 관련해서 **같이 언급된 2단어 조합 TOP 10 + 단어 TOP 5**을 보내줘요. 완전 무료예요.

| 구분 | 출처 | 기간 |
|---|---|---|
| 🇰🇷 한국 | 네이버 블로그 + 유튜브(한글 제목·설명·댓글) | 전일 / 최근 7일 |
| 🔎 검색량 | 네이버 데이터랩 검색어 트렌드 | 전일·최근 7일, 직전 기간 대비 % |
| 🌏 영어 | 유튜브(영어 제목·설명·댓글) + Bluesky | 전일 / 최근 7일 |

- 숫자 = 그 단어가 함께 나온 글 수
- 🔥 = 평소(이전 13일)보다 전일에 2배 이상 급증한 키워드 (최대 3개)

## GitHub Secrets

- `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` — NAVER API HUB Application에서 **블로그·검색어트렌드** 사용 설정 필요
- `YOUTUBE_API_KEY` — Google Cloud 콘솔에서 YouTube Data API v3 사용 설정 후 API 키 (무료)
- `BOT_TOKEN`, `CHAT_ID` — 텔레그램

## 설정 (`config.json`)

- `ko_queries` / `en_queries`: 검색할 이름
- `self_words`, `ko_stopwords`, `en_stopwords`: 순위에서 뺄 단어 (의미 없는 단어가 자꾸 올라오면 여기에 추가)
