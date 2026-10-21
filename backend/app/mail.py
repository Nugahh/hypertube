import logging
import os
import smtplib
from email.message import EmailMessage

SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", "1025"))  # Mailpit's default, see docker-compose.yml
SMTP_USER = os.getenv("SMTP_USER", "")  # set it (and the password) for a real server: TLS + login are then used
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
MAIL_FROM = os.getenv("MAIL_FROM", "Hypertube <no-reply@hypertube.local>")


def send_email(to, subject, body):
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = MAIL_FROM, to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
            if SMTP_USER:
                smtp.starttls()
                smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(msg)
    except OSError as e:  # smtplib's errors are OSErrors; never log the address or the message
        logging.getLogger("uvicorn.error").warning("Email not sent: %s", type(e).__name__)
