import requests
from bs4 import BeautifulSoup
from datetime import datetime
import os

TISTORY_ACCESS_TOKEN = os.environ.get("TISTORY_ACCESS_TOKEN")
TISTORY_BLOG_NAME = "mynote86786"

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
    rows = soup.select("table.list_type tbody tr")

    for row in rows:
        cells = row.select("td")
        if len(cells) < 7:
            continue

        title_tag = cells[1].select_one("a")
        title = title_tag.get_text(strip=True) if title_tag else cells[1].get_text(strip=True)
        org = cells[2].get_text(strip=True)
        location = cells[3].get_text(strip=True)
        job_type = cells[4].get_text(strip=True)
        deadline = cells[6].get_text(strip=True).replace("\n", " ").strip()

        href = title_tag.get("href", "") if title_tag else ""
        if href.startswith("/"):
            link = f"https://job.alio.go.kr{href}"
        else:
            link = href

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


def build_post(jobs):
    today = datetime.now().strftime("%Y년 %m월 %d일")
    lines = []
    lines.append(f"<h2>📋 {today} 기준 공공기관 전산직 채용공고</h2>")
    lines.append("<p>비전공자도 지원 가능한 공공기관 전산직 정규직 채용공고를 정리했습니다.</p>")
    lines.append("<hr/>")

    if not jobs:
        lines.append("<p>현재 진행 중인 공고가 없습니다. 내일 다시 확인해주세요.</p>")
    else:
        lines.append("<table border='1' cellpadding='8' cellspacing='0' style='border-collapse:collapse;width:100%'>")
        lines.append("<thead><tr style='background:#f0f0f0'>")
        lines.append("<th>기관명</th><th>채용제목</th><th>지역</th><th>고용형태</th><th>마감일</th><th>링크</th>")
        lines.append("</tr></thead><tbody>")

        for job in jobs:
            link_html = f"<a href='{job['link']}' target='_blank'>바로가기</a>" if job["link"] else "-"
            lines.append(f"<tr>")
            lines.append(f"<td>{job['org']}</td>")
            lines.append(f"<td>{job['title']}</td>")
            lines.append(f"<td>{job['location']}</td>")
            lines.append(f"<td>{job['job_type']}</td>")
            lines.append(f"<td>{job['deadline']}</td>")
            lines.append(f"<td>{link_html}</td>")
            lines.append("</tr>")

        lines.append("</tbody></table>")

    lines.append("<hr/>")
    lines.append("<p><small>※ 본 포스팅은 알리오(job.alio.go.kr) 공공기관 채용정보를 자동 수집하여 작성됩니다.</small></p>")

    return "\n".join(lines)


def post_to_tistory(title, content):
    url = "https://www.tistory.com/apis/post/write"
    params = {
        "access_token": TISTORY_ACCESS_TOKEN,
        "output": "json",
        "blogName": TISTORY_BLOG_NAME,
        "title": title,
        "content": content,
        "visibility": "3",
        "tag": "전산직,공공기관채용,비전공자,정규직채용",
    }
    resp = requests.post(url, data=params)
    result = resp.json()
    print("포스팅 결과:", result)
    return result


if __name__ == "__main__":
    print("공고 수집 중...")
    jobs = fetch_jobs()
    print(f"수집된 공고: {len(jobs)}건")

    today = datetime.now().strftime("%Y.%m.%d")
    title = f"[{today}] 공공기관 전산직 정규직 채용공고 모음"
    content = build_post(jobs)

    if TISTORY_ACCESS_TOKEN:
        post_to_tistory(title, content)
    else:
        print("TISTORY_ACCESS_TOKEN 없음 - 포스팅 건너뜀")
        print("생성된 제목:", title)
        print("공고 수:", len(jobs))
