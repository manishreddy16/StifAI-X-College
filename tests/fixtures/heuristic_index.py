"""Small SYNTHETIC index with SVCE-shaped URLs and FICTIONAL text.

Purpose: exercise the hard-coded URL/topic heuristics in api/retrieval.py
(admission page, contact page, placement statistics, syllabus penalties).
The text is invented for testing; it is not college data.
"""

HEURISTIC_CHUNKS = [
    {"chunk_id": "h-adm-0", "doc_id": "h-adm", "title": "Admissions", "url": "https://svce.edu.in/admission.php",
     "verification_status": "VERIFIED",
     "text": "Quick Links Examination Cell Campus Life Fresher's Fest Home About. Admission process. Candidates are "
             "admitted through EAPCET counselling. Management quota and lateral entry seats follow merit. "},
    {"chunk_id": "h-adm-1", "doc_id": "h-adm", "title": "Admissions", "url": "https://svce.edu.in/admission.php",
     "text": "Admission process documents are verified at the help desk during counselling. EAPCET rank cards are checked."},
    {"chunk_id": "h-adm-pdf", "doc_id": "h-adm-pdf", "title": "Syllabus and course structure", "url": "https://svce.edu.in/files/syllabus.pdf",
     "text": "Course structure and syllabus for the programme. Admission to this course requires a pass. EAPCET is not discussed."},
    {"chunk_id": "h-con-0", "doc_id": "h-con", "title": "Contact Us", "url": "https://svce.edu.in/contactus.php",
     "text": "Contact Us. Address, phone and email of the college office are listed here for visitors."},
    {"chunk_id": "h-con-bank", "doc_id": "h-bank", "title": "Bank details", "url": "https://example.test/bank-details.pdf",
     "text": "Bank account contact phone for fee payment to the college account."},
    {"chunk_id": "h-pl-0", "doc_id": "h-pl", "title": "Placements 2024-25", "url": "https://svce.edu.in/placements.php",
     "text": "Placement details 2024-25. Highest package 12 LPA. Average package 4 LPA. Total recruiters 40. Students placed 300."},
    {"chunk_id": "h-pl-1", "doc_id": "h-pl2", "title": "Placement Stories", "url": "https://svce.edu.in/placement-stories.php",
     "text": "Placement stories from students describing interviews and their journey to a job offer."},
    {"chunk_id": "h-pl-syl", "doc_id": "h-pls", "title": "Placement training syllabus", "url": "https://svce.edu.in/files/placement-training-syllabus.pdf",
     "text": "Syllabus and course structure for the placement training elective with units on aptitude."},
    {"chunk_id": "h-fee-0", "doc_id": "h-fee", "title": "Fee Structure", "url": "https://svce.edu.in/fees.php",
     "verification_status": "NEEDS_VERIFICATION",
     "text": "Fee structure. Tuition fee per year is listed in the table. Scholarship and refund policy follow."},
    {"chunk_id": "h-lib-0", "doc_id": "h-lib", "title": "Library", "url": "https://svce.edu.in/library.php",
     "text": "Library timings and borrowing rules for members of the institution."},
]

HEURISTIC_QUERIES = [
    "What is the admission process?",
    "How to apply for B.Tech admission through EAPCET?",
    "documents required for admission",
    "contact phone number",
    "What is the college address?",
    "email address of the principal office",
    "highest package placement",
    "placement statistics 2024-25",
    "average package and recruiters",
    "fee structure and scholarship",
    "library timings",
    "management quota lateral entry",
    "syllabus course structure",
]
