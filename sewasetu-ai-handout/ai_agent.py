"""FastAPI and LangGraph orchestrator for the Seva Setu MCP servers."""

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel, Field


load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

CITIZEN_SERVER_URL = os.getenv("CITIZEN_MCP_URL", "http://localhost:8101/sse")
OFFICER_SERVER_URL = os.getenv("OFFICER_MCP_URL", "http://localhost:8102/sse")

CITIZEN_TOOL_NAMES = {
    "request_otp", "verify_otp", "submit_application", "get_application_status"
}
OFFICER_TOOL_NAMES = {"get_pending_queue", "submit_decision"}

SYSTEM_PROMPTS = {
    "citizen": """You are the Seva Setu citizen assistant for the old-age pension portal.
Guide the citizen patiently and step by step. Explain eligibility and required information in
plain language. Ask for only the next missing detail, and confirm important values before using
a tool. Use request_otp before verify_otp, then use the returned session token for submission or
get_application_status. Never invent an OTP, application number, status, eligibility result, or
policy rule. Never ask the citizen to reveal a password or a session token in chat. If a tool
reports an error, explain the exact next action without hiding the error. Do not claim an
application was submitted until submit_application returns success, or claim a status until
get_application_status returns it. Reply in the same language as the citizen: use Hindi when
the citizen writes or speaks Hindi, and English when the citizen uses English. Keep names,
numbers, OTPs, and application IDs exactly as provided. You can only use citizen tools and must
never discuss or attempt officer operations.""",
    "officer": """You are the Seva Setu block-officer assistant.
Help the authenticated officer inspect and process applications for the requested pilot block.
Use get_pending_queue before discussing the queue or making a decision. Summarize records from
the tool accurately and do not invent missing facts. Before submit_decision, confirm the target
application, whether the decision is APPROVE or REJECT, and the reason. Use only exact uppercase
decision values. Never reveal credentials or ask the officer to provide the MCP authorization
header. You can only use officer tools and must never access or describe citizen OTP or
application-submission operations.""",
}


class ChatRequest(BaseModel):
    """A single message in a persistent agent conversation."""

    session_id: str = Field(min_length=1, description="Stable conversation identifier.")
    user_message: str = Field(min_length=1, description="The user's latest message.")
    user_role: Literal["citizen", "officer"]


class ChatResponse(BaseModel):
    response: str


mcp_client: MultiServerMCPClient | None = None
agents: dict[str, Any] = {}


def _tool_server_name(tool_name: str) -> str:
    """Return the unqualified tool name used by either MCP server."""
    return tool_name.rsplit("__", 1)[-1]


def _tools_for_role(tools: list[Any], role: str) -> list[Any]:
    allowed = CITIZEN_TOOL_NAMES if role == "citizen" else OFFICER_TOOL_NAMES
    selected = [tool for tool in tools if _tool_server_name(tool.name) in allowed]
    if not selected:
        raise RuntimeError("No MCP tools were loaded for the %s role" % role)
    if any(_tool_server_name(tool.name) not in allowed for tool in selected):
        raise RuntimeError("MCP tool routing policy rejected a tool")
    return selected


def _create_agent(model: ChatGoogleGenerativeAI, tools: list[Any], prompt: str, memory: MemorySaver) -> Any:
    """Create a ReAct agent across LangGraph versions that renamed prompt."""
    try:
        return create_react_agent(model, tools, prompt=prompt, checkpointer=memory)
    except TypeError as error:
        if "prompt" not in str(error):
            raise
        return create_react_agent(model, tools, state_modifier=prompt, checkpointer=memory)


def _response_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for part in content:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                text_parts.append(part["text"])
        if text_parts:
            return "".join(text_parts)
    return str(content)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global mcp_client, agents

    officer_token = os.getenv("OFFICER_MCP_TOKEN", "")
    mcp_client = MultiServerMCPClient({
        "citizen": {
            "transport": "sse",
            "url": CITIZEN_SERVER_URL,
        },
        "officer": {
            "transport": "sse",
            "url": OFFICER_SERVER_URL,
            "headers": {"Authorization": "Bearer %s" % officer_token},
        },
    })
    tools = await mcp_client.get_tools()
    model = ChatGoogleGenerativeAI(
        model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
        temperature=0,
        google_api_key=os.getenv("GOOGLE_API_KEY"),
    )
    memory = MemorySaver()
    agents = {
        "citizen": _create_agent(
            model, _tools_for_role(tools, "citizen"), SYSTEM_PROMPTS["citizen"], memory
        ),
        "officer": _create_agent(
            model, _tools_for_role(tools, "officer"), SYSTEM_PROMPTS["officer"], memory
        ),
    }
    yield
    agents.clear()
    mcp_client = None


app = FastAPI(title="Seva Setu AI Agent", lifespan=lifespan)
logger = logging.getLogger("sewa-setu-agent")


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Run one role-scoped message through the LangGraph ReAct agent."""
    if request.user_role not in agents:
        raise HTTPException(status_code=503, detail="Agent is still starting")

    try:
        result = await agents[request.user_role].ainvoke(
            {"messages": [{"role": "user", "content": request.user_message}]},
            config={"configurable": {
                "thread_id": "%s:%s" % (request.user_role, request.session_id)
            }},
        )
    except Exception as error:
        logger.exception("agent request failed")
        error_text = str(error).lower()
        if "resource_exhausted" in error_text or "quota" in error_text or "429" in error_text:
            detail = "The assistant is temporarily unavailable. Please try again later."
        elif "unauthenticated" in error_text or "invalid api key" in error_text:
            detail = "The assistant is temporarily unavailable. Please try again later."
        else:
            detail = "The assistant is temporarily unavailable. Please try again later."
        raise HTTPException(
            status_code=502,
            detail=detail,
        )
    messages = result.get("messages", [])
    if not messages:
        raise HTTPException(status_code=502, detail="Agent returned no response")
    return ChatResponse(response=_response_text(messages[-1]))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("AI_AGENT_PORT", "8200")))