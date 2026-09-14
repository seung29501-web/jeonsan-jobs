import io
import re
import time
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
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

# ── 지원 가능 분야 판정 ────────────────────────────────────────────────────
# 전산직과 사무·행정 계열 둘 다 지원 대상. 나머지 현장·전문 직종은 제외한다.
IT_FIELD = re.compile(
    r"(전산|정보통신|정보시스템|정보화|정보처리|정보보안|사이버보안|보안관제"
    r"|소프트웨어|디지털|빅데이터|데이터|인공지능|네트워크"
    r"|시스템\s*운영|시스템\s*개발|개발운영|정보기술"
    # 한글·밑줄 옆에 붙은 약어는 \b 경계가 잡히지 않아(예: "_SW정책연구") 영문자 기준으로 판정한다.
    r"|(?<![A-Za-z])(?:IT|ICT|SW|AI|DX)(?![A-Za-z]))",
    re.I,
)
OFFICE_FIELD = re.compile(r"(사무|행정|경영|일반직|총무|기획|경영지원|고객지원|사무행정)")

# 위 키워드가 걸려도 대졸 비전공자가 지원할 수 없는 현장·전문 직종.
FIELD_NOT = re.compile(
    r"((?<!무)기계|토목|건축|화공|전기|설비|시설|산림|조경|환경|안전|방호"
    r"|간호|의무|약무|보건|의료|임상|방사선|물리치료|조리|미화|경비|운전|청원경찰"
    r"|사서|상담|사회복지|교원|교수|연구위원|박사)"
)

# 전산·사무 분야라도 계약직·대체인력은 제외한다. 단 무기계약직은 정년이 보장되므로 남긴다.
FIELD_TEMPORARY = re.compile(r"((?<!무기)계약직|기간제|인턴|육아휴직|대체인력|단시간|시간선택)")

# 제목만으로 지원 대상이 아님이 분명한 공고는 상세페이지를 열지 않고 건너뛴다.
SKIP_TITLE = re.compile(
    r"(간호사|간호직|간호조무|조리원|조리사|환경미화|미화원|경비원|운전원|전문의|의무직"
    r"|약사|임상병리|방사선사|물리치료|작업치료|사회복지사|청원경찰|장례|주차관리|치과위생"
    r"|의사|한의사|수의사|영양사|보육교사|사서직|교원|교수|초빙)"
)

# ── 응시자격 판정 ──────────────────────────────────────────────────────────
ENG_REQ = re.compile(
    r"(공인\s*어학성적|유효한?\s*어학성적|어학성적\s*기준|어학성적\s*보유자|영어능력평가"
    r"|(?:TOEIC|TOEFL|TEPS|OPIc|토익|토플|텝스|오픽)[^\n]{0,15}\d{2,4}\s*점?\s*이상"
    r"|(?:TOEIC|TOEFL|TEPS)\s*\d{3}"
    r"|(?:어학|영어)[^\n]{0,25}\d{3}\s*점\s*이상)",
    re.I,
)
ENG_EVAL = re.compile(r"어학[^\n]{0,25}(환산|배점|계량|가점|반영|평가)")
ENG_NONE = re.compile(r"(어학|영어|외국어)[^\n]{0,20}(제한\s*없|무관|불필요)")
ENG_ANY = re.compile(r"어학|토익|TOEIC|TEPS|OPIc", re.I)

# 대졸자가 지원할 수 없는 학력 요건
EDU_OPEN = re.compile(r"(학력\s*무관|학력\s*제한\s*없|고졸|대졸|초대졸|전문대|학사)")
EDU_GRAD_ONLY = re.compile(r"(박사학위\s*(?:이상\s*)?(?:소지|취득|보유)|박사\s*이상"
                           r"|석사학위\s*(?:이상\s*)?(?:소지|취득|보유)|석사\s*이상)")

MAJ_NONE = re.compile(r"전공[^\n]{0,20}(제한\s*없|무관|별도\s*제한\s*없)")
MAJ_REQ = re.compile(
    r"((?:해당|관련)\s*(?:분야\s*)?전공자|전공\s*분야\s*해당자"
    r"|전공자에?\s*한(?:함|하여)|(?:컴퓨터공학|전산학|소프트웨어)\s*(?:등\s*)?(?:관련\s*)?전공)"
)

# 특정 지역 출신 우대·제한 조항 (대전 거주자 기준 유불리가 갈려 표시만 한다)
REGION_TALENT = re.compile(
    r"((?:비수도권|수도권|서울|부산|대구|인천|광주|대전|울산|세종|경기|강원"
    r"|충청|충북|충남|전라|전북|전남|경상|경북|경남|제주)[^\n]{0,8}?)\s*지역\s*인재"
)

# ── 모집분야별 지원 가능 여부 ──────────────────────────────────────────────
# 통합채용은 공고 전체가 "학력무관"이어도 분야마다 자격이 다르다.
# 분야명에 붙은 직급(4급, 5급가, 공무직 …)을 응시자격 본문에서 찾아 그 분야 조건만 본다.
GRADE_TOKEN = re.compile(r"(\d+급(?:가|나|다)?|공무직|무기계약직|일반직|전문직)")
CAREER_REQ = re.compile(r"(\d+\s*년\s*이상[^\n]{0,25}(?:경력|경험)"
                        r"|경력이\s*있는\s*자|경력자로서|경력\s*\d+\s*년\s*이상"
                        r"|실무\s*경력\s*\d+\s*년|관련\s*경력\s*\d+\s*년)")
PHD_ROLE = re.compile(r"(부연구위원|연구위원|전임연구원|책임연구원|교원|교수|초빙|석좌|박사급|수석연구)")

# 지원자가 보유한 자격증. 우대사항·지원자격에 있으면 목록 위로 올린다.
CERT_BONUS = re.compile(r"(정보처리\s*기사|빅데이터\s*분석\s*기사|정보처리기사|빅데이터분석기사)")


# 특정 자격을 갖춘 사람만 지원할 수 있는 제한경쟁 분야. 일반 대졸 지원자는 낼 수 없다.
RESTRICTED_FIELD = re.compile(
    r"(장애인|보훈|국가유공|취업지원|제대군인"
    r"|고졸|특성화고|마이스터|학교장\s*추천"
    r"|경력단절|북한이탈|새터민|다문화|외국인\s*전형)"
)


def eligible_field(name):
    """모집분야명이 지원 대상(전산 또는 사무·행정)인지."""
    if FIELD_NOT.search(name) or FIELD_TEMPORARY.search(name):
        return False
    if RESTRICTED_FIELD.search(name):
        return False
    return bool(IT_FIELD.search(name) or OFFICE_FIELD.search(name))


def field_blocker(name, qual):
    """모집분야 하나가 신입·대졸 지원자에게 막혀 있으면 그 사유를 돌려준다."""
    if PHD_ROLE.search(name):
        return "박사급 직위"
    grades = set(GRADE_TOKEN.findall(name))
    for line in qual.split("\n"):
        if grades and not any(g in line for g in grades):
            continue
        if not grades:
            continue
        if CAREER_REQ.search(line):
            return "경력 필요"
        if EDU_GRAD_ONLY.search(line):
            return "석·박사만"
    return ""


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


def judge(fields, sections, positions, title, notice=""):
    """공고 하나를 판정해 결과를 dict로 돌려준다.

    통합채용은 공고 전체가 "학력·전공 제한 없음"이어도 분야마다 조건이 달라서,
    지원 가능한 분야 각각에 대해 경력·학위 요건을 따로 확인한다.
    상세페이지 요약에 없고 첨부 공고문에만 적힌 어학 기준도 있어 PDF 본문까지 합쳐 본다.
    """
    qual = sections.get("응시자격", "") or "\n".join(sections.values())
    edu_field = fields.get("학력정보", "")
    basis = "\n".join([qual, edu_field, notice])

    if ENG_REQ.search(basis):
        eng = "필수"
    elif ENG_EVAL.search(basis):
        eng = "평가반영"
    elif ENG_NONE.search(basis):
        eng = "없음"
    elif ENG_ANY.search(basis):
        eng = "확인필요"
    else:
        eng = "없음"

    # 통합공고는 "전공 제한 없음"과 특정 분야의 전공 요건이 함께 적힌다.
    # 둘 다 있으면 전공을 안 보는 분야가 존재한다는 뜻이므로 "제한 없음" 쪽을 따른다.
    if MAJ_NONE.search(basis):
        major = "무관"
    elif MAJ_REQ.search(qual):
        major = "제한있음"
    else:
        major = "언급없음"

    # 학력도 같다. 알리오 학력정보에 학력무관·대졸이 섞여 있으면 대졸이 지원할 분야가 있다.
    # (예: "학력무관,석사,박사" — 석·박사는 연구직 요건이고 일반직은 학력무관)
    if EDU_OPEN.search(edu_field):
        edu = "무관"
    elif edu_field in ("박사", "석사", "석사,박사") or EDU_GRAD_ONLY.search(qual):
        edu = "석·박사만"
    elif EDU_OPEN.search(qual):
        edu = "무관"
    else:
        edu = "확인필요"

    candidates = [x for x in positions if eligible_field(x)]
    open_fields, blocked = [], []
    for name in candidates:
        why = field_blocker(name, qual)
        if why:
            blocked.append(f"{name[:26]} → {why}")
        else:
            open_fields.append(name)

    if open_fields:
        fit = "있음"
    elif candidates:
        fit = "막힘"      # 지원 가능 분야는 있으나 경력·학위 요건에 걸림
    elif positions:
        fit = "없음"      # 모집분야가 공개돼 있는데 전산·사무 계열이 하나도 없음
    else:
        fit = "확인필요"

    # 한 공고에 전산과 사무가 같이 있으면 두 분류에 모두 들어간다.
    kinds = []
    if any(IT_FIELD.search(x) for x in open_fields):
        kinds.append("IT")
    if any(OFFICE_FIELD.search(x) and not IT_FIELD.search(x) for x in open_fields):
        kinds.append("OFFICE")

    regions = sorted({clean(m.group(1)) for m in REGION_TALENT.finditer(basis)})
    return {
        "eng": eng, "major": major, "edu": edu, "fit": fit, "kinds": kinds or ["OFFICE"],
        "it_fields": open_fields, "blocked": blocked,
        "region": ", ".join(r + " 지역인재" for r in regions[:2]),
        "cert": bool(CERT_BONUS.search(basis)),
        "edu_raw": edu_field or "-",
    }



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


def notice_text(session, html, max_pages=30):
    """첨부된 채용 공고문 PDF를 받아 본문 텍스트를 뽑는다.

    알리오 상세페이지의 응시자격은 요약이라 "학력·전공 제한 없음"만 적어두고
    실제 어학 기준·지역인재 조항은 공고문 PDF에만 있는 경우가 많다.
    """
    soup = BeautifulSoup(html, "html.parser")
    target = None
    for a in soup.select("a[href*='download.json']"):
        name = a.get_text(strip=True)
        if not name.lower().endswith(".pdf"):
            continue
        if "공고" in name:
            target = a["href"]
            break
        target = target or a["href"]
    if not target:
        return ""

    try:
        resp = session.get(target, timeout=60)
        if not resp.content.startswith(b"%PDF"):
            return ""
        reader = PdfReader(io.BytesIO(resp.content))
        pages = (page.extract_text() or "" for page in reader.pages[:max_pages])
        return re.sub(r"[ \t]+", " ", "\n".join(pages))
    except Exception as e:
        print(f"    공고문 PDF 읽기 실패: {type(e).__name__}")
        return ""


def enrich(session, jobs):
    kept, skipped = [], {}

    def drop(reason, job=None):
        skipped[reason] = skipped.get(reason, 0) + 1
        if job:
            print(f"  {job['org'][:16]:<17} 제외 — {reason}")

    for job in jobs:
        try:
            resp = request(session, job["link"], tries=2)
            fields, sections, positions = parse_detail(resp.text)

            # 지원 가능 분야가 아예 없는 공고까지 PDF를 받으면 느려서, 먼저 분야만 훑고 거른다.
            if judge(fields, sections, positions, job["title"])["fit"] == "없음":
                drop("전산·사무 분야 없음")
                continue

            job.update(judge(fields, sections, positions, job["title"],
                             notice_text(session, resp.text)))
        except Exception as e:
            print(f"  상세 조회 실패 ({job['org']}): {e}")
            job.update(eng="확인필요", major="언급없음", edu="확인필요", fit="확인필요",
                       it_fields=[], blocked=[], region="", cert=False, edu_raw="-", kinds=["IT"])

        # 요청한 조건에 어긋나는 공고는 목록에서 뺀다.
        if job["fit"] == "막힘":
            drop("경력·학위 요건", job)
        elif job["edu"] == "석·박사만":
            drop("석·박사만 지원 가능", job)
        elif job["major"] == "제한있음":
            drop("전공 제한 있음", job)
        elif job["eng"] in ("필수", "평가반영"):
            drop(f"어학 {job['eng']}", job)
        else:
            kept.append(job)
            mark = "★" if job["cert"] else " "
            tag = ", ".join(job["it_fields"])[:34] or "확인필요"
            extra = f" 지역={job['region']}" if job["region"] else ""
            print(f" {mark}{job['org'][:16]:<17} 학력={job['edu']:<5} 전공={job['major']:<5} "
                  f"분야={tag}{extra}")
        time.sleep(0.4)

    print("제외: " + ", ".join(f"{k} {v}건" for k, v in sorted(skipped.items())))
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
                    "eng": "확인필요", "major": "언급없음", "fit": "확인필요",
                    "it_fields": ["정보통신 분야"], "edu": "확인필요", "region": "",
                    "edu_raw": "-", "blocked": [], "cert": False, "kinds": ["IT"],
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
                    "eng": "확인필요", "major": "언급없음", "fit": "확인필요",
                    "it_fields": ["공고 제목 기준"], "edu": "확인필요", "region": "",
                    "edu_raw": "-", "blocked": [], "cert": False, "kinds": ["IT"],
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

    # 보유 자격증이 우대사항에 있는 공고를 맨 위로, 그다음 마감이 임박한 순서로.
    jobs.sort(key=lambda j: (not j["cert"], deadline_info(j["deadline"])[1] if
                             deadline_info(j["deadline"])[1] is not None else 999))

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
    edu_cls = {"무관": "ok", "확인필요": "warn", "석·박사만": "bad"}
    safe = sum(1 for j in jobs if j["cert"])
    n_it = sum(1 for j in jobs if "IT" in j["kinds"])
    n_office = sum(1 for j in jobs if "OFFICE" in j["kinds"])
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
        <tr data-eng="{job['eng']}" data-edu="{job['edu']}" data-kind="{' '.join(job['kinds'])}">
          <td data-label="기관">
            <div class="org">{job['org']}</div>
            <span class="src {src_cls.get(job['source'], '')}">{job['source']}</span>
          </td>
          <td data-label="공고">
            <a href="{job['link']}" target="_blank" rel="noopener">{job['title']}</a>
            {'<span class="cert">정보처리·빅데이터 우대</span>' if job['cert'] else ''}
            <div class="fields">{fields}</div>
          </td>
          <td data-label="지역">{job['location']}</td>
          <td data-label="어학"><span class="pill {eng_cls[job['eng']]}">{job['eng']}</span></td>
          <td data-label="전공"><span class="pill {maj_cls[job['major']]}">{job['major']}</span></td>
          <td data-label="학력">
            <span class="pill {edu_cls.get(job['edu'], 'warn')}">{job['edu']}</span>
            {f'<div class="region">{job["region"]}</div>' if job["region"] else ''}
          </td>
          <td data-label="마감">
            <div class="due">{due_text}</div>
            <span class="dday {dcls}">{dday}</span>
            <div class="meta">{job['job_type']}</div>
          </td>
        </tr>""")

    rows_html = "".join(rows) or '<tr><td colspan="7" class="empty">조건에 맞는 진행중인 공고가 없습니다.</td></tr>'

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
  .tabs {{ display: flex; gap: 6px; padding: 12px 14px 0; flex-wrap: wrap; }}
  .tab {{ border: 1px solid var(--border); background: var(--surface); color: var(--muted);
         border-radius: 999px; padding: 7px 15px; font-size: 13px; font-weight: 600;
         cursor: pointer; font-family: inherit; }}
  .tab b {{ margin-left: 5px; font-weight: 800; }}
  .tab:hover {{ border-color: var(--brand); color: var(--brand); }}
  .tab.on {{ background: var(--brand); border-color: var(--brand); color: #fff; }}
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
  .cert {{ display: inline-block; margin-left: 6px; padding: 2px 8px; border-radius: 999px;
          font-size: 10.5px; font-weight: 800; background: var(--ok-bg); color: var(--ok-fg); }}
  .region {{ margin-top: 5px; font-size: 10.5px; color: var(--warn-fg); font-weight: 700; }}
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
    <p>전공무관 · 대졸/학력무관 · 어학 안 봄 · 신입 · 정규직/무기계약직 · 제주 제외<br>
       공고 본문과 <b>첨부 공고문 PDF까지 읽어서</b> 조건에 맞는 것만 남겼어. 하루 4번 자동 갱신.</p>
  </div>
</header>
<div class="wrap">
  <div class="stats">
    <div class="stat"><div class="n good">{safe}</div><div class="l">내 자격증 우대</div></div>
    <div class="stat"><div class="n hot">{closing}</div><div class="l">일주일 내 마감</div></div>
    <div class="stat"><div class="n">{len(jobs)}</div><div class="l">전체 공고</div></div>
    <div class="stat"><div class="n sm">{now.strftime("%m월 %d일 %H:%M")}</div><div class="l">마지막 업데이트</div></div>
  </div>

  <div class="panel">
    <div class="panel-h">수집 현황</div>
    <div class="chips">{source_html}</div>
  </div>

  <div class="panel">
    <div class="tabs">
      <button class="tab on" data-k="ALL">전체 <b>{len(jobs)}</b></button>
      <button class="tab" data-k="IT">전산 · IT <b>{n_it}</b></button>
      <button class="tab" data-k="OFFICE">사무 · 행정 <b>{n_office}</b></button>
    </div>
    <div class="tools">
      <label><input type="checkbox" id="hideEng"> 어학 <b>확인필요</b>도 숨기기</label>
      <label><input type="checkbox" id="hideMajor"> 학력 <b>확인필요</b>도 숨기기</label>
      <span id="count" style="color:var(--muted)"></span>
    </div>
    <div class="tablewrap">
      <table>
        <thead><tr>
          <th>기관</th><th>공고 / 전산 모집분야</th><th>지역</th><th>어학</th><th>전공</th><th>학력</th><th>마감</th>
        </tr></thead>
        <tbody id="tbody">{rows_html}</tbody>
      </table>
    </div>
  </div>

  <p class="note">
    제목 아래 <b style="color:#16a34a">초록색 글씨</b>가 그 공고에서 실제로 뽑는 전산 계열 모집분야야. 전산 분야가 없는 공고는 목록에서 뺐어.<br>
    <b>어학 / 전공</b>은 공고의 <b>응시자격</b> 항목만 읽어 판정했어. <b>평가반영</b>은 지원자격은 아니지만 서류 점수에 반영되는 경우,
    <b>확인필요</b>는 자동 판정이 어려워 직접 봐야 하는 경우야 (지방공기업·나라일터가 대부분 여기 해당).<br>
    알리오 공고는 <b>첨부된 채용 공고문 PDF까지 내려받아</b> 어학 기준·학위 요건·지역인재 조항을 찾아봤어. 석사·박사만 지원할 수 있는 공고는 아예 목록에서 뺐고, 특정 지역 출신을 우대하는 조항이 있으면 학력 칸 아래에 표시했어.<br>
    통합채용은 분야마다 조건이 달라 자동 판정이 틀릴 수 있으니, 지원 전엔 공고문 원본을 꼭 확인해.
  </p>
</div>
<footer>출처: 알리오 · 클린아이 잡플러스 · 나라일터 · GitHub Actions 자동 수집</footer>
<script>
  var he = document.getElementById('hideEng'), hm = document.getElementById('hideMajor');
  var kind = 'ALL';
  function apply() {{
    var shown = 0;
    document.querySelectorAll('#tbody tr[data-eng]').forEach(function (tr) {{
      var kinds = (tr.dataset.kind || '').split(' ');
      var hide = (kind !== 'ALL' && kinds.indexOf(kind) < 0)
              || (he.checked && tr.dataset.eng === '확인필요')
              || (hm.checked && tr.dataset.edu === '확인필요');
      tr.hidden = hide;
      if (!hide) shown++;
    }});
    document.getElementById('count').textContent = shown + '건 표시 중';
  }}
  document.querySelectorAll('.tab').forEach(function (btn) {{
    btn.addEventListener('click', function () {{
      document.querySelectorAll('.tab').forEach(function (b) {{ b.classList.remove('on'); }});
      btn.classList.add('on');
      kind = btn.dataset.k;
      apply();
    }});
  }});
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
