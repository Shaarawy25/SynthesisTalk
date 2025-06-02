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

# ─── API Endpoints ───────────────────────────────────────────────────────────────

@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)):
    """
    Upload and process a document for RAG.
    Supported types: .pdf, .docx, .txt
    """
    try:
        collection_id = str(uuid.uuid4())
        file_content = await file.read()
        
        # Extract text based on file type
        if file.filename.lower().endswith(".pdf"):
            text = DocumentProcessor.extract_text_from_pdf(file_content)
        elif file.filename.lower().endswith(".docx"):
            text = DocumentProcessor.extract_text_from_docx(file_content)
        elif file.filename.lower().endswith(".txt"):
            text = file_content.decode("utf-8", errors="ignore")
        else:
            raise HTTPException(status_code=400, detail="Unsupported file type. Only .pdf, .docx, .txt allowed.")
        
        if not text.strip():
            raise HTTPException(status_code=400, detail="No text could be extracted from the document.")
        
        # Chunk the text with overlap
        chunks = DocumentProcessor.chunk_text(text, chunk_size=1000, overlap=200)
        
        # Create embeddings and store in ChromaDB
        try:
            embeddings = embedding_model.encode(chunks)
            collection = chroma_client.create_collection(name=collection_id)
            collection.add(
                embeddings=embeddings.tolist(),
                documents=chunks,
                ids=[f"chunk_{i}" for i in range(len(chunks))]
            )
        except Exception:
            # Fallback to in-memory storage if ChromaDB fails
            pass
        
        # Store document metadata and raw chunks for fallback
        document_collections[collection_id] = {
            "filename": file.filename,
            "upload_time": datetime.now().isoformat(),
            "chunk_count": len(chunks),
            "documents": {
                file.filename: {
                    "text": text,
                    "chunks": chunks
                }
            }
        }
        
        return {
            "collection_id": collection_id,
            "filename": file.filename,
            "chunk_count": len(chunks),
            "message": "Document uploaded and processed successfully."
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"upload_document error: {e}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@app.post("/api/chat")
async def chat(request: ConversationRequest):
    """
    Main chat endpoint with tool integration and document Q&A.
    Supports:
      - `/reset` to clear context
      - direct “Search for information about:” queries (when use_tools=True)
      - document_collections: list of collection IDs for RAG
      - full_conversation: entire chat history (used by insights)
    """
    try:
        conversation_id = request.conversation_id
        message_text = request.message.strip()

        # ─── 1) If the user typed exactly "/reset", clear in-memory conversation history ─────────────────────
        if message_text.lower() == "/reset":
            # Clear the in-memory history for this conversation:
            conversations[conversation_id] = []
            return {
                "response": "🗑️ Context cleared. You can start a new conversation now.",
                "conversation_id": conversation_id,
                "reasoning_type": "reset",
                "timestamp": datetime.now().isoformat()
            }

        # ─── 2) If the message is "Search for information about: <X>" and use_tools=True, call web_search directly ────
        direct_query = is_direct_search(message_text)
        if direct_query and request.use_tools:
            tool_result = await tool_manager.execute_tool("web_search", {"query": direct_query, "num_results": 5})
            if tool_result.get("success"):
                results = tool_result.get("results", [])
                if not results:
                    return {
                        "response": f"⚠️ No search results found for \"{direct_query}\".",
                        "conversation_id": conversation_id,
                        "reasoning_type": "tool",
                        "timestamp": datetime.now().isoformat()
                    }
                # Format the results
                lines = ["🔍 Web search results:\n"]
                for idx, entry in enumerate(results, start=1):
                    title = entry.get("title", "No title")
                    url = entry.get("url", "")
                    snippet = entry.get("snippet", "")
                    lines.append(f"{idx}. **{title}**\n{url}\n\n{snippet}\n")
                combined = "\n".join(lines)

                # Append to conversation
                if conversation_id not in conversations:
                    conversations[conversation_id] = []
                conversations[conversation_id].append(ChatMessage(
                    role="assistant",
                    content=combined,
                    timestamp=datetime.now(),
                    sources=[e["url"] for e in results],
                    reasoning_type="tool"
                ))
                return {
                    "response": combined,
                    "conversation_id": conversation_id,
                    "reasoning_type": "tool",
                    "timestamp": datetime.now().isoformat()
                }
            else:
                error_msg = tool_result.get("error", "Unknown error during web search.")
                return {
                    "response": f"⚠️ Web search failed: {error_msg}",
                    "conversation_id": conversation_id,
                    "reasoning_type": "tool_error",
                    "timestamp": datetime.now().isoformat()
                }

        # ─── 3) Otherwise, proceed with the usual conversation flow ─────────────────────────────────────────────────━─

        # Initialize conversation if not present
        if conversation_id not in conversations:
            conversations[conversation_id] = []

        # Append user's message
        user_msg = ChatMessage(
            role="user",
            content=message_text,
            timestamp=datetime.now()
        )
        conversations[conversation_id].append(user_msg)

        # Build chat context from last (context_limit - 1) turns (excluding this new user message)
        recent_msgs = conversations[conversation_id][-request.context_limit:]
        context_lines = [f"{msg.role}: {msg.content}" for msg in recent_msgs[:-1]]
        chat_context = "\n".join(context_lines)

        # Retrieve relevant chunks from provided document_collections (for RAG)
        retrieved_chunks_text = ""
        if request.document_collections:
            all_relevant_chunks: List[str] = []
            for coll_id in request.document_collections:
                if coll_id in document_collections:
                    try:
                        collection = chroma_client.get_collection(name=coll_id)
                        query_emb = embedding_model.encode([message_text])
                        results = collection.query(
                            query_embeddings=query_emb.tolist(),
                            n_results=3
                        )
                        raw_chunks = results['documents'][0] if results['documents'] else []
                    except Exception:
                        # Fallback to substring search
                        raw_chunks = []
                        info = document_collections[coll_id]
                        query_l = message_text.lower()
                        for doc_id, doc_data in info['documents'].items():
                            for chunk in doc_data['chunks']:
                                if query_l in chunk.lower():
                                    raw_chunks.append(chunk)
                                if len(raw_chunks) >= 3:
                                    break
                            if len(raw_chunks) >= 3:
                                break

                    for chunk in raw_chunks[:3]:
                        all_relevant_chunks.append(chunk)

            if all_relevant_chunks:
                retrieved_chunks_text = (
                    "Here are relevant passages from the uploaded document(s):\n\n"
                    + "\n---\n".join(all_relevant_chunks)
                    + "\n\n"
                )

        # Combine retrieved chunks and chat context
        combined_context = ""
        if retrieved_chunks_text:
            combined_context += retrieved_chunks_text
        if chat_context:
            combined_context += chat_context + "\n\n"

        # Determine reasoning path
        reasoning_type = None
        if request.use_chain_of_thought:
            response_content = ReasoningEngine.chain_of_thought(message_text, combined_context)
            reasoning_type = "chain_of_thought"
        elif request.use_tools and request.document_collections:
            react_query = combined_context + f"User: {message_text}"
            response_content = await ReasoningEngine.react_reasoning(react_query, tool_manager, conversation_id)
            reasoning_type = "react"
        else:
            # Direct LLM call
            try:
                prompt_messages = [
                    {"role": "system", "content": "You are a helpful research assistant. Provide accurate and comprehensive responses."},
                    {"role": "user", "content": f"Context:\n{combined_context}User: {message_text}"}
                ]
                response = groq_client.chat.completions.create(
                    model="llama3-8b-8192",
                    messages=prompt_messages,
                    max_tokens=1000
                )
                response_content = response.choices[0].message.content
                reasoning_type = "direct"
            except Exception:
                response_content = "I’m sorry, but I’m having trouble processing your request right now."
                reasoning_type = "error"

        # Append assistant message
        assistant_msg = ChatMessage(
            role="assistant",
            content=response_content,
            timestamp=datetime.now(),
            sources=[],
            reasoning_type=reasoning_type
        )
        conversations[conversation_id].append(assistant_msg)

        return {
            "response": response_content,
            "conversation_id": conversation_id,
            "reasoning_type": reasoning_type,
            "timestamp": assistant_msg.timestamp.isoformat()
        }

    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=f"Chat failed: {str(e)}")


@app.get("/api/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    """Get conversation history"""
    if conversation_id not in conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        "conversation_id": conversation_id,
        "messages": [
            {
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat(),
                "sources": msg.sources,
                "reasoning_type": msg.reasoning_type
            }
            for msg in conversations[conversation_id]
        ]
    }


@app.post("/api/tools/{tool_name}")
async def execute_tool_endpoint(tool_name: str, parameters: Dict[str, Any]):
    """Execute a specific tool by name"""
    try:
        result = await tool_manager.execute_tool(tool_name, parameters)
        return result
    except Exception as e:
        logger.error(f"Tool execution error for {tool_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Tool execution failed: {str(e)}")


@app.get("/api/documents")
async def list_documents():
    """List all uploaded document collections"""
    return {
        "collections": [
            {
                "collection_id": cid,
                "filename": info["filename"],
                "upload_time": info["upload_time"],
                "chunk_count": info["chunk_count"]
            }
            for cid, info in document_collections.items()
        ]
    }


@app.delete("/api/documents/{collection_id}")
async def delete_document(collection_id: str):
    """Delete a document collection (from ChromaDB and memory)"""
    if collection_id not in document_collections:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        try:
            chroma_client.delete_collection(collection_id)
        except Exception:
            pass
        del document_collections[collection_id]
        return {"message": "Document deleted successfully"}
    except Exception as e:
        logger.error(f"delete_document error: {e}")
        raise HTTPException(status_code=500, detail=f"Deletion failed: {str(e)}")


@app.get("/api/insights/{conversation_id}")
async def get_insights(conversation_id: str):
    """Get stored research insights for a conversation"""
    if conversation_id not in research_insights:
        return {"insights": []}
    return {
        "conversation_id": conversation_id,
        "insights": [insight.dict() for insight in research_insights[conversation_id]]
    }


@app.get("/api/notes/{conversation_id}")
async def get_notes_endpoint(conversation_id: str, category: Optional[str] = None):
    """Get notes for a conversation, optionally filtered by category"""
    result = await tool_manager.get_notes(conversation_id, category)
    return result


@app.post("/api/notes/{conversation_id}")
async def take_note_endpoint(conversation_id: str, note_data: Dict[str, str]):
    """Save a note for a conversation"""
    note = note_data.get("note", "")
    category = note_data.get("category", "general")
    if not note:
        raise HTTPException(status_code=400, detail="Note content is required")
    result = await tool_manager.take_note(conversation_id, note, category)
    return result


@app.get("/api/export/{conversation_id}")
async def export_conversation(conversation_id: str, format: str = "json"):
    """Export conversation in JSON or PDF format"""
    if conversation_id not in conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = conversations[conversation_id]
    try:
        if format.lower() == "json":
            return {
                "conversation_id": conversation_id,
                "export_time": datetime.now().isoformat(),
                "messages": [
                    {
                        "role": msg.role,
                        "content": msg.content,
                        "timestamp": msg.timestamp.isoformat(),
                        "sources": msg.sources,
                        "reasoning_type": msg.reasoning_type
                    }
                    for msg in messages
                ]
            }
        elif format.lower() == "pdf":
            # Generate a PDF exactly as in the original code
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import letter

            filename = f"conversation_{conversation_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            filepath = f"/tmp/{filename}"
            c = canvas.Canvas(filepath, pagesize=letter)
            width, height = letter
            y = height - 50
            c.setFont("Helvetica-Bold", 16)
            c.drawString(50, y, f"Conversation Export - {conversation_id}")
            y -= 30
            c.setFont("Helvetica", 10)
            c.drawString(50, y, f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            y -= 40
            for msg in messages:
                if y < 100:
                    c.showPage()
                    y = height - 50
                c.setFont("Helvetica-Bold", 12)
                c.drawString(50, y, f"{msg.role.upper()}:")
                y -= 20
                c.setFont("Helvetica", 10)
                words = msg.content.split()
                line = ""
                for word in words:
                    if len(line + word) < 80:
                        line += word + " "
                    else:
                        if y < 50:
                            c.showPage()
                            y = height - 50
                        c.drawString(70, y, line.strip())
                        y -= 15
                        line = word + " "
                if line:
                    if y < 50:
                        c.showPage()
                        y = height - 50
                    c.drawString(70, y, line.strip())
                    y -= 15
                y -= 10
            c.save()
            return FileResponse(filepath, media_type="application/pdf", filename=filename)
        else:
            raise HTTPException(status_code=400, detail="Unsupported export format")
    except Exception as e:
        logger.error(f"export_conversation error: {e}")
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "groq": "connected" if groq_client else "disconnected",
            "chroma": "connected",
            "embedding": "loaded"
        }
    }


@app.get("/api/stats")
async def get_stats():
    """Get system-wide statistics"""
    return {
        "conversations_count": len(conversations),
        "documents_count": len(document_collections),
        "total_messages": sum(len(msgs) for msgs in conversations.values()),
        "insights_count": sum(len(ins) for ins in research_insights.values()),
        "notes_count": sum(len(n) for n in user_notes.values())
    }
# ─── Error handlers ───────────────────────────────────────────────────────────────

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "status_code": exc.status_code}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "status_code": 500}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
