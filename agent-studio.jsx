import { useState, useEffect } from "react";

const API = "http://localhost:8000";
const AGENT_ID = "vamos-events";

// Seed data for demo (matches the training.json we created)
const SEED = {
  rules: [
    { rule: "Never quote a specific fixed price. Always use ranges and say 'approximate'.", added_at: "2026-02-08" },
    { rule: "Do NOT confirm availability for specific dates. Say we'll check during consultation.", added_at: "2026-02-08" },
    { rule: "For destination events outside Ontario, mention travel surcharges ($2,000–$5,000).", added_at: "2026-02-08" },
    { rule: "No events with fewer than 30 days notice.", added_at: "2026-02-08" },
  ],
  faq: [
    { question: "Do you travel for destination weddings?", answer: "Yes! We've performed across Canada, the US, Mexico, and the Caribbean. Travel surcharges of $2,000–$5,000 apply.", added_at: "2026-02-08" },
    { question: "Can we see you perform before booking?", answer: "Absolutely! We can show videos from past events during a consultation, plus highlights at vamosevents.ca/gallery.", added_at: "2026-02-08" },
    { question: "What genres do you play?", answer: "Genre-versatile — Top 40, R&B, Hip Hop, Latin, House, Afrobeats, Bollywood, Greek, Arabic, and more. Custom playlists for each event.", added_at: "2026-02-08" },
  ],
  examples: [
    { scenario: "Prospect asks about pricing for a small wedding", good_response: "For an intimate wedding, MC/DJ packages start around $5,000. A beautiful package usually comes together in the $5,000–$8,000 range.", bad_response: "Our minimum is $5,000. What's your budget?", added_at: "2026-02-08" },
    { scenario: "Prospect is comparing multiple vendors", good_response: "It's smart to explore options! Our focus is on curating every moment as a fully coordinated experience — not just playing music.", bad_response: "We're the best in the industry.", added_at: "2026-02-08" },
  ],
  corrections: [
    { situation: "When a prospect mentions a venue we've worked at", wrong: "That's a nice venue!", correction: "If we've worked there, mention it and share a detail: 'We've worked at The Arlington Estate several times — the acoustics are wonderful.'", added_at: "2026-02-08" },
  ],
};

/* ====== STYLES ====== */
const S = {
  page: { minHeight: "100vh", background: "#0A0A0A", color: "#F5F0E8", fontFamily: "'DM Sans', -apple-system, sans-serif", padding: "32px 24px" },
  container: { maxWidth: 900, margin: "0 auto" },
  header: { marginBottom: 40 },
  h1: { fontSize: 32, fontWeight: 700, color: "#C8A96E", marginBottom: 8 },
  subtitle: { fontSize: 15, color: "#B0A898", lineHeight: 1.6 },
  tabs: { display: "flex", gap: 4, marginBottom: 32, flexWrap: "wrap" },
  tab: (active) => ({
    padding: "10px 20px", fontSize: 13, fontWeight: 600, borderRadius: 8, cursor: "pointer", border: "1px solid transparent", transition: "all 0.2s",
    background: active ? "rgba(200,169,110,0.1)" : "transparent",
    color: active ? "#C8A96E" : "#B0A898",
    borderColor: active ? "rgba(200,169,110,0.2)" : "transparent",
  }),
  card: { background: "#1A1A1A", border: "1px solid #2A2A2A", borderRadius: 12, padding: 24, marginBottom: 16 },
  cardHeader: { display: "flex", justifyContent: "space-between", alignItems: "start", marginBottom: 12 },
  label: { fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: 1.5, color: "#706A60", marginBottom: 8, display: "block" },
  input: { width: "100%", padding: "12px 16px", background: "#2A2A2A", border: "1px solid #2A2A2A", borderRadius: 10, color: "#F5F0E8", fontFamily: "inherit", fontSize: 14, outline: "none" },
  textarea: { width: "100%", padding: "12px 16px", background: "#2A2A2A", border: "1px solid #2A2A2A", borderRadius: 10, color: "#F5F0E8", fontFamily: "inherit", fontSize: 14, outline: "none", resize: "vertical", minHeight: 80, lineHeight: 1.5 },
  btnPrimary: { padding: "12px 24px", background: "linear-gradient(135deg, #C8A96E, #A68B4B)", color: "#0A0A0A", fontWeight: 600, fontSize: 14, border: "none", borderRadius: 10, cursor: "pointer", fontFamily: "inherit" },
  btnSecondary: { padding: "8px 16px", background: "transparent", border: "1px solid #2A2A2A", color: "#B0A898", fontSize: 13, fontWeight: 600, borderRadius: 8, cursor: "pointer", fontFamily: "inherit" },
  btnDanger: { padding: "6px 12px", background: "rgba(199,80,80,0.1)", border: "1px solid rgba(199,80,80,0.2)", color: "#E88888", fontSize: 12, fontWeight: 600, borderRadius: 6, cursor: "pointer", fontFamily: "inherit" },
  badge: { display: "inline-block", padding: "3px 10px", borderRadius: 100, fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.5, background: "rgba(200,169,110,0.15)", color: "#C8A96E" },
  empty: { textAlign: "center", padding: 40, color: "#706A60" },
  hint: { fontSize: 12, color: "#706A60", marginTop: 4 },
  divider: { height: 1, background: "#2A2A2A", margin: "24px 0" },
  howBox: { background: "#1A1A1A", border: "1px solid #2A2A2A", borderRadius: 12, padding: 24 },
};

function Field({ label, hint, children }) {
  return (
    <div style={{ marginBottom: 20 }}>
      {label && <label style={S.label}>{label}</label>}
      {children}
      {hint && <div style={S.hint}>{hint}</div>}
    </div>
  );
}

/* ====== TABS ====== */
function RulesTab({ rules, setRules }) {
  const [newRule, setNewRule] = useState("");
  const add = () => { if (newRule.trim()) { setRules([...rules, { rule: newRule.trim(), added_at: new Date().toISOString().slice(0, 10) }]); setNewRule(""); } };
  const remove = (i) => setRules(rules.filter((_, j) => j !== i));
  return (
    <div>
      <p style={{ fontSize: 14, color: "#B0A898", marginBottom: 24, lineHeight: 1.6 }}>
        Rules are absolute instructions your AI agent must follow. They override default behavior. Use these for things the agent should <strong style={{ color: "#F5F0E8" }}>always</strong> or <strong style={{ color: "#F5F0E8" }}>never</strong> do.
      </p>
      {rules.map((r, i) => (
        <div key={i} style={S.card}>
          <div style={S.cardHeader}>
            <div style={{ flex: 1, fontSize: 14, lineHeight: 1.6 }}>{r.rule}</div>
            <button style={S.btnDanger} onClick={() => remove(i)}>Remove</button>
          </div>
        </div>
      ))}
      <div style={{ ...S.card, borderStyle: "dashed" }}>
        <Field label="Add a new rule" hint='Example: "Never discuss competitor pricing" or "Always mention our 5-star Google rating"'>
          <textarea style={S.textarea} placeholder="Type a rule your AI must follow..." value={newRule} onChange={e => setNewRule(e.target.value)} rows={2} />
        </Field>
        <button style={S.btnPrimary} onClick={add} disabled={!newRule.trim()}>Add Rule</button>
      </div>
    </div>
  );
}

function FAQTab({ faq, setFaq }) {
  const [q, setQ] = useState(""); const [a, setA] = useState("");
  const add = () => { if (q.trim() && a.trim()) { setFaq([...faq, { question: q.trim(), answer: a.trim(), added_at: new Date().toISOString().slice(0, 10) }]); setQ(""); setA(""); } };
  const remove = (i) => setFaq(faq.filter((_, j) => j !== i));
  return (
    <div>
      <p style={{ fontSize: 14, color: "#B0A898", marginBottom: 24, lineHeight: 1.6 }}>
        When prospects ask these questions, your AI will use your exact answers. This ensures accurate, owner-approved responses for common questions.
      </p>
      {faq.map((f, i) => (
        <div key={i} style={S.card}>
          <div style={S.cardHeader}>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 8, color: "#C8A96E" }}>Q: {f.question}</div>
              <div style={{ fontSize: 14, color: "#B0A898", lineHeight: 1.6 }}>A: {f.answer}</div>
            </div>
            <button style={S.btnDanger} onClick={() => remove(i)}>Remove</button>
          </div>
        </div>
      ))}
      <div style={{ ...S.card, borderStyle: "dashed" }}>
        <Field label="Question"><input style={S.input} placeholder="What do prospects commonly ask?" value={q} onChange={e => setQ(e.target.value)} /></Field>
        <Field label="Your approved answer"><textarea style={S.textarea} placeholder="The answer you want the AI to give..." value={a} onChange={e => setA(e.target.value)} /></Field>
        <button style={S.btnPrimary} onClick={add} disabled={!q.trim() || !a.trim()}>Add FAQ</button>
      </div>
    </div>
  );
}

function ExamplesTab({ examples, setExamples }) {
  const [scenario, setScenario] = useState(""); const [good, setGood] = useState(""); const [bad, setBad] = useState("");
  const add = () => { if (scenario.trim() && good.trim()) { setExamples([...examples, { scenario: scenario.trim(), good_response: good.trim(), bad_response: bad.trim() || null, added_at: new Date().toISOString().slice(0, 10) }]); setScenario(""); setGood(""); setBad(""); } };
  const remove = (i) => setExamples(examples.filter((_, j) => j !== i));
  return (
    <div>
      <p style={{ fontSize: 14, color: "#B0A898", marginBottom: 24, lineHeight: 1.6 }}>
        Teach your AI by example. Describe a situation, show what a <strong style={{ color: "#5CB85C" }}>good</strong> response looks like, and optionally what to <strong style={{ color: "#E88888" }}>avoid</strong>. The AI learns your style from these patterns.
      </p>
      {examples.map((ex, i) => (
        <div key={i} style={S.card}>
          <div style={S.cardHeader}><div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600, fontSize: 13, color: "#706A60", marginBottom: 8 }}>SCENARIO</div>
            <div style={{ fontSize: 14, marginBottom: 12 }}>{ex.scenario}</div>
            <div style={{ padding: 12, background: "rgba(92,184,92,0.08)", border: "1px solid rgba(92,184,92,0.15)", borderRadius: 8, marginBottom: 8 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "#5CB85C", marginBottom: 4 }}>✓ GOOD RESPONSE</div>
              <div style={{ fontSize: 13, color: "#B0A898", lineHeight: 1.5 }}>{ex.good_response}</div>
            </div>
            {ex.bad_response && <div style={{ padding: 12, background: "rgba(199,80,80,0.08)", border: "1px solid rgba(199,80,80,0.15)", borderRadius: 8 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "#E88888", marginBottom: 4 }}>✗ AVOID</div>
              <div style={{ fontSize: 13, color: "#B0A898", lineHeight: 1.5 }}>{ex.bad_response}</div>
            </div>}
          </div><button style={S.btnDanger} onClick={() => remove(i)}>Remove</button></div>
        </div>
      ))}
      <div style={{ ...S.card, borderStyle: "dashed" }}>
        <Field label="Scenario" hint="Describe the situation"><input style={S.input} placeholder="e.g., Prospect asks about a last-minute booking" value={scenario} onChange={e => setScenario(e.target.value)} /></Field>
        <Field label="Good response" hint="What should the AI say?"><textarea style={S.textarea} placeholder="The ideal response..." value={good} onChange={e => setGood(e.target.value)} /></Field>
        <Field label="What to avoid (optional)" hint="What should the AI NOT say?"><textarea style={S.textarea} placeholder="A bad response pattern to avoid..." value={bad} onChange={e => setBad(e.target.value)} /></Field>
        <button style={S.btnPrimary} onClick={add} disabled={!scenario.trim() || !good.trim()}>Add Example</button>
      </div>
    </div>
  );
}

function CorrectionsTab({ corrections, setCorrections }) {
  const [sit, setSit] = useState(""); const [wrong, setWrong] = useState(""); const [fix, setFix] = useState("");
  const add = () => { if (sit.trim() && fix.trim()) { setCorrections([...corrections, { situation: sit.trim(), wrong: wrong.trim() || null, correction: fix.trim(), added_at: new Date().toISOString().slice(0, 10) }]); setSit(""); setWrong(""); setFix(""); } };
  const remove = (i) => setCorrections(corrections.filter((_, j) => j !== i));
  return (
    <div>
      <p style={{ fontSize: 14, color: "#B0A898", marginBottom: 24, lineHeight: 1.6 }}>
        Noticed the AI doing something wrong? Add a correction here. This is the most powerful tuning tool — the AI treats these as direct feedback from you.
      </p>
      {corrections.map((c, i) => (
        <div key={i} style={S.card}>
          <div style={S.cardHeader}><div style={{ flex: 1 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "#706A60", marginBottom: 4 }}>WHEN: {c.situation}</div>
            {c.wrong && <div style={{ fontSize: 13, color: "#E88888", marginBottom: 4 }}>Instead of: {c.wrong}</div>}
            <div style={{ fontSize: 14, color: "#7DD87D" }}>Do this: {c.correction}</div>
          </div><button style={S.btnDanger} onClick={() => remove(i)}>Remove</button></div>
        </div>
      ))}
      <div style={{ ...S.card, borderStyle: "dashed" }}>
        <Field label="When does this happen?"><input style={S.input} placeholder="e.g., When prospect mentions a specific venue" value={sit} onChange={e => setSit(e.target.value)} /></Field>
        <Field label="What the AI does wrong (optional)"><input style={S.input} placeholder="e.g., Gives a generic 'nice venue' response" value={wrong} onChange={e => setWrong(e.target.value)} /></Field>
        <Field label="What it should do instead"><textarea style={S.textarea} placeholder="e.g., If we've worked at their venue, mention it specifically and share a relevant detail..." value={fix} onChange={e => setFix(e.target.value)} /></Field>
        <button style={S.btnPrimary} onClick={add} disabled={!sit.trim() || !fix.trim()}>Add Correction</button>
      </div>
    </div>
  );
}

function HowItWorksTab() {
  return (
    <div>
      <div style={S.howBox}>
        <h3 style={{ fontSize: 20, fontWeight: 700, color: "#C8A96E", marginBottom: 16 }}>How Agent Tuning Works</h3>
        <p style={{ fontSize: 14, color: "#B0A898", lineHeight: 1.8, marginBottom: 24 }}>
          Your AI concierge is powered by a large language model. Everything it knows about your business — how to talk, what to quote, when to qualify — comes from a <strong style={{ color: "#F5F0E8" }}>system prompt</strong> that's generated dynamically from your configuration and training data.
        </p>
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {[
            ["🏗️", "Rules", "Absolute instructions the AI must follow. These are injected directly into the system prompt as non-negotiable directives. Use for hard business constraints.", "\"Never quote fixed prices\" → AI always uses ranges"],
            ["❓", "FAQ", "Pre-approved answers to common questions. When a prospect asks a matching question, the AI uses your exact answer instead of generating one. Ensures accuracy on important topics.", "\"Do you travel?\" → Your specific answer about destinations and surcharges"],
            ["📝", "Examples", "Show-don't-tell training. The AI learns your communication style by seeing what good and bad responses look like in specific scenarios. Most effective for tone and approach.", "Scenario: prospect comparing vendors → Good: focus on value. Bad: trash talk competitors"],
            ["🔧", "Corrections", "Real-time fixes. When you see the AI doing something wrong in actual conversations, add a correction. These get highest priority in the prompt — the AI treats them as direct owner feedback.", "\"When they mention Hotel X, say we've worked there before\" → AI becomes venue-aware"],
          ].map(([emoji, title, desc, example], i) => (
            <div key={i} style={{ padding: 20, background: "#2A2A2A", borderRadius: 10 }}>
              <div style={{ display: "flex", gap: 12, alignItems: "start" }}>
                <div style={{ fontSize: 24, flexShrink: 0, lineHeight: 1.2 }}>{emoji}</div>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 15, marginBottom: 4 }}>{title}</div>
                  <div style={{ fontSize: 13, color: "#B0A898", lineHeight: 1.6, marginBottom: 8 }}>{desc}</div>
                  <div style={{ fontSize: 12, color: "#706A60", fontStyle: "italic" }}>Example: {example}</div>
                </div>
              </div>
            </div>
          ))}
        </div>
        <div style={{ ...S.divider }} />
        <h4 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12, color: "#F5F0E8" }}>The feedback loop</h4>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
          {["Agent talks to prospects", "You review conversations in dashboard", "You spot something to improve", "Add rule/FAQ/example/correction", "Agent immediately improves"].map((step, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ padding: "6px 12px", background: "rgba(200,169,110,0.1)", borderRadius: 8, fontSize: 13, color: "#C8A96E", fontWeight: 500 }}>{step}</span>
              {i < 4 && <span style={{ color: "#706A60" }}>→</span>}
            </div>
          ))}
        </div>
        <p style={{ fontSize: 13, color: "#706A60", lineHeight: 1.6 }}>
          Changes take effect immediately — no retraining, no deployment, no waiting. The system prompt is regenerated on every conversation from your latest config + training data.
        </p>
      </div>
    </div>
  );
}

/* ====== MAIN APP ====== */
export default function AgentStudio() {
  const [tab, setTab] = useState("how");
  const [rules, setRules] = useState(SEED.rules);
  const [faq, setFaq] = useState(SEED.faq);
  const [examples, setExamples] = useState(SEED.examples);
  const [corrections, setCorrections] = useState(SEED.corrections);
  const [saved, setSaved] = useState(false);

  const save = () => { setSaved(true); setTimeout(() => setSaved(false), 2000); };

  const tabs = [
    { id: "how", label: "How It Works", icon: "💡" },
    { id: "rules", label: `Rules (${rules.length})`, icon: "🏗️" },
    { id: "faq", label: `FAQ (${faq.length})`, icon: "❓" },
    { id: "examples", label: `Examples (${examples.length})`, icon: "📝" },
    { id: "corrections", label: `Corrections (${corrections.length})`, icon: "🔧" },
  ];

  return (
    <div style={S.page}>
      <div style={S.container}>
        <div style={S.header}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start", flexWrap: "wrap", gap: 16 }}>
            <div>
              <h1 style={S.h1}>Agent Studio</h1>
              <p style={S.subtitle}>Train your AI concierge. Add rules, FAQs, examples, and corrections — changes take effect immediately.</p>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              {saved && <span style={{ fontSize: 13, color: "#5CB85C" }}>✓ Saved</span>}
              <button style={S.btnPrimary} onClick={save}>Save All Changes</button>
            </div>
          </div>
        </div>

        <div style={S.tabs}>
          {tabs.map(t => (
            <button key={t.id} style={S.tab(tab === t.id)} onClick={() => setTab(t.id)}>
              {t.icon} {t.label}
            </button>
          ))}
        </div>

        {tab === "how" && <HowItWorksTab />}
        {tab === "rules" && <RulesTab rules={rules} setRules={setRules} />}
        {tab === "faq" && <FAQTab faq={faq} setFaq={setFaq} />}
        {tab === "examples" && <ExamplesTab examples={examples} setExamples={setExamples} />}
        {tab === "corrections" && <CorrectionsTab corrections={corrections} setCorrections={setCorrections} />}
      </div>
    </div>
  );
}
