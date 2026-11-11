"""
FHIR R4 connector: how OziCare can plug into a national health app (e.g. Sahatna) or shared
record (e.g. Malaffi) without either
side writing custom glue.

In  POST /fhir/Bundle   A transaction or collection Bundle carrying the
                        Patient and the screening Observations (LOINC). The
                        risk rules decide whether it is actionable; if so a
                        case opens and the referral goes out.
    POST /fhir/Encounter An Encounter for the referral (status=finished)
                        closes the loop: attended, time to assessment
                        recorded. status=cancelled with reason "no-show"
                        triggers re-booking.
Out GET  /fhir/ServiceRequest/{case}  the referral, for the receiving facility
    GET  /fhir/Appointment/{case}     the booking, for the health app to show
    GET  /fhir/Task/{case}            loop status, for the health app to show

Patients are matched by Emirates ID (identifier system below), falling back
to phone. Only the fields OziCare needs are read; everything else in the
resource is ignored, so a richer upstream payload never breaks intake.
"""

from __future__ import annotations

import logging
import re

from . import cases

logger = logging.getLogger("ozicare.fhir")

EMIRATES_ID_SYSTEM = "http://doh.gov.ae/fhir/identifier/emirates-id"
OZICARE_SYSTEM = "https://ozicare.publicaai.com/fhir/case"

# LOINC -> reading key used by risk.RULES
LOINC = {
    "8480-6": "systolic",
    "8462-4": "diastolic",
    "4548-4": "hba1c",
    "17856-6": "hba1c",
    "1558-6": "fasting_glucose",
    "2339-0": "random_glucose",
    "2345-7": "random_glucose",
    "39156-5": "bmi",
    "19762-4": "cervical_cytology",
    "10524-7": "cervical_cytology",
    "77379-6": "cervical_cytology",  # HPV
    "29771-3": "fit",
    "57905-2": "fit",
    "36625-2": "birads",  # mammogram study
    "24606-6": "birads",
}
# BP panel components arrive inside one Observation.
BP_PANEL = "85354-9"

REGION_WORDS = {"al ain": "al_ain", "alain": "al_ain", "dhafra": "al_dhafra", "abu dhabi": "abu_dhabi", "abudhabi": "abu_dhabi"}


class FhirError(ValueError):
    pass


def _codes(cc: dict | None) -> list[str]:
    return [c.get("code", "") for c in (cc or {}).get("coding", [])]


def _value(obs: dict):
    if "valueQuantity" in obs:
        return obs["valueQuantity"].get("value")
    if "valueCodeableConcept" in obs:
        vc = obs["valueCodeableConcept"]
        return vc.get("text") or " ".join(c.get("display") or c.get("code", "") for c in vc.get("coding", []))
    for k in ("valueString", "valueInteger", "valueBoolean"):
        if k in obs:
            return obs[k]
    return None


def readings_from_observations(observations: list[dict]) -> dict:
    out: dict = {}
    for obs in observations:
        codes = _codes(obs.get("code"))
        if BP_PANEL in codes or obs.get("component"):
            for comp in obs.get("component", []):
                key = next((LOINC[c] for c in _codes(comp.get("code")) if c in LOINC), None)
                if key:
                    out[key] = _value(comp)
            if BP_PANEL in codes:
                continue
        key = next((LOINC[c] for c in codes if c in LOINC), None)
        if key and _value(obs) is not None:
            if key == "birads":
                m = re.search(r"\b([0-6])\b", str(_value(obs)))
                out[key] = m.group(1) if m else _value(obs)
            else:
                out[key] = _value(obs)
    return out


def _patient_fields(p: dict) -> dict:
    name = (p.get("name") or [{}])[0]
    display = name.get("text") or " ".join([*name.get("given", []), name.get("family", "")]).strip()
    phone = next((t.get("value") for t in p.get("telecom", []) if t.get("system") == "phone"), "")
    eid = next((i.get("value") for i in p.get("identifier", []) if i.get("system") == EMIRATES_ID_SYSTEM), "")
    lang = "en"
    for comm in p.get("communication", []):
        if any(c.lower().startswith("ar") for c in _codes(comm.get("language"))):
            lang = "ar"
    region = ""
    for addr in p.get("address", []):
        text = " ".join([addr.get("city", ""), addr.get("district", ""), addr.get("state", ""), addr.get("text", "")]).lower()
        region = next((v for k, v in REGION_WORDS.items() if k in text), region)
    return {"display_name": display, "phone": phone, "emirates_id": eid, "language": lang, "region": region}


def _insurance(resources: list[dict]) -> str:
    for r in resources:
        if r.get("resourceType") == "Coverage":
            for payor in r.get("payor", []):
                text = (payor.get("display") or "").lower()
                plan = " ".join(c.get("value", "") for c in r.get("class", [])).lower()
                if "thiqa" in text:
                    return "Thiqa"
                if "daman" in text:
                    return "Daman Enhanced" if "enhanced" in plan else "Daman Basic"
                if text:
                    return "Private"
    return ""


async def ingest_bundle(bundle: dict, *, source: str = "fhir") -> dict:
    """Bundle in -> case (or a clear 'not actionable')."""
    if bundle.get("resourceType") != "Bundle":
        raise FhirError("expected a FHIR Bundle")
    resources = [e.get("resource", {}) for e in bundle.get("entry", [])]
    patients = [r for r in resources if r.get("resourceType") == "Patient"]
    observations = [r for r in resources if r.get("resourceType") == "Observation"]
    if not patients:
        raise FhirError("the Bundle has no Patient")
    if not observations:
        raise FhirError("the Bundle has no Observation")
    pf = _patient_fields(patients[0])
    if not pf["phone"]:
        raise FhirError("the Patient has no phone telecom: OziCare cannot reach them")
    readings = readings_from_observations(observations)
    if not readings:
        raise FhirError("no Observation carries a LOINC code OziCare screens on")

    from .risk import assess

    assessment = assess(readings)
    ref = bundle.get("identifier", {}).get("value") or observations[0].get("id") or ""
    if not assessment["actionable"]:
        logger.info("FHIR bundle %s: not actionable", ref)
        return {"actionable": False, "readings": readings, "message": "within agreed criteria, no case opened"}
    summary = "; ".join(f["reason"] for f in assessment["findings"])
    case = await cases.create_case(
        phone=pf["phone"],
        display_name=pf["display_name"] or "Patient",
        language=pf["language"],
        emirates_id=pf["emirates_id"],
        region=pf["region"],
        insurance=_insurance(resources),
        readings=readings,
        source=source,
        external_ref=ref,
        actor="system",
    )
    # Internal reasons are for staff; the patient sees only approved wording.
    await cases.log_event(case["_id"], "system", "fhir_ingested", {"bundle": ref, "readings": readings, "findings": summary})
    return {"actionable": True, "case_id": case["_id"], "urgency": case["urgency"], "pathway": case["pathway"], "referral": case["referral"]["service_label"]}


async def apply_encounter(enc: dict) -> dict:
    """Encounter from the facility -> attended / no-show on the matching case."""
    if enc.get("resourceType") != "Encounter":
        raise FhirError("expected a FHIR Encounter")
    case_id = ""
    for b in enc.get("basedOn", []):
        m = re.search(r"ServiceRequest/(OC-[0-9A-Fa-f]+)", b.get("reference", ""))
        if m:
            case_id = m.group(1).upper()
    for i in enc.get("identifier", []):
        if i.get("system") == OZICARE_SYSTEM:
            case_id = i.get("value", "").upper()
    if not case_id:
        raise FhirError("Encounter.basedOn must reference ServiceRequest/<OziCare case id>")
    case = await cases.get_case(case_id)
    if case is None:
        raise FhirError(f"no case {case_id}")
    status = enc.get("status")
    reason_text = " ".join(str(c.get("text", "")) + " ".join(_codes(c)) for c in enc.get("reasonCode", [])).lower()
    if status in ("finished", "in-progress", "arrived"):
        case = await cases.record_attendance(case, True, actor="system", note="Encounter received from facility")
    elif status == "cancelled" and ("no-show" in reason_text or "noshow" in reason_text or "did not attend" in reason_text):
        case = await cases.record_attendance(case, False, actor="system", note="Facility reported no-show")
    else:
        raise FhirError(f"Encounter status {status!r} does not change the loop")
    return {"case_id": case_id, "status": case["status"]}


# --------------------------------------------------------------------------
# Outbound resources
# --------------------------------------------------------------------------


def _patient_ref(case: dict) -> dict:
    ref = {"display": case["patient_name"]}
    if case.get("emirates_id"):
        ref["identifier"] = {"system": EMIRATES_ID_SYSTEM, "value": case["emirates_id"]}
    return ref


def _iso(v) -> str | None:
    return v.isoformat() if hasattr(v, "isoformat") else v


def service_request(case: dict) -> dict:
    ref = case.get("referral") or {}
    status = {"sent": "active", "accepted": "active", "declined": "revoked"}.get(ref.get("status", ""), "draft")
    if case["status"].startswith("closed"):
        status = "completed" if case["status"] == "closed_completed" else "revoked"
    return {
        "resourceType": "ServiceRequest",
        "id": case["_id"],
        "identifier": [{"system": OZICARE_SYSTEM, "value": case["_id"]}],
        "status": status,
        "intent": "order",
        "priority": {"urgent": "urgent", "soon": "asap"}.get(case["urgency"], "routine"),
        "code": {"text": ref.get("service_label", "")},
        "subject": _patient_ref(case),
        "performer": [{"display": ref.get("facility_name", "")}] if ref.get("facility_name") else [],
        "reasonCode": [{"text": f["reason"]} for f in case.get("risk_findings", [])],
        "authoredOn": _iso(ref.get("sent_at")),
        "insurance": [{"display": case["insurance"]}] if case.get("insurance") else [],
    }


def appointment(case: dict) -> dict | None:
    appt = case.get("appointment")
    if not appt:
        return None
    status = "fulfilled" if case.get("attended_at") else "booked"
    return {
        "resourceType": "Appointment",
        "id": case["_id"],
        "status": status,
        "basedOn": [{"reference": f"ServiceRequest/{case['_id']}"}],
        "start": appt["slot_iso"],
        "description": appt["label"],
        "participant": [
            {"actor": _patient_ref(case), "status": "accepted"},
            {"actor": {"display": appt["clinic"]}, "status": "accepted"},
        ],
    }


TASK_STATUS = {
    "new": "requested",
    "contacted": "requested",
    "acknowledged": "accepted",
    "booked": "in-progress",
    "in_care": "in-progress",
    "escalated": "on-hold",
    "closed_completed": "completed",
    "closed_declined": "rejected",
    "closed_lost": "failed",
    "closed_transferred": "cancelled",
}


def task(case: dict) -> dict:
    return {
        "resourceType": "Task",
        "id": case["_id"],
        "status": TASK_STATUS[case["status"]],
        "businessStatus": {"text": case["status"]},
        "intent": "order",
        "priority": {"urgent": "urgent", "soon": "asap"}.get(case["urgency"], "routine"),
        "focus": {"reference": f"ServiceRequest/{case['_id']}"},
        "for": _patient_ref(case),
        "owner": {"display": case.get("owner_name") or ""},
        "authoredOn": _iso(case["created_at"]),
        "lastModified": _iso(case["updated_at"]),
    }


def capability() -> dict:
    return {
        "resourceType": "CapabilityStatement",
        "status": "active",
        "kind": "instance",
        "fhirVersion": "4.0.1",
        "format": ["json"],
        "rest": [
            {
                "mode": "server",
                "resource": [
                    {"type": "Bundle", "interaction": [{"code": "create"}]},
                    {"type": "Encounter", "interaction": [{"code": "create"}]},
                    {"type": "ServiceRequest", "interaction": [{"code": "read"}]},
                    {"type": "Appointment", "interaction": [{"code": "read"}]},
                    {"type": "Task", "interaction": [{"code": "read"}]},
                ],
            }
        ],
    }


def example_bundle(phone: str = "+971500000000", name: str = "Mariam Al Mansoori") -> dict:
    """A ready-to-send sample, used in the README and the dashboard."""
    given, _, family = name.partition(" ")
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "identifier": {"system": "urn:screening-programme:result", "value": "SCR-2026-000123"},
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "identifier": [{"system": EMIRATES_ID_SYSTEM, "value": "784-1985-1234567-1"}],
                    "name": [{"given": [given], "family": family}],
                    "telecom": [{"system": "phone", "value": phone}],
                    "communication": [{"language": {"coding": [{"code": "ar"}]}}],
                    "address": [{"city": "Al Ain"}],
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "status": "final",
                    "code": {"coding": [{"system": "http://loinc.org", "code": BP_PANEL}]},
                    "component": [
                        {"code": {"coding": [{"system": "http://loinc.org", "code": "8480-6"}]}, "valueQuantity": {"value": 168, "unit": "mmHg"}},
                        {"code": {"coding": [{"system": "http://loinc.org", "code": "8462-4"}]}, "valueQuantity": {"value": 102, "unit": "mmHg"}},
                    ],
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "status": "final",
                    "code": {"coding": [{"system": "http://loinc.org", "code": "4548-4"}]},
                    "valueQuantity": {"value": 7.2, "unit": "%"},
                }
            },
            {"resource": {"resourceType": "Coverage", "status": "active", "payor": [{"display": "Thiqa"}]}},
        ],
    }
