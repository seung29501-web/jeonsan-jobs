import re
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime

BASE = "https://job.alio.go.kr"
LIST_URL = f"{BASE}/recruit.do"

# 알리오 검색 폼 코드값
NCS_INFO_COMM = "R600020"      # 표준직무(NCS) - 정보통신
WORK_TYPE_REGULAR = "R1010"    # 고용형태 - 정규직
WORK_TYPE_PERMANENT = "R1030"  # 고용형태 - 무기계약직
STATUS_ONGOING = "2"           # 상태 - 진행중
CAREER_NEW = "R2010"           # 채용구분 - 신입
CAREER_BOTH = "R2030"          # 채용구분 - 신입+경력

EXCLUDE_LOCATIONS = ["제주"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Referer": LIST_URL,
}

# 모집분야명이 전산 계열인지 판정. 단독 "보안"/"개발"은 안전직·연구직 오탐이 많아 제외한다.
IT_FIELD = re.compile(
    r"(전산|정보통신|정보시스템|정보화|정보처리|정보보안|사이버보안|보안관제"
    r"|소프트웨어|디지털|빅데이터|데이터|인공지능|네트워크|통신|시스템|개발운영"
    r"|\bIT\b|\bICT\b|\bSW\b|\bAI\b|\bDX\b)",
    re.I,
)

# --- 응시자격 판정 규칙 ---
ENG_NONE = re.compile(r"(어학|영어|외국어)[^\n]{0,20}(제한\s*없|무관|불필요)")
ENG_REQ = re.compile(
    r"(공인\s*어학성적|유효한?\s*어학성적|어학성적\s*기준|어학성적\s*보유자"
    r"|(?:TOEIC|TOEFL|TEPS|OPIc|토익|토플|텝스|오픽)[^\n]{0,15}\d{2,4}\s*점?\s*이상"
    r"|(?:TOEIC|TOEFL|TEPS)\s*\d{3}"
    r"|(?:어학|영어)[^\n]{0,25}\d{3}\s*점\s*이상)",
    re.I,
)
ENG_EVAL = re.compile(r"어학[^\n]{0,25}(환산|배점|계량|가점|반영)")
ENG_ANY = re.compile(r"어학|토익|TOEIC|TEPS|OPIc", re.I)

MAJ_NONE = re.compile(r"전공[^\n]{0,20}(제한\s*없|무관|별도\s*제한\s*없)")
MAJ_REQ = re.compile(
    r"((?:해당|관련)\s*(?:분야\s*)?전공자|전공\s*분야\s*해당자"
    r"|전공자에?\s*한(?:함|하여)|(?:컴퓨터공학|전산학|소프트웨어)\s*(?:등\s*)?(?:관련\s*)?전공)"
)


def clean(text):
    return re.sub(r"\s+", " ", text).strip()


def parse_detail(html):
    """상세페이지에서 메타 필드, h4 섹션 본문, 모집분야 목록을 분리한다."""
    soup = BeautifulSoup(html, "html.parser")

    fields = {}
    for th in soup.select("th"):
        td = th.find_next_sibling("td")
        if td:
            fields[clean(th.get_text())] = clean(td.get_text(" "))

    sections = {}
    for head in soup.select("h4"):
        parts = []
        for sib in head.next_siblings:
            if getattr(sib, "name", None) == "h4":
                break
            if hasattr(sib, "get_text"):
                text = sib.get_text("\n", strip=True)
                if text:
                    parts.append(text)
        sections[clean(head.get_text())] = re.sub(r"[ \t]+", " ", "\n".join(parts))

    # 전형단계별 채용정보는 모집분야마다 표가 하나씩이고, 첫 행이 분야명 한 칸이다.
    positions = []
    for table in soup.select("table"):
        first = table.select_one("tr")
        if not first:
            continue
        cells = first.select("th, td")
        if len(cells) == 1:
            name = clean(cells[0].get_text(" "))
            if name:
                positions.append(name)

    return fields, sections, positions


def judge(fields, sections, positions, title):
    """응시자격 본문과 모집분야 목록을 근거로 요건을 판정한다."""
    qual = sections.get("응시자격", "") or "\n".join(sections.values())
    basis = f"{qual}\n{fields.get('학력정보', '')}"

    if ENG_NONE.search(basis):
        eng = "없음"
    elif ENG_REQ.search(basis):
        eng = "필수"
    elif ENG_EVAL.search(basis):
        eng = "평가반영"
    elif ENG_ANY.search(basis):
        eng = "확인필요"
    else:
        eng = "없음"

    if MAJ_NONE.search(basis):
        major = "무관"
    elif MAJ_REQ.search(basis):
        major = "제한있음"
    else:
        major = "언급없음"

    it_fields = [p for p in positions if IT_FIELD.search(p)]
    if it_fields:
        it = "있음"
    elif positions:
        it = "없음"  # 모집분야가 공개돼 있는데 전산 계열이 하나도 없음
    else:
        it = "확인필요"

    return eng, major, it, it_fields


def fetch_list(session, max_pages=10):
    session.get(LIST_URL, timeout=20)
    items, seen = [], set()

    for page in range(1, max_pages + 1):
        payload = [
            ("pageNo", str(page)),
            ("detail_code", NCS_INFO_COMM),
            ("work_type", WORK_TYPE_REGULAR),
            ("work_type", WORK_TYPE_PERMANENT),
            ("career", CAREER_NEW),
            ("career", CAREER_BOTH),
            ("ing", STATUS_ONGOING),
        ]
        resp = session.post(LIST_URL, data=payload, timeout=20)
        resp.encoding = "utf-8"
        rows = BeautifulSoup(resp.text, "html.parser").select("table.type_03 tbody tr")
        print(f"[목록 {page}p] 수신 {len(rows)}건")
        if not rows:
            break

        new_count = 0
        for row in rows:
            cells = row.select("td")
            if len(cells) < 9:
                continue
            title = clean(cells[2].get_text(" "))
            org = clean(cells[3].get_text(" "))
            if (title, org) in seen:
                continue
            seen.add((title, org))
            new_count += 1

            location = clean(cells[4].get_text(" "))
            if any(x in location for x in EXCLUDE_LOCATIONS):
                continue

            link_tag = cells[2].select_one("a[href]")
            items.append({
                "title": title,
                "org": org,
                "location": location,
                "job_type": clean(cells[5].get_text(" ")),
                "deadline": clean(cells[7].get_text(" ")),
                "link": f"{BASE}{link_tag['href']}" if link_tag else LIST_URL,
            })

        if new_count == 0:
            break

    return items


def enrich(session, jobs):
    kept, dropped = [], []
    for job in jobs:
        try:
            resp = session.get(job["link"], timeout=20)
            resp.encoding = "utf-8"
            fields, sections, positions = parse_detail(resp.text)
            eng, major, it, it_fields = judge(fields, sections, positions, job["title"])
            job.update(eng=eng, major=major, it=it, it_fields=it_fields,
                       edu=fields.get("학력정보", "-"))
        except Exception as e:
            print(f"  상세 조회 실패 ({job['org']}): {e}")
            job.update(eng="확인필요", major="언급없음", it="확인필요", it_fields=[], edu="-")

        if job["it"] == "없음":
            dropped.append(job)
            print(f"  {job['org'][:16]:<17} 제외 — 전산 모집분야 없음")
            continue

        kept.append(job)
        tag = ", ".join(job["it_fields"])[:40] or "확인필요"
        print(f"  {job['org'][:16]:<17} 어학={job['eng']:<5} 전공={job['major']:<5} 분야={tag}")
        time.sleep(0.3)

    print(f"전산 분야 없어서 제외: {len(dropped)}건")
    return kept


def fetch_jobs():
    session = requests.Session()
    session.headers.update(HEADERS)
    jobs = fetch_list(session)
    print(f"목록 필터링 후: {len(jobs)}건 — 상세 확인 중")
    jobs = enrich(session, jobs)
    penalty = {"없음": 0, "언급없음": 0, "무관": 0, "있음": 0,
               "평가반영": 2, "확인필요": 3, "제한있음": 3, "필수": 5}
    jobs.sort(key=lambda j: (penalty[j["eng"]] + penalty[j["major"]] + penalty[j["it"]], j["deadline"]))
    return jobs


def build_html(jobs):
    today = datetime.now().strftime("%Y년 %m월 %d일 %H:%M")
    eng_cls = {"없음": "ok", "평가반영": "warn", "확인필요": "warn", "필수": "bad"}
    maj_cls = {"무관": "ok", "언급없음": "ok", "제한있음": "bad"}
    safe = sum(1 for j in jobs if j["eng"] == "없음" and j["major"] != "제한있음")

    if jobs:
        rows_html = "".join(
            f"""
        <tr data-eng="{j['eng']}" data-major="{j['major']}">
          <td class="org">{j['org']}</td>
          <td><a href="{j['link']}" target="_blank" rel="noopener">{j['title']}</a>
              <div class="sub">{' · '.join(j['it_fields']) if j['it_fields'] else '전산 분야 확인 필요 (첨부 공고문 참조)'}</div></td>
          <td>{j['location']}</td>
          <td><span class="pill {eng_cls[j['eng']]}">{j['eng']}</span></td>
          <td><span class="pill {maj_cls[j['major']]}">{j['major']}</span></td>
          <td class="dl">{j['job_type']}<br><b>{j['deadline']}</b><br><span class="edu">{j['edu']}</span></td>
        </tr>"""
            for j in jobs
        )
    else:
        rows_html = '<tr><td colspan="6" class="empty">조건에 맞는 진행중인 공고가 없습니다.</td></tr>'

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
  header p {{ font-size: 13px; opacity: .85; line-height: 1.6; }}
  .container {{ max-width: 1240px; margin: 24px auto; padding: 0 16px; }}
  .stats {{ display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }}
  .stat-box {{ background: #fff; border-radius: 8px; padding: 16px 24px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  .stat-box .num {{ font-size: 28px; font-weight: 700; color: #1e3a5f; }}
  .stat-box .num.hl {{ color: #1a7f37; }}
  .stat-box .label {{ font-size: 12px; color: #888; margin-top: 2px; }}
  .toolbar {{ background: #fff; border-radius: 8px; padding: 12px 16px; margin-bottom: 16px;
             box-shadow: 0 1px 4px rgba(0,0,0,.08); font-size: 13px; display: flex; gap: 20px; flex-wrap: wrap; }}
  .toolbar label {{ cursor: pointer; user-select: none; }}
  .card {{ background: #fff; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.08); overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; min-width: 940px; }}
  th {{ background: #1e3a5f; color: #fff; padding: 12px 14px; text-align: left; font-size: 13px; white-space: nowrap; }}
  td {{ padding: 12px 14px; border-bottom: 1px solid #f0f0f0; font-size: 13px; vertical-align: top; }}
  tr:last-child td {{ border-bottom: none; }}
  tbody tr:hover td {{ background: #f8f9ff; }}
  .org {{ white-space: nowrap; color: #555; }}
  .sub {{ font-size: 11px; color: #1a7f37; margin-top: 5px; font-weight: 600; }}
  .dl {{ white-space: nowrap; font-size: 11px; color: #777; line-height: 1.7; }}
  .dl b {{ color: #d14; font-size: 13px; }}
  .edu {{ color: #aaa; }}
  a {{ color: #1e3a5f; text-decoration: none; font-weight: 500; }}
  a:hover {{ text-decoration: underline; }}
  .pill {{ display: inline-block; padding: 2px 9px; border-radius: 12px; font-size: 11px; white-space: nowrap; font-weight: 600; }}
  .pill.ok {{ background: #e6f4ea; color: #1a7f37; }}
  .pill.warn {{ background: #fff4e5; color: #9a6400; }}
  .pill.bad {{ background: #fde8e8; color: #b42318; }}
  .empty {{ text-align: center; padding: 40px; color: #888; }}
  .note {{ font-size: 12px; color: #999; margin-top: 12px; line-height: 1.7; }}
  footer {{ text-align: center; padding: 24px; font-size: 12px; color: #aaa; }}
</style>
</head>
<body>
<header>
  <h1>공공기관 전산직 채용공고 모아보기</h1>
  <p>정규직·무기계약직 · 신입 · 진행중 · 제주 제외<br>
     알리오 필터만 믿지 않고 <b>공고 본문의 모집분야와 응시자격까지 읽어서</b> 걸러냄 · 매일 오전 7시 자동 갱신</p>
</header>
<div class="container">
  <div class="stats">
    <div class="stat-box"><div class="num hl">{safe}</div><div class="label">토익·전공 조건 없는 공고</div></div>
    <div class="stat-box"><div class="num">{len(jobs)}</div><div class="label">전산 분야 있는 공고</div></div>
    <div class="stat-box"><div class="num" style="font-size:14px;padding-top:8px;">{today}</div><div class="label">마지막 업데이트</div></div>
  </div>
  <div class="toolbar">
    <label><input type="checkbox" id="hideEng" checked> 어학성적 <b>필수</b>인 공고 숨기기</label>
    <label><input type="checkbox" id="hideMajor" checked> 전공 <b>제한있음</b>인 공고 숨기기</label>
  </div>
  <div class="card">
    <table>
      <thead>
        <tr><th>기관명</th><th>채용제목 / 전산 모집분야</th><th>지역</th><th>어학요건</th><th>전공요건</th><th>형태 / 마감 / 학력</th></tr>
      </thead>
      <tbody id="tbody">{rows_html}
      </tbody>
    </table>
  </div>
  <p class="note">
    제목 아래 <b style="color:#1a7f37">초록색 글씨</b>가 그 공고에서 실제로 뽑는 전산 계열 모집분야야.
    전산 분야가 하나도 없는 공고는 아예 목록에서 뺐어.<br>
    <b>어학요건 / 전공요건</b>은 <b>응시자격</b> 항목만 읽어서 판정했어 (전형절차의 &ldquo;전공시험&rdquo; 같은 건 요건이 아니라 제외).
    <b>평가반영</b>은 지원자격은 아니지만 서류 점수에 반영되는 경우, <b>확인필요</b>는 애매한 경우야.<br>
    통합채용은 분야마다 조건이 달라서 자동 판정이 틀릴 수 있으니, 지원 전엔 공고문 원본을 꼭 확인해.
  </p>
</div>
<footer>출처: 알리오(job.alio.go.kr) · GitHub Actions 자동 수집</footer>
<script>
  function apply() {{
    var he = document.getElementById('hideEng').checked;
    var hm = document.getElementById('hideMajor').checked;
    document.querySelectorAll('#tbody tr[data-eng]').forEach(function (tr) {{
      tr.hidden = (he && tr.dataset.eng === '필수') || (hm && tr.dataset.major === '제한있음');
    }});
  }}
  document.getElementById('hideEng').addEventListener('change', apply);
  document.getElementById('hideMajor').addEventListener('change', apply);
  apply();
</script>
</body>
</html>"""


if __name__ == "__main__":
    print("공고 수집 중...")
    jobs = fetch_jobs()
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(build_html(jobs))
    print(f"index.html 생성 완료 ({len(jobs)}건)")
