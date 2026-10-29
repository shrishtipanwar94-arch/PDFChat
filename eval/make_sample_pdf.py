"""Generate eval/sample.pdf: a short, fictional employee handbook.

The questions in questions.json were written against this text, so the eval is
reproducible without shipping a third-party PDF.
"""

from pathlib import Path

import pymupdf

PAGES = [
    ("Welcome to Northwind Lantern Co.",
     "Northwind Lantern Co. was founded in 2011 in Duluth, Minnesota, and designs "
     "handmade outdoor lighting. The company has about 140 employees across design, "
     "workshop, and customer care teams. Our chief executive officer is Maria Okafor. "
     "This handbook explains how we work together, what you can expect from us, and "
     "what we expect from you. It is reviewed every January; the version you are "
     "reading is the 2026 edition."),
    ("Working hours and remote work",
     "Core hours are 10:00 to 15:00, Monday to Friday. Outside core hours you may "
     "arrange your day as suits you and your team. The Duluth office opens at 07:00 "
     "and closes at 20:00. Employees may work remotely up to three days per week, "
     "agreed with their manager. Each new remote-eligible employee receives a one-time "
     "home office equipment stipend of $600."),
    ("Time off",
     "Full-time employees receive 22 days of paid time off (PTO) per year. Up to 5 unused "
     "PTO days may be carried over into the next year; the rest expire on 31 December. "
     "In addition there are 10 paid sick days per year. Parental leave is 16 weeks at full "
     "pay for any new parent. Bereavement leave is 5 paid days. Requests for PTO should be "
     "made at least two weeks in advance for absences longer than three days."),
    ("Expenses and travel",
     "Submit expense claims within 30 days of the purchase through Ledgerly, our expense "
     "tool. Receipts are required for any item over $25. The daily meal allowance while "
     "travelling is $55. Book economy class for flights under 6 hours; premium economy is "
     "allowed for longer flights. Hotel bookings must be approved by your manager before "
     "travel."),
    ("Equipment and security",
     "Company laptops are replaced every 3 years. Report a lost or stolen device to the IT "
     "team within 24 hours. Passwords must be at least 14 characters long, and multi-factor "
     "authentication (MFA) is required on every company account. Never share your password, "
     "even with IT staff. Personal software may not be installed on company laptops without "
     "IT approval."),
    ("Customer refunds",
     "Customers may request a full refund within 30 days of purchase. Between 31 and 90 days "
     "after purchase we offer store credit instead of a refund. Items that arrive damaged are "
     "replaced free of charge. Original shipping costs are refunded only when the item was "
     "defective. Refunds are issued to the original payment method within 7 business days."),
    ("Benefits",
     "We match 401(k) contributions up to 4% of salary. Health insurance starts on your first "
     "day of employment. Employees can claim a gym reimbursement of $40 per month. Every "
     "employee has a learning budget of $1,200 per year for courses, books and conferences. "
     "Unused learning budget does not roll over."),
]


def build(path: Path) -> None:
    doc = pymupdf.open()
    for title, body in PAGES:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(72, 72, 540, 110), title, fontsize=18, fontname="helv")
        page.insert_textbox(pymupdf.Rect(72, 120, 540, 760), body, fontsize=11, fontname="helv")
    doc.save(path)
    doc.close()


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "sample.pdf"
    build(out)
    print(f"Wrote {out}")
