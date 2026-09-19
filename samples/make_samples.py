"""Generate a realistic demo corpus with deliberate cross-document discrepancies (samples/demo/).

  Vendor Contract - Nimbus Software.docx   net-30 payment, INR 12,00,000 fee, 99.5% SLA, 60-day termination notice
  Invoice Register FY26.xlsx               ~300 invoices; Nimbus rows carry "Net 45" terms + one 12.5% uplift; formulas;
                                           HIDDEN sheet "Adjustments" with a waived-penalty note
  Vendor Policy.pdf                        3 pages; says net-30, SLA >= 99.9%, CFO approval above INR 10,00,000
  Board Minutes Q2 FY26.docx               approved Nimbus at INR 12,00,000, records 90-day termination notice
  + 12 other vendor contracts (same template, other numbers) so retrieval must actually choose.

Run:  python samples/make_samples.py   ->  samples/demo/*  and samples/demo_corpus.zip (upload the zip in one go).
"""
from __future__ import annotations

import random
import zipfile
from datetime import date, timedelta
from pathlib import Path

from docx import Document
from openpyxl import Workbook

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz

OUT = Path(__file__).parent / "demo"
OUT.mkdir(exist_ok=True)

BOILERPLATE = [
    ("8. Data Protection", [
        "Each party shall comply with applicable data protection laws, including the Digital Personal Data Protection Act, 2023, in relation to any personal data processed under this Agreement. Vendor shall process personal data only on documented instructions from Client and shall implement appropriate technical and organisational measures to protect such data against unauthorised or unlawful processing and against accidental loss, destruction or damage.",
        "Vendor shall notify Client without undue delay, and in any event within seventy-two (72) hours, after becoming aware of a personal data breach affecting Client data, and shall provide all reasonable assistance to Client in meeting its own notification obligations.",
    ]),
    ("9. Intellectual Property", [
        "All intellectual property rights in the Services and any software, documentation or materials provided by Vendor remain the property of Vendor or its licensors. Client is granted a non-exclusive, non-transferable licence to use such materials during the Term solely for its internal business purposes.",
        "All intellectual property rights in Client data, and in any deliverables created specifically for Client and paid for under a statement of work, vest in Client upon payment.",
    ]),
    ("10. Warranties", [
        "Vendor warrants that the Services will be performed with reasonable skill and care by suitably qualified personnel and in accordance with good industry practice, and that the Services will conform in all material respects to the specifications in Schedule A.",
        "Except as expressly set out in this Agreement, all warranties, conditions and terms implied by statute or common law are excluded to the fullest extent permitted by law.",
    ]),
    ("11. Limitation of Liability", [
        "Nothing in this Agreement limits or excludes either party's liability for death or personal injury caused by negligence, for fraud or fraudulent misrepresentation, or for any liability that cannot lawfully be limited or excluded.",
        "Subject to the foregoing, each party's total aggregate liability arising out of or in connection with this Agreement in any contract year shall not exceed the fees paid or payable by Client in that contract year. Neither party shall be liable for any indirect or consequential loss, loss of profit, loss of business or loss of data.",
    ]),
    ("12. Insurance", [
        "Vendor shall maintain, at its own cost, professional indemnity insurance of not less than INR 5,00,00,000 per claim and public liability insurance of not less than INR 2,00,00,000 per claim with a reputable insurer for the duration of this Agreement and for two (2) years thereafter, and shall provide evidence of such cover on request.",
    ]),
    ("13. Force Majeure", [
        "Neither party shall be in breach of this Agreement nor liable for delay in performing, or failure to perform, any of its obligations if such delay or failure results from events, circumstances or causes beyond its reasonable control. If the period of delay continues for sixty (60) days, the party not affected may terminate this Agreement by giving fourteen (14) days' written notice.",
    ]),
    ("14. Notices", [
        "Any notice given under this Agreement shall be in writing and delivered by hand, by pre-paid registered post or by email to the address of the relevant party set out in Schedule B. Notices sent by email are deemed received on the next business day.",
    ]),
    ("15. Assignment and Subcontracting", [
        "Neither party may assign, transfer or subcontract any of its rights or obligations under this Agreement without the prior written consent of the other party, such consent not to be unreasonably withheld. Vendor remains fully responsible for the acts and omissions of any permitted subcontractor.",
    ]),
    ("16. Dispute Resolution", [
        "The parties shall attempt in good faith to resolve any dispute arising out of this Agreement through negotiation between senior executives within thirty (30) days of written notice of the dispute. Any dispute not so resolved shall be referred to arbitration under the Arbitration and Conciliation Act, 1996, by a sole arbitrator seated in Mumbai, with proceedings conducted in English.",
    ]),
    ("17. Entire Agreement", [
        "This Agreement, together with its Schedules, constitutes the entire agreement between the parties and supersedes all prior negotiations, representations and agreements relating to its subject matter. No variation of this Agreement is effective unless in writing and signed by authorised representatives of both parties.",
    ]),
]


def contract_docx(path: Path, vendor: str, fee: str, net: int, sla: str, notice: int, product: str, licences: int = 250):
    d = Document()
    d.add_heading(f"Master Services Agreement — {vendor}", 0)
    d.add_paragraph(f"This Master Services Agreement (the \"Agreement\") is entered into on 1 April 2026 between Treelife Technologies Pvt. Ltd. (\"Client\") and {vendor} (\"Vendor\").")
    d.add_heading("1. Scope of Services", 1)
    d.add_paragraph(f"Vendor shall provide {product} as described in Schedule A, including onboarding, maintenance and support (the \"Services\").")
    d.add_heading("2. Term", 1)
    d.add_paragraph("The initial term is twelve (12) months from the Effective Date and renews automatically for successive twelve-month periods unless terminated in accordance with clause 5.")
    d.add_heading("3. Fees and Payment", 1)
    d.add_paragraph(f"Client shall pay Vendor an annual fee of {fee} (exclusive of GST), invoiced quarterly in advance.")
    d.add_paragraph(f"Payment terms: all undisputed invoices are payable within {net} days of receipt. Late payments accrue interest at 2% per month.")
    d.add_paragraph("Any increase to the fees requires a signed change order; Vendor shall not invoice amounts beyond the agreed fee without one.")
    d.add_heading("4. Service Levels", 1)
    d.add_paragraph(f"Vendor guarantees {sla} monthly uptime. Each 0.1% shortfall entitles Client to a service credit of 5% of the monthly fee, claimable within 30 days.")
    d.add_heading("5. Termination", 1)
    d.add_paragraph(f"Either party may terminate this Agreement for convenience with {notice} days' written notice. Client may terminate immediately for material breach not cured within 15 days.")
    d.add_heading("6. Confidentiality", 1)
    d.add_paragraph("Each party shall keep the other party's Confidential Information confidential for three (3) years after termination.")
    d.add_heading("7. Governing Law", 1)
    d.add_paragraph("This Agreement is governed by the laws of India; courts in Mumbai, Maharashtra have exclusive jurisdiction subject to clause 16.")
    for heading, paras in BOILERPLATE:
        d.add_heading(heading, 1)
        for p in paras:
            d.add_paragraph(p)
    d.add_heading("Schedule A — Deliverables", 1)
    t = d.add_table(rows=1, cols=3)
    t.style = "Table Grid"
    for i, h in enumerate(["Item", "Description", "Quantity"]):
        t.rows[0].cells[i].text = h
    for item, desc, qty in [("Licences", f"{product} user licences", str(licences)), ("Onboarding", "Implementation and data migration", "1"), ("Support", "24x7 priority support", "12 months")]:
        r = t.add_row().cells
        r[0].text, r[1].text, r[2].text = item, desc, qty
    d.add_heading("Schedule B — Notices", 1)
    d.add_paragraph(f"Client: Treelife Technologies Pvt. Ltd., 4th Floor, Bandra Kurla Complex, Mumbai 400051; legal@treelife-demo.example.\nVendor: {vendor}, registered office as per the Companies Register; notices@{vendor.lower().replace(' ', '')}.example.")
    d.save(path)


VENDORS = [
    ("Quartz Analytics", 720000, "analytics platform"), ("Cedar Logistics", 480000, "freight management software"),
    ("Falcon Media", 960000, "media buying services"), ("Kestrel Finance", 840000, "treasury software"),
    ("Granite Builders", 600000, "facilities services"), ("Orchid Hotels", 360000, "corporate travel accommodation"),
    ("Lotus Education", 480000, "e-learning platform"), ("Meridian Energy", 720000, "energy monitoring"),
    ("Indigo Textiles", 360000, "uniform supply"), ("Horizon Travel", 600000, "travel desk services"),
    ("Juniper Health", 840000, "health benefits administration"), ("Sapphire Jewels", 360000, "corporate gifting"),
]


def invoice_register(path: Path):
    rnd = random.Random(5)
    wb = Workbook()
    ws = wb.active
    ws.title = "Invoices"
    ws.append(["Invoice No", "Vendor", "Invoice Date", "Amount (INR)", "Terms", "Due Date", "Paid Date", "Status", "PO Number", "Days To Pay"])
    rows = []
    # planted Nimbus rows: paid on net-45, Q2 uplifted 12.5%
    rows += [
        ("NS-2026-01", "Nimbus Software", date(2026, 4, 5), 300000, "Net 45", "PO-4481", 43),
        ("NS-2026-02", "Nimbus Software", date(2026, 7, 3), 337500, "Net 45", "PO-4481", 48),
        ("NS-2026-03", "Nimbus Software", date(2026, 9, 10), 337500, "Net 45", "PO-4481", None),
    ]
    for i, (v, fee, _) in enumerate(VENDORS):
        code = "".join(w[0] for w in v.split())
        monthly = round(fee / 12, -2)
        for m in range(1, 13):
            d = date(2025, 9, 1) + timedelta(days=30 * m + i)
            paid_days = None if (m >= 12 or (m + i) % 11 == 0) else rnd.choice([25, 28, 29, 30, 31, 33])
            rows.append((f"{code}-{d.year}-{m:02d}", v, d, monthly + rnd.choice([0, 0, 0, 1500, -800]), "Net 30", f"PO-{4100 + i * 7}", paid_days))
    rows.sort(key=lambda r: r[2])
    for r, (no, vendor, d, amt, terms, po, paid_days) in enumerate(rows, start=2):
        net = int(terms.split()[1])
        due = d + timedelta(days=net)
        paid = (d + timedelta(days=paid_days)) if paid_days else None
        status = "Paid" if paid else ("Overdue" if due < date(2026, 9, 19) else "Open")
        ws.append([no, vendor, d, amt, terms, due, paid, status, po, f'=IF(G{r}="","",G{r}-C{r})'])
    for col, w in zip("ABCDEFGHIJ", (14, 20, 13, 14, 9, 13, 13, 10, 11, 12)):
        ws.column_dimensions[col].width = w
    for r in range(2, ws.max_row + 1):
        for col in ("C", "F", "G"):
            ws[f"{col}{r}"].number_format = "yyyy-mm-dd"
    ws.freeze_panes = "A2"
    s = wb.create_sheet("Summary")
    s.append(["Vendor", "Total Invoiced (INR)", "Open Amount (INR)", "Invoices"])
    names = ["Nimbus Software"] + [v for v, _, _ in VENDORS]
    for i, v in enumerate(names, start=2):
        s.append([v, f'=SUMIF(Invoices!B:B,A{i},Invoices!D:D)', f'=SUMIFS(Invoices!D:D,Invoices!B:B,A{i},Invoices!H:H,"Open")', f'=COUNTIF(Invoices!B:B,A{i})'])
    s.append(["TOTAL", f"=SUM(B2:B{len(names) + 1})", f"=SUM(C2:C{len(names) + 1})", f"=SUM(D2:D{len(names) + 1})"])
    h = wb.create_sheet("Adjustments")
    h.sheet_state = "hidden"
    h.append(["Ref", "Vendor", "Note", "Amount (INR)"])
    h.append(["ADJ-01", "Nimbus Software", "Q2 invoice NS-2026-02 uplifted 12.5% for 'additional licences' - no change order on file", 37500])
    h.append(["ADJ-02", "Nimbus Software", "Late-payment interest waived per verbal agreement with vendor; 2% penalty clause not applied", 0])
    h.append(["ADJ-03", "Falcon Media", "Disputed - awaiting credit note", -80000])
    wb.save(path)


POLICY = """Treelife Technologies - Vendor & Procurement Policy (v3.2, effective 1 January 2026)

1. Purpose and scope
This policy governs the selection, contracting, monitoring and payment of third-party vendors across all Treelife entities. It applies to every employee who requests, approves or pays for goods or services, and to every contract regardless of value. Departures from this policy are permitted only with a written exception approved by the CFO and recorded in the exceptions register.

2. Contract approvals
2.1 Any vendor contract with an annual value above INR 10,00,000 requires written approval of the CFO before signature.
2.2 Contracts above INR 25,00,000 additionally require Board approval recorded in the minutes.
2.3 Legal must review every contract using a non-standard template before signature.
2.4 Auto-renewal clauses must be flagged to Finance ninety (90) days before the renewal date.

3. Payment terms
3.1 Standard payment terms for all vendor contracts are net 30 days from receipt of a valid invoice.
3.2 Deviations from net 30 must be documented in the contract and approved by Finance in writing before the first invoice is paid.
3.3 Invoices must be matched to a purchase order before payment; unmatched invoices are returned to the vendor.
3.4 Early-payment discounts may be taken only where the discount exceeds the company's cost of capital.

4. Service levels
4.1 Software-as-a-service vendors must commit to a minimum of 99.9% monthly uptime.
4.2 Service credits must be claimed within 30 days of the shortfall; the requesting department is responsible for monitoring.
4.3 Vendors must provide a quarterly service report covering availability, incidents and open actions.

5. Termination
5.1 Contracts must allow termination for convenience with no more than 60 days' notice.
5.2 Contracts must allow immediate termination for material breach, insolvency or change of control of the vendor.

6. Invoice adjustments and waivers
6.1 Any uplift to an invoiced amount requires a signed change order referencing the original purchase order.
6.2 Waivers of contractual penalties or interest must be approved in writing by the CFO; verbal agreements are not recognised.
6.3 Credit notes must be obtained for disputed amounts within 60 days of the dispute being raised.

7. Vendor onboarding
7.1 New vendors must complete the vendor questionnaire, provide GST registration, PAN and bank details on company letterhead, and pass a sanctions and adverse-media screening before the first purchase order is issued.
7.2 Vendors processing personal data must sign the standard data processing addendum and evidence ISO 27001 certification or an equivalent independent assessment.
7.3 Vendor master data may be changed only by the Finance master-data team following a call-back verification with the vendor.

8. Information security requirements
8.1 Vendors with access to Treelife systems must use multi-factor authentication and named accounts; shared credentials are prohibited.
8.2 Vendors must notify Treelife of any security incident affecting Treelife data within 72 hours.
8.3 Access rights are reviewed quarterly and revoked within one business day of contract termination.

9. Conflicts of interest and gifts
9.1 Employees must declare any personal or financial interest in a vendor before participating in its selection or management.
9.2 Gifts or hospitality from vendors above INR 5,000 in value must be declared and may not be accepted during an active tender.

10. Monitoring and audit
10.1 Internal Audit reviews a sample of vendor contracts, invoices and adjustments every quarter and reports findings to the Audit Committee.
10.2 Departments must retain contracts, change orders, invoices and correspondence for eight years.
"""


def policy_pdf(path: Path):
    doc = fitz.open()
    chunks = POLICY.split("\n\n")
    page_text, page_texts = "", []
    for c in chunks:
        if len(page_text) + len(c) > 2600:
            page_texts.append(page_text)
            page_text = ""
        page_text += c + "\n\n"
    page_texts.append(page_text)
    for i, t in enumerate(page_texts, start=1):
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(56, 56, 540, 790), t, fontsize=10.5, fontname="helv")
        page.insert_text((56, 815), f"Vendor & Procurement Policy v3.2 - page {i} of {len(page_texts)}", fontsize=8, fontname="helv")
    doc.save(path)


def board_minutes(path: Path):
    d = Document()
    d.add_heading("Board Meeting Minutes — Q2 FY26", 0)
    d.add_paragraph("Date: 28 March 2026. Venue: Mumbai office. Present: R. Mehta (CEO), G. Sharma (CFO), I. Kapoor (CTO), P. Nair (Company Secretary), two independent directors.")
    d.add_heading("Item 1 — Minutes of the previous meeting", 1)
    d.add_paragraph("The minutes of the meeting held on 19 December 2025 were approved as a correct record.")
    d.add_heading("Item 2 — Financial update", 1)
    d.add_paragraph("The CFO presented the Q4 FY25 management accounts. Revenue was 8% ahead of budget; vendor spend was 3% above budget, driven by software subscriptions. The Board asked for a vendor-spend review at the next meeting.")
    d.add_heading("Item 3 — Hiring plan", 1)
    d.add_paragraph("The Board approved twelve additional engineering hires for FY26 within the approved budget.")
    d.add_heading("Item 4 — Vendor contracts", 1)
    d.add_paragraph("The Board reviewed the proposed Master Services Agreement with Nimbus Software for the CRM platform at an annual fee of INR 12,00,000 for 250 user licences. The CFO confirmed approval under section 2.1 of the Procurement Policy.")
    d.add_paragraph("The Board noted that the agreement provides for termination for convenience on 90 days' notice and asked Legal to confirm alignment with policy section 5.1.")
    d.add_paragraph("Resolved: the Nimbus Software agreement is approved for signature by the CEO.")
    d.add_heading("Item 5 — Quartz Analytics renewal", 1)
    d.add_paragraph("Renewal of the Quartz Analytics subscription at INR 7,20,000 per annum was approved; payment terms remain net 30.")
    d.add_heading("Item 6 — Any other business", 1)
    d.add_paragraph("The Company Secretary reminded directors that the annual conflicts-of-interest declarations are due by 30 April 2026. The next meeting is scheduled for 26 June 2026.")
    d.save(path)


def main():
    contract_docx(OUT / "Vendor Contract - Nimbus Software.docx", "Nimbus Software", "INR 12,00,000", 30, "99.5%", 60, "the Nimbus CRM platform")
    for v, fee, product in VENDORS:
        contract_docx(OUT / f"Vendor Contract - {v}.docx", v, f"INR {fee // 100000},{(fee % 100000) // 1000:02d},000".replace(",00,000", ",00,000"), 30, "99.9%", 60, product, licences=50 + (fee // 10000))
    invoice_register(OUT / "Invoice Register FY26.xlsx")
    policy_pdf(OUT / "Vendor Policy.pdf")
    board_minutes(OUT / "Board Minutes Q2 FY26.docx")
    (OUT / "README-answers.md").write_text(
        "Planted discrepancies (NOT included in the zip):\n"
        "- Nimbus contract: net-30 payment, INR 12,00,000, 99.5% SLA, 60-day notice.\n"
        "- Invoice register: Nimbus rows on 'Net 45'; NS-2026-02 uplifted 12.5% (hidden sheet 'Adjustments' ADJ-01); interest waived verbally (ADJ-02).\n"
        "- Vendor policy: net 30 standard (3.1), SLA >= 99.9% (4.1), waivers need CFO in writing (6.2), uplifts need change order (6.1).\n"
        "- Board minutes: record 90-day termination notice for Nimbus (contract says 60).\n", encoding="utf-8")
    zpath = OUT.parent / "demo_corpus.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(OUT.iterdir()):
            if p.suffix.lower() in (".docx", ".xlsx", ".pdf"):
                z.write(p, p.name)
    print(f"wrote {len(list(OUT.glob('*.docx'))) + 2} documents to {OUT} and {zpath}")


if __name__ == "__main__":
    main()
