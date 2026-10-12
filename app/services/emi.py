import calendar
from datetime import date


def calc_emi(principal: float, annual_rate: float, months: int) -> float:
    r = annual_rate / 1200.0
    if months <= 0:
        return 0.0
    if r == 0:
        return round(principal / months, 2)
    f = (1 + r) ** months
    return round(principal * r * f / (f - 1), 2)


def add_months(d: date, k: int) -> date:
    m = d.month - 1 + k
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def build_schedule(principal: float, annual_rate: float, months: int, first_due: date):
    r = annual_rate / 1200.0
    emi = calc_emi(principal, annual_rate, months)
    bal, rows = principal, []
    for n in range(1, months + 1):
        interest = round(bal * r, 2)
        princ = round(emi - interest, 2)
        if n == months:  # clear rounding residue on the last instalment
            princ = round(bal, 2)
        bal = round(bal - princ, 2)
        rows.append({"number": n, "due_date": add_months(first_due, n - 1),
                     "emi_amount": round(princ + interest, 2),
                     "principal_part": princ, "interest_part": interest})
    return rows
