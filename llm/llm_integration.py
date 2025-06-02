# backend/llm_integration.py

import os
import json
import re
import uuid
import logging
import asyncio
import aiohttp

from datetime import datetime
from io import BytesIO
from typing import List, Dict, Any, Optional

from groq import Groq
import chromadb
from sentence_transformers import SentenceTransformer

import PyPDF2
import docx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Initialize Groq Client ───────────────────────────────────────────────────────
try:
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        raise ValueError("GROQ_API_KEY environment variable is not set")
    groq_client = Groq(api_key=groq_api_key)
    logger.info("Groq client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Groq client: {e}")
    raise

# ─── Initialize ChromaDB Client and Embedding Model ─────────────────────────────────
try:
    chroma_client = chromadb.Client()
    embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
    logger.info("ChromaDB client and embedding model initialized")
except Exception as e:
    logger.error(f"Failed to initialize ChromaDB or embedding model: {e}")
    raise

# ─── Global In-Memory Storage ───────────────────────────────────────────────────────
conversations: Dict[str, Any] = {}       # conversation_id → List[ChatMessage]
document_collections: Dict[str, Any] = {}  # collection_id → metadata & chunks
research_insights: Dict[str, Any] = {}    # conversation_id → List[ResearchInsight]
user_notes: Dict[str, Any] = {}           # conversation_id → List[note dict]


# ─── Data Models ───────────────────────────────────────────────────────────────────
from pydantic import BaseModel

class ChatMessage(BaseModel):
    role: str
    content: str
    timestamp: datetime = datetime.now()
    sources: List[str] = []
    reasoning_type: Optional[str] = None

class ConversationRequest(BaseModel):
    message: str
    conversation_id: str
    use_chain_of_thought: bool = False
    use_tools: bool = True
    context_limit: int = 10

    # New fields to support arbitrary Q&A over uploaded documents
    document_collections: Optional[List[str]] = None
    full_conversation: Optional[List[Dict[str, Any]]] = None

class ToolCall(BaseModel):
    name: str
    parameters: Dict[str, Any]

class ResearchInsight(BaseModel):
    title: str
    content: str
    sources: List[str]
    confidence: float
    visualization_data: Optional[Dict] = None


# ─── DocumentProcessor ─────────────────────────────────────────────────────────────
class DocumentProcessor:
    """Handle document processing and chunking for RAG"""
    
    @staticmethod
    def extract_text_from_pdf(file_content: bytes) -> str:
        """Extract text from PDF file"""
        try:
            pdf_reader = PyPDF2.PdfReader(BytesIO(file_content))
            text = ""
            for page in pdf_reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
            return text
        except Exception as e:
            logger.error(f"PDF extraction error: {e}")
            return ""
    
    @staticmethod
    def extract_text_from_docx(file_content: bytes) -> str:
        """Extract text from DOCX file"""
        try:
            doc = docx.Document(BytesIO(file_content))
            text = ""
            for paragraph in doc.paragraphs:
                text += paragraph.text + "\n"
            return text
        except Exception as e:
            logger.error(f"DOCX extraction error: {e}")
            return ""
    
    @staticmethod
    def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> List[str]:
        """Split text into overlapping chunks of ~chunk_size words with overlap"""
        words = text.split()
        chunks: List[str] = []
        for i in range(0, len(words), chunk_size - overlap):
            chunk = " ".join(words[i : i + chunk_size])
            if chunk.strip():
                chunks.append(chunk)
        return chunks


# ─── WebSearchTool ─────────────────────────────────────────────────────────────────
class WebSearchTool:
    """
    Web search using DuckDuckGo’s “HTML” endpoint, then scrape and summarize each URL.
    """

    @staticmethod
    async def search(query: str, num_results: int = 5) -> List[Dict[str, Any]]:
        """
        Perform a DuckDuckGo search via html.duckduckgo.com/html/ 
        and return up to num_results items of {title, url, snippet}.
        """
        try:
            search_url = "https://html.duckduckgo.com/html/"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
            }
            form_data = {'q': query}
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.post(search_url, data=form_data, headers=headers) as response:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    results: List[Dict[str, Any]] = []
                    # Each result is in a <div class="result"> or similar
                    # In DuckDuckGo HTML, links appear as <a class="result__a" href="...">Title</a>
                    anchors = soup.find_all("a", {"class": "result__a"})
                    count = 0
                    for a in anchors:
                        if count >= num_results:
                            break
                        url = a.get("href")
                        title = a.get_text(strip=True)
                        # Snippet is usually in a sibling <a> or <div class="result__snippet">
                        snippet_tag = a.find_parent("div", {"class": "result"}).find("a", {"class": "result__snippet"})
                        snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
                        if url and title:
                            results.append({
                                "title": title[:150],
                                "url": url,
                                "snippet": snippet[:300]
                            })
                            count += 1
                    if results:
                        logger.info(f"Web search (HTML endpoint) returned {len(results)} results for query: {query}")
                        return results
            # No results found
            logger.warning(f"No real search results found for '{query}'")
            return []
        except Exception as e:
            logger.error(f"Web search error: {e}")
            return []

    @staticmethod
    async def scrape_content(url: str) -> str:
        """Scrape text from a webpage, with basic cleanup (up to 5000 chars)."""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
            }
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                            tag.decompose()
                        main_content = ""
                        selectors = ['article', 'main', '.content', '.post-content', '.entry-content', '#content']
                        for sel in selectors:
                            element = soup.select_one(sel)
                            if element:
                                main_content = element.get_text(separator=" ", strip=True)
                                break
                        if not main_content:
                            main_content = soup.get_text(separator=" ", strip=True)
                        # Clean whitespace
                        lines = (line.strip() for line in main_content.splitlines())
                        phrases = (phrase.strip() for line in lines for phrase in line.split("  "))
                        clean = ' '.join(phrase for phrase in phrases if phrase)
                        return clean[:5000]  # limit length
                    else:
                        return f"Unable to fetch content (HTTP {response.status})"
        except Exception as e:
            logger.error(f"Scraping error for URL {url}: {e}")
            return f"Error fetching content from {url}: {str(e)}"


# ─── ToolManager ───────────────────────────────────────────────────────────────────
class ToolManager:
    """Manage and execute various tools with robust error handling."""
    
    def __init__(self):
        self.tools = {
            "web_search": self.web_search,
            "document_summarize": self.document_summarize,
            "document_extract": self.document_extract,
            "take_note": self.take_note,
            "get_notes": self.get_notes,
            "explain_concept": self.explain_concept,
            "clarify_information": self.clarify_information,
            "generate_insights": self.generate_insights
        }
    
    async def execute_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a specific tool by name, returning its result or an error dict."""
        if tool_name not in self.tools:
            return {"error": f"Tool '{tool_name}' not found. Available: {list(self.tools.keys())}"}
        try:
            logger.info(f"Executing tool '{tool_name}' with parameters: {parameters}")
            result = await self.tools[tool_name](**parameters)
            logger.info(f"Tool '{tool_name}' executed successfully")
            return result
        except TypeError as e:
            logger.error(f"Invalid parameters for '{tool_name}': {e}")
            return {"error": f"Invalid parameters for '{tool_name}': {str(e)}"}
        except Exception as e:
            logger.error(f"Error executing tool '{tool_name}': {e}")
            return {"error": f"Execution error in '{tool_name}': {str(e)}"}
    
    async def web_search(self, query: str, num_results: int = 5) -> Dict[str, Any]:
        """
        Perform a web search via WebSearchTool.search, scrape & summarize each URL, and return.
        Summaries are generated with Groq to stay under token limits.
        """
        try:
            raw_results = await WebSearchTool.search(query, num_results)
            if not raw_results:
                return {
                    "tool": "web_search",
                    "results": [],
                    "count": 0,
                    "success": True,
                    "message": f"No search results found for '{query}'."
                }

            summarized_results: List[Dict[str, Any]] = []
            for entry in raw_results:
                url = entry["url"]
                title = entry["title"]
                snippet = entry.get("snippet", "")

                # 1) Scrape the page content (up to ~5000 chars)
                page_text = await WebSearchTool.scrape_content(url)

                # 2) Summarize that scraped content with Groq (limit ~200 words)
                summary = ""
                try:
                    # Keep Groq prompt + text under its token limit; we slice to first ~2000 chars
                    truncated = page_text[:2000]
                    groq_prompt = (
                        "You are a research assistant. Provide a concise summary (in ~200 words) "
                        "of the following web page content:\n\n"
                        f"{truncated}"
                    )
                    response = groq_client.chat.completions.create(
                        model="llama3-8b-8192",
                        messages=[
                            {"role": "system", "content": "Summarize this web page content clearly."},
                            {"role": "user", "content": groq_prompt}
                        ],
                        max_tokens=400  # ~200 words
                    )
                    summary = response.choices[0].message.content.strip()
                except Exception as e:
                    logger.warning(f"Groq summarization failed for URL {url}: {e}")
                    summary = snippet or "No summary available."

                summarized_results.append({
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "summary": summary
                })

            return {
                "tool": "web_search",
                "results": summarized_results,
                "count": len(summarized_results),
                "success": True
            }
        except Exception as e:
            logger.error(f"web_search error: {e}")
            return {"tool": "web_search", "results": [], "count": 0, "success": False, "error": str(e)}
    
    async def document_summarize(self, collection_id: str, max_length: int = 500) -> Dict[str, Any]:
        """Summarize the document collection with Groq or fallback."""
        if collection_id not in document_collections:
            return {"error": "Collection not found", "success": False}
        try:
            collection_info = document_collections[collection_id]
            all_chunks: List[str] = []
            for doc_id, doc_data in collection_info['documents'].items():
                chunks = doc_data['chunks']
                all_chunks.extend(chunks[:5])  # top 5 chunks
            content = "\n\n".join(all_chunks)
            
            response = groq_client.chat.completions.create(
                model="llama3-8b-8192",
                messages=[
                    {"role": "system", "content": "You are a research assistant. Provide a concise summary of the following text."},
                    {"role": "user", "content": f"Summarize in ~{max_length} words:\n\n{content}"}
                ],
                max_tokens=max_length * 2
            )
            summary_text = response.choices[0].message.content
            return {
                "tool": "document_summarize",
                "summary": summary_text,
                "source_count": len(collection_info['documents']),
                "success": True
            }
        except Exception as e:
            logger.error(f"document_summarize error: {e}")
            return {"error": str(e), "success": False}
    
    async def document_extract(self, collection_id: str, query: str, max_length: int = 200) -> Dict[str, Any]:
        """Extract relevant snippets around query using ChromaDB or fallback."""
        if collection_id not in document_collections:
            return {"error": "Collection not found", "success": False}
        try:
            # Attempt vector search in ChromaDB
            try:
                collection = chroma_client.get_collection(name=collection_id)
                query_embedding = embedding_model.encode([query])
                results = collection.query(
                    query_embeddings=query_embedding.tolist(),
                    n_results=3
                )
                raw_chunks = results['documents'][0] if results['documents'] else []
            except Exception as e:
                logger.warning(f"ChromaDB query failed: {e}. Falling back to substring search.")
                raw_chunks = []
                doc_info = document_collections[collection_id]
                query_low = query.lower()
                for doc_id, doc_data in doc_info['documents'].items():
                    for chunk in doc_data['chunks']:
                        if query_low in chunk.lower():
                            raw_chunks.append(chunk)
                        if len(raw_chunks) >= 3:
                            break
                    if len(raw_chunks) >= 3:
                        break
            
            # From each chunk, extract the sentence containing the query
            relevant_sentences: List[str] = []
            for chunk in raw_chunks:
                sentences = re.split(r'(?<=[.!?])\s+', chunk)
                for sent in sentences:
                    if query.lower() in sent.lower():
                        words = sent.split()
                        if len(words) > max_length:
                            sent = ' '.join(words[:max_length]) + '…'
                        relevant_sentences.append(sent.strip())
                        break
                if len(relevant_sentences) >= 3:
                    break
            
            # Fallback if no relevant sentences
            if not relevant_sentences:
                fallback: List[str] = []
                for chunk in raw_chunks[:3]:
                    words = chunk.split()
                    if len(words) > max_length:
                        truncated = " ".join(words[:max_length]) + "…"
                    else:
                        truncated = chunk
                    fallback.append(truncated)
                relevant_sentences = fallback
            
            return {
                "tool": "document_extract",
                "query": query,
                "relevant_chunks": relevant_sentences,
                "chunk_count": len(relevant_sentences),
                "success": True
            }
        except Exception as e:
            logger.error(f"document_extract error: {e}")
            return {"error": str(e), "success": False}
    
    async def take_note(self, conversation_id: str, note: str, category: str = "general") -> Dict[str, Any]:
        """Store a note under the given conversation."""
        try:
            if conversation_id not in user_notes:
                user_notes[conversation_id] = []
            note_entry = {
                "id": str(uuid.uuid4()),
                "content": note,
                "category": category,
                "timestamp": datetime.now().isoformat()
            }
            user_notes[conversation_id].append(note_entry)
            return {"tool": "take_note", "note_id": note_entry["id"], "message": "Note saved", "success": True}
        except Exception as e:
            logger.error(f"take_note error: {e}")
            return {"error": str(e), "success": False}
    
    async def get_notes(self, conversation_id: str, category: Optional[str] = None) -> Dict[str, Any]:
        """Retrieve notes for a conversation, optionally filtered by category."""
        try:
            if conversation_id not in user_notes:
                return {"tool": "get_notes", "notes": [], "success": True}
            notes = user_notes[conversation_id]
            if category:
                notes = [n for n in notes if n['category'] == category]
            return {"tool": "get_notes", "notes": notes, "count": len(notes), "success": True}
        except Exception as e:
            logger.error(f"get_notes error: {e}")
            return {"error": str(e), "success": False}
    
    async def explain_concept(self, concept: str, level: str = "intermediate") -> Dict[str, Any]:
        """Explain a concept at a specified level of detail."""
        try:
            prompts = {
                "beginner": "Explain in simple terms for someone new to the subject.",
                "intermediate": "Provide a detailed explanation with examples.",
                "advanced": "Give a comprehensive technical explanation with nuances."
            }
            system_msg = prompts.get(level, prompts["intermediate"])
            response = groq_client.chat.completions.create(
                model="llama3-8b-8192",
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": f"Explain: {concept}"}
                ],
                max_tokens=1000
            )
            return {"tool": "explain_concept", "concept": concept, "explanation": response.choices[0].message.content, "success": True}
        except Exception as e:
            logger.error(f"explain_concept error: {e}")
            return {"error": str(e), "success": False}
    
    async def clarify_information(self, information: str, context: str = "") -> Dict[str, Any]:
        """Clarify provided information using the LLM."""
        try:
            prompt = f"Clarify this information: {information}"
            if context:
                prompt += f"\nContext: {context}"
            response = groq_client.chat.completions.create(
                model="llama3-8b-8192",
                messages=[
                    {"role": "system", "content": "You are a research assistant. Clarify the following text clearly."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=800
            )
            return {"tool": "clarify_information", "clarification": response.choices[0].message.content, "success": True}
        except Exception as e:
            logger.error(f"clarify_information error: {e}")
            return {"error": str(e), "success": False}
    
    async def generate_insights(self, conversation_id: str) -> Dict[str, Any]:
        """Generate insights from the last 10 messages in a conversation."""
        if conversation_id not in conversations:
            return {"error": "Conversation not found", "success": False}
        try:
            recent_msgs = conversations[conversation_id][-10:]
            conversation_text = "\n".join([msg.content for msg in recent_msgs])
            response = groq_client.chat.completions.create(
                model="llama3-8b-8192",
                messages=[
                    {"role": "system", "content": "Analyze the following conversation and provide key insights."},
                    {"role": "user", "content": f"Conversation:\n{conversation_text}"}
                ],
                max_tokens=1000
            )
            insight = ResearchInsight(
                title="Conversation Insights",
                content=response.choices[0].message.content,
                sources=["conversation"],
                confidence=0.8
            )
            if conversation_id not in research_insights:
                research_insights[conversation_id] = []
            research_insights[conversation_id].append(insight)
            return {"tool": "generate_insights", "insights": [insight.dict()], "success": True}
        except Exception as e:
            logger.error(f"generate_insights error: {e}")
            return {"error": str(e), "success": False}


# ─── Instantiate a single ToolManager ───────────────────────────────────────────────
tool_manager = ToolManager()


# ─── ReasoningEngine ────────────────────────────────────────────────────────────────
class ReasoningEngine:
    """Handle Chain of Thought and ReAct reasoning patterns"""

    @staticmethod
    def chain_of_thought(query: str, context: str = "") -> str:
        """Perform Chain-of-Thought reasoning using Groq."""
        prompt = f"""
        Let's think step by step about this query: {query}
        
        Context: {context}
        
        1. What is being asked?
        2. What information do I already have?
        3. What steps should I follow?
        4. What is my conclusion?
        
        Provide your reasoning and final answer.
        """
        try:
            response = groq_client.chat.completions.create(
                model="llama3-8b-8192",
                messages=[
                    {"role": "system", "content": "Use step-by-step reasoning."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=1500
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"chain_of_thought error: {e}")
            return f"Error during chain-of-thought reasoning: {str(e)}"

    @staticmethod
    async def react_reasoning(query: str, tool_manager: ToolManager, conversation_id: str) -> str:
        """Perform ReAct reasoning with iterative tool calls."""
        max_iterations = 3
        reasoning_log: List[str] = []

        try:
            for i in range(max_iterations):
                thought_prompt = f"""
                Query: {query}
                Previous reasoning steps: {reasoning_log[-2:] if reasoning_log else 'None'}

                Available tools:
                - web_search(query, num_results)
                - document_summarize(collection_id, max_length)
                - document_extract(collection_id, query, max_length)
                - take_note(conversation_id, note, category)
                - generate_insights(conversation_id)
                - explain_concept(concept, level)
                - clarify_information(information, context)

                Think about the next action. If you have enough information, respond with 'finish'.
                Otherwise, choose a tool and provide parameters.

                Respond in the format:
                Thought: ...
                Action: <tool_name or 'finish'>
                Parameters: {{ ... }}
                """
                response = groq_client.chat.completions.create(
                    model="llama3-8b-8192",
                    messages=[
                        {"role": "system", "content": "You are a reasoning agent. Think step by step."},
                        {"role": "user", "content": thought_prompt}
                    ],
                    max_tokens=500
                )
                reasoning_step = response.choices[0].message.content
                reasoning_log.append(f"Iteration {i+1}: {reasoning_step}")

                if re.search(r"Action:\s*finish", reasoning_step, re.IGNORECASE):
                    logger.info("ReAct: finished reasoning loop")
                    break

                action_match = re.search(r"Action:\s*(\w+)", reasoning_step, re.IGNORECASE)
                if not action_match:
                    reasoning_log.append("No action identified; breaking.")
                    break

                action = action_match.group(1).lower()
                params: Dict[str, Any] = {}
                params_match = re.search(r"Parameters:\s*(\{.*\})", reasoning_step, re.DOTALL)
                if params_match:
                    try:
                        params = json.loads(params_match.group(1))
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse parameters JSON: {params_match.group(1)}")

                # Defaults and filtering for each tool
                if action == "web_search":
                    if "query" not in params:
                        params["query"] = query
                    params = {k: v for k, v in params.items() if k in ["query", "num_results"]}
                elif action == "document_summarize":
                    if "collection_id" not in params:
                        logger.warning("Missing collection_id for document_summarize; skipping action")
                        continue
                    params = {k: v for k, v in params.items() if k in ["collection_id", "max_length"]}
                elif action == "document_extract":
                    if "collection_id" not in params or "query" not in params:
                        logger.warning("Missing parameters for document_extract; skipping action")
                        continue
                    params = {k: v for k, v in params.items() if k in ["collection_id", "query", "max_length"]}
                elif action == "take_note":
                    if "conversation_id" not in params:
                        params["conversation_id"] = conversation_id
                    if "note" not in params:
                        params["note"] = f"Note regarding: {query}"
                    params = {k: v for k, v in params.items() if k in ["conversation_id", "note", "category"]}
                elif action == "generate_insights":
                    if "conversation_id" not in params:
                        params["conversation_id"] = conversation_id
                    params = {k: v for k, v in params.items() if k in ["conversation_id"]}
                elif action == "explain_concept":
                    if "concept" not in params:
                        params["concept"] = query
                    params = {k: v for k, v in params.items() if k in ["concept", "level"]}
                elif action == "clarify_information":
                    if "information" not in params:
                        params["information"] = query
                    params = {k: v for k, v in params.items() if k in ["information", "context"]}

                logger.info(f"ReAct executing tool '{action}' with params {params}")
                tool_result = await tool_manager.execute_tool(action, params)
                reasoning_log.append(f"Tool '{action}' result: {tool_result}")

            # After iterations, synthesize a final answer
            final_prompt = f"""
            Original query: {query}
            Reasoning steps:
            {json.dumps(reasoning_log, indent=2)}

            Based on the above reasoning, provide a concise final answer.
            """
            final_response = groq_client.chat.completions.create(
                model="llama3-8b-8192",
                messages=[
                    {"role": "system", "content": "Synthesize the reasoning and answer the query."},
                    {"role": "user", "content": final_prompt}
                ],
                max_tokens=1000
            )
            return final_response.choices[0].message.content

        except Exception as e:
            logger.error(f"react_reasoning error: {e}")
            return f"I encountered an error during reasoning. Here's a direct response: {query}"
