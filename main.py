import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime

BASE = "https://job.alio.go.kr"
LIST_URL = f"{BASE}/recruit.do"

# 알리오 검색 폼 코드값
NCS_INFO_COMM = "R600020"   # 표준직무(NCS) - 정보통신
WORK_TYPE_REGULAR = "R1010"  # 고용형태 - 정규직
STATUS_ONGOING = "2"         # 진행중

EXCLUDE_LOCATIONS = ["제주"]
EXCLUDE_TYPES = ["청년인턴", "체험형"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Referer": LIST_URL,
}


def clean(text):
    return re.sub(r"\s+", " ", text).strip()


def fetch_jobs(max_pages=10):
    session = requests.Session()
    session.headers.update(HEADERS)
    session.get(LIST_URL, timeout=20)

    jobs = []
    seen = set()

    for page in range(1, max_pages + 1):
        payload = {
            "pageNo": str(page),
            "detail_code": NCS_INFO_COMM,
            "work_type": WORK_TYPE_REGULAR,
            "ing": STATUS_ONGOING,
        }
        resp = session.post(LIST_URL, data=payload, timeout=20)
        resp.encoding = "utf-8"

        soup = BeautifulSoup(resp.text, "html.parser")
        rows = soup.select("table.type_03 tbody tr")
        print(f"[페이지 {page}] 수신 {len(rows)}건")

        if not rows:
            break

        new_on_page = 0
        for row in rows:
            cells = row.select("td")
            if len(cells) < 9:
                continue

            title = clean(cells[2].get_text(" ", strip=True))
            org = clean(cells[3].get_text(" ", strip=True))
            location = clean(cells[4].get_text(" ", strip=True))
            job_type = clean(cells[5].get_text(" ", strip=True))
            deadline = clean(cells[7].get_text(" ", strip=True))

            link_tag = cells[2].select_one("a[href]")
            link = f"{BASE}{link_tag['href']}" if link_tag else LIST_URL

            key = (title, org)
            if key in seen:
                continue
            seen.add(key)
            new_on_page += 1

            if any(x in location for x in EXCLUDE_LOCATIONS):
                continue
            if any(x in job_type for x in EXCLUDE_TYPES):
                continue

            jobs.append({
                "title": title,
                "org": org,
                "location": location,
                "job_type": job_type,
                "deadline": deadline,
                "link": link,
            })

        if new_on_page == 0:
            break

    print(f"필터링 후: {len(jobs)}건")
    return jobs


def build_html(jobs):
    today = datetime.now().strftime("%Y년 %m월 %d일 %H:%M")

    if jobs:
        rows_html = "".join(
            f"""
        <tr>
          <td class="org">{j['org']}</td>
          <td><a href="{j['link']}" target="_blank" rel="noopener">{j['title']}</a></td>
          <td>{j['location']}</td>
          <td><span class="tag">{j['job_type']}</span></td>
          <td class="deadline">{j['deadline']}</td>
        </tr>"""
            for j in jobs
        )
    else:
        rows_html = ('<tr><td colspan="5" class="empty">'
                     '현재 조건에 맞는 진행중인 공고가 없습니다.</td></tr>')

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>공공기관 전산직 채용공고</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, 'Malgun Gothic', sans-serif; background: #f5f7fa; color: #333; }}
  header {{ background: #1e3a5f; color: #fff; padding: 24px 32px; }}
  header h1 {{ font-size: 21px; margin-bottom: 6px; }}
  header p {{ font-size: 13px; opacity: .85; }}
  .container {{ max-width: 1100px; margin: 24px auto; padding: 0 16px; }}
  .stats {{ display: flex; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; }}
  .stat-box {{ background: #fff; border-radius: 8px; padding: 16px 24px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  .stat-box .num {{ font-size: 28px; font-weight: 700; color: #1e3a5f; }}
  .stat-box .label {{ font-size: 12px; color: #888; margin-top: 2px; }}
  .card {{ background: #fff; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.08); overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; min-width: 760px; }}
  th {{ background: #1e3a5f; color: #fff; padding: 12px 16px; text-align: left; font-size: 13px; white-space: nowrap; }}
  td {{ padding: 12px 16px; border-bottom: 1px solid #f0f0f0; font-size: 13px; vertical-align: top; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: #f8f9ff; }}
  .org {{ white-space: nowrap; color: #555; }}
  .deadline {{ white-space: nowrap; color: #d14; font-weight: 600; }}
  a {{ color: #1e3a5f; text-decoration: none; font-weight: 500; }}
  a:hover {{ text-decoration: underline; }}
  .tag {{ display: inline-block; background: #e8f0fe; color: #1e3a5f; padding: 2px 8px; border-radius: 12px; font-size: 11px; white-space: nowrap; }}
  .empty {{ text-align: center; padding: 40px; color: #888; }}
  footer {{ text-align: center; padding: 24px; font-size: 12px; color: #aaa; }}
</style>
</head>
<body>
<header>
  <h1>공공기관 전산직 채용공고 모아보기</h1>
  <p>알리오 NCS 직무 &ldquo;정보통신&rdquo; · 정규직 · 진행중 · 제주 제외 · 매일 오전 7시 자동 업데이트</p>
</header>
<div class="container">
  <div class="stats">
    <div class="stat-box">
      <div class="num">{len(jobs)}</div>
      <div class="label">진행중인 공고</div>
    </div>
    <div class="stat-box">
      <div class="num" style="font-size:14px;padding-top:8px;">{today}</div>
      <div class="label">마지막 업데이트</div>
    </div>
  </div>
  <div class="card">
    <table>
      <thead>
        <tr>
          <th>기관명</th><th>채용제목</th><th>지역</th><th>고용형태</th><th>마감일</th>
        </tr>
      </thead>
      <tbody>{rows_html}
      </tbody>
    </table>
  </div>
</div>
<footer>출처: 알리오(job.alio.go.kr) · GitHub Actions 자동 수집</footer>
</body>
</html>"""


if __name__ == "__main__":
    print("공고 수집 중...")
    jobs = fetch_jobs()
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(build_html(jobs))
    print(f"index.html 생성 완료 ({len(jobs)}건)")
