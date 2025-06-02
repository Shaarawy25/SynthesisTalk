// App.js
import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Send,
  Upload,
  FileText,
  Search,
  Brain,
  MessageSquare,
  BarChart3,
  Lightbulb,
  StickyNote,
  Loader
} from 'lucide-react';
import {
  BarChart,
  Bar,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip
} from 'recharts';

const API_BASE = 'http://localhost:8000';

const ChatInput = React.memo(({
  fileInputRef,
  isLoading,
  inputRef,
  handleKeyPress,
  onSend
}) => (
  <div className="p-4 border-t bg-white">
    <div className="flex space-x-2">
      <button
        onClick={() => fileInputRef.current?.click()}
        className="p-2 bg-gray-100 hover:bg-gray-200 rounded-lg disabled:opacity-50"
        title="Upload document"
        disabled={isLoading}
      >
        <Upload className="w-5 h-5" />
      </button>
      <textarea
        ref={inputRef}
        placeholder="Ask a question, request analysis, or upload documents..."
        className="flex-1 p-3 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none min-h-[44px] max-h-32"
        disabled={isLoading}
        autoComplete="off"
        rows={1}
        style={{ height: 'auto', minHeight: '44px' }}
        onInput={e => {
          e.target.style.height = 'auto';
          e.target.style.height = Math.min(e.target.scrollHeight, 128) + 'px';
        }}
        onKeyDown={handleKeyPress}
      />
      <button
        onClick={onSend}
        disabled={isLoading}
        className="p-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        <Send className="w-5 h-5" />
      </button>
    </div>
  </div>
));

export default function SynthesisTalk() {
  // ─── State Hooks ────────────────────────────────────────────────────────────────
  const [conversationId] = useState(() => `conv_${Date.now()}`);
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const [activeTab, setActiveTab] = useState('chat');
  const [useChainOfThought, setUseChainOfThought] = useState(false);
  const [useTools, setUseTools] = useState(false);
  const [insights, setInsights] = useState([]);

  // ─── Notes-specific state ───────────────────────────────────────────────────────
  const [notes, setNotes] = useState([]);
  const [notesLoading, setNotesLoading] = useState(false);
  const [notesError, setNotesError] = useState(null);

  // ─── Extract Modal state ────────────────────────────────────────────────────────
  const [showExtractModal, setShowExtractModal] = useState(false);
  const [currentExtractCollection, setCurrentExtractCollection] = useState(null);
  const [extractQuery, setExtractQuery] = useState('');

  // ─── Notes Modal state ───────────────────────────────────────────────────────────
  const [showNoteModal, setShowNoteModal] = useState(false);
  const [newNoteText, setNewNoteText] = useState('');
  const [newNoteCategory, setNewNoteCategory] = useState('');

  // ─── Usage stats for Analytics ─────────────────────────────────────────────────
  const [usageStats, setUsageStats] = useState({
    summaries: 0,
    extracts: 0,
    chains: 0,
    reacts: 0
  });

  const messagesContainerRef = useRef(null);
  const fileInputRef = useRef(null);
  const inputRef = useRef(null);

  // ─── Scroll to bottom on new messages ─────────────────────────────────────────
  useEffect(() => {
    if (activeTab === 'chat' && messagesContainerRef.current) {
      window.requestAnimationFrame(() => {
        const container = messagesContainerRef.current;
        container.scrollTop = container.scrollHeight;
      });
    }
  }, [messages, activeTab]);

  // ─── Focus textarea when switching to Chat tab ────────────────────────────────
  useEffect(() => {
    if (activeTab === 'chat') {
      inputRef.current?.focus();
    }
  }, [activeTab]);

  // ─── Generic tool executor ────────────────────────────────────────────────────────
  const executeTool = async (toolName, parameters) => {
    setIsLoading(true);
    try {
      const response = await fetch(`${API_BASE}/api/tools/${toolName}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(parameters)
      });
      return await response.json();
    } catch (error) {
      console.error('Tool execution error:', error);
      return { error: 'Tool execution failed' };
    } finally {
      setIsLoading(false);
    }
  };

  // ─── LOAD INSIGHTS ─────────────────────────────────────────────────────────────
  const loadInsights = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/insights/${conversationId}`, {
        method: 'GET'
      });
      const data = await response.json();
      setInsights(data.insights || []);
    } catch (error) {
      console.error('Insights loading error:', error);
    }
  }, [conversationId]);

  // ─── SEND CHAT MESSAGE ─────────────────────────────────────────────────────────
  const sendMessage = useCallback(async () => {
    const text = inputRef.current?.value.trim();
    if (!text || isLoading) return;

    // Clear textarea immediately, preserving focus
    inputRef.current.value = '';
    inputRef.current.style.height = 'auto';

    const userMsg = {
      role: 'user',
      content: text,
      timestamp: new Date().toISOString()
    };
    setMessages(prev => [...prev, userMsg]);
    setIsLoading(true);

    try {
      const collections = uploadedFiles.map(f => f.collection_id);
      const response = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          conversation_id: conversationId,
          use_chain_of_thought: useChainOfThought,
          use_tools: useTools,
          document_collections: collections,
          full_conversation: messages
        })
      });
      const data = await response.json();

      // ─── Always increment 'reacts' if reasoning_type === 'react' ───────────────────────
      let reasoningType = null;
      if (data.reasoning_type === 'chain_of_thought') {
        reasoningType = 'chain_of_thought';
        setUsageStats(prev => ({ ...prev, chains: prev.chains + 1 }));
      } else if (data.reasoning_type === 'react') {
        reasoningType = 'react';
        setUsageStats(prev => ({ ...prev, reacts: prev.reacts + 1 }));
      }

      const assistantMsg = {
        role: 'assistant',
        content: data.response,
        timestamp: new Date().toISOString(),
        reasoning_type: reasoningType
      };
      setMessages(prev => [...prev, assistantMsg]);
      await loadInsights();
    } catch (error) {
      console.error('Chat error:', error);
      const errMsg = {
        role: 'assistant',
        content: 'An error occurred. Please try again.',
        timestamp: new Date().toISOString(),
        isError: true
      };
      setMessages(prev => [...prev, errMsg]);
    } finally {
      setIsLoading(false);
    }
  }, [
    conversationId,
    useChainOfThought,
    useTools,
    uploadedFiles,
    messages,
    loadInsights,
    isLoading
  ]);

  // ─── UPLOAD DOCUMENT ───────────────────────────────────────────────────────────
  const uploadFile = async (file) => {
    if (!file) return;
    setIsLoading(true);

    const formData = new FormData();
    formData.append('file', file);
    try {
      const response = await fetch(`${API_BASE}/api/upload`, {
        method: 'POST',
        body: formData
      });
      const data = await response.json();
      setUploadedFiles(prev => [...prev, data]);

      const sysMsg = {
        role: 'system',
        content: `📄 Uploaded: ${data.filename} (${data.chunk_count} chunks)`,
        timestamp: new Date().toISOString(),
      };
      setMessages(prev => [...prev, sysMsg]);
    } catch (error) {
      console.error('Upload error:', error);
      alert('Failed to upload file. Please try again.');
    } finally {
      setIsLoading(false);
      inputRef.current?.focus();
    }
  };

  // ─── LOAD NOTES ────────────────────────────────────────────────────────────────
  const loadNotes = useCallback(async () => {
    setNotesLoading(true);
    setNotesError(null);
    try {
      const result = await executeTool('get_notes', { conversation_id: conversationId });
      if (result.error) {
        throw new Error(result.error);
      }
      if (Array.isArray(result.notes)) {
        setNotes(result.notes);
      } else {
        setNotes([]);
      }
    } catch (error) {
      console.error('Notes loading error:', error);
      setNotesError('Failed to load notes');
      setNotes([]);
    } finally {
      setNotesLoading(false);
    }
  }, [conversationId]);

  // ─── RELOAD NOTES WHEN ACTIVE TAB CHANGES ─────────────────────────────────────
  useEffect(() => {
    if (activeTab === 'notes') {
      loadNotes();
    }
  }, [activeTab, loadNotes]);

  // ─── EXPORT INSIGHTS ──────────────────────────────────────────────────────────
  const exportInsights = () => {
    const header = `Research Insights Export\nGenerated on ${new Date().toLocaleString()}\n\n`;
    const body = insights.map((ins, idx) => {
      return `Insight ${idx + 1}:\nTitle: ${ins.title}\nContent:\n${ins.content}\nSources: ${ins.sources.join(
        ', '
      )}\nConfidence: ${(ins.confidence * 100).toFixed(1)}%\n\n`;
    }).join('');
    const fullText = header + body;
    const blob = new Blob([fullText], { type: 'text/plain' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `insights_export_${Date.now()}.txt`;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);
  };

  // ─── INPUT HANDLERS ────────────────────────────────────────────────────────────────
  const handleKeyPress = useCallback((e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }, [sendMessage]);
}
