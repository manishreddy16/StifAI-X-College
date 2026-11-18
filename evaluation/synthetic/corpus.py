"""Deterministic synthetic corpus + synthetic ground truth (fictional institute).

The documents are built into a real ``chunks.jsonl`` with the project's own
chunker (``ingestion.build_fast_index.build_index``), into a temporary
directory, so chunk shapes (1800 chars, 250 overlap, exact-duplicate skipping,
record fields) match what production data looks like.

SYNTHETIC GROUND TRUTH: expected sources were authored together with the
documents. They were written AFTER the weaknesses in docs/BACKEND_RETRIEVAL_AUDIT.md
were identified, so this set demonstrates that identified defect classes are
fixed; it is NOT an estimate of accuracy on the real college index.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

BASE = "https://example.test"

NAV = ("Home | About Us | Academics | Admissions | Examination Cell | Campus Life | "
       "Fresher's Fest | Placements | Contact Us | Quick Links | Login")
FOOTER = "Copyright Northfield Institute of Technology. Privacy Policy | Sitemap | Careers"

# Generic filler that deliberately avoids every topic word used in the queries.
_FILLER = (
    "The institute encourages a culture of curiosity and teamwork across all programmes. "
    "Seminar rooms, open lawns and quiet corners give people space to read and to talk. "
    "Visitors are welcome on working days between the opening and closing bells. "
    "Committees meet regularly to review progress and to plan the coming year. "
    "Notices are displayed on boards near the main corridor and in the central quadrangle. "
)


def _pad(n: int) -> str:
    return (_FILLER * n).strip()


@dataclass(frozen=True)
class Doc:
    path: str
    title: str
    body: str
    content_type: str = "text/html"
    verification_status: str = "NEEDS_VERIFICATION"

    @property
    def url(self) -> str:
        return BASE + self.path


def _page(body: str, pad: int = 0) -> str:
    return f"{NAV}\n{body}\n{_pad(pad) if pad else ''}\n{FOOTER}".replace("\n\n\n", "\n\n")


_ADMISSIONS_BODY = (
    "Admission process. Candidates are admitted through the state entrance test followed by "
    "web counselling. A limited number of seats are filled under the management quota as per "
    "government norms. Lateral entry into the second year is open to diploma holders through a "
    "separate entrance test. Merit lists are published on the notice board."
)

DOCS: list[Doc] = [
    Doc("/about", "About the Institute", _page("Northfield Institute of Technology was founded as a small "
        "engineering school and has grown into a multi-branch institute. Vision and mission statements "
        "are displayed in the main hall.", 3)),
    Doc("/admissions", "Admissions", _page(_ADMISSIONS_BODY, 2), verification_status="VERIFIED"),
    Doc("/admissions?print=1", "Admissions", _page("Printer-friendly version. " + _ADMISSIONS_BODY, 2)),
    Doc("/admissions/management-quota", "Management Quota Admissions", _page(
        "Management quota seats are allotted on merit among applicants who register with the office. "
        "The management quota application opens after the counselling schedule is announced. "
        "Applicants must submit the management quota form with the required certificates.", 2)),
    Doc("/about/governance", "Governing Body", _page(
        "The management committee meets every quarter. Reservation policy follows the quota prescribed "
        "by the government. The management also reviews budgets and appoints the principal.", 3)),
    Doc("/admissions/lateral-entry", "Lateral Entry", _page(
        "Lateral entry applicants join the second year directly. Eligible candidates hold a diploma "
        "in a related branch. Lateral entry seats are limited and filled by an entrance test.", 2)),
    Doc("/programmes/btech", "B.Tech Programmes", _page(
        "The B.Tech programme runs for four years across eight semesters. Eligibility for B.Tech is a "
        "pass in the higher secondary examination with Mathematics, Physics and Chemistry. The B.Tech "
        "branches are Computer Science and Engineering, Electronics and Communication Engineering, "
        "Electrical and Electronics Engineering, Mechanical Engineering and Civil Engineering.", 3)),
    Doc("/programmes/mtech", "M.Tech Programmes", _page(
        "The M.Tech programme runs for two years across four semesters. Eligibility for M.Tech is a "
        "bachelor's degree in a related branch with a valid graduate aptitude score. M.Tech "
        "specialisations include VLSI Design, Thermal Engineering and Structural Engineering.", 3)),
    Doc("/programmes/mba", "MBA Programme", _page(
        "The MBA programme is a two year full time course in management studies with specialisations "
        "in finance and marketing.", 3)),
    Doc("/departments/cse", "Department of Computer Science and Engineering", _page(
        "The Computer Science and Engineering department has laboratories for programming, networks "
        "and data analysis. Faculty guide student projects in software engineering and machine "
        "learning. The department admits one hundred and eighty students every year.", 3)),
    Doc("/departments/ece", "Department of Electronics and Communication Engineering", _page(
        "The Electronics and Communication Engineering department runs laboratories for circuits, "
        "microwave engineering and embedded systems. Students build working prototypes in the "
        "final year.", 3)),
    Doc("/departments/eee", "Department of Electrical and Electronics Engineering", _page(
        "The Electrical and Electronics Engineering department covers power systems, machines and "
        "control. Laboratories include a high voltage lab and a power electronics lab.", 3)),
    Doc("/departments/mech", "Department of Mechanical Engineering", _page(
        "The Mechanical Engineering department offers thermal and design streams. The Head of "
        "Department is Prof. R. Sample. Workshops include machining, welding and a foundry.", 3)),
    Doc("/departments/civil", "Department of Civil Engineering", _page(
        "The Civil Engineering department has surveying, concrete and geotechnical laboratories.", 3)),
    Doc("/fees/structure", "Fee Structure", _page(
        "Tuition fee per semester (synthetic figures for testing): Semester 1: 40000. Semester 2: 40000. "
        "Semester 3: 42000. Semester 4: 42000. The fee must be paid before the semester registration "
        "deadline. Late payment attracts a penalty.", 2), verification_status="VERIFIED"),
    Doc("/fees/structure?print=1", "Fee Structure", _page(
        "Printer-friendly version. Tuition fee per semester (synthetic figures for testing): Semester 1: "
        "40000. Semester 2: 40000. Semester 3: 42000. Semester 4: 42000. The fee must be paid before "
        "the semester registration deadline. Late payment attracts a penalty.", 2)),
    Doc("/fees/scholarships", "Scholarship", _page(
        "A merit scholarship is awarded to the top rankers of each branch. The scholarship covers a "
        "part of the tuition. Students apply for the scholarship through the student office after "
        "results are announced.", 2)),
    Doc("/hostel/fee", "Hostel Fee", _page(
        "The hostel fee for the academic year covers a shared room and the mess. The hostel fee is "
        "collected in two instalments. A refundable caution deposit is collected with the first "
        "instalment.", 2)),
    Doc("/hostel/facilities", "Hostel Facility", _page(
        "The hostel facility includes a dining mess, laundry, reading room and wireless internet. "
        "A visiting room is available for guardians. Round the clock security is provided.", 2)),
    Doc("/hostel/rules", "Hostel Rules and Regulations", _page(
        "Residents must return to the hostel before the gate closing time. Visitors are not allowed "
        "in rooms. Misuse of facilities results in disciplinary action.", 2)),
    Doc("/transport", "Transport", _page(
        "College buses run on fixed routes from the city centre and the railway station. Pass "
        "holders board at designated stops. Timings change during examinations.", 2)),
    Doc("/library", "Central Library", _page(
        "The library facility is open from morning to evening on working days. Members may borrow "
        "books for fifteen days. Journals and e-resources are available in the digital section.", 2)),
    Doc("/placements", "Training and Placement Cell", _page(
        "The Training and Placement Cell organises campus drives and aptitude training. Recruiters "
        "from software, core engineering and service companies visit the campus every year.", 2)),
    Doc("/placements/statistics-2023-24", "Placement Statistics 2023-24", _page(
        "Placement statistics for 2023-24 (synthetic figures for testing). Students placed: 410. "
        "Highest package: 18 LPA. Average package: 5 LPA. Total recruiters: 62.", 2)),
    Doc("/placements/stories", "Placement Stories", _page(
        "Placement stories from alumni describe interview rounds and preparation tips. One student "
        "recalls a group discussion round followed by a technical interview.", 3)),
    Doc("/examinations/regulations", "Examination Regulations", _page(
        "A minimum attendance of seventy five percent is required to appear for the semester "
        "examination. Grading follows a ten point scale. Malpractice is reported to the "
        "examination committee.", 3)),
    Doc("/examinations/revaluation", "Revaluation and Recounting", _page(
        "Students may apply for revaluation of answer scripts within ten days of result "
        "announcement by paying the prescribed charge.", 2)),
    Doc("/examinations/calendar.pdf", "Academic Calendar 2024-25", (
        "Academic Calendar 2024-25. Commencement of classes. First internal test. Semester "
        "examinations. Vacation. " + _pad(2)), content_type="application/pdf"),
    Doc("/syllabus/btech-cse.pdf", "B.Tech CSE Syllabus", (
        "B.Tech Computer Science and Engineering course structure and syllabus. Semester 1: "
        "Mathematics, Physics, Programming. Semester 2: Data Structures, Chemistry. Elective: "
        "Professional Ethics and Placement Readiness. Fee payment and admission are not covered "
        "in this syllabus document. " + _pad(4)), content_type="application/pdf"),
    Doc("/syllabus/mtech-vlsi.pdf", "M.Tech VLSI Syllabus", (
        "M.Tech VLSI Design course structure and syllabus. Semester 1: Digital Design, Analog "
        "Circuits. Semester 2: Physical Design, Testing. " + _pad(4)), content_type="application/pdf"),
    Doc("/campus/anti-ragging", "Anti-Ragging Committee", _page(
        "Ragging is prohibited and punishable. Complaints are received by the committee and acted "
        "on promptly. A helpline poster is displayed in every block.", 2)),
    Doc("/campus/grievance", "Grievance Redressal Cell", _page(
        "Students and staff may submit a grievance in writing to the cell. The cell acknowledges "
        "each grievance and resolves it within thirty days.", 2)),
    Doc("/campus/sports", "Sports and Clubs", _page(
        "Playgrounds for cricket, football and basketball are open to students. Technical, "
        "literary and cultural clubs organise events through the year.", 3)),
    Doc("/research/centres", "Research Centres", _page(
        "Research centres focus on renewable energy and embedded systems. Doctoral scholars "
        "work under guides listed in each department.", 3)),
    Doc("/faculty/directory", "Faculty Directory", _page(
        "Faculty directory. Prof. R. Sample, Mechanical Engineering. Dr. T. Example, Computer "
        "Science and Engineering. Dr. K. Placeholder, Civil Engineering.", 2)),
    Doc("/news/annual-day", "Annual Day Celebrations", _page(
        "The annual day was celebrated with cultural programmes, prize distribution and a chief "
        "guest address.", 4)),
    # Hindi / Telugu pages (simple vocabulary, authored for tokenizer tests only).
    Doc("/hi/hostel", "छात्रावास शुल्क", _page(
        "छात्रावास शुल्क और सुविधाएँ। छात्रावास शुल्क दो किस्तों में जमा किया जाता है।", 0)),
    Doc("/hi/admissions", "प्रवेश प्रक्रिया", _page(
        "प्रवेश प्रक्रिया परामर्श के माध्यम से होती है। आवेदन की अंतिम तिथि सूचना पट पर दी जाती है।", 0)),
    Doc("/te/hostel", "హాస్టల్ ఫీజు", _page(
        "హాస్టల్ ఫీజు రెండు వాయిదాలలో చెల్లించాలి. హాస్టల్ సౌకర్యాలు విద్యార్థులకు అందుబాటులో ఉన్నాయి.", 0)),
    Doc("/te/admissions", "ప్రవేశాలు", _page(
        "ప్రవేశాలు కౌన్సెలింగ్ ద్వారా జరుగుతాయి. దరఖాస్తు చివరి తేదీ నోటీసు బోర్డులో ఉంటుంది.", 0)),
]


def _generated_distractors(seed: int = 20260101) -> list[Doc]:
    """Deterministic distractor pages (news, faculty, courses) to give BM25 a realistic
    vocabulary distribution. They never contain the answer to a benchmark query."""
    import random

    rng = random.Random(seed)
    depts = ["Computer Science and Engineering", "Electronics and Communication Engineering",
             "Mechanical Engineering", "Civil Engineering", "Electrical and Electronics Engineering"]
    topics = ["robotics", "signal processing", "thermodynamics", "structural analysis", "databases",
              "compilers", "control systems", "fluid mechanics", "wireless networks", "machine design"]
    verbs = ["presented a paper on", "organised a workshop on", "delivered a talk about",
             "led a student project in", "visited an industry unit working on"]
    common = ["students", "department", "laboratory", "semester", "programme", "guest lecture",
              "examination", "project", "seminar", "faculty"]
    docs: list[Doc] = []
    for i in range(36):
        dept, topic, verb = rng.choice(depts), rng.choice(topics), rng.choice(verbs)
        words = " ".join(rng.choice(common) for _ in range(12))
        docs.append(Doc(f"/news/item-{i:02d}", f"News: {topic.title()} update {i}", _page(
            f"The {dept} department {verb} {topic}. Participating {words}. " + _pad(rng.randint(2, 7)))))
    for i in range(24):
        dept, topic = rng.choice(depts), rng.choice(topics)
        docs.append(Doc(f"/faculty/profile-{i:02d}", f"Faculty Profile {i}: Dr. Person{i}", _page(
            f"Dr. Person{i} teaches in the {dept} department. Research interests include {topic}. "
            f"Courses handled: {rng.choice(common)} and {rng.choice(common)}. " + _pad(rng.randint(1, 3)))))
    for i in range(24):
        topic = rng.choice(topics)
        docs.append(Doc(f"/courses/course-{i:02d}.pdf", f"Course {i}: Introduction to {topic.title()}", (
            f"Course {i}. Introduction to {topic}. Credits: {rng.randint(2, 4)}. Prerequisite: basic "
            f"mathematics. Units cover fundamentals, laboratory exercises and a small project. "
            + _pad(rng.randint(2, 6))), content_type="application/pdf"))
    return docs


DOCS.extend(_generated_distractors())


@dataclass(frozen=True)
class Query:
    id: str
    text: str
    kind: str          # defect class or control
    expected: tuple    # expected URL paths (any-of for hit@k; recall counts found/total)
    answerable: bool = True
    note: str = ""


def _q(id, text, kind, *expected, answerable=True, note=""):
    return Query(id, text, kind, tuple(BASE + e for e in expected), answerable, note)


QUERIES: list[Query] = [
    # --- controls: plain keyword questions that should already work ---
    _q("C01", "What is the library borrowing period?", "control", "/library"),
    _q("C02", "Which laboratories does the mechanical engineering department have?", "control", "/departments/mech"),
    _q("C03", "What is the minimum attendance for semester examinations?", "control", "/examinations/regulations"),
    _q("C04", "When can I apply for revaluation of answer scripts?", "control", "/examinations/revaluation"),
    _q("C05", "Tell me about the grievance redressal cell", "control", "/campus/grievance"),
    _q("C06", "What is the highest package in 2023-24?", "control", "/placements/statistics-2023-24"),
    _q("C07", "What is the hostel gate closing time rule?", "control", "/hostel/rules"),
    _q("C08", "What is the semester 3 tuition fee?", "control", "/fees/structure", "/fees/structure?print=1"),
    # --- tokenisation of degree names ---
    _q("D01", "What is the duration of M.Tech?", "degree-name", "/programmes/mtech"),
    _q("D02", "What is the duration of B.Tech?", "degree-name", "/programmes/btech"),
    _q("D03", "btech eligibility", "degree-name", "/programmes/btech"),
    _q("D04", "M Tech specialisations", "degree-name", "/programmes/mtech"),
    # --- plural / inflection mismatch ---
    _q("P01", "hostel fees", "plural", "/hostel/fee"),
    _q("P02", "scholarships available for students", "plural", "/fees/scholarships"),
    _q("P03", "What facilities are in the hostel?", "plural", "/hostel/facilities"),
    _q("P04", "bus routes", "plural", "/transport"),
    # --- abbreviations / alternative terminology ---
    _q("S01", "CSE department laboratories", "synonym", "/departments/cse"),
    _q("S02", "ECE labs", "synonym", "/departments/ece"),
    _q("S03", "Who is the HOD of mechanical?", "synonym", "/departments/mech", "/faculty/directory"),
    _q("S04", "EEE power lab", "synonym", "/departments/eee"),
    # --- exact phrase vs scattered words ---
    _q("H01", "management quota", "phrase", "/admissions/management-quota", "/admissions"),
    _q("H02", "lateral entry", "phrase", "/admissions/lateral-entry", "/admissions"),
    _q("H03", "anti ragging complaint", "title-match", "/campus/anti-ragging"),
    # --- near-duplicate crowding: two distinct relevant pages exist ---
    _q("R01", "admission lateral entry diploma holders", "diversity", "/admissions", "/admissions/lateral-entry",
       note="expects both the admissions page and the lateral-entry page"),
    _q("R02", "fee payment and scholarship", "diversity", "/fees/structure", "/fees/scholarships",
       note="fee page has a printer-friendly near-duplicate"),
    # --- Hindi / Telugu keyword queries against same-script pages ---
    _q("L01", "छात्रावास शुल्क", "indic-keyword", "/hi/hostel"),
    _q("L02", "प्रवेश प्रक्रिया", "indic-keyword", "/hi/admissions"),
    _q("L03", "హాస్టల్ ఫీజు", "indic-keyword", "/te/hostel"),
    _q("L04", "ప్రవేశాలు", "indic-keyword", "/te/admissions"),
    # --- unanswerable (nothing in the corpus can answer) ---
    _q("U01", "Who won the cricket world cup?", "off-topic", answerable=False),
    _q("U02", "Best pizza near campus", "off-topic", answerable=False),
    _q("U03", "What is the weather tomorrow?", "off-topic", answerable=False),
    _q("U04", "Current bitcoin price", "off-topic", answerable=False),
    _q("U05", "How do I bake a chocolate cake?", "off-topic", answerable=False),
    _q("U06", "What is the capital of France?", "off-topic", answerable=False),
    _q("U07", "Explain quantum entanglement", "off-topic", answerable=False),
    _q("U08", "Is there a swimming pool at the institute?", "unanswerable-topical", answerable=False,
       note="topical but absent from the corpus; 'institute' is a weak shared term"),
    # --- cross-script: English <-> Indic. Not supported by lexical retrieval (documented limitation). ---
    _q("X01", "hostel fee in Hindi", "cross-script", "/hi/hostel", answerable=True,
       note="English query for a Hindi-only page: a lexical engine cannot link these"),
]


def build_chunks_file(directory: str | Path | None = None, docs: list[Doc] | None = None) -> Path:
    """Build the synthetic index with the project's chunker; returns chunks.jsonl path."""
    from ingestion.build_fast_index import build_index

    base = Path(directory) if directory else Path(tempfile.mkdtemp(prefix="synthetic_idx_"))
    src, idx, rep = base / "processed", base / "index", base / "reports"
    src.mkdir(parents=True, exist_ok=True)
    for i, doc in enumerate(docs if docs is not None else DOCS):
        (src / f"doc_{i:03d}.json").write_text(json.dumps({
            "doc_id": f"doc_{i:03d}", "url": doc.url, "title": doc.title, "text": doc.body,
            "content_type": doc.content_type, "verification_status": doc.verification_status,
        }, ensure_ascii=False), encoding="utf-8")
    build_index(source_dir=src, index_dir=idx, report_dir=rep, min_chunks=1,
                max_invalid_ratio=0.5, min_size_ratio=0.0)
    return idx / "chunks.jsonl"
