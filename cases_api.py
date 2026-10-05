"""Fetch hearings for a day from the Tracking CRM ABI API."""
import time

import requests

import config


class CasesApiError(RuntimeError):
    pass


def fetch_hearings(day: str, retries: int = 3) -> dict:
    """Return the /app/hearings/day payload for `day` (YYYY-MM-DD).

    Only hearings with status 'scheduled' are included (API default).
    """
    url = f"{config.API_BASE}/app/hearings/day"
    headers = {"X-App-Key": config.APP_KEY, "Accept": "application/json"}

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, params={"date": day}, headers=headers, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                if not data.get("ok"):
                    raise CasesApiError(f"API returned not-ok: {data}")
                return data
            # 403 / 422 will not fix themselves on retry.
            if resp.status_code in (401, 403, 422):
                raise CasesApiError(f"API {resp.status_code}: {resp.text[:300]}")
            last_error = CasesApiError(f"API {resp.status_code}: {resp.text[:300]}")
        except requests.RequestException as exc:
            last_error = exc
        time.sleep(5 * attempt)

    raise CasesApiError(f"Could not reach cases API after {retries} tries: {last_error}")
