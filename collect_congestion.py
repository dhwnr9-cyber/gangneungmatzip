"""
collect_congestion.py
─────────────────────────────────────────────────────────────
강릉 맛집지도용 혼잡도 데이터 수집기

두 가지 실데이터를 합쳐서 프론트엔드가 읽는
congestion_data.json 을 만든다.

  [1] 구글 Popular Times  → 가게별 "지금 얼마나 붐비나"(실시간) + 요일별 주간 패턴
  [2] 공공데이터 유동인구  → 강릉 지역 유동인구로 지역 보정(백그라운드 밀집도)

⚠️ 정직하게 알아둘 점
  - 기지국 원본 데이터는 통신사만 접근 가능. 개인은 못 받는다.
    그래서 "휴대폰 포화도"에 가장 가까운 현실적 대안이 구글 Popular Times다.
    (구글이 안드로이드 위치·검색에서 집계한 실제 혼잡도라 사실상 폰 밀집도와 비슷)
  - 구글 current_popularity(실시간)는 '지금 붐비는 곳 + 영업시간'일 때만 값이 나온다.
    값이 없으면 그날 요일 패턴으로 대체한다.
  - 공공데이터 유동인구는 실시간이 아니라 '집계'이고 동/읍면 단위라
    가게별이 아니라 지역 보정용으로만 쓴다.

실행:  python collect_congestion.py
결과:  같은 폴더에 congestion_data.json 생성  (cron으로 5~10분마다 반복 실행 권장)
"""

import json
import os
import time
import datetime as dt
from pathlib import Path

# ── 설정 ──────────────────────────────────────────────
# GitHub Actions에서 돌릴 때는 Secrets에 등록한 값이 환경변수로 자동 주입된다.
# 로컬 컴퓨터에서 직접 돌릴 때는 아래 두 줄의 따옴표 안에 키를 직접 넣어도 된다.
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "여기에_구글_Places_API_키")
PUBLIC_DATA_KEY = os.environ.get("PUBLIC_DATA_KEY", "여기에_공공데이터포털_인증키")

OUT_PATH = Path(__file__).parent / "congestion_data.json"
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# 맛집 목록 (프론트엔드 index.html의 PLACES 와 name 이 정확히 일치해야 매칭됨)
PLACES = [
    {"name": "엄지네포장마차 본점", "query": "엄지네포장마차 강릉"},
    {"name": "초당할머니순두부",     "query": "초당할머니순두부 강릉"},
    {"name": "동화가든 본점",        "query": "동화가든 강릉 순두부"},
    {"name": "큰기와집순두부",       "query": "기와옥초당순두부 강릉"},
    {"name": "토담순두부",           "query": "토담순두부 강릉 초당"},
    {"name": "카페 툇마루",          "query": "툇마루 강릉 초당동 카페"},
    {"name": "순두부젤라또 1호점",   "query": "순두부젤라또 강릉 초당"},
    {"name": "테라로사 커피공장",    "query": "테라로사 커피공장 강릉"},
    {"name": "보헤미안 박이추커피",  "query": "보헤미안 박이추 커피 강릉 연곡"},
    {"name": "카페 산토리니",        "query": "산토리니 커피 강릉"},
    {"name": "만동빵집",             "query": "만동빵집 강릉"},
    {"name": "강릉중앙시장",         "query": "강릉중앙시장"},
    {"name": "중앙시장 닭강정골목",  "query": "중앙닭강정 강릉"},
    {"name": "월화거리",             "query": "강릉 월화거리"},
    {"name": "교동반점",             "query": "교동반점 강릉"},
    {"name": "강릉감자옹심이 본점",  "query": "강릉감자옹심이 본점"},
    {"name": "형제칼국수",           "query": "형제칼국수 강릉"},
    {"name": "삼교리동치미막국수",   "query": "삼교리동치미막국수 헤드쿼터 구정면 강릉"},
    {"name": "해성횟집",             "query": "해성횟집 강릉"},
    {"name": "오봉집 물회",          "query": "오봉이 해물칼국수 강릉"},
    {"name": "경포호 주변 횟집거리", "query": "피쉬맨 경포대본점 강릉"},
    {"name": "안목해변 커피거리",    "query": "안목해변 커피거리 강릉"},
    {"name": "강문해변 카페거리",    "query": "강문해변 카페 강릉"},
    {"name": "버드나무브루어리",     "query": "버드나무브루어리 강릉"},
]


# ══════════════════════════════════════════════════════
# [1] 구글 Popular Times
# ══════════════════════════════════════════════════════
def fetch_google(place):
    """
    가게 하나의 구글 혼잡도를 가져온다.
    반환: dict(lat,lng,current,weekly,source) 또는 None
    - current : 0~100 실시간 혼잡도 (없으면 None)
    - weekly  : {mon:[24개],...} 요일별 시간대 혼잡도(0~100)
    """
    try:
        import populartimes  # pip install git+https://github.com/m-wrzr/populartimes
        import googlemaps
    except ImportError:
        print("  ! populartimes / googlemaps 미설치 → 구글 데이터 건너뜀")
        return None

    gmaps = googlemaps.Client(key=GOOGLE_API_KEY)

    # 1) 이름으로 place_id 찾기
    found = gmaps.find_place(
        input=place["query"], input_type="textquery",
        fields=["place_id", "geometry/location"],
    )
    cands = found.get("candidates", [])
    if not cands:
        print(f"  ! '{place['name']}' 구글에서 못 찾음")
        return None
    place_id = cands[0]["place_id"]
    loc = cands[0].get("geometry", {}).get("location", {})

    # 2) Popular Times 조회
    data = populartimes.get_id(GOOGLE_API_KEY, place_id)

    weekly = {}
    for day_block in data.get("populartimes", []):
        # day_block = {"name":"Monday","data":[24개 0~100]}
        idx = ["Monday","Tuesday","Wednesday","Thursday",
               "Friday","Saturday","Sunday"].index(day_block["name"])
        weekly[DAYS[idx]] = [int(x) for x in day_block["data"]]

    current = data.get("current_popularity")  # 실시간 (없을 수 있음)

    return {
        "lat": loc.get("lat"),
        "lng": loc.get("lng"),
        "current": int(current) if current is not None else None,
        "weekly": weekly or None,
        "source": "google",
    }


# ══════════════════════════════════════════════════════
# [2] 공공데이터 유동인구 (지역 보정용)
# ══════════════════════════════════════════════════════
def fetch_public_footfall():
    """
    강릉 지역의 현재 시간대 유동인구 수준(0~100)을 하나의 지역 보정값으로 반환.
    실시간·가게별이 아니므로 '오늘 강릉이 전반적으로 얼마나 붐비나' 정도로만 쓴다.

    ※ 공공데이터포털에는 유동인구 관련 API가 여러 개 있고 엔드포인트/파라미터가
       제각각이다. 아래는 요청 골격이며, 실제 사용하는 API 명세에 맞춰
       URL·파라미터·응답 파싱만 바꾸면 된다. 키가 없으면 None 반환.
    """
    if not PUBLIC_DATA_KEY or PUBLIC_DATA_KEY.startswith("여기에"):
        return None
    try:
        import requests
        # 예시 골격 — 실제 쓰는 유동인구 API의 URL로 교체
        url = "https://api.odcloud.kr/api/[유동인구_API_경로]"
        params = {
            "serviceKey": PUBLIC_DATA_KEY,
            "page": 1, "perPage": 50,
            "cond[지역명::EQ]": "강릉시",
        }
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        rows = r.json().get("data", [])
        if not rows:
            return None
        # 현재 시각대의 유동인구를 0~100으로 정규화 (예시 로직)
        hour = dt.datetime.now().hour
        vals = [float(row.get("유동인구수", 0)) for row in rows]
        if not vals:
            return None
        vmax = max(vals) or 1
        # 시간대 비중을 반영한 대략적 지역 밀집도
        approx = (sum(vals) / len(vals)) / vmax * 100
        # 심야 감쇠
        if hour < 7 or hour >= 23:
            approx *= 0.4
        return max(0, min(100, round(approx)))
    except Exception as e:
        print(f"  ! 공공 유동인구 실패: {e}")
        return None


# ══════════════════════════════════════════════════════
# 합치기 → JSON
# ══════════════════════════════════════════════════════
def build():
    print("혼잡도 수집 시작…")
    footfall = fetch_public_footfall()
    print(f"  · 공공 유동인구 지역보정값: {footfall}")

    out_places = []
    for p in PLACES:
        print(f"  · {p['name']}")
        g = None
        try:
            g = fetch_google(p)
        except Exception as e:
            print(f"    구글 실패: {e}")
        time.sleep(0.4)  # API rate limit 배려

        row = {"name": p["name"]}
        if g:
            row.update({
                "lat": g["lat"], "lng": g["lng"],
                "current": g["current"], "weekly": g["weekly"],
                "footfall": footfall,
                "source": "google",
                "updated": dt.datetime.now().isoformat(timespec="seconds"),
            })
        else:
            # 구글 실패한 가게는 값 없이 넣어둠 → 프론트가 자체 추정으로 폴백
            row.update({"current": None, "weekly": None,
                        "footfall": footfall, "source": "estimate",
                        "updated": dt.datetime.now().isoformat(timespec="seconds")})
        out_places.append(row)

    payload = {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "places": out_places,
    }
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"완료 → {OUT_PATH}")


if __name__ == "__main__":
    build()
