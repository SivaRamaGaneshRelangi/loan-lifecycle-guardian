from datetime import date

from .models import (ADMIN, CUSTOMER, OFFICER, BankAccount, CustomerProfile, LoanApplication,
                     LoanProduct, User)
from .schemas import ApplicationIn
from .security import hash_password
from .services import documents
from .services.lifecycle import activate_loan, create_application

PRODUCTS = [
    # code, name, min_amt, max_amt, min_ten, max_ten, rate, min_inc, min_cs, foir, ltv, max_age, docs
    ("HOME", "Home Loan", 500000, 20000000, 60, 360, 8.5, 30000, 700, 0.50, 0.80, 70,
     "ID_PROOF,ADDRESS_PROOF,INCOME_PROOF,PROPERTY_PAPERS"),
    ("PERSONAL", "Personal Loan", 50000, 2500000, 12, 60, 10.5, 20000, 700, 0.50, None, 60,
     "ID_PROOF,ADDRESS_PROOF,INCOME_PROOF"),
    ("AUTO", "Vehicle Loan", 100000, 3000000, 12, 84, 9.0, 25000, 680, 0.50, 0.85, 65,
     "ID_PROOF,ADDRESS_PROOF,INCOME_PROOF,VEHICLE_QUOTATION"),
    ("EDUCATION", "Education Loan", 100000, 5000000, 12, 180, 9.5, 15000, 650, 0.60, None, 70,
     "ID_PROOF,ADDRESS_PROOF,ADMISSION_LETTER,INCOME_PROOF"),
    ("GOLD", "Gold Loan", 20000, 2000000, 3, 36, 9.0, 10000, 600, 0.70, 0.75, 75,
     "ID_PROOF,ADDRESS_PROOF,GOLD_VALUATION"),
]
ALL3 = ["ID_PROOF", "ADDRESS_PROOF", "INCOME_PROOF"]


def _user(db, username, pw, name, role, **prof):
    u = User(username=username, full_name=name, email=f"{username}@demo-bank.test",
             password_hash=hash_password(pw), role=role)
    db.add(u)
    db.flush()
    if role == CUSTOMER:
        db.add(CustomerProfile(user_id=u.id, pan=prof.pop("pan"), **prof))
        db.add(BankAccount(user_id=u.id, account_no=prof_acc(u.id), balance=0))
        db.flush()
    return u


_seq = [0]


def u_seq():
    _seq[0] += 7919
    return _seq[0] % 100000000


def prof_acc(uid):
    return f"501000{uid:06d}"


def seed(db):
    if db.query(User).count():
        return
    for p in PRODUCTS:
        db.add(LoanProduct(code=p[0], name=p[1], min_amount=p[2], max_amount=p[3], min_tenure=p[4],
                           max_tenure=p[5], base_rate=p[6], min_income=p[7], min_credit_score=p[8],
                           max_foir=p[9], max_ltv=p[10], max_age_at_maturity=p[11], required_docs=p[12]))
    db.flush()
    _user(db, "admin", "Admin@123", "Asha Admin", ADMIN)
    officer = _user(db, "officer1", "Officer@123", "Omkar Officer", OFFICER)

    def cust(un, name, dob, inc, emi, cs, pan, kyc=True, emp="SALARIED", docs=ALL3, city="Kadapa"):
        u = _user(db, un, "Cust@1234", name, CUSTOMER, dob=dob, monthly_income=inc,
                  existing_emi=emi, credit_score=cs, employment_type=emp, kyc_verified=kyc, pan=pan,
                  phone="98" + f"{u_seq():08d}", address=f"{u_seq() % 90 + 10}, Main Road", city=city,
                  pincode="516001", employer="Demo Employer Pvt Ltd" if emp == "SALARIED" else "Self-employed")
        for d in docs:
            documents.make_sample(db, u, d)  # real PDFs in the uploads folder, auto-verified
        return u

    def loan_for(u, code, amt, ten, asset=0, docs=None, balance=0, autopay=True, netbanking=True):
        a = create_application(db, u, ApplicationIn(product_code=code, amount=amt, tenure_months=ten,
                                                     asset_value=asset, docs=docs or ALL3))
        a.status, a.officer_id = "APPROVED", officer.id
        loan = activate_loan(db, a, first_due=date.today())  # first EMI due today -> demo the engine
        if autopay:
            loan.autopay_enabled, loan.mandate_status, loan.mandate_limit = True, "ACTIVE", round(loan.emi * 1.25, 2)
        acc = db.query(BankAccount).filter_by(user_id=u.id).first()
        acc.balance, acc.netbanking_enabled = balance, netbanking
        db.flush()

    rahul = cust("rahul", "Rahul Sharma", date(1992, 4, 12), 85000, 8000, 745, "ABCPS1234D")
    loan_for(rahul, "PERSONAL", 300000, 36, balance=2000)                       # -> INSUFFICIENT_BALANCE
    priya = cust("priya", "Priya Reddy", date(1988, 9, 3), 150000, 0, 790, "BCDPR2345E",
                 docs=ALL3 + ["PROPERTY_PAPERS"])
    loan_for(priya, "HOME", 4000000, 240, asset=5500000,
             docs=ALL3 + ["PROPERTY_PAPERS"], balance=500000, netbanking=False)  # -> NETBANKING_DISABLED
    suresh = cust("suresh", "Suresh Kumar", date(1985, 1, 20), 70000, 0, 720, "CDEPK3456F",
                  docs=ALL3 + ["VEHICLE_QUOTATION"])
    loan_for(suresh, "AUTO", 600000, 60, asset=800000,
             docs=ALL3 + ["VEHICLE_QUOTATION"], balance=100000)                   # -> PAID
    anita = cust("anita", "Anita Verma", date(1990, 6, 15), 90000, 0, 780, "DEFPV4567G")
    create_application(db, anita, ApplicationIn(product_code="PERSONAL", amount=300000, tenure_months=36,
                                                purpose="Home renovation", docs=ALL3))      # -> APPROVE
    vikram = cust("vikram", "Vikram Singh", date(1995, 11, 2), 30000, 12000, 640, "EFGPS5678H", kyc=False, docs=["ID_PROOF"])
    create_application(db, vikram, ApplicationIn(product_code="PERSONAL", amount=2000000, tenure_months=48,
                                                  purpose="Business", docs=["ID_PROOF"]))   # -> REJECT
    db.commit()
