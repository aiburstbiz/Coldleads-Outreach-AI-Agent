"""
gmail_sender.py — Dev2 service
Sends an email with optional .pptx attachment via Gmail API.
"""
import os
import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from googleapiclient.errors import HttpError
from dev2_delivery.services.gmail_auth import get_gmail_service


def send_email(
    to: str,
    subject: str,
    body_html: str,
    attachment_path: str = None,
) -> dict:
    """
    Send an email via Gmail API.
    Returns {"success": True, "message_id": ...} or {"success": False, "error": ...}
    """
    try:
        service = get_gmail_service()

        msg = MIMEMultipart("mixed")
        msg["To"] = to
        msg["Subject"] = subject

        # HTML body
        msg.attach(MIMEText(body_html, "html"))

        # Optional .pptx attachment
        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, "rb") as f:
                part = MIMEBase(
                    "application",
                    "vnd.openxmlformats-officedocument.presentationml.presentation"
                )
                part.set_payload(f.read())
                encoders.encode_base64(part)
                filename = os.path.basename(attachment_path)
                part.add_header(
                    "Content-Disposition",
                    f"attachment; filename={filename}"
                )
                msg.attach(part)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        result = service.users().messages().send(
            userId="me",
            body={"raw": raw}
        ).execute()

        return {"success": True, "message_id": result.get("id")}

    except HttpError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": str(e)}