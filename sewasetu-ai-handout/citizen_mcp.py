"""Citizen-facing Seva Setu MCP server."""

import base64
import hashlib
import hmac
import json
import os
import random
import sys
from datetime import date, datetime
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from fastmcp import FastMCP
from mcp_sse import run_sse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
import app as portal  # noqa: E402


mcp = FastMCP("Seva Setu Citizen Server")

OTP_VALIDITY_SECONDS = portal.OTP_VALIDITY_SECONDS
SESSION_VALIDITY_SECONDS = 2 * 60 * 60
TOKEN_SECRET = os.environ.get("MCP_TOKEN_SECRET", portal.app.secret_key).encode("utf-8")

PILOT_BLOCKS = {
    "purvanchal_pilot_1": "Sonari",
    "purvanchal_pilot_2": "Rajapara",
    "purvanchal_pilot_3": "Dhemaji Pathar",
    "purvanchal_pilot_4": "Borgaon",
    "purvanchal_pilot_5": "Namti",
    "purvanchal_pilot_6": "Khelua",
}


class BankDetails(BaseModel):
    """Bank account details supplied by the applicant."""

    account_number: str = Field(description="The 9 to 18 digit bank account number.")
    ifsc: str = Field(description="The 11-character IFSC code.")


def _result(status: str, message: str, **data: Any) -> dict[str, Any]:
    return {"status": status, "message": message, **data}


def _sign_token(payload: dict[str, Any]) -> str:
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    signature = hmac.new(TOKEN_SECRET, encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return "%s.%s" % (encoded, signature)


def _read_token(token: str) -> dict[str, Any] | None:
    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(TOKEN_SECRET, encoded.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8"))
        if int(payload["expires_at"]) < int(datetime.now().timestamp()):
            return None
        return payload
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


@mcp.tool()
def request_otp(mobile_number: str) -> dict[str, Any]:
    """Send an OTP to a citizen's 10-digit mobile number.

    Use this before ``verify_otp`` when the citizen wants to start an
    application. The returned value confirms delivery was requested; do not
    ask the citizen to disclose the OTP in normal chat.
    """
    mobile = mobile_number.strip()
    if len(mobile) != 10 or not mobile.isdigit():
        return _result("error", "mobile_number must contain exactly 10 digits")

    code = str(random.randint(100000, 999999))
    connection = portal.get_db()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "INSERT INTO otps (mobile, code, created_at) VALUES (%s, %s, %s)",
            (mobile, code, datetime.now()),
        )
        connection.commit()
        portal.send_sms(mobile, "Your Sewa Setu OTP is %s. Valid for 5 minutes." % code)
    finally:
        cursor.close()
        connection.close()
    return _result("success", "OTP sent to the registered mobile number")


@mcp.tool()
def verify_otp(mobile_number: str, code: str) -> dict[str, Any]:
    """Verify the latest OTP and return a short-lived citizen session token.

    ``mobile_number`` must match the number used with ``request_otp``. Use
    the returned ``session_token`` with ``submit_application`` or
    ``get_application_status``.
    """
    mobile = mobile_number.strip()
    connection = portal.get_db()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT code, created_at FROM otps WHERE mobile = %s "
            "ORDER BY id DESC LIMIT 1",
            (mobile,),
        )
        row = cursor.fetchone()
    finally:
        cursor.close()
        connection.close()

    if not row or str(row[0]) != code.strip():
        return _result("error", "invalid OTP")
    age = (datetime.now() - portal.parse_timestamp(row[1])).total_seconds()
    if age > OTP_VALIDITY_SECONDS:
        return _result("error", "OTP has expired")

    token = _sign_token({
        "mobile": mobile,
        "expires_at": int(datetime.now().timestamp()) + SESSION_VALIDITY_SECONDS,
    })
    return _result("success", "OTP verified", session_token=token)


@mcp.tool()
def submit_application(
    token: str,
    name: str,
    age: int,
    block_id: str,
    bank_details: BankDetails,
) -> dict[str, Any]:
    """Submit a pension application after OTP verification.

    ``token`` is the session token returned by ``verify_otp``. ``age`` must
    be at least 60 and ``block_id`` must be a published pilot block ID.
    The application is written as pending and must complete the portal's
    required age-proof workflow before approval.
    """
    session_data = _read_token(token)
    if not session_data:
        return _result("error", "invalid or expired session token")
    if age < portal.MIN_AGE:
        return _result("error", "applicant must be at least %d years old" % portal.MIN_AGE)
    block = PILOT_BLOCKS.get(block_id)
    if not block:
        return _result("error", "unknown block_id", allowed_blocks=list(PILOT_BLOCKS))

    today = portal.now_ist().date()
    dob = date(today.year - age, today.month, today.day)
    data = {
        "applicant_name": name,
        "village": "MCP submission",
        "block": block,
        "bank_account": bank_details.account_number,
        "ifsc": bank_details.ifsc,
        "dob": dob.strftime("%d/%m/%Y"),
    }
    errors, cleaned = portal.validate_application(data, "mcp://age-proof-upload-required")
    if errors:
        return _result("error", "application failed validation", errors=errors)

    connection = portal.get_db()
    cursor = connection.cursor()
    try:
        existing = portal.active_application(cursor, session_data["mobile"])
        if existing:
            return _result("error", "an active application already exists", application_no=existing[1])
        application_id, application_no = portal.create_application(
            cursor, session_data["mobile"], cleaned
        )
        connection.commit()
    finally:
        cursor.close()
        connection.close()
    return _result(
        "success",
        "application submitted and is pending review",
        application_id=application_id,
        application_no=application_no,
        block=block,
    )


@mcp.tool()
def get_application_status(token: str) -> dict[str, Any]:
    """Return the latest application status for an OTP-verified citizen.

    ``token`` must be the session token returned by ``verify_otp``. The lookup
    is limited to the mobile number bound to that token and follows the status
    portal's latest-application behavior.
    """
    session_data = _read_token(token)
    if not session_data:
        return _result("error", "invalid or expired session token")

    connection = portal.get_db()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT application_no, applicant_name, mobile, dob, village, block, "
            "status, submitted_at, decided_at "
            "FROM applications WHERE mobile = %s "
            "ORDER BY submitted_at DESC LIMIT 1",
            (session_data["mobile"],),
        )
        row = cursor.fetchone()
    finally:
        cursor.close()
        connection.close()

    if not row:
        return _result("error", "no application found for this mobile number")

    fields = (
        "application_no", "applicant_name", "mobile", "dob", "village",
        "block", "status", "submitted_at", "decided_at",
    )
    return _result("success", "application status loaded", application=dict(zip(fields, row)))


if __name__ == "__main__":
    run_sse(mcp, int(os.environ.get("MCP_PORT", "8101")))