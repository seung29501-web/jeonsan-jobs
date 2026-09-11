import re
import time
import requests
from bs4 import BeautifulSoup
from datetime import date, datetime, timedelta, timezone

# 알리오가 막혀 재시도가 길어져도 실행 전체가 이 시간을 넘기지 않게 한다.
START = time.monotonic()
BUDGET = 900
KST = timezone(timedelta(hours=9))

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

# 클린아이 잡플러스(지방공기업) — 지방공공기관 채용정보
CE_BASE = "https://job.cleaneye.go.kr"
CE_LIST = f"{CE_BASE}/user/ypRecruitment.do"
CE_API = f"{CE_BASE}/user/selectYpRecruitment.do"
CE_FIELD_INFO_COMM = "700020"  # 모집분야 - 정보통신
CE_TYPE_REGULAR = "702001"     # 고용형태 - 일반정규직
CE_TYPE_PERMANENT = "702002"   # 고용형태 - 무기계약직
CE_CAREER_NEW = "703001"       # 채용구분 - 신입
CE_CAREER_BOTH = "703003"      # 채용구분 - 신입+경력
CE_STATUS_ONGOING = "709001"   # 진행중
CE_JOBTYPE = {"702001": "정규직", "702002": "무기계약직"}
CE_SIDO = {
    "007001": "서울", "007002": "부산", "007003": "대구", "007004": "인천",
    "007006": "대전", "007007": "울산", "007017": "세종", "007008": "경기",
    "007009": "강원", "007010": "충북", "007011": "충남", "007012": "전북",
    "007013": "전남광주", "007014": "경북", "007015": "경남", "007016": "제주",
}

# 나라일터(gojobs.go.kr) — 국가기관·지자체 공무원 채용
GJ_BASE = "https://www.gojobs.go.kr"
GJ_LIST = f"{GJ_BASE}/apmList_recruit.do?menuNo=401&mngrMenuYn=N"
GJ_VIEW = f"{GJ_BASE}/apmView_recruit.do"

# 공고 제목이 전산 계열인지 판정 (나라일터는 목록에 직렬 정보가 없어 제목으로만 판단한다).
GJ_IT = re.compile(
    r"(전산|정보통신|정보화|정보시스템|정보보안|정보기술|전산직|소프트웨어"
    r"|빅데이터|공공데이터|데이터|인공지능|사이버|전자계산"
    r"|(?<![A-Za-z])(?:IT|ICT|SW|AI)(?![A-Za-z]))",
    re.I,
)
# 정년이 보장되지 않거나 채용공고가 아닌 글은 제외한다.
GJ_SKIP = re.compile(
    r"(기간제|시간선택제|임기제|촉탁|합격자|결과\s*발표|최종\s*발표|명단|취소|연기|재공고\s*안내"
    r"|필기시험\s*장소|면접\s*일정|공고문\s*정정)"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Referer": LIST_URL,
}

# 모집분야명이 전산 계열인지 판정.
# 단독 "보안"/"개발"/"시스템"은 안전직·연구직·설비직 오탐이 많아 쓰지 않는다.
IT_FIELD = re.compile(
    r"(전산|정보통신|정보시스템|정보화|정보처리|정보보안|사이버보안|보안관제"
    r"|소프트웨어|디지털|빅데이터|데이터|인공지능|네트워크|통신"
    r"|시스템\s*운영|시스템\s*개발|개발운영|정보기술"
    # 한글·밑줄 옆에 붙은 약어는 \b 경계가 잡히지 않아(예: "_SW정책연구") 영문자 기준으로 판정한다.
    r"|(?<![A-Za-z])(?:IT|ICT|SW|AI|DX)(?![A-Za-z]))",
    re.I,
)

# 위 키워드가 걸려도 실제로는 전산직이 아닌 분야명. (예: "전기기계통신기사_기계")
# "무기계약직" 안의 "기계"에 걸리지 않도록 앞에 "무"가 오는 경우는 뺀다.
IT_FIELD_NOT = re.compile(r"((?<!무)기계|토목|건축|화공|간호|의무|약무|조리|미화|경비|운전|청원경찰)")

# 전산 분야라도 계약직·대체인력은 제외한다. 단 무기계약직은 정년이 보장되므로 남긴다.
FIELD_TEMPORARY = re.compile(r"((?<!무기)계약직|기간제|인턴|육아휴직|대체인력|단시간)")

# 제목만으로 전산과 무관함이 분명한 공고는 상세페이지를 열지 않고 건너뛴다.
SKIP_TITLE = re.compile(
    r"(간호사|간호직|간호조무|조리원|조리사|환경미화|미화원|경비원|운전원|전문의|의무직"
    r"|약사|임상병리|방사선사|물리치료|작업치료|사회복지사|청원경찰|장례|주차관리|치과위생)"
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


def request(session, url, data=None, tries=4):
    """알리오는 클라우드 IP를 간헐적으로 막아서, 실패하면 간격을 늘려가며 재시도한다.

    재시도가 요청마다 쌓이면 실행이 끝없이 길어지므로 전체 예산(BUDGET) 안에서만 기다린다.
    """
    for attempt in range(1, tries + 1):
        if time.monotonic() - START > BUDGET:
            raise requests.ConnectionError("전체 시간 예산 초과")
        try:
            if data is None:
                resp = session.get(url, timeout=30)
            else:
                resp = session.post(url, data=data, timeout=30)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return resp
        except requests.RequestException as e:
            if attempt == tries:
                raise
            wait = 15 * attempt
            print(f"  요청 실패 {attempt}/{tries} ({type(e).__name__}) — {wait}초 후 재시도")
            time.sleep(wait)


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

    it_fields = [p for p in positions
                 if IT_FIELD.search(p)
                 and not IT_FIELD_NOT.search(p)
                 and not FIELD_TEMPORARY.search(p)]
    if it_fields:
        it = "있음"
    elif positions:
        it = "없음"  # 모집분야가 공개돼 있는데 전산 계열이 하나도 없음
    else:
        it = "확인필요"

    return eng, major, it, it_fields


def fetch_list(session, max_pages=10):
    request(session, LIST_URL)
    items, seen = [], set()

    for page in range(1, max_pages + 1):
        # NCS "정보통신" 태그는 기관이 잘 안 붙여서(101건 중 16건만) 쓰지 않는다.
        # 대신 전체를 받아 상세페이지의 모집분야로 전산 여부를 판정한다.
        payload = [
            ("pageNo", str(page)),
            ("work_type", WORK_TYPE_REGULAR),
            ("work_type", WORK_TYPE_PERMANENT),
            ("career", CAREER_NEW),
            ("career", CAREER_BOTH),
            ("ing", STATUS_ONGOING),
        ]
        try:
            resp = request(session, LIST_URL, data=payload)
        except requests.RequestException as e:
            print(f"[목록 {page}p] 포기 ({type(e).__name__}) — 여기까지 수집한 걸로 진행")
            break
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
            if SKIP_TITLE.search(title):
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
            resp = request(session, job["link"], tries=2)
            fields, sections, positions = parse_detail(resp.text)
            eng, major, it, it_fields = judge(fields, sections, positions, job["title"])
            job.update(eng=eng, major=major, it=it, it_fields=it_fields,
                       edu=fields.get("학력정보", "-"))
        except Exception as e:
            print(f"  상세 조회 실패 ({job['org']}): {e}")
            job.update(eng="확인필요", major="언급없음", it="확인필요", it_fields=[], edu="-")

        if job["it"] == "없음":
            dropped.append(job)
            continue

        kept.append(job)
        tag = ", ".join(job["it_fields"])[:40] or "확인필요"
        print(f"  {job['org'][:16]:<17} 어학={job['eng']:<5} 전공={job['major']:<5} 분야={tag}")
        time.sleep(0.4)

    print(f"전산 분야 없어서 제외: {len(dropped)}건")
    return kept


def fetch_cleaneye():
    """클린아이 잡플러스(지방공기업) — 서울교통공사·도시공사·시설공단 등 지방공공기관."""
    session = requests.Session()
    session.headers.update({**HEADERS, "Referer": CE_LIST, "X-Requested-With": "XMLHttpRequest"})
    jobs, note = [], ""
    try:
        request(session, CE_LIST)
        query = {
            "entRecruitList[]": CE_FIELD_INFO_COMM,
            "jobTypeList[]": [CE_TYPE_REGULAR, CE_TYPE_PERMANENT],
            "employGbList[]": [CE_CAREER_NEW, CE_CAREER_BOTH],
            "status": CE_STATUS_ONGOING,
        }
        for page in range(1, 11):
            resp = request(session, CE_API, data={**query, "pageIndex": str(page)})
            rows = resp.json().get("list") or []
            print(f"[지방공기업 {page}p] 수신 {len(rows)}건")
            if not rows:
                break
            for row in rows:
                location = CE_SIDO.get(row.get("sidoCd", ""), "")
                if any(x in location for x in EXCLUDE_LOCATIONS):
                    continue
                jobs.append({
                    "title": clean(row.get("entTitle", "")),
                    "org": clean(row.get("entName", "")),
                    "location": location or "-",
                    "job_type": CE_JOBTYPE.get(row.get("jobType", ""), "-"),
                    "deadline": row.get("pubEndDate", "-"),
                    "link": (f"{CE_BASE}/user/ypCareersData.do?empyear={row.get('empyear')}"
                             f"&ypEntId={row.get('ypEntId')}&entSeq={row.get('entSeq')}"),
                    "source": "지방공기업",
                    # 클린아이는 상세 자격요건을 첨부 공고문에만 두는 곳이 많아 자동 판정을 하지 않는다.
                    "eng": "확인필요", "major": "언급없음", "it": "있음",
                    "it_fields": ["정보통신 분야"], "edu": "-",
                })
        if not jobs:
            note = latest_closed(session)
    except Exception as e:
        print(f"[지방공기업] 수집 실패 ({type(e).__name__}) — 알리오 결과만 사용")
        return jobs, "수집 실패"
    print(f"[지방공기업] 결과: {len(jobs)}건 {note}")
    return jobs, note


def latest_closed(session):
    """지방공기업 전산직이 0건일 때, 가장 최근에 마감된 공고를 찾아 상황을 설명한다."""
    try:
        resp = request(session, CE_API, data={
            "entRecruitList[]": CE_FIELD_INFO_COMM,
            "jobTypeList[]": [CE_TYPE_REGULAR, CE_TYPE_PERMANENT],
            "employGbList[]": [CE_CAREER_NEW, CE_CAREER_BOTH],
            "pageIndex": "1",
        })
        rows = resp.json().get("list") or []
        if not rows:
            return ""
        last = max(rows, key=lambda r: r.get("pubEndDate", ""))
        return f"가장 최근 공고는 {last['pubEndDate']} 마감 ({clean(last['entName'])})"
    except Exception:
        return ""


def fetch_alio():
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        jobs = fetch_list(session)
    except Exception as e:
        print(f"[알리오] 접속 실패 ({type(e).__name__}) — 지방공기업만으로 진행")
        return []
    print(f"목록 필터링 후: {len(jobs)}건 — 상세 확인 중")
    jobs = enrich(session, jobs)
    for job in jobs:
        job.setdefault("source", "알리오")
    return jobs


def fetch_gojobs(max_pages=12):
    """나라일터(gojobs.go.kr) — 국가기관·지자체 공무원 채용."""
    session = requests.Session()
    session.headers.update({**HEADERS, "Referer": GJ_LIST})
    jobs = []
    try:
        request(session, f"{GJ_BASE}/mainIndex.do")
        for page in range(1, max_pages + 1):
            resp = request(session, f"{GJ_LIST}&pageIndex={page}")
            tables = [t for t in BeautifulSoup(resp.text, "html.parser").select("table") if not t.get("class")]
            rows = tables[0].select("tbody tr") if tables else []
            if not rows:
                break
            for row in rows:
                cells = row.select("td")
                link = row.select_one("a[href]")
                if len(cells) < 5 or not link:
                    continue
                title = clean(cells[1].get_text(" "))
                org = clean(cells[2].get_text(" "))
                if not GJ_IT.search(title) or GJ_SKIP.search(title):
                    continue
                if any(x in org for x in EXCLUDE_LOCATIONS):
                    continue
                args = re.findall(r"'([^']*)'", link["href"])
                if len(args) < 2:
                    continue
                jobs.append({
                    "title": title,
                    "org": org,
                    "location": "-",
                    "job_type": "공무원",
                    "deadline": clean(cells[4].get_text(" ")),
                    "link": f"{GJ_VIEW}?menuNo=401&flag=U&searchJobsecode={args[0]}&empmnsn={args[1]}",
                    "source": "나라일터",
                    # 나라일터도 자격요건이 첨부 공고문에만 있어 자동 판정하지 않는다.
                    "eng": "확인필요", "major": "언급없음", "it": "있음",
                    "it_fields": ["공고 제목 기준"], "edu": "-",
                })
    except Exception as e:
        print(f"[나라일터] 수집 실패 ({type(e).__name__})")
    print(f"[나라일터] 결과: {len(jobs)}건")
    return jobs


def fetch_jobs():
    alio = fetch_alio()
    local, local_note = fetch_cleaneye()
    gov = fetch_gojobs()
    jobs = alio + local + gov
    sources = [
        ("알리오", "중앙 공공기관", len(alio), ""),
        ("지방공기업", "클린아이", len(local), local_note),
        ("나라일터", "공무원", len(gov), ""),
    ]

    penalty = {"없음": 0, "언급없음": 0, "무관": 0, "있음": 0,
               "평가반영": 2, "확인필요": 3, "제한있음": 3, "필수": 5}
    jobs.sort(key=lambda j: (penalty[j["eng"]] + penalty[j["major"]] + penalty[j["it"]], j["deadline"]))
    return jobs, sources


def deadline_info(text):
    """공고마다 마감일 표기가 달라서(26.09.22 / 2026-09-22) 날짜로 통일하고 D-day를 계산한다."""
    m = re.search(r"(\d{2,4})[.\-/](\d{1,2})[.\-/](\d{1,2})", text or "")
    if not m:
        return text or "-", None
    year, month, day = (int(x) for x in m.groups())
    if year < 100:
        year += 2000
    try:
        due = date(year, month, day)
    except ValueError:
        return text or "-", None
    return due.strftime("%Y.%m.%d"), (due - datetime.now(KST).date()).days


def build_html(jobs, sources):
    now = datetime.now(KST)
    eng_cls = {"없음": "ok", "평가반영": "warn", "확인필요": "warn", "필수": "bad"}
    maj_cls = {"무관": "ok", "언급없음": "ok", "제한있음": "bad"}
    src_cls = {"알리오": "alio", "지방공기업": "local", "나라일터": "gov"}
    safe = sum(1 for j in jobs if j["eng"] == "없음" and j["major"] != "제한있음")
    closing = sum(1 for j in jobs if (deadline_info(j["deadline"])[1] or 99) <= 7)

    source_html = "".join(
        f'<span class="chip {src_cls.get(name, "")}">'
        f'<i></i>{name} <b>{count}</b>'
        + (f'<em>{note}</em>' if note else "")
        + "</span>"
        for name, desc, count, note in sources
    )

    rows = []
    for job in jobs:
        due_text, days = deadline_info(job["deadline"])
        if days is None:
            dday, dcls = "", ""
        elif days < 0:
            dday, dcls = "마감", "gone"
        elif days == 0:
            dday, dcls = "오늘 마감", "urgent"
        else:
            dday, dcls = f"D-{days}", "urgent" if days <= 3 else ("soon" if days <= 7 else "")
        fields = " · ".join(job["it_fields"]) if job["it_fields"] else "전산 분야 확인 필요"
        rows.append(f"""
        <tr data-eng="{job['eng']}" data-major="{job['major']}">
          <td data-label="기관">
            <div class="org">{job['org']}</div>
            <span class="src {src_cls.get(job['source'], '')}">{job['source']}</span>
          </td>
          <td data-label="공고">
            <a href="{job['link']}" target="_blank" rel="noopener">{job['title']}</a>
            <div class="fields">{fields}</div>
          </td>
          <td data-label="지역">{job['location']}</td>
          <td data-label="어학"><span class="pill {eng_cls[job['eng']]}">{job['eng']}</span></td>
          <td data-label="전공"><span class="pill {maj_cls[job['major']]}">{job['major']}</span></td>
          <td data-label="마감">
            <div class="due">{due_text}</div>
            <span class="dday {dcls}">{dday}</span>
            <div class="meta">{job['job_type']} · {job['edu']}</div>
          </td>
        </tr>""")

    rows_html = "".join(rows) or '<tr><td colspan="6" class="empty">조건에 맞는 진행중인 공고가 없습니다.</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>공공기관 전산직 채용공고</title>
<style>
  :root {{
    --bg: #f4f6fb; --surface: #fff; --border: #e6e9f0; --text: #1c2333; --muted: #6b7382;
    --brand: #4f46e5; --brand2: #7c3aed; --shadow: 0 1px 3px rgba(20,25,45,.07), 0 8px 24px rgba(20,25,45,.05);
    --ok-bg: #dcfce7; --ok-fg: #15803d; --warn-bg: #fef3c7; --warn-fg: #a16207;
    --bad-bg: #ffe4e6; --bad-fg: #be123c;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #0e1016; --surface: #171b24; --border: #262c38; --text: #e8eaf0; --muted: #98a0b0;
      --shadow: 0 1px 3px rgba(0,0,0,.4);
      --ok-bg: #052e1a; --ok-fg: #4ade80; --warn-bg: #38260a; --warn-fg: #fbbf24;
      --bad-bg: #3d0d1b; --bad-fg: #fb7185;
    }}
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); line-height: 1.5;
         font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Malgun Gothic", sans-serif; }}
  header {{ background: linear-gradient(135deg, var(--brand), var(--brand2)); color: #fff; padding: 34px 24px 30px; }}
  .head-in {{ max-width: 1180px; margin: 0 auto; }}
  header h1 {{ font-size: 25px; font-weight: 800; letter-spacing: -.4px; }}
  header p {{ margin-top: 8px; font-size: 13.5px; opacity: .9; max-width: 760px; }}
  .wrap {{ max-width: 1180px; margin: -18px auto 40px; padding: 0 16px; }}
  .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(168px, 1fr)); gap: 12px; }}
  .stat {{ background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
          padding: 16px 18px; box-shadow: var(--shadow); }}
  .stat .n {{ font-size: 30px; font-weight: 800; letter-spacing: -1px; }}
  .stat .n.good {{ color: #16a34a; }}
  .stat .n.hot {{ color: #e11d48; }}
  .stat .n.sm {{ font-size: 16px; padding-top: 9px; }}
  .stat .l {{ font-size: 12px; color: var(--muted); margin-top: 3px; }}
  .panel {{ background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
           box-shadow: var(--shadow); margin-top: 14px; }}
  .panel-h {{ padding: 13px 18px; font-size: 12px; font-weight: 700; color: var(--muted);
             letter-spacing: .4px; border-bottom: 1px solid var(--border); }}
  .chips {{ padding: 13px 18px; display: flex; flex-wrap: wrap; gap: 9px; }}
  .chip {{ display: inline-flex; align-items: center; gap: 7px; font-size: 12.5px;
          background: var(--bg); border: 1px solid var(--border); border-radius: 999px; padding: 6px 13px; }}
  .chip i {{ width: 7px; height: 7px; border-radius: 50%; background: var(--muted); }}
  .chip.alio i {{ background: #4f46e5; }} .chip.local i {{ background: #a855f7; }} .chip.gov i {{ background: #10b981; }}
  .chip b {{ font-weight: 700; }}
  .chip em {{ font-style: normal; color: var(--muted); font-size: 11.5px; }}
  .tools {{ padding: 13px 18px; display: flex; flex-wrap: wrap; gap: 18px; font-size: 13px; }}
  .tools label {{ display: inline-flex; align-items: center; gap: 7px; cursor: pointer; user-select: none; }}
  .tablewrap {{ overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; min-width: 900px; }}
  th {{ position: sticky; top: 0; background: var(--surface); text-align: left; font-size: 11.5px;
       color: var(--muted); font-weight: 700; letter-spacing: .3px; padding: 12px 16px;
       border-bottom: 1px solid var(--border); }}
  td {{ padding: 15px 16px; border-bottom: 1px solid var(--border); font-size: 13.5px; vertical-align: top; }}
  tbody tr:last-child td {{ border-bottom: none; }}
  tbody tr:hover td {{ background: color-mix(in srgb, var(--brand) 4%, transparent); }}
  .org {{ font-weight: 600; white-space: nowrap; }}
  .src {{ display: inline-block; margin-top: 6px; padding: 2px 8px; border-radius: 999px;
         font-size: 10.5px; font-weight: 700; background: var(--bg); color: var(--muted); border: 1px solid var(--border); }}
  .src.alio {{ color: #4f46e5; }} .src.local {{ color: #9333ea; }} .src.gov {{ color: #059669; }}
  td a {{ color: var(--text); text-decoration: none; font-weight: 600; }}
  td a:hover {{ color: var(--brand); text-decoration: underline; }}
  .fields {{ margin-top: 6px; font-size: 11.5px; font-weight: 600; color: #16a34a; }}
  .pill {{ display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 11.5px;
          font-weight: 700; white-space: nowrap; }}
  .pill.ok {{ background: var(--ok-bg); color: var(--ok-fg); }}
  .pill.warn {{ background: var(--warn-bg); color: var(--warn-fg); }}
  .pill.bad {{ background: var(--bad-bg); color: var(--bad-fg); }}
  .due {{ font-weight: 600; white-space: nowrap; }}
  .dday {{ display: inline-block; margin-top: 4px; padding: 2px 9px; border-radius: 6px;
          font-size: 11.5px; font-weight: 800; background: var(--bg); color: var(--muted); }}
  .dday.soon {{ background: var(--warn-bg); color: var(--warn-fg); }}
  .dday.urgent {{ background: var(--bad-bg); color: var(--bad-fg); }}
  .dday.gone {{ opacity: .5; }}
  .meta {{ margin-top: 5px; font-size: 11px; color: var(--muted); white-space: nowrap; }}
  .empty {{ text-align: center; padding: 48px; color: var(--muted); }}
  .note {{ margin-top: 14px; font-size: 12px; color: var(--muted); line-height: 1.85; }}
  .note b {{ color: var(--text); }}
  footer {{ text-align: center; padding: 26px; font-size: 12px; color: var(--muted); }}
  @media (max-width: 760px) {{
    header {{ padding: 26px 18px 26px; }}
    header h1 {{ font-size: 20px; }}
    table {{ min-width: 0; }}
    thead {{ display: none; }}
    tbody tr {{ display: block; padding: 14px 16px; border-bottom: 1px solid var(--border); }}
    tbody td {{ display: flex; gap: 10px; border: none; padding: 4px 0; font-size: 13px; }}
    tbody td::before {{ content: attr(data-label); flex: 0 0 52px; color: var(--muted); font-size: 11.5px; padding-top: 2px; }}
    .org, .meta, .due {{ white-space: normal; }}
  }}
</style>
</head>
<body>
<header>
  <div class="head-in">
    <h1>공공기관 전산직 채용공고</h1>
    <p>정규직·무기계약직 · 신입 · 진행중 · 제주 제외 — 알리오 필터만 믿지 않고
       공고 본문의 <b>모집분야와 응시자격까지 읽어서</b> 걸러냈어. 하루 4번 자동 갱신.</p>
  </div>
</header>
<div class="wrap">
  <div class="stats">
    <div class="stat"><div class="n good">{safe}</div><div class="l">토익·전공 조건 없음</div></div>
    <div class="stat"><div class="n hot">{closing}</div><div class="l">일주일 내 마감</div></div>
    <div class="stat"><div class="n">{len(jobs)}</div><div class="l">전체 공고</div></div>
    <div class="stat"><div class="n sm">{now.strftime("%m월 %d일 %H:%M")}</div><div class="l">마지막 업데이트</div></div>
  </div>

  <div class="panel">
    <div class="panel-h">수집 현황</div>
    <div class="chips">{source_html}</div>
  </div>

  <div class="panel">
    <div class="tools">
      <label><input type="checkbox" id="hideEng" checked> 어학성적 <b>필수</b> 숨기기</label>
      <label><input type="checkbox" id="hideMajor" checked> 전공 <b>제한있음</b> 숨기기</label>
      <span id="count" style="color:var(--muted)"></span>
    </div>
    <div class="tablewrap">
      <table>
        <thead><tr>
          <th>기관</th><th>공고 / 전산 모집분야</th><th>지역</th><th>어학</th><th>전공</th><th>마감</th>
        </tr></thead>
        <tbody id="tbody">{rows_html}</tbody>
      </table>
    </div>
  </div>

  <p class="note">
    제목 아래 <b style="color:#16a34a">초록색 글씨</b>가 그 공고에서 실제로 뽑는 전산 계열 모집분야야. 전산 분야가 없는 공고는 목록에서 뺐어.<br>
    <b>어학 / 전공</b>은 공고의 <b>응시자격</b> 항목만 읽어 판정했어. <b>평가반영</b>은 지원자격은 아니지만 서류 점수에 반영되는 경우,
    <b>확인필요</b>는 자격요건이 첨부 공고문에만 있어 직접 봐야 하는 경우야 (지방공기업·나라일터가 대부분 여기 해당).<br>
    통합채용은 분야마다 조건이 달라 자동 판정이 틀릴 수 있으니, 지원 전엔 공고문 원본을 꼭 확인해.
  </p>
</div>
<footer>출처: 알리오 · 클린아이 잡플러스 · 나라일터 · GitHub Actions 자동 수집</footer>
<script>
  var he = document.getElementById('hideEng'), hm = document.getElementById('hideMajor');
  function apply() {{
    var shown = 0;
    document.querySelectorAll('#tbody tr[data-eng]').forEach(function (tr) {{
      var hide = (he.checked && tr.dataset.eng === '필수') || (hm.checked && tr.dataset.major === '제한있음');
      tr.hidden = hide;
      if (!hide) shown++;
    }});
    document.getElementById('count').textContent = shown + '건 표시 중';
  }}
  he.addEventListener('change', apply);
  hm.addEventListener('change', apply);
  apply();
</script>
</body>
</html>"""


if __name__ == "__main__":
    print("공고 수집 중...")
    jobs, sources = fetch_jobs()

    # 한 건도 못 가져왔으면 알리오가 죽은 것이므로, 빈 페이지로 덮어쓰지 않고 기존 사이트를 유지한다.
    if not jobs:
        raise SystemExit("수집 결과 0건 — 배포를 건너뛰고 기존 사이트를 유지한다")

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(build_html(jobs, sources))
    print(f"index.html 생성 완료 ({len(jobs)}건)")
