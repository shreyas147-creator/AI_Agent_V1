import { useState, useRef, useEffect, useCallback } from "react";

const API = "http://127.0.0.1:8000";

const QUICK_ACTIONS = [
  { label: "📅 Today's events", prompt: "What's on my calendar today?" },
  { label: "⏰ Add reminder", prompt: "Remind me at " },
  { label: "📄 Read PDF", prompt: "Index this PDF: " },
  { label: "📧 Draft email", prompt: "Draft an email to " },
  { label: "🧠 Remember", prompt: "Remember that " },
];

function ConfirmCard({ data, onConfirm, onCancel }) {
  const p = data.preview || {};
  return (
    <div className="confirm-card">
      <div className="confirm-header">
        <span className="confirm-icon">⚠️</span>
        <span>Confirm Action</span>
      </div>
      {p.to && (
        <div className="confirm-field">
          <span className="field-label">To</span>
          <span>{p.to}</span>
        </div>
      )}
      {p.subject && (
        <div className="confirm-field">
          <span className="field-label">Subject</span>
          <span>{p.subject}</span>
        </div>
      )}
      {p.body && (
        <div className="confirm-field">
          <span className="field-label">Body</span>
          <pre className="confirm-body">{p.body}</pre>
        </div>
      )}
      {!p.to && p.description && (
        <div className="confirm-field">
          <span className="field-label">Action</span>
          <span>{p.description}</span>
        </div>
      )}
      {p.warning && <div className="confirm-warning">{p.warning}</div>}
      <div className="confirm-actions">
        <button className="btn-cancel" onClick={onCancel}>Cancel</button>
        <button className="btn-confirm" onClick={onConfirm}>Confirm & Send</button>
      </div>
    </div>
  );
}

function Message({ msg }) {
  const isUser = msg.role === "user";
  return (
    <div className={`message ${isUser ? "msg-user" : "msg-assistant"}`}>
      {!isUser && <div className="msg-avatar">P</div>}
      <div className="msg-bubble">
        {msg.type === "confirmation_required" ? (
          <span className="msg-text">{msg.text}</span>
        ) : (
          <span className="msg-text">{msg.text}</span>
        )}
        {msg.latency_ms && !isUser && (
          <span className="msg-meta">{msg.latency_ms}ms</span>
        )}
      </div>
      {isUser && <div className="msg-avatar user-avatar">Y</div>}
    </div>
  );
}

function StatusDot({ status }) {
  return (
    <div className={`status-dot ${status}`} title={
      status === "ok" ? "Model connected"
      : status === "error" ? "Model offline"
      : "Checking..."
    } />
  );
}

export default function App() {
  const [messages, setMessages] = useState([
    {
      id: 0,
      role: "assistant",
      type: "response",
      text: "Hello. I'm your private local assistant. Everything stays on your machine.\n\nWhat can I do for you?",
    }
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("checking");
  const [pendingConfirm, setPendingConfirm] = useState(null); // {action_id, preview}
  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    checkHealth();
    const t = setInterval(checkHealth, 15000);
    return () => clearInterval(t);
  }, []);

  async function checkHealth() {
    try {
      const r = await fetch(`${API}/health`, { signal: AbortSignal.timeout(3000) });
      const d = await r.json();
      setStatus(d.model_loaded ? "ok" : "warn");
    } catch {
      setStatus("error");
    }
  }

  const addMessage = useCallback((msg) => {
    setMessages(prev => [...prev, { id: Date.now() + Math.random(), ...msg }]);
  }, []);

  async function send(text) {
    if (!text.trim() || loading) return;
    const userText = text.trim();
    setInput("");
    addMessage({ role: "user", type: "message", text: userText });
    setLoading(true);

    try {
      const r = await fetch(`${API}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userText, session_id: "main" }),
      });
      const data = await r.json();

      if (data.type === "confirmation_required") {
        setPendingConfirm({ action_id: data.action_id, preview: data.preview, tool: data.tool });
        addMessage({
          role: "assistant",
          type: "confirmation_required",
          text: `Ready to ${data.tool}. Please review below:`,
          latency_ms: data.latency_ms,
        });
      } else if (data.type === "clarify") {
        addMessage({ role: "assistant", type: "response", text: data.text, latency_ms: data.latency_ms });
      } else {
        addMessage({ role: "assistant", type: "response", text: data.text, latency_ms: data.latency_ms });
      }
    } catch (e) {
      addMessage({ role: "assistant", type: "error", text: "Connection failed. Is the backend running? (python main.py)" });
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  }

  async function handleConfirm(confirmed) {
    if (!pendingConfirm) return;
    const { action_id } = pendingConfirm;
    setPendingConfirm(null);
    setLoading(true);

    try {
      const r = await fetch(`${API}/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action_id, confirmed, session_id: "main" }),
      });
      const data = await r.json();
      addMessage({ role: "assistant", type: "response", text: data.text });
    } catch (e) {
      addMessage({ role: "assistant", type: "error", text: "Confirmation failed." });
    } finally {
      setLoading(false);
    }
  }

  function handleKey(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(input);
    }
  }

  return (
    <div className="app">
      <header className="header">
        <div className="header-left">
          <div className="logo">PA</div>
          <div>
            <div className="app-name">PrivateAI</div>
            <div className="app-sub">Local · Offline · Yours</div>
          </div>
        </div>
        <StatusDot status={status} />
      </header>

      <div className="quick-actions">
        {QUICK_ACTIONS.map(a => (
          <button
            key={a.label}
            className="quick-btn"
            onClick={() => setInput(a.prompt)}
          >
            {a.label}
          </button>
        ))}
      </div>

      <div className="messages">
        {messages.map(msg => <Message key={msg.id} msg={msg} />)}
        {loading && (
          <div className="message msg-assistant">
            <div className="msg-avatar">P</div>
            <div className="msg-bubble loading-bubble">
              <span className="dot" /><span className="dot" /><span className="dot" />
            </div>
          </div>
        )}
        {pendingConfirm && (
          <div className="message msg-assistant">
            <div className="msg-avatar">P</div>
            <ConfirmCard
              data={pendingConfirm}
              onConfirm={() => handleConfirm(true)}
              onCancel={() => handleConfirm(false)}
            />
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="input-area">
        <textarea
          ref={inputRef}
          className="chat-input"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKey}
          placeholder="Type a message… (Enter to send)"
          rows={1}
          disabled={loading}
        />
        <button
          className="send-btn"
          onClick={() => send(input)}
          disabled={!input.trim() || loading}
        >
          ↑
        </button>
      </div>
    </div>
  );
}
