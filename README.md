# ABI LAW FIRM – Hearing Reminders on WhatsApp

Every day at 8:00 PM (IST), this bot fetches the next day's scheduled hearings from the
Tracking CRM ABI API and posts them to the **ABI LAW FIRM** WhatsApp group. It sends
through WhatsApp Web (Selenium + Chrome) using a saved login.

**Data source:** `GET https://cases.abilawfirm.in/api/v1/app/hearings/day?date=YYYY-MM-DD`,
authenticated with the `X-App-Key` header. This is the CRM's read-only key, the same one
the mobile app uses. Only hearings with status `scheduled` are included.

## Setup (one time)

```powershell
pip install -r requirements.txt
python main.py login
```

`login` opens Chrome with WhatsApp Web. On the phone for **63792 29627**, go to
**WhatsApp → Settings → Linked devices → Link a device** and scan the QR code. The session
is saved in `whatsapp_session/`, so you won't have to scan again. You only need to repeat
`login` if the phone unlinks the device, or if the phone stays offline for about 14 days
or more.

## Commands

| Command | What it does |
|---|---|
| `python main.py preview` | Print tomorrow's message without sending it |
| `python main.py preview --date 2026-11-12` | Preview the message for any date |
| `python main.py send` | Send tomorrow's hearings now |
| `python main.py send --date 2026-11-12 --force` | Send a specific date, even if it was already sent |
| `python main.py run` | Keep running and send every day at `SEND_TIME` |

## Scheduling at 8 PM daily

**Recommended:** Windows Task Scheduler. Run this once:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_task.ps1
```

The task runs `main.py send` at 20:00. If the PC was off at that time, it runs as soon as
the PC is back on. The PC must be on and the user logged in.

**Alternative:** leave `python main.py run` open in a terminal.

## Notes

- Each hearing is sent as its own message ("Hearing 1 of N"), in order of hearing time.
- `sent_log.json` records every case sent, per date. A date is never posted twice, and if sending
  stops partway, the next run sends only the cases that are still missing.
- Logs are written to `logs/automation.log`.
- Settings are in `.env`: group name, send time, `SEND_WHEN_EMPTY` (whether to post a
  "No cases scheduled" note), and `HEADLESS`.
- Close any Chrome window that is using `whatsapp_session` before the bot runs. Your normal
  Chrome is fine.
- If WhatsApp Web changes its layout and sending breaks, update the selectors at the top
  of `whatsapp.py`.
