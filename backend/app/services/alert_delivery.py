"""Persistent SMTP delivery worker. Run explicitly after configuring the recipient."""
import argparse
import smtplib
import ssl
import time
from email.message import EmailMessage

from backend.app.config.settings import get_settings
from backend.app.schemas.intelligence import AlertRead
from backend.app.services.alerts import alert_database


def deliver_pending(send=None):
    settings = get_settings()
    if not all((settings.smtp_host, settings.smtp_from, settings.alert_email_to)):
        raise RuntimeError("Configure SMTP_HOST, SMTP_FROM and ALERT_EMAIL_TO before starting delivery.")
    with alert_database() as db:
        db.execute("CREATE TABLE IF NOT EXISTS email_jobs(id TEXT PRIMARY KEY, attempts INTEGER, retry_at REAL)")
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("""SELECT a.payload, coalesce(j.attempts,0) FROM alerts a LEFT JOIN email_jobs j ON j.id=a.id
            WHERE json_extract(a.payload,'$.delivery_status') IN ('pending','failed')
            AND coalesce(j.attempts,0)<5 AND coalesce(j.retry_at,0)<=?
            ORDER BY a.timestamp LIMIT 1""", (time.time(),)).fetchone()
        if row is None:
            return False
        alert = AlertRead.model_validate_json(row[0])
        attempts = row[1] + 1
        db.execute("INSERT OR REPLACE INTO email_jobs VALUES(?,?,?)", (alert.id, attempts, time.time() + 120))
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = settings.alert_email_to
    message["Subject"] = "FlightPulse: " + alert.title
    message["Message-ID"] = f"<{alert.id}@flightpulse.local>"
    message.set_content(f"{alert.explanation}\n\nEvidence source: {alert.source}\nEvidence time: {alert.evidence_time}\nAlert ID: {alert.id}")
    failure = None
    try:
        if send:
            send(message)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                if settings.smtp_username:
                    smtp.login(settings.smtp_username, settings.smtp_password or "")
                refused = smtp.send_message(message)
                if refused:
                    raise RuntimeError("Recipient refused")
    except Exception as error:
        # Do not persist credentials, server text, or email addresses in error messages.
        failure = type(error).__name__
    with alert_database() as db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute("SELECT payload FROM alerts WHERE id=?", (alert.id,)).fetchone()
        if current:
            alert = AlertRead.model_validate_json(current[0])
            alert.delivery_status = "failed" if failure else "sent"
            alert.delivery_error = failure
            db.execute("UPDATE alerts SET payload=? WHERE id=?", (alert.model_dump_json(), alert.id))
            db.execute("UPDATE email_jobs SET retry_at=? WHERE id=?", (time.time() + min(3600, 30 * 2 ** attempts), alert.id))
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    while True:
        worked = deliver_pending()
        if args.once:
            return
        if not worked:
            time.sleep(5)


if __name__ == "__main__":
    main()
