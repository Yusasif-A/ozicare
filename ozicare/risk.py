"""
Risk identification: raw screening readings -> urgency, pathway, reasons.

Slide step 02 asks for "agreed criteria" applied the same way every time. They
live in RULES below as plain data so a programme can review and change them in
one place, and every case stores the reasons that fired, so a clinician can see
exactly why a person was prioritised.

The thresholds are demo values in line with common screening guidance. A
programme must have its own clinicians sign them off before go-live.

Two scores live here:
  assess(readings)  -> clinical priority of the result (once, at intake)
  loss_risk(case)   -> how likely this person is to be lost between steps
                       (recomputed on every read; drives outreach)
"""

from __future__ import annotations

from datetime import datetime, timezone

URGENCY_RANK = {"routine": 0, "soon": 1, "urgent": 2}

# pathway -> the screening_type whose approved wording the patient receives
PATHWAY_SCREENING = {
    "hypertension": "blood_pressure",
    "diabetes": "diabetes",
    "obesity": "obesity",
    "cervical": "cervical",
    "colorectal": "colorectal",
    "breast": "breast",
    "general": "general_abnormal",
}

PATHWAY_LABELS = {
    "hypertension": "Hypertension",
    "diabetes": "Diabetes",
    "obesity": "Obesity",
    "cervical": "Cervical cancer screening",
    "colorectal": "Colorectal cancer screening",
    "breast": "Breast cancer screening",
    "general": "General review",
}

# The readings a result can carry, for forms and docs.
READINGS = {
    "systolic": "Systolic BP (mmHg)",
    "diastolic": "Diastolic BP (mmHg)",
    "hba1c": "HbA1c (%)",
    "fasting_glucose": "Fasting glucose (mg/dL)",
    "random_glucose": "Random glucose (mg/dL)",
    "bmi": "BMI (kg/m²)",
    "cervical_cytology": "Cervical cytology / HPV (e.g. HSIL, LSIL, ASC-US, HPV16)",
    "fit": "FIT stool test (positive / negative)",
    "birads": "Mammogram BI-RADS category (0-6)",
}

CERVICAL_TERMS = {
    "urgent": ("suspected cancer", "carcinoma", "scc"),
    "soon": ("hsil", "asc-h", "agc", "hpv16", "hpv 16", "hpv18", "hpv 18"),
    "routine": ("asc-us", "ascus", "lsil", "hrhpv", "hpv positive", "hpv+"),
}


def _num(v) -> float | None:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


# Each rule: (pathway, urgency, reason, test). The first matching rule per
# pathway wins, so within a pathway they run most to least severe.
RULES: list[tuple[str, str, str, callable]] = [
    ("hypertension", "urgent", "BP ≥ 180/120: severe range, same-day review", lambda r: (_num(r.get("systolic")) or 0) >= 180 or (_num(r.get("diastolic")) or 0) >= 120),
    ("hypertension", "soon", "BP ≥ 160/100: stage 2 range", lambda r: (_num(r.get("systolic")) or 0) >= 160 or (_num(r.get("diastolic")) or 0) >= 100),
    ("hypertension", "routine", "BP ≥ 140/90: raised, repeat check", lambda r: (_num(r.get("systolic")) or 0) >= 140 or (_num(r.get("diastolic")) or 0) >= 90),
    ("diabetes", "urgent", "HbA1c ≥ 10% or glucose ≥ 300 mg/dL: very high", lambda r: (_num(r.get("hba1c")) or 0) >= 10 or (_num(r.get("random_glucose")) or 0) >= 300 or (_num(r.get("fasting_glucose")) or 0) >= 300),
    ("diabetes", "soon", "HbA1c ≥ 6.5% or fasting glucose ≥ 126 mg/dL: diabetes range", lambda r: (_num(r.get("hba1c")) or 0) >= 6.5 or (_num(r.get("fasting_glucose")) or 0) >= 126 or (_num(r.get("random_glucose")) or 0) >= 200),
    ("diabetes", "routine", "HbA1c 5.7–6.4% or fasting glucose 100–125 mg/dL: prediabetes range", lambda r: (_num(r.get("hba1c")) or 0) >= 5.7 or (_num(r.get("fasting_glucose")) or 0) >= 100),
    ("obesity", "soon", "BMI ≥ 40: severe obesity", lambda r: (_num(r.get("bmi")) or 0) >= 40),
    ("obesity", "routine", "BMI ≥ 30: obesity", lambda r: (_num(r.get("bmi")) or 0) >= 30),
    ("cervical", "urgent", "Cytology suggests cancer: fast-track colposcopy", lambda r: any(t in str(r.get("cervical_cytology", "")).lower() for t in CERVICAL_TERMS["urgent"])),
    ("cervical", "soon", "High-grade cytology or HPV 16/18: colposcopy", lambda r: any(t in str(r.get("cervical_cytology", "")).lower() for t in CERVICAL_TERMS["soon"])),
    ("cervical", "routine", "Low-grade cytology or other high-risk HPV: follow-up", lambda r: any(t in str(r.get("cervical_cytology", "")).lower() for t in CERVICAL_TERMS["routine"])),
    ("colorectal", "soon", "FIT positive: colonoscopy", lambda r: str(r.get("fit", "")).strip().lower() in ("positive", "pos", "+", "detected", "true", "1")),
    ("breast", "urgent", "BI-RADS 4/5: suspicious, cancer diagnostic pathway", lambda r: (_num(r.get("birads")) or 0) in (4, 5)),
    ("breast", "soon", "BI-RADS 0: incomplete, recall imaging", lambda r: str(r.get("birads", "")).strip() == "0"),
    ("breast", "routine", "BI-RADS 3: short-interval follow-up", lambda r: (_num(r.get("birads")) or 0) == 3),
]


def assess(readings: dict | None) -> dict:
    """
    Apply RULES. Returns {"actionable", "urgency", "pathway", "screening_type",
    "findings": [{pathway, urgency, reason}]}. The primary pathway is the most
    urgent finding; cancer pathways win ties because their delays cost most.
    """
    readings = {k: v for k, v in (readings or {}).items() if v not in (None, "")}
    findings: list[dict] = []
    seen: set[str] = set()
    for pathway, urgency, reason, test in RULES:
        if pathway in seen:
            continue
        try:
            hit = test(readings)
        except Exception:  # noqa: BLE001 - a malformed reading must not fail intake
            hit = False
        if hit:
            seen.add(pathway)
            findings.append({"pathway": pathway, "urgency": urgency, "reason": reason})
    if not findings:
        return {"actionable": False, "urgency": None, "pathway": None, "screening_type": None, "findings": []}
    cancer = ("breast", "cervical", "colorectal")
    findings.sort(key=lambda f: (-URGENCY_RANK[f["urgency"]], f["pathway"] not in cancer))
    top = findings[0]
    return {
        "actionable": True,
        "urgency": top["urgency"],
        "pathway": top["pathway"],
        "screening_type": PATHWAY_SCREENING[top["pathway"]],
        "findings": findings,
    }


def rules_table() -> list[dict]:
    return [{"pathway": p, "pathway_label": PATHWAY_LABELS[p], "urgency": u, "criterion": reason} for p, u, reason, _ in RULES]


# --------------------------------------------------------------------------
# Lost-to-follow-up risk
# --------------------------------------------------------------------------


def _hours_since(ts) -> float:
    if not isinstance(ts, datetime):
        return 0.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds() / 3600


def loss_risk(case: dict) -> dict:
    """
    0-100 score of how likely this person is to fall out of the loop, with the
    reasons. Simple and explainable on purpose: staff act on the reasons.
    """
    status = case.get("status", "")
    if status.startswith("closed") or status in ("in_care", "follow_up"):
        return {"score": 0, "level": "none", "reasons": []}
    score, reasons = 0, []

    def add(points: int, why: str) -> None:
        nonlocal score
        score += points
        reasons.append(why)

    attempts = case.get("attempts", 0) or 0
    if not case.get("acknowledged_at") and attempts:
        add(min(15 * attempts, 45), f"no reply after {attempts} message{'s' if attempts > 1 else ''}")
    if not case.get("first_contact_at") and _hours_since(case.get("created_at")) > 1:
        add(20, "not yet reached")
    no_shows = case.get("no_show_count", 0) or 0
    if no_shows:
        add(min(30 * no_shows, 60), f"missed {no_shows} appointment{'s' if no_shows > 1 else ''}")
    if case.get("overdue"):
        add(20, "past its deadline")
    if case.get("urgency") == "urgent":
        add(10, "urgent result")
    ref = case.get("referral") or {}
    if ref.get("status") == "declined":
        add(15, "referral declined, needs re-referral")
    if ref and ref.get("network_ok") is False:
        add(10, "facility may be outside insurance network")
    if status == "acknowledged" and _hours_since(case.get("acknowledged_at")) > 48:
        add(10, "engaged but not booked for 2+ days")
    if status == "booked":
        score = max(score - 25, 0)
    score = min(score, 100)
    level = "high" if score >= 50 else "medium" if score >= 25 else "low"
    return {"score": score, "level": level, "reasons": reasons}
