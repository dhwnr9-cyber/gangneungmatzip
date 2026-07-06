"""
collect_festival_news.py
─────────────────────────────────────────────────────────────
강릉 축제·행사 소식 수집기.

강릉관광개발공사(gtdc.or.kr) 공식 "행사안내" 게시판을 긁어와서
festival_news.json 을 만든다. 프론트엔드(index.html)가 이 파일을
읽어서 지도 하단에 최신 소식 몇 개를 보여준다.

⚠️ 정직하게 알아둘 점
  - 이 사이트는 공식 RSS/API를 제공하지 않아서 HTML을 직접 파싱한다.
    사이트 구조가 바뀌면 파싱이 깨질 수 있다 (그 경우 이 스크립트의
    선택자 부분만 다시 맞춰주면 된다).
  - "축제"만 나오는 게 아니라 공식 행사·이벤트·할인 안내도 섞여 있다.
    강릉관광개발공사가 공식으로 올리는 관광 관련 소식 전체를 가져온다.

실행:  python collect_festival_news.py
결과:  같은 폴더에 festival_news.json 생성 (GitHub Actions가 주기 실행)
"""

import json
import re
import datetime as dt
from pathlib import Path

SOURCE_URL = "https://www.gtdc.or.kr/pub/bbsevent.do"
OUT_PATH = Path(__file__).parent / "festival_news.json"
MAX_ITEMS = 8

# 게시글 제목 끝에 붙어있는 "26-05-28 (목) 14:58" 같은 작성 시각 꼬리표 제거용
TRAILING_DATE_RE = re.compile(r"\s*\d{2}-\d{2}-\d{2}\s*\([가-힣]\)\s*\d{2}:\d{2}\s*$")


def clean_title(raw: str) -> str:
    """제목 문자열에서 첨부파일 표시, 뒤에 붙은 작성시각을 제거한다."""
    t = raw.strip()
    t = TRAILING_DATE_RE.sub("", t)
    t = t.replace("첨부된 파일있음", "").replace("첨부파일", "")
    return t.strip()


def fetch_items():
    import requests
    from bs4 import BeautifulSoup

    headers = {"User-Agent": "Mozilla/5.0 (compatible; GangneungFoodMapBot/1.0)"}
    res = requests.get(SOURCE_URL, headers=headers, timeout=15)
    res.raise_for_status()
    res.encoding = res.apparent_encoding or "utf-8"
    soup = BeautifulSoup(res.text, "html.parser")

    # "제목" / "작성일" 헤더가 들어있는 표를 찾는다 (클래스명에 의존하지 않고
    # 구조로 찾아서, 사이트 리뉴얼에도 어느 정도 버티게 한다)
    target_table = None
    for table in soup.find_all("table"):
        header_text = table.get_text()
        if "제목" in header_text and "작성일" in header_text:
            target_table = table
            break
    if target_table is None:
        raise RuntimeError("게시판 표를 찾지 못했습니다 (사이트 구조가 바뀌었을 수 있음)")

    items = []
    for row in target_table.find_all("tr"):
        link = row.find("a", href=True)
        if not link:
            continue
        title = clean_title(link.get_text(" ", strip=True))
        if not title:
            continue
        href = link["href"]
        if href.startswith("http"):
            url = href
        else:
            url = "https://www.gtdc.or.kr" + (href if href.startswith("/") else "/" + href)

        # 작성일 칸 찾기: "2026/05/28" 형태 텍스트를 가진 셀
        date_text = ""
        for cell in row.find_all("td"):
            m = re.search(r"\d{4}/\d{2}/\d{2}", cell.get_text())
            if m:
                date_text = m.group(0).replace("/", "-")
                break

        items.append({"title": title, "date": date_text, "url": url})
        if len(items) >= MAX_ITEMS:
            break

    return items


def build():
    print("강릉 축제·행사 소식 수집 시작…")
    try:
        items = fetch_items()
        print(f"  · {len(items)}건 수집")
    except Exception as e:
        print(f"  ! 수집 실패: {e}")
        # 실패해도 기존 파일이 있으면 그대로 두고, 없으면 빈 목록으로 생성
        if OUT_PATH.exists():
            print("  · 기존 festival_news.json 유지")
            return
        items = []

    payload = {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "source": SOURCE_URL,
        "items": items,
    }
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"완료 → {OUT_PATH}")


if __name__ == "__main__":
    build()
