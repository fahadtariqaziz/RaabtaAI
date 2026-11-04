# Meta WhatsApp policy checklist (step 6.8.5)

Run through this before connecting an institution's number and again at each pilot review.
Sources: Meta WhatsApp Business Messaging Policy + Commerce Policy; PLAN §15.2, §21, G6–G8, G12.

## Account & number
- [ ] Business verification complete in Meta Business Manager (U-01).
- [ ] Number is dedicated to the WABA (not also on the WhatsApp / WhatsApp Business app).
- [ ] Display name = the institution's real name (approved by Meta); profile photo = its logo.
- [ ] Business profile: address, website, email, short description ("Admissions & fee help").
- [ ] Permanent **system-user** token with `whatsapp_business_messaging` + `whatsapp_business_management`
      only; stored in env (`META_ACCESS_TOKEN`), never in the repo or logs.
- [ ] Webhook subscribed to `messages` + `message_template_status_update`; `META_APP_SECRET` set
      (signature check) and `META_VERIFY_TOKEN` random (`openssl rand -hex 16`).
- [ ] `institutions.wa_phone_number_id` and `waba_id` set for the tenant (one number ↔ one tenant).

## Consent & opt-out (G7)
- [ ] Parents start the conversation (inbound or "Continue on WhatsApp"); no cold messaging of
      bought/scraped lists. Imported fee contacts (Phase 7) come from the institution's own records
      with the institution as the sender of record.
- [ ] First reply of every conversation carries the privacy line (automatic; `phrase("privacy")`).
- [ ] Opt-out words work in EN / Roman Urdu / Urdu (STOP, band karo, msg na karen, بند کریں …):
      confirmation sent once, all pending follow-ups cancelled, staff replies refused (409).
- [ ] START re-subscribes. Opted-out contacts are never messaged proactively.

## 24-hour window & templates
- [ ] Free-form messages only within 24 h of the parent's last message (enforced in code; inbox shows
      the closed window and disables the composer).
- [ ] Outside the window: approved **utility** templates only (reminders, confirmations, follow-ups,
      summaries). No **marketing** templates in the MVP.
- [ ] Template wording reviewed by the institution (tone: respectful, no threats/shaming in fee
      reminders — G5), includes the institution's name, no variable at the start/end.
- [ ] Rejected templates: read the reason, fix wording, resubmit under the same name only while
      rejected; otherwise use a new name.

## Frequency & timing (G6, G8)
- [ ] Quiet hours respected (institution tz; default 20:00–09:00) and the Friday Jumma window
      (12:30–14:30) — proactive sends are rescheduled, replies to parents are not delayed.
- [ ] ≤ 3 proactive messages per contact per 7 days (weekly cap); per-contact inbound rate limit on.
- [ ] Plan template limit enforced (follow-ups held + admin alert when reached).

## Content
- [ ] No prohibited content (Meta Commerce Policy); no collection of card numbers / passwords /
      CNIC images over chat; fee data only after `verify_parent` (Phase 7).
- [ ] Human takeover available during office hours; escalation keywords configured.

## Monitoring
- [ ] Quality rating checked weekly (`uv run python -m scripts.wa_check`); act on "Medium"/"Low"
      (reduce proactive volume, review templates with high block rates).
- [ ] Messaging tier vs. volume (tier 1 = 1k unique contacts/24 h) — enough for pilots.
- [ ] Failed sends visible in the inbox (`messages.error`); `webhook_events` with `status=failed`
      reviewed and replayed.
