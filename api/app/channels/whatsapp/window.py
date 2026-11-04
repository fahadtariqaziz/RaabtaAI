"""24-hour customer-service window (step 6.3.2, PLAN §15.2): free-form messages are allowed only
within 24 h of the contact's last inbound message; outside it only approved templates."""

import datetime as dt

WINDOW = dt.timedelta(hours=24)
# Small safety margin: a reply composed at 23:59:58 must not reach Meta after the window closed.
MARGIN = dt.timedelta(minutes=2)


def window_expires_at(last_inbound_at: dt.datetime | None) -> dt.datetime | None:
    return last_inbound_at + WINDOW if last_inbound_at is not None else None


def free_form_allowed(last_inbound_at: dt.datetime | None, now: dt.datetime) -> bool:
    if last_inbound_at is None:
        return False
    return now - last_inbound_at < WINDOW - MARGIN
