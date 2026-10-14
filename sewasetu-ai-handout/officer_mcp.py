"""Officer-facing Seva Setu MCP server."""

import os
import sys
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
from fastmcp import FastMCP
from mcp_sse import run_sse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
import app as portal  # noqa: E402


mcp = FastMCP("Seva Setu Officer Server")

OFFICER_TOKEN = os.environ.get("OFFICER_MCP_TOKEN", "")
OFFICER_NAME = os.environ.get("MCP_OFFICER_NAME", "mcp-officer")

PILOT_BLOCKS = {
    "purvanchal_pilot_1": "Sonari",
    "purvanchal_pilot_2": "Rajapara",
    "purvanchal_pilot_3": "Dhemaji Pathar",
    "purvanchal_pilot_4": "Borgaon",
    "purvanchal_pilot_5": "Namti",
    "purvanchal_pilot_6": "Khelua",
}


def _result(status: str, message: str, **data: Any) -> dict[str, Any]:
    return {"status": status, "message": message, **data}


def _authorized(officer_token: str) -> bool:
    return bool(OFFICER_TOKEN) and officer_token == OFFICER_TOKEN


@mcp.tool()
def get_pending_queue(officer_token: str, block_id: str) -> dict[str, Any]:
    """Return pending pension applications for an authenticated block officer.

    ``officer_token`` is the server-issued officer credential. ``block_id``
    must be a published pilot block ID; use this tool before deciding an
    application so the officer assistant sees only its assigned block queue.
    """
    if not _authorized(officer_token):
        return _result("error", "invalid officer token")
    block = PILOT_BLOCKS.get(block_id)
    if not block:
        return _result("error", "unknown block_id", allowed_blocks=list(PILOT_BLOCKS))

    connection = portal.get_db()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT id, application_no, applicant_name, mobile, dob, village, block, "
            "bank_account, ifsc, submitted_at FROM applications "
            "WHERE status = 'PENDING' AND block = %s ORDER BY submitted_at ASC",
            (block,),
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
        connection.close()

    fields = (
        "id", "application_no", "applicant_name", "mobile", "dob", "village",
        "block", "bank_account", "ifsc", "submitted_at",
    )
    applications = [dict(zip(fields, row)) for row in rows]
    return _result("success", "pending queue loaded", block=block, applications=applications)


@mcp.tool()
def submit_decision(
    officer_token: str,
    application_id: str,
    decision: str,
    reason: str,
) -> dict[str, Any]:
    """Approve or reject one pending application for an authenticated officer.

    ``application_id`` is the numeric ID returned by ``get_pending_queue``.
    ``decision`` must be exactly ``APPROVE`` or ``REJECT``. ``reason`` is
    recorded in the audit trail and should explain the decision plainly.
    """
    if not _authorized(officer_token):
        return _result("error", "invalid officer token")
    if decision not in ("APPROVE", "REJECT"):
        return _result("error", "decision must be exactly APPROVE or REJECT")
    try:
        numeric_id = int(application_id)
    except (TypeError, ValueError):
        return _result("error", "application_id must be numeric")

    new_status = "APPROVED" if decision == "APPROVE" else "REJECTED"
    connection = portal.get_db()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "UPDATE applications SET status = %s, decided_at = %s, decided_by = %s "
            "WHERE id = %s AND status = 'PENDING'",
            (new_status, datetime.now(), OFFICER_NAME, numeric_id),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            return _result("error", "application was not found or is no longer pending")
        portal.write_audit(cursor, numeric_id, new_status, "officer:%s" % OFFICER_NAME, reason)
        connection.commit()
    finally:
        cursor.close()
        connection.close()
    return _result("success", "application decision recorded", application_id=numeric_id,
                   decision=decision)


if __name__ == "__main__":
    run_sse(mcp, int(os.environ.get("MCP_PORT", "8102")))