"""Turn the API payload into WhatsApp message text."""
from datetime import datetime


def _v(value) -> str:
    value = (str(value).strip() if value is not None else "")
    return value or "-"


def _date_label(day: str) -> str:
    return datetime.strptime(day, "%Y-%m-%d").strftime("%d-%m-%Y")


def _time_label(hhmm) -> str:
    if not hhmm:
        return "Not specified"
    return datetime.strptime(hhmm, "%H:%M").strftime("%I:%M %p").lstrip("0")


def _representing(h: dict) -> str:
    # API gives a label ("Judgment Debtor") and a key ("judgment_debtor").
    label = h.get("representing_label")
    if not label and h.get("representing"):
        label = str(h["representing"]).replace("_", " ").title()
    return _v(label)


def build_messages(payload: dict) -> list[tuple[str, str]]:
    """One message per hearing, as (key, text) pairs.

    The key (the hearing id) lets the sender remember which cases went out,
    so a retry after a partial failure does not repeat them.
    Returns [] when there are no hearings.
    """
    day = payload["date"]
    hearings = payload.get("hearings", [])
    total = len(hearings)

    messages = []
    for i, h in enumerate(hearings, 1):
        text = "\n".join([
            f"*ABI LAW FIRM - Hearing {i} of {total}*",
            "",
            f"*Case No:* {_v(h.get('case_no'))}",
            f"*Case Name:* {_v(h.get('case_name'))}",
            f"*Court Name:* {_v(h.get('court_name'))}",
            f"*Party Name:* {_v(h.get('party_name'))}",
            f"*Representing:* {_representing(h)}",
            f"*Purpose for Hearing:* {_v(h.get('purpose') or h.get('hearing_type'))}",
            f"*Hearing Date:* {_date_label(h.get('hearing_date') or day)}",
            f"*Hearing Time:* {_time_label(h.get('hearing_time'))}",
        ])
        messages.append((str(h.get("hearing_id") or f"{day}-{i}"), text))
    return messages


def build_empty_message(payload: dict) -> str:
    return (
        f"*ABI LAW FIRM - Hearings for {payload.get('weekday', '')}, "
        f"{_date_label(payload['date'])}*\nNo cases scheduled for hearing."
    )
