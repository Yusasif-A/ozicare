"""
Referral: the right service, at a facility in the person's region that takes
their insurance, accepted by the receiving clinician.

Slide step 03. Every actionable case gets a referral at intake (auto_refer),
the receiving side accepts or declines it (respond), clinicians on both sides
can leave consult notes on it (consult), and a declined referral is sent on to
the next suitable facility (re_refer).

FACILITIES is a demo directory with generic names. A pilot replaces it with
the DoH facility registry and the payers' network lists.
"""

from __future__ import annotations

import logging

from .db import db, new_id, now

logger = logging.getLogger("ozicare.referrals")

REGIONS = {"abu_dhabi": "Abu Dhabi", "al_ain": "Al Ain", "al_dhafra": "Al Dhafra"}
INSURANCES = ("Thiqa", "Daman Basic", "Daman Enhanced", "Private", "Self-pay")

# service -> (English label, Arabic label)
SERVICES = {
    "pc_bp_review": ("Primary care: blood pressure review", "الرعاية الأولية: مراجعة ضغط الدم"),
    "urgent_bp": ("Same-day urgent cardiometabolic review", "مراجعة عاجلة لأمراض القلب والتمثيل الغذائي في نفس اليوم"),
    "pc_diabetes_prevention": ("Primary care: diabetes prevention", "الرعاية الأولية: الوقاية من السكري"),
    "endocrinology": ("Diabetes & endocrinology clinic", "عيادة السكري والغدد الصماء"),
    "healthy_weight": ("Healthy weight clinic", "عيادة الوزن الصحي"),
    "colposcopy": ("Colposcopy clinic", "عيادة تنظير عنق الرحم"),
    "colonoscopy": ("Gastroenterology: colonoscopy", "الجهاز الهضمي: تنظير القولون"),
    "breast_diagnostic": ("Breast diagnostic clinic", "عيادة تشخيص الثدي"),
    "pc_review": ("Primary care review", "مراجعة في الرعاية الأولية"),
}

# (pathway, urgency) -> service. Missing urgency falls back to the pathway's
# "*" entry.
ROUTING = {
    ("hypertension", "urgent"): "urgent_bp",
    ("hypertension", "*"): "pc_bp_review",
    ("diabetes", "routine"): "pc_diabetes_prevention",
    ("diabetes", "*"): "endocrinology",
    ("obesity", "*"): "healthy_weight",
    ("cervical", "*"): "colposcopy",
    ("colorectal", "*"): "colonoscopy",
    ("breast", "*"): "breast_diagnostic",
    ("general", "*"): "pc_review",
}

# Which pathway a case belongs to when it was created without readings.
SCREENING_PATHWAY = {
    "blood_pressure": "hypertension",
    "diabetes": "diabetes",
    "obesity": "obesity",
    "cervical": "cervical",
    "colorectal": "colorectal",
    "breast": "breast",
    "general_abnormal": "general",
}

_ALL = list(INSURANCES)
_PUBLIC = ["Thiqa", "Daman Basic", "Daman Enhanced", "Self-pay"]
_PRIVATE = ["Thiqa", "Daman Enhanced", "Private", "Self-pay"]

FACILITIES = [
    {
        "id": "FAC-AD-PHC",
        "name": {"en": "Abu Dhabi Central Primary Health Centre", "ar": "مركز أبوظبي المركزي للرعاية الصحية الأولية"},
        "address": {"en": "Al Khalidiyah, Abu Dhabi", "ar": "الخالدية، أبوظبي"},
        "region": "abu_dhabi",
        "services": ["pc_bp_review", "pc_diabetes_prevention", "healthy_weight", "pc_review"],
        "networks": _ALL,
    },
    {
        "id": "FAC-AD-SPEC",
        "name": {"en": "Abu Dhabi Specialist Hospital", "ar": "مستشفى أبوظبي التخصصي"},
        "address": {"en": "Al Maqtaa, Abu Dhabi", "ar": "المقطع، أبوظبي"},
        "region": "abu_dhabi",
        "services": ["urgent_bp", "endocrinology", "colposcopy", "colonoscopy", "breast_diagnostic"],
        "networks": _PUBLIC,
    },
    {
        "id": "FAC-AD-WOMEN",
        "name": {"en": "Corniche Women's Health Centre", "ar": "مركز الكورنيش لصحة المرأة"},
        "address": {"en": "Corniche Road, Abu Dhabi", "ar": "شارع الكورنيش، أبوظبي"},
        "region": "abu_dhabi",
        "services": ["colposcopy", "breast_diagnostic"],
        "networks": _PRIVATE,
    },
    {
        "id": "FAC-AA-PHC",
        "name": {"en": "Al Ain Family Health Centre", "ar": "مركز العين لصحة الأسرة"},
        "address": {"en": "Al Jimi, Al Ain", "ar": "الجيمي، العين"},
        "region": "al_ain",
        "services": ["pc_bp_review", "pc_diabetes_prevention", "healthy_weight", "pc_review"],
        "networks": _ALL,
    },
    {
        "id": "FAC-AA-SPEC",
        "name": {"en": "Al Ain Regional Hospital", "ar": "مستشفى العين الإقليمي"},
        "address": {"en": "Al Mutawaa, Al Ain", "ar": "المطوع، العين"},
        "region": "al_ain",
        "services": ["urgent_bp", "endocrinology", "colposcopy", "colonoscopy", "breast_diagnostic"],
        "networks": _PUBLIC,
    },
    {
        "id": "FAC-DH-PHC",
        "name": {"en": "Madinat Zayed Health Centre", "ar": "مركز مدينة زايد الصحي"},
        "address": {"en": "Madinat Zayed, Al Dhafra", "ar": "مدينة زايد، الظفرة"},
        "region": "al_dhafra",
        "services": ["pc_bp_review", "pc_diabetes_prevention", "healthy_weight", "pc_review", "urgent_bp"],
        "networks": _ALL,
    },
    {
        "id": "FAC-DH-HOSP",
        "name": {"en": "Ruwais Regional Hospital", "ar": "مستشفى الرويس الإقليمي"},
        "address": {"en": "Ruwais, Al Dhafra", "ar": "الرويس، الظفرة"},
        "region": "al_dhafra",
        "services": ["endocrinology", "colposcopy", "breast_diagnostic"],
        "networks": _PUBLIC,
    },
]
FACILITY_BY_ID = {f["id"]: f for f in FACILITIES}

# Where to send someone when their own region has no facility for a service.
NEAREST = {"al_dhafra": ["abu_dhabi", "al_ain"], "al_ain": ["abu_dhabi", "al_dhafra"], "abu_dhabi": ["al_ain", "al_dhafra"]}


def service_for(pathway: str, urgency: str) -> str:
    return ROUTING.get((pathway, urgency)) or ROUTING.get((pathway, "*")) or "pc_review"


def choose_facility(service: str, region: str, insurance: str, exclude: set[str] | None = None) -> tuple[dict | None, bool]:
    """
    Best facility for the service: own region and in network, then own region
    out of network, then the nearest regions. Returns (facility, network_ok).
    """
    exclude = exclude or set()
    region = region if region in REGIONS else "abu_dhabi"
    candidates = [f for f in FACILITIES if service in f["services"] and f["id"] not in exclude]
    for reg in [region, *NEAREST[region]]:
        in_net = [f for f in candidates if f["region"] == reg and (not insurance or insurance in f["networks"])]
        if in_net:
            return in_net[0], True
    own = [f for f in candidates if f["region"] == region]
    if own:
        return own[0], False
    return (candidates[0], False) if candidates else (None, False)


def facility_public(f: dict | None, lang: str = "en") -> dict | None:
    if not f:
        return None
    return {"id": f["id"], "name": f["name"][lang], "address": f["address"][lang], "region": f["region"], "region_label": REGIONS[f["region"]]}


def clinic_for(case: dict, lang: str) -> dict:
    """The clinic a patient is told about: the referral's facility, else the demo clinic."""
    from .content import CLINIC

    ref = case.get("referral") or {}
    f = FACILITY_BY_ID.get(ref.get("facility_id", ""))
    if f:
        return {"name": f["name"][lang], "address": f["address"][lang]}
    return CLINIC[lang if lang in CLINIC else "en"]


def _build(case: dict, service: str, facility: dict | None, network_ok: bool, previous: list | None = None) -> dict:
    return {
        "id": new_id("RF"),
        "service": service,
        "service_label": SERVICES[service][0],
        "facility_id": facility["id"] if facility else None,
        "facility_name": facility["name"]["en"] if facility else None,
        "facility_region": facility["region"] if facility else None,
        "patient_region": case.get("region") or "abu_dhabi",
        "insurance": case.get("insurance") or "",
        "network_ok": network_ok,
        "status": "sent" if facility else "no_facility",
        "sent_at": now(),
        "responded_at": None,
        "responder": None,
        "response_note": "",
        "consult": [],
        "previous": previous or [],
    }


async def auto_refer(case: dict) -> dict:
    """Create the referral for a new case and record it. Returns the referral."""
    from . import cases

    pathway = case.get("pathway") or SCREENING_PATHWAY.get(case["screening_type"], "general")
    service = service_for(pathway, case["urgency"])
    facility, network_ok = choose_facility(service, case.get("region", ""), case.get("insurance", ""))
    ref = _build(case, service, facility, network_ok)
    await cases.update_case(case["_id"], {"referral": ref, "pathway": pathway})
    await cases.log_event(
        case["_id"],
        "system",
        "referral_sent",
        {"service": ref["service_label"], "facility": ref["facility_name"], "region": REGIONS.get(ref["facility_region"] or "", ""), "insurance": ref["insurance"], "network_ok": network_ok},
    )
    logger.info("Case %s referred to %s at %s", case["_id"], service, ref["facility_name"])
    return ref


async def respond(case: dict, accept: bool, *, staff: dict, note: str = "") -> dict:
    """The receiving clinician accepts or declines the referral."""
    from . import cases

    ref = case.get("referral")
    if not ref:
        raise ValueError("this case has no referral")
    if ref["status"] not in ("sent",):
        raise ValueError(f"referral is already {ref['status']}")
    if not accept and not note.strip():
        raise ValueError("declining a referral needs a reason for the referring team")
    ref = {**ref, "status": "accepted" if accept else "declined", "responded_at": now(), "responder": staff["name"], "response_note": note.strip()}
    case = await cases.update_case(case["_id"], {"referral": ref})
    await cases.log_event(case["_id"], "staff", "referral_accepted" if accept else "referral_declined", {"facility": ref["facility_name"], "by": staff["name"], "note": note}, staff["_id"])
    return case


async def consult(case: dict, *, staff: dict, text: str) -> dict:
    """Clinician-to-clinician note on the referral, visible to both teams."""
    from . import cases

    ref = case.get("referral")
    if not ref:
        raise ValueError("this case has no referral")
    entry = {"by": staff["name"], "role": staff["role"], "text": text.strip(), "at": now()}
    case = await cases.update_case(case["_id"], {"referral": {**ref, "consult": [*ref.get("consult", []), entry]}})
    await cases.log_event(case["_id"], "staff", "consult_note", {"by": staff["name"], "text": text.strip()}, staff["_id"])
    return case


async def re_refer(case: dict, *, staff: dict | None, facility_id: str | None = None, service: str | None = None, note: str = "") -> dict:
    """Send the referral on: to a chosen facility, or the next suitable one."""
    from . import cases

    old = case.get("referral") or {}
    service = service or old.get("service") or service_for(case.get("pathway") or "general", case["urgency"])
    if service not in SERVICES:
        raise ValueError(f"unknown service {service}")
    tried = {p.get("facility_id") for p in old.get("previous", [])} | {old.get("facility_id")}
    if facility_id:
        facility = FACILITY_BY_ID.get(facility_id)
        if not facility or service not in facility["services"]:
            raise ValueError("that facility does not offer this service")
        network_ok = not case.get("insurance") or case["insurance"] in facility["networks"]
    else:
        facility, network_ok = choose_facility(service, case.get("region", ""), case.get("insurance", ""), exclude={t for t in tried if t})
    history = [*old.get("previous", []), {k: old.get(k) for k in ("facility_name", "facility_id", "status", "response_note", "responder")}] if old else []
    ref = _build(case, service, facility, network_ok, history)
    case = await cases.update_case(case["_id"], {"referral": ref})
    await cases.log_event(
        case["_id"],
        "staff" if staff else "system",
        "referral_sent",
        {"service": ref["service_label"], "facility": ref["facility_name"], "re_referral": True, "note": note, "network_ok": network_ok},
        staff["_id"] if staff else None,
    )
    return case


def directory() -> dict:
    return {
        "regions": REGIONS,
        "insurances": INSURANCES,
        "services": {k: v[0] for k, v in SERVICES.items()},
        "facilities": [{**facility_public(f), "services": f["services"], "networks": f["networks"]} for f in FACILITIES],
    }
