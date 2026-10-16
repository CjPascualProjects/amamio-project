"""Facility records — the client's paper forms for the production site.

* General Cleaning & Sanitation Record — every production day the five
  areas are checked before (PRE-PRODUCTION) and after (POST-PRODUCTION)
  work.  An area that is not clean gets an action to undertake; it stays
  "open" until the date it was undertaken is filled in.
* Pest Control Monitoring Record (QMS-PCMR, Rev. 01) — done once a month,
  one row per area: pest activity seen, observation, corrective action and
  the signature of the monitoring in-charge.

Storage follows ``db.SCHEMA``: ``sanitation_records`` (child list
``areas``) and ``pest_control_records`` (child list ``areas``).

Public helpers other modules may call (e.g. the home page):
    open_sanitation_actions()   list of areas still needing action
    open_sanitation_count()     how many
    sanitation_summary()        figures for the sanitation page
    pest_months(n)              last n months, done / missing
    pest_due()                  True when this month's inspection is missing
    facility_overview()         small dict of the above for dashboards
"""
from datetime import date, timedelta

import db
import services

# --- Cleaning & sanitation ---------------------------------------------------
PRE = "PRE-PRODUCTION"
POST = "POST-PRODUCTION"
SANITATION_PHASES = [PRE, POST]
# How each phase is headed on the paper form.
PHASE_PAPER = {PRE: "PRE-PRODUCTION", POST: "POST PRODUCTION"}

LOCATIONS = ["Locker Room", "Storage Area", "Washing Area", "Production Area",
             "Finished Products Area"]
# The paper abbreviates the last location.
LOCATION_PAPER = {"Finished Products Area": "Finished Prod. Area"}

CLEAN = "Clean"
NEEDS_CLEANING = "Needs cleaning"
NEEDS_REPAIR = "Needs repair"
NOT_CHECKED = "Not checked"
SANITATION_STATUSES = [CLEAN, NEEDS_CLEANING, NEEDS_REPAIR, NOT_CHECKED]
ACTION_STATUSES = (NEEDS_CLEANING, NEEDS_REPAIR)
STATUS_BADGE = {CLEAN: "badge-ok", NEEDS_CLEANING: "badge-warn",
                NEEDS_REPAIR: "badge-danger", NOT_CHECKED: "badge-muted"}

# --- Pest control ------------------------------------------------------------
PEST_AREAS = ["Locker Room", "Storage Area", "Washing Area", "Production Area",
              "Finished Products Area"]
PEST_DOC_NO = "QMS-PCMR"
PEST_REVISION = "01"
PEST_ISSUE_DATE = "2026-01-05"
NO_ACTIVITY = "No pest activity observed"


class RecordError(ValueError):
    """A record could not be saved.  ``step`` is the wizard step to reopen."""

    def __init__(self, message, step=0):
        super().__init__(message)
        self.step = step


# --- Small date helpers ------------------------------------------------------
def _parse_date(value):
    try:
        return date.fromisoformat((value or "").strip()[:10])
    except ValueError:
        return None


def nice_date(value, with_year=False):
    """'2026-10-16' -> 'Fri, 16 Oct' (or 'Fri, 16 Oct 2026')."""
    d = _parse_date(value)
    if not d:
        return value or "—"
    return d.strftime("%a, %d %b %Y" if with_year else "%a, %d %b")


def relative_day(value):
    """'Today' / 'Yesterday' / 'Fri, 16 Oct' — for the figures strip."""
    d = _parse_date(value)
    if not d:
        return "—"
    delta = (date.today() - d).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Yesterday"
    return d.strftime("%d %b")


def month_label(period, short=False):
    """'2026-10' -> 'October 2026' (or 'Oct')."""
    try:
        y, m = (int(x) for x in period.split("-"))
        d = date(y, m, 1)
    except (ValueError, AttributeError):
        return period or "—"
    return d.strftime("%b" if short else "%B %Y")


def shift_month(period, delta):
    y, m = (int(x) for x in period.split("-"))
    m += delta
    while m < 1:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    return "%04d-%02d" % (y, m)


def month_last_day(period):
    """'2026-09' -> '2026-09-30' (capped at today)."""
    nxt = shift_month(period, 1)
    y, m = (int(x) for x in nxt.split("-"))
    last = date(y, m, 1) - timedelta(days=1)
    return min(last, date.today()).isoformat()


def week_start():
    today = date.today()
    return (today - timedelta(days=today.weekday())).isoformat()


# =============================================================================
# Cleaning & sanitation
# =============================================================================
def area_needs_action(area):
    """An area marked dirty / broken whose action has not been undertaken."""
    return (area.get("current_status") in ACTION_STATUSES
            and not area.get("date_undertaken"))


def sanitation_records(date_from=None, date_to=None):
    """Records newest first, optionally within [date_from, date_to]."""
    rows = []
    for r in db.read("sanitation_records"):
        d = r.get("record_date") or ""
        if date_from and d < date_from:
            continue
        if date_to and d > date_to:
            continue
        rows.append(r)
    phase_order = {PRE: 0, POST: 1}
    rows.sort(key=lambda r: (r.get("record_date") or "",
                             phase_order.get(r.get("phase"), 2),
                             r.get("id", 0)), reverse=True)
    return rows


def sanitation_view(rec):
    """A record decorated for templates."""
    areas = []
    for i, a in enumerate(rec.get("areas") or []):
        status = a.get("current_status") or NOT_CHECKED
        areas.append(dict(a, index=i, current_status=status,
                          badge=STATUS_BADGE.get(status, "badge-muted"),
                          is_open=area_needs_action(a),
                          paper_location=LOCATION_PAPER.get(a.get("location"),
                                                            a.get("location"))))
    open_areas = [a for a in areas if a["is_open"]]
    flagged = [a for a in areas if a["current_status"] in ACTION_STATUSES]
    clean = sum(1 for a in areas if a["current_status"] == CLEAN)
    parts = ["%d area%s" % (len(areas), "" if len(areas) == 1 else "s")]
    if open_areas:
        parts.append("%d need%s action" % (len(open_areas),
                                           "s" if len(open_areas) == 1 else ""))
    elif flagged:
        parts.append("%d fixed" % len(flagged))
    else:
        parts.append("all clean" if clean == len(areas) else "%d clean" % clean)
    not_checked = sum(1 for a in areas if a["current_status"] == NOT_CHECKED)
    if not_checked and not open_areas:
        parts.append("%d not checked" % not_checked)
    return dict(rec, areas=areas, open_areas=open_areas, flagged=flagged,
                open_count=len(open_areas), not_checked=not_checked,
                summary=" · ".join(parts),
                nice_date=nice_date(rec.get("record_date"), with_year=True),
                short_date=nice_date(rec.get("record_date")),
                paper_phase=PHASE_PAPER.get(rec.get("phase"), rec.get("phase")),
                recorded_by_name=services.user_name(rec.get("recorded_by")),
                created=services.fmt_dt(rec.get("created_at")))


def open_sanitation_actions():
    """Every area still needing action, oldest first — for the 'Needs action'
    view and the home page."""
    rows = []
    for rec in sanitation_records():
        for i, a in enumerate(rec.get("areas") or []):
            if area_needs_action(a):
                rows.append({
                    "record_id": rec["id"], "index": i,
                    "record_date": rec.get("record_date"),
                    "nice_date": nice_date(rec.get("record_date")),
                    "phase": rec.get("phase"),
                    "location": a.get("location"),
                    "current_status": a.get("current_status"),
                    "badge": STATUS_BADGE.get(a.get("current_status"), "badge-muted"),
                    "action": a.get("action") or "",
                    "remarks": a.get("remarks") or "",
                })
    rows.sort(key=lambda r: (r["record_date"] or "", r["record_id"]))
    return rows


def open_sanitation_count():
    return len(open_sanitation_actions())


def sanitation_summary():
    """Figures for the top of the sanitation page."""
    records = sanitation_records()
    month = services.this_month()
    last = {}
    for r in records:                      # newest first
        last.setdefault(r.get("phase"), r.get("record_date"))
    return {
        "month_count": sum(1 for r in records
                           if (r.get("record_date") or "").startswith(month)),
        "open_actions": open_sanitation_count(),
        "last_pre": relative_day(last.get(PRE)),
        "last_post": relative_day(last.get(POST)),
        "last_pre_iso": last.get(PRE),
        "last_post_iso": last.get(POST),
    }


def _clean(value, limit=300):
    return (value or "").strip()[:limit]


def save_sanitation(user_id, record_date, phase, areas, conducted_by,
                    inspected_by, remarks="", notify=True):
    """Save one General Cleaning & Sanitation Record.

    ``areas`` is a list (in LOCATIONS order) of dicts with current_status,
    action, date_undertaken, remarks.  Raises RecordError(message, step) where
    step is the wizard step to reopen (0 = date & phase, 1..5 = an area,
    6 = people)."""
    d = _parse_date(record_date)
    if not d:
        raise RecordError("Pick the date the areas were checked.", 0)
    if d > date.today():
        raise RecordError("The date can't be in the future.", 0)
    if phase not in SANITATION_PHASES:
        raise RecordError("Choose PRE-PRODUCTION or POST-PRODUCTION.", 0)
    for r in db.read("sanitation_records"):
        if r.get("record_date") == d.isoformat() and r.get("phase") == phase:
            raise RecordError("The %s check for %s is already recorded."
                              % (phase.lower(), nice_date(d.isoformat())), 0)
    if len(areas) != len(LOCATIONS):
        raise RecordError("Check all five areas.", 1)

    rows = []
    for i, (location, a) in enumerate(zip(LOCATIONS, areas)):
        status = (a.get("current_status") or "").strip()
        if status not in SANITATION_STATUSES:
            raise RecordError("Choose the current status of the %s." % location, i + 1)
        row = {"location": location, "current_status": status, "action": "",
               "date_undertaken": None, "remarks": _clean(a.get("remarks"))}
        if status in ACTION_STATUSES:
            row["action"] = _clean(a.get("action"))
            if not row["action"]:
                raise RecordError("Say what will be done about the %s." % location, i + 1)
            if a.get("date_undertaken"):
                done = _parse_date(a.get("date_undertaken"))
                if not done:
                    raise RecordError("The date undertaken for the %s is not a valid date."
                                      % location, i + 1)
                if done < d:
                    raise RecordError("The %s can't be fixed before it was checked."
                                      % location, i + 1)
                if done > date.today():
                    raise RecordError("The date undertaken can't be in the future.", i + 1)
                row["date_undertaken"] = done.isoformat()
        elif status == NOT_CHECKED:
            row["action"] = _clean(a.get("action"))
        rows.append(row)

    conducted_by = _clean(conducted_by, 80)
    inspected_by = _clean(inspected_by, 80)
    if not conducted_by:
        raise RecordError("Who conducted the cleaning?", 6)
    if not inspected_by:
        raise RecordError("Who inspected the areas?", 6)

    rec = db.insert("sanitation_records", {
        "record_date": d.isoformat(), "phase": phase,
        "conducted_by": conducted_by, "inspected_by": inspected_by,
        "remarks": _clean(remarks, 500), "recorded_by": user_id,
        "created_at": services.now_iso(), "areas": rows,
    })
    repairs = [r["location"] for r in rows
               if r["current_status"] == NEEDS_REPAIR and not r["date_undertaken"]]
    if notify and repairs:
        services.notify_team(
            {"assets_head"},
            "Repair needed (%s, %s): %s." % (phase.lower(), nice_date(rec["record_date"]),
                                              ", ".join(repairs)),
            link="/facility/sanitation/%d" % rec["id"])
    return rec


def mark_sanitation_done(record_id, index, date_undertaken, remarks=None, user_id=None):
    """Fill in the DATE UNDERTAKEN of one area's action.  Returns the record."""
    rec = db.get("sanitation_records", record_id)
    if not rec:
        raise RecordError("That record no longer exists.")
    areas = rec.get("areas") or []
    try:
        index = int(index)
        area = areas[index]
    except (TypeError, ValueError, IndexError):
        raise RecordError("That area is not on this record.")
    if area.get("current_status") not in ACTION_STATUSES:
        raise RecordError("The %s did not need any action." % area.get("location"))
    if area.get("date_undertaken"):
        raise RecordError("The action for the %s was already done." % area.get("location"))
    done = _parse_date(date_undertaken)
    if not done:
        raise RecordError("Enter the date the action was undertaken.")
    if done > date.today():
        raise RecordError("The date undertaken can't be in the future.")
    if rec.get("record_date") and done.isoformat() < rec["record_date"]:
        raise RecordError("The action can't be done before the area was checked.")
    area["date_undertaken"] = done.isoformat()
    if remarks and remarks.strip():
        note = _clean(remarks)
        area["remarks"] = "%s; %s" % (area["remarks"], note) if area.get("remarks") else note
    return db.update("sanitation_records", rec["id"], {"areas": areas})


def sanitation_paper_rows(date_from, date_to):
    """Rows for the printable form: grouped by date, then PRE / POST headings
    with the five locations each — oldest first, as written on paper."""
    by_date = {}
    for r in sanitation_records(date_from, date_to):
        by_date.setdefault(r["record_date"], {})[r.get("phase")] = sanitation_view(r)
    groups = []
    for d in sorted(by_date):
        phases = []
        for phase in SANITATION_PHASES:
            rec = by_date[d].get(phase)
            if rec:
                phases.append(rec)
        groups.append({"date": d, "nice_date": nice_date(d, with_year=True),
                       "records": phases})
    return groups


# =============================================================================
# Pest control
# =============================================================================
def pest_records():
    rows = db.read("pest_control_records")
    rows.sort(key=lambda r: (r.get("period") or "", r.get("record_date") or "",
                             r.get("id", 0)), reverse=True)
    return rows


def pest_record_for(period):
    for r in db.read("pest_control_records"):
        if r.get("period") == period:
            return r
    return None


def pest_view(rec):
    areas = []
    for a in rec.get("areas") or []:
        areas.append(dict(a, pest_activity=bool(a.get("pest_activity"))))
    found = [a for a in areas if a["pest_activity"]]
    if found:
        summary = "Pest activity in %s" % ", ".join(a.get("area") for a in found)
    else:
        summary = "%d areas · no pest activity" % len(areas)
    return dict(rec, areas=areas, found=found, activity_count=len(found),
                summary=summary, month=month_label(rec.get("period")),
                nice_date=nice_date(rec.get("record_date"), with_year=True),
                recorded_by_name=services.user_name(rec.get("recorded_by")),
                created=services.fmt_dt(rec.get("created_at")))


def pest_months(n=12):
    """The last ``n`` months (oldest first) with their state:

    done      — inspection recorded (``activity`` True if pests were seen)
    due       — this month, not yet recorded
    missing   — a past month that was skipped
    untracked — before the first inspection ever recorded
    """
    records = {r.get("period"): r for r in db.read("pest_control_records")}
    first = min(records) if records else None
    current = services.this_month()
    months = []
    for k in range(n - 1, -1, -1):
        period = shift_month(current, -k)
        rec = records.get(period)
        if rec:
            state = "done"
        elif period == current:
            state = "due"
        elif first and period > first:
            state = "missing"
        else:
            state = "untracked"
        months.append({
            "period": period, "label": month_label(period, short=True),
            "year": period[:4], "long": month_label(period), "state": state,
            "record_id": rec["id"] if rec else None,
            "activity": bool(rec and any(a.get("pest_activity")
                                         for a in rec.get("areas") or [])),
            "is_current": period == current,
        })
    return months


def pest_due():
    return pest_record_for(services.this_month()) is None


def pest_missing_count(n=12):
    return sum(1 for m in pest_months(n) if m["state"] == "missing")


def save_pest(user_id, period, record_date, areas, monitored_by, remarks="",
              notify=True):
    """Save one month's Pest Control Monitoring Record.

    ``areas`` (in PEST_AREAS order) are dicts with pest_activity (bool),
    observation, corrective_action.  Raises RecordError(message, step):
    0 = month & date, 1..5 = an area, 6 = monitored by."""
    period = (period or "").strip()[:7]
    try:
        shift_month(period, 0)
        if len(period) != 7 or period[4] != "-":
            raise ValueError
    except (ValueError, AttributeError):
        raise RecordError("Pick the month being inspected.", 0)
    if period > services.this_month():
        raise RecordError("You can't record a month that hasn't started.", 0)
    d = _parse_date(record_date)
    if not d:
        raise RecordError("Enter the date of monitoring.", 0)
    if d > date.today():
        raise RecordError("The date of monitoring can't be in the future.", 0)
    if d.isoformat()[:7] != period:
        raise RecordError("The date of monitoring must fall in %s." % month_label(period), 0)
    if pest_record_for(period):
        raise RecordError("The inspection for %s is already recorded." % month_label(period), 0)
    if len(areas) != len(PEST_AREAS):
        raise RecordError("Inspect all five areas.", 1)
    monitored_by = _clean(monitored_by, 80)

    rows = []
    for i, (name, a) in enumerate(zip(PEST_AREAS, areas)):
        activity = a.get("pest_activity")
        if activity is None:
            raise RecordError("Was there any pest activity in the %s?" % name, i + 1)
        activity = bool(activity)
        observation = _clean(a.get("observation"))
        corrective = _clean(a.get("corrective_action"))
        if activity and not observation:
            raise RecordError("Describe what was seen in the %s." % name, i + 1)
        if activity and not corrective:
            raise RecordError("Pest activity in the %s needs a corrective action." % name, i + 1)
        rows.append({"area": name, "pest_activity": activity,
                     "observation": observation or NO_ACTIVITY,
                     "corrective_action": corrective if activity else (corrective or ""),
                     "signed_by": monitored_by})
    if not monitored_by:
        raise RecordError("Who did the monitoring? Their name is the signature.", 6)

    rec = db.insert("pest_control_records", {
        "period": period, "record_date": d.isoformat(),
        "monitored_by": monitored_by, "remarks": _clean(remarks, 500),
        "recorded_by": user_id, "created_at": services.now_iso(), "areas": rows,
    })
    found = [r["area"] for r in rows if r["pest_activity"]]
    if notify and found:
        services.notify_team(
            {"assets_head"},
            "Pest activity found (%s): %s." % (month_label(period), ", ".join(found)),
            link="/facility/pest/%d" % rec["id"])
    return rec


def pest_paper_rows(date_from, date_to):
    rows = [pest_view(r) for r in pest_records()
            if date_from <= (r.get("record_date") or "") <= date_to]
    rows.sort(key=lambda r: r.get("record_date") or "")
    return rows


# =============================================================================
# Dashboard helper
# =============================================================================
def facility_overview():
    """Small summary for the home page."""
    return {
        "open_sanitation_actions": open_sanitation_count(),
        "pest_due": pest_due(),
        "pest_missing": pest_missing_count(),
        "sanitation_today": [r.get("phase") for r in db.read("sanitation_records")
                             if r.get("record_date") == services.today_iso()],
    }


# =============================================================================
# Demo data
# =============================================================================
def _working_days(count):
    """The last ``count`` weekdays before today, oldest first."""
    days, d = [], date.today()
    while len(days) < count:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            days.append(d)
    return list(reversed(days))


def seed_demo(users):
    """Example sanitation records for the last five working days and pest
    control inspections for the previous two months and this month."""
    users = users or {}
    assets = users.get("assets_head") or users.get("assets") or {}
    prod = users.get("production_head") or users.get("production") or {}
    uid = assets.get("id") or prod.get("id")
    conducted = assets.get("name") or "Assets Maintenance Head"
    inspected = prod.get("name") or "Production Team Head"

    clean = [{"current_status": CLEAN} for _ in LOCATIONS]
    days = _working_days(5)
    for n, d in enumerate(days):
        for phase in SANITATION_PHASES:
            areas = [dict(a) for a in clean]
            remarks = ""
            if n == 1 and phase == POST:
                areas[2] = {"current_status": NEEDS_CLEANING,
                            "action": "Scrub floor drain and wash basins with chlorine solution",
                            "date_undertaken": d.isoformat(),
                            "remarks": "Honey residue around the basins"}
            if n == len(days) - 1 and phase == POST:
                areas[2] = {"current_status": NEEDS_REPAIR,
                            "action": "Replace leaking faucet at the washing sink",
                            "date_undertaken": "",
                            "remarks": "Water pooling under the sink"}
                remarks = "Faucet repair reported to assets maintenance."
            if n == 3 and phase == PRE:
                areas[0] = {"current_status": NOT_CHECKED, "action": "",
                            "remarks": "Locker room key with the guard"}
            try:
                save_sanitation(uid, d.isoformat(), phase, areas, conducted,
                                inspected, remarks=remarks)
            except RecordError:
                continue

    current = services.this_month()
    today = date.today()
    for back in (2, 1, 0):
        period = shift_month(current, -back)
        y, m = (int(x) for x in period.split("-"))
        day = date(y, m, 5)
        if day > today:
            day = today
        areas = [{"pest_activity": False, "observation": ""} for _ in PEST_AREAS]
        if back == 1:
            areas[1] = {"pest_activity": True,
                        "observation": "Rat droppings near the sugar sacks",
                        "corrective_action": "Set bait stations, sealed gap under the door, "
                                             "sacks raised on pallets"}
        try:
            save_pest(uid, period, day.isoformat(), areas, conducted)
        except RecordError:
            continue
