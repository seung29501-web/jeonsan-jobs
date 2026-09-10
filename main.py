import requests
from bs4 import BeautifulSoup
from datetime import datetime


def fetch_jobs():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })

    session.get("https://job.alio.go.kr/recruit.do")

    data = {
        "pageIndex": "1",
        "pageUnit": "100",
        "srch_state": "ing",
        "srch_work_type_main": "전산직",
        "srch_career_type": "정규직",
    }

    resp = session.post("https://job.alio.go.kr/recruit.do", data=data)
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    jobs = []
    rows = soup.select("table tbody tr")

    for row in rows:
        cells = row.select("td")
        if len(cells) < 7:
            continue

        title_tag = cells[1].select_one("a")
        title = title_tag.get_text(strip=True) if title_tag else cells[1].get_text(strip=True)
        org = cells[2].get_text(strip=True)
        location = cells[3].get_text(strip=True)
        job_type = cells[4].get_text(strip=True)
        deadline = cells[6].get_text(strip=True).split("\n")[0].strip()

        href = title_tag.get("href", "") if title_tag else ""
        link = f"https://job.alio.go.kr{href}" if href.startswith("/") else href

        if "제주" in location:
            continue

        jobs.append({
            "title": title,
            "org": org,
            "location": location,
            "job_type": job_type,
            "deadline": deadline,
            "link": link,
        })

    return jobs


def build_html(jobs):
    today = datetime.now().strftime("%Y년 %m월 %d일 %H:%M")
    count = len(jobs)

    rows_html = ""
    if not jobs:
        rows_html = '<tr><td colspan="5" style="text-align:center;padding:40px;color:#888;">현재 진행 중인 공고가 없습니다.</td></tr>'
    else:
        for job in jobs:
            rows_html += f"""
            <tr>
                <td>{job['org']}</td>
                <td><a href="{job['link']}" target="_blank">{job['title']}</a></td>
                <td>{job['location']}</td>
                <td>{job['job_type']}</td>
                <td>{job['deadline']}</td>
            </tr>"""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>공공기관 전산직 채용공고</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Malgun Gothic', sans-serif; background: #f5f7fa; color: #333; }}
  header {{ background: #1e3a5f; color: white; padding: 24px 32px; }}
  header h1 {{ font-size: 22px; margin-bottom: 6px; }}
  header p {{ font-size: 13px; opacity: 0.8; }}
  .container {{ max-width: 1100px; margin: 24px auto; padding: 0 16px; }}
  .stats {{ display: flex; gap: 12px; margin-bottom: 20px; }}
  .stat-box {{ background: white; border-radius: 8px; padding: 16px 24px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
  .stat-box .num {{ font-size: 28px; font-weight: bold; color: #1e3a5f; }}
  .stat-box .label {{ font-size: 12px; color: #888; margin-top: 2px; }}
  .card {{ background: white; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); overflow: hidden; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{ background: #1e3a5f; color: white; padding: 12px 16px; text-align: left; font-size: 13px; }}
  td {{ padding: 12px 16px; border-bottom: 1px solid #f0f0f0; font-size: 13px; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: #f8f9ff; }}
  a {{ color: #1e3a5f; text-decoration: none; font-weight: 500; }}
  a:hover {{ text-decoration: underline; }}
  .badge {{ display: inline-block; background: #e8f0fe; color: #1e3a5f; padding: 2px 8px; border-radius: 12px; font-size: 11px; }}
  footer {{ text-align: center; padding: 24px; font-size: 12px; color: #aaa; }}
</style>
</head>
<body>
<header>
  <h1>📋 공공기관 전산직 채용공고 모아보기</h1>
  <p>정규직 · 비전공자 지원 가능 공고 중심 · 제주 제외 · 매일 오전 7시 자동 업데이트</p>
</header>
<div class="container">
  <div class="stats">
    <div class="stat-box">
      <div class="num">{count}</div>
      <div class="label">진행중인 공고</div>
    </div>
    <div class="stat-box">
      <div class="num" style="font-size:14px;padding-top:6px;">{today}</div>
      <div class="label">마지막 업데이트</div>
    </div>
  </div>
  <div class="card">
    <table>
      <thead>
        <tr>
          <th>기관명</th>
          <th>채용제목</th>
          <th>지역</th>
          <th>고용형태</th>
          <th>마감일</th>
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
  </div>
</div>
<footer>
  출처: 알리오(job.alio.go.kr) · GitHub Actions 자동 수집
</footer>
</body>
</html>"""


if __name__ == "__main__":
    print("공고 수집 중...")
    jobs = fetch_jobs()
    print(f"수집된 공고: {len(jobs)}건")

    html = build_html(jobs)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("index.html 생성 완료")
