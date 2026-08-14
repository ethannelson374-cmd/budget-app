from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.core.config import Settings


class EmailDeliveryError(RuntimeError):
    pass


def send_email(settings: Settings, *, to_email: str, subject: str, text: str) -> None:
    if not settings.email_configured or settings.smtp_host is None or settings.smtp_from_email is None:
        raise EmailDeliveryError("Email delivery is not configured")

    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(text)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as client:
            client.ehlo()
            if settings.smtp_starttls:
                client.starttls()
                client.ehlo()
            if settings.smtp_username:
                if settings.smtp_password is None:
                    raise EmailDeliveryError("SMTP password is not configured")
                client.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            client.send_message(message)
    except EmailDeliveryError:
        raise
    except (OSError, smtplib.SMTPException) as exc:
        raise EmailDeliveryError("Email delivery failed") from exc


def invitation_email(invite_url: str) -> tuple[str, str]:
    return (
        "You're invited to Budget",
        "You've been invited to a private Budget workspace.\n\n"
        f"Accept the invitation: {invite_url}\n\n"
        "This invitation expires in 7 days. If you weren't expecting it, you can ignore this message.",
    )


def password_reset_email(reset_url: str) -> tuple[str, str]:
    return (
        "Reset your Budget password",
        "A password reset was requested for your Budget account.\n\n"
        f"Reset your password: {reset_url}\n\n"
        "This link expires in 30 minutes and can only be used once. If you didn't request it, you can ignore this message.",
    )
