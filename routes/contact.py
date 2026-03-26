"""
Contact/inquiry routes for website form submissions.
"""

import smtplib
import ssl
from email.message import EmailMessage

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from config import (
    CONTACT_TO_EMAIL,
    SMTP_FROM_EMAIL,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USE_SSL,
    SMTP_USE_TLS,
    SMTP_USERNAME,
)
from tracing import get_trace_logger

router = APIRouter(prefix="/contact", tags=["Contact"])
trace_logger = get_trace_logger()


class InquiryRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    organisation: str = Field(default="", max_length=150)
    phone: str = Field(default="", max_length=50)
    query_type: str = Field(..., min_length=2, max_length=50)
    message: str = Field(..., min_length=10, max_length=5000)


def _build_email_body(payload: InquiryRequest) -> str:
    lines = [
        "New inquiry from website contact form",
        "",
        f"Name: {payload.name}",
        f"Email: {payload.email}",
        f"Organisation: {payload.organisation or 'N/A'}",
        f"Phone: {payload.phone or 'N/A'}",
        f"Query Type: {payload.query_type}",
        "",
        "Message:",
        payload.message,
    ]
    return "\n".join(lines)


def _send_email(message: EmailMessage) -> None:
    if SMTP_USE_SSL:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            if SMTP_USERNAME and SMTP_PASSWORD:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(message)
        return

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
        if SMTP_USE_TLS:
            server.starttls(context=ssl.create_default_context())
        if SMTP_USERNAME and SMTP_PASSWORD:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(message)


@router.post("/inquiry")
def submit_inquiry(payload: InquiryRequest, request: Request):
    request_id = getattr(request.state, "request_id", None)
    trace_logger.log_operation(
        "Contact Inquiry Submission",
        {"name": payload.name, "email": str(payload.email), "query_type": payload.query_type},
        request_id,
    )

    if not SMTP_HOST or not SMTP_FROM_EMAIL or not CONTACT_TO_EMAIL:
        trace_logger.log_error(
            "Email service configuration missing for contact inquiry",
            request_id=request_id,
        )
        raise HTTPException(
            status_code=503,
            detail="Email service is not configured. Please contact support directly.",
        )

    email_message = EmailMessage()
    email_message["Subject"] = f"[TDSC Inquiry] {payload.query_type} - {payload.name}"
    email_message["From"] = SMTP_FROM_EMAIL
    email_message["To"] = CONTACT_TO_EMAIL
    email_message["Reply-To"] = str(payload.email)
    email_message.set_content(_build_email_body(payload))

    try:
        _send_email(email_message)
        trace_logger.log_operation(
            "Contact Inquiry Email Sent",
            {"to": CONTACT_TO_EMAIL, "from": SMTP_FROM_EMAIL},
            request_id,
        )
    except Exception as exc:
        trace_logger.log_error("Failed to send contact inquiry email", exc, request_id)
        raise HTTPException(
            status_code=502,
            detail="Failed to send inquiry email. Please try again later.",
        ) from exc

    return {"message": "Inquiry sent successfully", "recipient": CONTACT_TO_EMAIL}
