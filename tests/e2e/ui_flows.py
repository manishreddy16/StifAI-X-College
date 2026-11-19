"""Browser end-to-end checks for CP2 (student/admin/enquiry/chat flows).

NOT part of the normal pytest run. It creates real student accounts and enquiries (example.com addresses)
in whatever database the server uses, so ONLY run it against a throwaway database:

    export STIF_DB_PATH=/tmp/e2e.db
    STIF_ADMIN_PASSWORD='<choose one>' python -m api.manage create-admin --email qa-admin@example.com --name "QA Admin"
    (cd frontend && npm run build)
    python -m uvicorn api.main:app --port 8000 &
    E2E_ADMIN_EMAIL=qa-admin@example.com E2E_ADMIN_PASSWORD='<same one>' python tests/e2e/ui_flows.py

Needs: pip install playwright && playwright install chromium. Expects a FRESH database (it asserts exact counts).
"""
import json, sys, re
PW = re.compile(r"^Password"); EM = re.compile(r"^Email")
from playwright.sync_api import sync_playwright, expect
import os, tempfile
B = os.environ.get("E2E_BASE", "http://127.0.0.1:8000")
ADMIN_EMAIL = os.environ["E2E_ADMIN_EMAIL"]      # an admin created with: python -m api.manage create-admin
ADMIN_PW = os.environ["E2E_ADMIN_PASSWORD"]
SHOTS = os.environ.get("E2E_SHOTS", os.path.join(tempfile.gettempdir(), "stif-e2e-shots"))
os.makedirs(SHOTS, exist_ok=True)
results = []
def check(name, cond, extra=""):
    results.append((name, bool(cond), extra)); print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))

def api(ctx, method, path, body=None):
    r = ctx.request.fetch(B + path, method=method, headers={"X-Requested-With": "stif-campus", "Content-Type": "application/json"},
                          data=json.dumps(body) if body is not None else None)
    return r.status, (r.json() if r.headers.get("content-type", "").startswith("application/json") else None)

with sync_playwright() as p:
    br = p.chromium.launch()
    def new(w=1280, h=900):
        c = br.new_context(viewport={"width": w, "height": h}); pg = c.new_page()
        errs = []; pg.on("pageerror", lambda e: errs.append(str(e))); pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        return c, pg, errs
    cA, A, errsA = new()

    # 1. signed-out protection
    A.goto(B + "/#dashboard"); A.wait_for_url("**#login*"); check("signed-out #dashboard redirects to student login", "#login" in A.url and "next=dashboard" in A.url, A.url)
    A.goto(B + "/#admin/enquiries"); A.wait_for_url("**#admin/login*"); check("signed-out #admin redirects to staff login", "#admin/login" in A.url, A.url)

    # 2. registration validation
    A.goto(B + "/#register"); A.get_by_role("button", name="Create account").click()
    check("register: empty submit shows field errors", A.locator(".field-error").count() >= 3, str(A.locator(".field-error").count()))
    A.get_by_label("Full name").fill("Anil Kumar"); A.get_by_label(EM).fill("anil.student@example.com")
    A.get_by_label(PW).fill("short"); A.get_by_label("Confirm password").fill("different")
    A.get_by_role("button", name="Create account").click()
    check("register: short password + mismatch rejected", A.get_by_text("Use at least 10 characters").count() == 1 and A.get_by_text("do not match").count() == 1)
    A.screenshot(path=SHOTS + "/register_errors.png")
    A.get_by_label(PW).fill("Campus-Learner-77"); A.get_by_label("Confirm password").fill("Campus-Learner-77")
    A.get_by_role("button", name="Create account").click(); A.wait_for_url("**#dashboard")
    check("register success lands on dashboard", A.get_by_role("heading", name="Hello, Anil").is_visible())
    A.wait_for_selector("text=No enquiries yet"); check("dashboard empty state for new student", True)
    A.screenshot(path=SHOTS + "/dashboard_empty.png")

    # duplicate registration (other context)
    cX, X, _ = new(); X.goto(B + "/#register")
    X.get_by_label("Full name").fill("Someone Else"); X.get_by_label(EM).fill("anil.student@example.com")
    X.get_by_label(PW).fill("Another-Pass-9988"); X.get_by_label("Confirm password").fill("Another-Pass-9988")
    X.get_by_role("button", name="Create account").click(); X.wait_for_selector(".alert--error")
    check("register: duplicate email rejected by backend", "already exists" in X.locator(".alert--error").inner_text().lower() or "already" in X.locator(".field-error").first.inner_text().lower())
    cX.close()

    # 3. enquiry form (signed in, no programmes configured yet -> free text)
    A.get_by_role("link", name="New enquiry").click(); A.wait_for_url("**#enquiry")
    check("enquiry form prefilled from account", A.get_by_label("Full name").input_value() == "Anil Kumar" and A.get_by_label(EM).input_value() == "anil.student@example.com")
    A.get_by_label("Phone number").fill("12345"); A.get_by_label("Your question").fill("short")
    A.get_by_role("button", name="Send enquiry").click()
    check("enquiry: bad phone/short message/no consent blocked", A.locator(".field-error").count() >= 3, str(A.locator(".field-error").count()))
    A.screenshot(path=SHOTS + "/enquiry_errors.png")
    A.get_by_label("Phone number").fill("9876543210"); A.get_by_label("Programme you are interested in").fill("Computer Science")
    A.get_by_label("Your question").fill("What documents are required for the admission counselling?")
    A.get_by_label(__import__("re").compile("I agree")).check()
    A.get_by_role("button", name="Send enquiry").click(); A.wait_for_selector("text=Enquiry received")
    ref = A.locator("dd.mono").inner_text(); check("enquiry submitted; reference shown", ref.startswith("ENQ-"), ref)
    A.screenshot(path=SHOTS + "/enquiry_success.png")

    # double submit -> duplicate
    A.get_by_role("button", name="Send another enquiry").click(); A.wait_for_selector("text=Ask the SVCE admissions team")
    A.get_by_label("Phone number").fill("9876543210"); A.get_by_label("Programme you are interested in").fill("Computer Science")
    A.get_by_label("Your question").fill("What documents are required for the admission counselling?"); A.get_by_label(__import__("re").compile("I agree")).check()
    A.get_by_role("button", name="Send enquiry").click(); A.wait_for_selector("text=We already have this enquiry")
    check("duplicate enquiry returns same reference, not a new row", A.locator("dd.mono").inner_text() == ref)

    # anonymous enquiry
    cN, N, _ = new(); N.goto(B + "/#enquiry"); N.wait_for_selector("text=Ask the SVCE admissions team")
    N.get_by_label("Full name").fill("Priya Reddy"); N.get_by_label(EM).fill("priya.guest@example.com"); N.get_by_label("Phone number").fill("+91 98765 43211")
    N.get_by_label("Your question").fill("Is hostel accommodation available for first-year girls?"); N.get_by_label(__import__("re").compile("I agree")).check()
    N.get_by_role("button", name="Send enquiry").click(); N.wait_for_selector("text=Enquiry received")
    check("anonymous enquiry accepted (General label)", "General" in N.locator("dd").nth(1).inner_text())
    cN.close()

    # 4. student sees only their own; second student sees none
    A.goto(B + "/#dashboard"); A.wait_for_selector(".enq-item")
    check("student A sees exactly their own enquiry", A.locator(".enq-item").count() == 1 and ref in A.locator(".enq-item").inner_text())
    A.screenshot(path=SHOTS + "/dashboard_enquiries.png", full_page=True)
    cB, Bp, _ = new(); Bp.goto(B + "/#register")
    Bp.get_by_label("Full name").fill("Second Student"); Bp.get_by_label(EM).fill("second.student@example.com")
    Bp.get_by_label(PW).fill("Second-Learner-55"); Bp.get_by_label("Confirm password").fill("Second-Learner-55")
    Bp.get_by_role("button", name="Create account").click(); Bp.wait_for_url("**#dashboard"); Bp.wait_for_selector("text=No enquiries yet")
    check("student B sees none of student A's enquiries", Bp.locator(".enq-item").count() == 0 and "Anil" not in Bp.inner_text("main"))

    # 5. student cannot access admin (UI + API)
    Bp.goto(B + "/#admin"); Bp.wait_for_selector("text=do not have access")
    check("student on #admin sees no-access (UI)", True)
    st, _ = api(cB, "GET", "/api/v1/admin/stats"); check("student -> admin stats API is 403", st == 403, str(st))
    st, _ = api(cB, "GET", "/api/v1/admin/enquiries/1"); check("student -> admin enquiry detail API is 403", st == 403, str(st))
    st, _ = api(cB, "PATCH", "/api/v1/admin/enquiries/1", {"status": "closed"}); check("student -> admin PATCH is 403", st == 403, str(st))
    cAnon = br.new_context(); st, _ = api(cAnon, "GET", "/api/v1/admin/stats"); check("anonymous -> admin stats API is 401", st == 401, str(st))
    st, _ = api(cAnon, "GET", "/api/v1/enquiries/mine"); check("anonymous -> /enquiries/mine is 401", st == 401, str(st))
    r = cAnon.request.fetch(B + "/api/v1/auth/login", method="POST", headers={"Content-Type": "application/json"}, data=json.dumps({"email": "a@b.co", "password": "x"}))
    check("POST without CSRF header is blocked (403)", r.status == 403, str(r.status))
    # student B logs out
    Bp.goto(B + "/#dashboard"); Bp.wait_for_selector("text=Hello, Second"); Bp.get_by_role("button", name="Sign out").first.click(); Bp.wait_for_url("**#home")
    Bp.goto(B + "/#dashboard"); Bp.wait_for_url("**#login*"); check("after logout #dashboard redirects to login", True)
    st, _ = api(cB, "GET", "/api/v1/enquiries/mine"); check("after logout cookie no longer works (401)", st == 401, str(st))
    cB.close()

    # 6. admin
    cM, M, errsM = new(); M.goto(B + "/#admin/login")
    M.get_by_label(EM).fill("anil.student@example.com"); M.get_by_label(PW).fill("Campus-Learner-77"); M.get_by_role("button", name="Sign in").click()
    M.wait_for_selector(".alert--error"); check("student credentials rejected on staff sign-in", "administrator access" in M.locator(".alert--error").inner_text())
    st, d = api(cM, "GET", "/api/v1/auth/me"); check("...and that session was revoked", d["user"] is None, str(d))
    M.get_by_label(EM).fill(ADMIN_EMAIL); M.get_by_label(PW).fill("wrong-password-1"); M.get_by_role("button", name="Sign in").click()
    M.wait_for_selector("text=Incorrect email or password"); check("wrong admin password shows generic error", True)
    M.get_by_label(PW).fill(ADMIN_PW); M.get_by_role("button", name="Sign in").click(); M.wait_for_url("**#admin")
    M.wait_for_selector(".stat"); check("admin overview shows stats", M.locator(".stat").count() == 5)
    vals = [int(x) for x in M.locator(".stat b").all_inner_texts()]; check("stats total=2 enquiries, 2 student accounts", vals[0] == 2 and vals[4] == 2, str(vals))
    M.screenshot(path=SHOTS + "/admin_overview.png", full_page=True)
    M.get_by_role("link", name="Enquiries").first.click(); M.wait_for_selector(".table")
    check("admin list shows both enquiries", M.locator("tbody tr").count() == 2)
    M.get_by_label("Search enquiries").fill("priya"); M.wait_for_function("document.querySelectorAll('tbody tr').length===1")
    check("admin search filters", "Priya" in M.locator("tbody").inner_text())
    M.get_by_label("Search enquiries").fill(""); M.get_by_label("Filter by status").select_option("responded"); M.wait_for_selector("text=No enquiries found")
    check("status filter + empty state", True); M.get_by_label("Filter by status").select_option("")
    M.wait_for_selector("tbody tr"); M.screenshot(path=SHOTS + "/admin_list.png")
    M.get_by_role("link", name=ref).click(); M.wait_for_selector("text=Student details")
    check("admin detail shows full message + phone", "admission counselling" in M.inner_text("main") and "9876543210" in M.inner_text("main"))
    M.get_by_label("Status").select_option("responded"); M.get_by_label("Internal notes").fill("Called back; sent document checklist.")
    M.get_by_role("button", name="Save changes").click(); M.wait_for_selector("text=Enquiry updated")
    M.screenshot(path=SHOTS + "/admin_detail.png", full_page=True)
    check("admin status update saved", M.locator(".badge").first.inner_text() == "Responded")

    # student sees status change but NOT admin notes
    A.reload(); A.wait_for_selector(".enq-item")
    txt = A.inner_text(".enq-item"); check("student sees updated status", "Responded" in txt)
    st, d = api(cA, "GET", "/api/v1/enquiries/mine"); check("student API never returns admin notes / others' contact", "admin_notes" not in json.dumps(d) and len(d["items"]) == 1)

    # programmes
    M.get_by_role("link", name="Programmes").click(); M.wait_for_selector("text=No programmes yet")
    M.get_by_label("New programme name").fill("Test Programme (QA only)"); M.get_by_role("button", name="Add").click(); M.wait_for_selector(".prog-list")
    check("admin can add programme", "Test Programme" in M.inner_text(".prog-list"))
    A.goto(B + "/#enquiry"); A.wait_for_selector("select.control"); check("enquiry form now lists the programme", "Test Programme (QA only)" in A.locator("select.control").inner_text())
    M.get_by_role("button", name="Hide from form").click(); M.wait_for_selector("text=Show on form")
    A.reload(); A.wait_for_selector("text=Ask the SVCE admissions team"); check("hidden programme removed from form", A.locator("select.control").count() == 0)

    # 7. chatbot preserved
    A.goto(B + "/#assistant"); A.wait_for_selector("main.assistant")
    check("chatbot page renders (signed in)", A.locator("main.assistant").is_visible())
    A.screenshot(path=SHOTS + "/assistant.png")
    ta = A.locator("textarea").first; ta.fill("What is the admission process for B.Tech?"); ta.press("Enter")
    A.wait_for_timeout(3500); A.screenshot(path=SHOTS + "/assistant_after_ask.png"); body = A.inner_text("main.assistant")
    check("chat request round-trips to /api/v1/chat (reply or graceful error shown)", len(body) > 200, body[-160:].replace("\n", " "))

    # 8. responsive + header
    cM2, M2, _ = new(390, 844); M2.goto(B + "/#enquiry"); M2.wait_for_selector("text=Ask the SVCE admissions team"); M2.screenshot(path=SHOTS + "/mobile_enquiry.png", full_page=True)
    check("mobile: no horizontal overflow on enquiry", M2.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
    M2.goto(B + "/#login"); M2.screenshot(path=SHOTS + "/mobile_login.png")
    cT, T, _ = new(820, 1100); T.goto(B + "/#login"); T.get_by_label(EM).fill(ADMIN_EMAIL); T.get_by_label(PW).fill(ADMIN_PW); T.get_by_role("button", name="Sign in").click(); T.wait_for_url("**#admin")
    T.wait_for_selector(".stat"); T.get_by_role("link", name="Enquiries").first.click(); T.wait_for_selector("tbody tr"); T.screenshot(path=SHOTS + "/tablet_admin_list.png")
    check("tablet: no horizontal overflow on admin list", T.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
    cM3, M3, _ = new(390, 844); M3.goto(B + "/#login"); M3.get_by_label(EM).fill(ADMIN_EMAIL); M3.get_by_label(PW).fill(ADMIN_PW); M3.get_by_role("button", name="Sign in").click(); M3.wait_for_url("**#admin")
    M3.goto(B + "/#admin/enquiries"); M3.wait_for_selector("tbody tr"); M3.screenshot(path=SHOTS + "/mobile_admin_list.png", full_page=True)
    check("mobile: no horizontal overflow on admin list", M3.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
    check("login via student page sends admin to #admin", True)
    # landing still OK
    A.goto(B + "/#home"); A.wait_for_selector("footer"); A.screenshot(path=SHOTS + "/home.png")
    check("landing page renders with new header links", A.get_by_role("link", name="Enquire").first.is_visible())
    allerr = [e for e in errsA + errsM if "favicon" not in e and "fonts.g" not in e and "401" not in e and "net::ERR" not in e]
    check("no unexpected JS console errors", not allerr, "; ".join(allerr)[:300])
    br.close()
fails = [r for r in results if not r[1]]
print(f"\n{len(results)-len(fails)}/{len(results)} passed"); sys.exit(1 if fails else 0)
