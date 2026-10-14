# 보넥도 트렌드 봇

매일 아침 8시, 보이넥스트도어(보넥도) 관련해서 **같이 언급된 키워드 TOP 10**을 보내줘요. 완전 무료예요.

| 구분 | 출처 | 기간 |
|---|---|---|
| 🇰🇷 한국 | 네이버 블로그·뉴스 (NAVER API HUB) | 전일 / 최근 7일 |
| 🔎 검색량 | 네이버 데이터랩 검색어 트렌드 | 전일·최근 7일, 직전 기간 대비 % |
| 🌏 영어 | 구글 뉴스 RSS + Bluesky | 전일 / 최근 7일 |

- 숫자 = 그 단어가 함께 나온 글 수
- 🔥 = 평소(이전 13일)보다 전일에 2배 이상 급증한 키워드 (최대 3개)

## GitHub Secrets

- `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` — NAVER API HUB Application에서 **블로그·뉴스·검색어트렌드** 사용 설정 필요
- `BOT_TOKEN`, `CHAT_ID` — 텔레그램

## 설정 (`config.json`)

- `ko_queries` / `en_queries`: 검색할 이름
- `self_words`, `ko_stopwords`, `en_stopwords`: 순위에서 뺄 단어 (의미 없는 단어가 자꾸 올라오면 여기에 추가)
