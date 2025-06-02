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

  // ─── QUICK ACTIONS ──────────────────────────────────────────────────────────────────
  const quickActions = [
    {
      label: 'Web Search',
      icon: Search,
      action: useCallback(() => {
        const prefix = 'Search for information about: ';
        inputRef.current.value = prefix;
        requestAnimationFrame(() => {
          if (inputRef.current) {
            inputRef.current.focus();
            inputRef.current.setSelectionRange(prefix.length, prefix.length);
          }
        });
      }, [])
    },
    {
      label: 'Summarize Docs',
      icon: FileText,
      action: async () => {
        if (uploadedFiles.length === 0) {
          alert('Please upload a document first.');
          return;
        }
        try {
          const result = await executeTool('document_summarize', {
            collection_id: uploadedFiles[0].collection_id
          });
          if (!result.success) {
            console.error('Summarize error:', result.error);
            alert(`Failed to summarize: ${result.error || 'Unknown error'}`);
            return;
          }
          setUsageStats(prev => ({ ...prev, summaries: prev.summaries + 1 }));

          const sumMsg = {
            role: 'assistant',
            content: `📋 Summary:\n\n${result.summary}`,
            timestamp: new Date().toISOString()
          };
          setMessages(prev => [...prev, sumMsg]);
          inputRef.current?.focus();
        } catch (error) {
          console.error('Summarize error:', error);
          alert('Failed to summarize document');
        }
      }
    },
    {
      label: 'Generate Insights',
      icon: Lightbulb,
      action: async () => {
        try {
          await executeTool('generate_insights', { conversation_id: conversationId });
          await loadInsights();
          const infoMsg = {
            role: 'system',
            content: '💡 Insights generated! Check the Insights tab.',
            timestamp: new Date().toISOString()
          };
          setMessages(prev => [...prev, infoMsg]);
          inputRef.current?.focus();
        } catch (error) {
          console.error('Generate insights error:', error);
          alert('Failed to generate insights');
        }
      }
    },
    {
      label: 'Take Note',
      icon: StickyNote,
      action: () => {
        setNewNoteText('');
        setNewNoteCategory('');
        setShowNoteModal(true);
      }
    }
  ];

  // ─── MESSAGE BUBBLE ────────────────────────────────────────────────────────────────
  const MessageBubble = React.memo(({ message }) => {
    const isUser = message.role === 'user';
    const isSystem = message.role === 'system';
    const showCoT = message.reasoning_type === 'chain_of_thought';
    const showReAct = message.reasoning_type === 'react';

    return (
      <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
        <div className={`
            max-w-[80%] p-4 rounded-lg ${
              isUser
                ? 'bg-blue-600 text-white'
                : isSystem
                  ? 'bg-gray-100 text-gray-700 border-l-4 border-blue-500'
                  : 'bg-white text-gray-800 shadow-md border'
            }
          `}
        >
          <div className="whitespace-pre-wrap">{message.content}</div>
          {showCoT && (
            <div className="mt-2 text-xs opacity-70 flex items-center">
              <Brain className="w-3 h-3 mr-1" />
              Chain of Thought
            </div>
          )}
          {showReAct && (
            <div className="mt-2 text-xs opacity-70 flex items-center">
              <Brain className="w-3 h-3 mr-1" />
              ReAct Reasoning
            </div>
          )}
          <div className="text-xs opacity-60 mt-1">
            {new Date(message.timestamp).toLocaleTimeString()}
          </div>
        </div>
      </div>
    );
  });

  // ─── CHAT INTERFACE ───────────────────────────────────────────────────────────────
  const ChatInterface = () => (
    <div className="flex flex-col h-full">
      {/* Settings & Export Insights */}
      <div className="bg-gray-50 p-4 border-b flex items-center justify-between">
        <div className="flex items-center space-x-4">
          <label className="flex items-center">
            <input
              type="checkbox"
              checked={useChainOfThought}
              onChange={(e) => setUseChainOfThought(e.target.checked)}
              className="mr-2"
            />
            <Brain className="w-4 h-4 mr-1" />
            Chain of Thought
          </label>
          <label className="flex items-center">
            <input
              type="checkbox"
              checked={useTools}
              onChange={(e) => setUseTools(e.target.checked)}
              className="mr-2"
            />
            ReAct (Tool-Calling)
          </label>
        </div>
        <button
          onClick={exportInsights}
          disabled={insights.length === 0}
          className="flex items-center px-3 py-1 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"
        >
          Export Insights
        </button>
      </div>

      {/* Quick Actions */}
      <div className="bg-white p-4 border-b">
        <div className="flex space-x-2 overflow-x-auto">
          {quickActions.map((action, idx) => (
            <button
              key={idx}
              onClick={action.action}
              disabled={isLoading}
              className="flex items-center px-3 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg whitespace-nowrap disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <action.icon className="w-4 h-4 mr-2" />
              {action.label}
            </button>
          ))}
        </div>
      </div>

      {/* Messages */}
      <div
        className="flex-1 overflow-y-auto p-4"
        ref={messagesContainerRef}
      >
        {messages.length === 0 ? (
          <div className="text-center text-gray-500 mt-8">
            <MessageSquare className="w-12 h-12 mx-auto mb-4 opacity-50" />
            <h3 className="text-lg font-semibold">Welcome to SynthesisTalk</h3>
            <p>Upload documents, ask questions, or explore with AI-powered insights.</p>
          </div>
        ) : (
          messages.map((message, idx) => (
            <MessageBubble key={`${message.timestamp}-${idx}`} message={message} />
          ))
        )}
        {isLoading && (
          <div className="flex justify-start mb-4">
            <div className="bg-white p-4 rounded-lg shadow-md border flex items-center">
              <Loader className="w-4 h-4 animate-spin mr-2" />
              Processing...
            </div>
          </div>
        )}
      </div>

      {/* Input Area */}
      <ChatInput
        fileInputRef={fileInputRef}
        isLoading={isLoading}
        inputRef={inputRef}
        handleKeyPress={handleKeyPress}
        onSend={sendMessage}
      />
    </div>
  );

  // ─── INSIGHTS PANEL ───────────────────────────────────────────────────────────────
  const InsightsPanel = () => (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between p-6 border-b">
        <h2 className="text-2xl font-bold flex items-center">
          <Lightbulb className="w-6 h-6 mr-2" />
          Research Insights
        </h2>
        <button
          onClick={loadInsights}
          disabled={isLoading}
          className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
        >
          Refresh
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-6">
        {insights.length === 0 ? (
          <div className="text-center text-gray-500 py-8">
            <Lightbulb className="w-12 h-12 mx-auto mb-4 opacity-50" />
            <p>No insights yet. Generate insights from the Chat tab.</p>
          </div>
        ) : (
          <div className="space-y-4">
            {insights.map((insight, idx) => (
              <div key={idx} className="bg-white p-6 rounded-lg shadow-md border">
                <h3 className="text-lg font-semibold mb-2">{insight.title}</h3>
                {/* Render bullet-formatted content with preserved line breaks */}
                <div className="text-gray-700 mb-3 whitespace-pre-wrap">
                  {insight.content}
                </div>
                <div className="flex items-center justify-between text-sm text-gray-500">
                  <div>Sources: {insight.sources.join(', ')}</div>
                  <div>Confidence: {(insight.confidence * 100).toFixed(1)}%</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );

  // ─── ANALYTICS & VISUALIZATIONS PANEL ─────────────────────────────────────────────
  const VisualizationsPanel = () => {
    const chartData = [
      { name: 'Summaries', value: usageStats.summaries },
      { name: 'Extracts', value: usageStats.extracts },
      { name: 'CoT Uses', value: usageStats.chains },
      { name: 'ReAct Uses', value: usageStats.reacts }
    ];

    return (
      <div className="flex flex-col h-full">
        <div className="flex items-center justify-between p-6 border-b">
          <h2 className="text-2xl font-bold flex items-center">
            <BarChart3 className="w-6 h-6 mr-2" />
            Analytics & Visualizations
          </h2>
          <button
            onClick={() => {}}
            disabled={isLoading}
            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
          >
            Refresh
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
            <div className="bg-white p-4 rounded-lg shadow-md border text-center">
              <div className="text-2xl font-bold text-blue-600">{usageStats.summaries}</div>
              <div className="text-sm text-gray-600">documents summarized</div>
            </div>
            <div className="bg-white p-4 rounded-lg shadow-md border text-center">
              <div className="text-2xl font-bold text-blue-600">{usageStats.extracts}</div>
              <div className="text-sm text-gray-600">extractions performed</div>
            </div>
            <div className="bg-white p-4 rounded-lg shadow-md border text-center">
              <div className="text-2xl font-bold text-blue-600">{usageStats.chains}</div>
              <div className="text-sm text-gray-600">CoT uses</div>
            </div>
            <div className="bg-white p-4 rounded-lg shadow-md border text-center">
              <div className="text-2xl font-bold text-blue-600">{usageStats.reacts}</div>
              <div className="text-sm text-gray-600">ReAct uses</div>
            </div>
          </div>
          <div className="bg-white p-6 rounded-lg shadow-md border">
            <h3 className="text-lg font-semibold mb-4">Tool Usage Chart</h3>
            <BarChart width={600} height={300} data={chartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis allowDecimals={false} />
              <Tooltip />
              <Bar dataKey="value" />
            </BarChart>
          </div>
        </div>
      </div>
    );
  };
}
