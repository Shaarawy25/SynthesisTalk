"""
SynthesisTalk - Advanced Research Assistant Backend
FastAPI application with LLM integration, tool calling, and RAG capabilities
"""

from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse

from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel

import os
import re
import uuid
import logging

# ─── Import everything that was moved into llm_integration.py ────────────────────
from llm.llm_integration import (
    groq_client,
    chroma_client,
    embedding_model,
    DocumentProcessor,
    WebSearchTool,
    ToolManager,
    tool_manager,
    ReasoningEngine,
    ChatMessage,
    ConversationRequest,
    ResearchInsight,
    conversations,
    document_collections,
    research_insights,
    user_notes
)

logger = logging.getLogger(__name__)

# ─── Configure FastAPI ──────────────────────────────────────────────────────────
app = FastAPI(title="SynthesisTalk API", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Helper: Detect “Search for information about:” queries ──────────────────────
def is_direct_search(message: str) -> Optional[str]:
    """
    Check if message is of the form "Search for information about: <query>"
    Returns the <query> portion if so, otherwise None.
    """
    pattern = r"^\s*Search for information about:\s*(.+)$"
    match = re.match(pattern, message, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None
