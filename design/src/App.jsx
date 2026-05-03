import React, { useState } from 'react';
import {
  Home, BookOpen, MessageSquare, BarChart3, Settings as SettingsIcon,
  Users, CreditCard, Shield, Server, DollarSign, Lock, Sparkles, Bot,
  ChevronRight, Check, AlertCircle, TrendingUp, Plus, Edit, Trash2,
  RefreshCw, ArrowRight, Award, Brain, QrCode, Clock, CheckCircle2,
  Zap, GraduationCap, Activity, Key, FileText, Search,
  Power, Copy, Smartphone, ShieldCheck
} from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend, Area, AreaChart
} from 'recharts';

export default function App() {
  const [mode, setMode] = useState('admin');
  const [view, setView] = useState('admin-dashboard');

  const userNav = [
    { id: 'user-dashboard', label: 'Dashboard', icon: Home },
    { id: 'user-chat', label: 'AI Tutor', icon: Sparkles, badge: '7/25' },
    { id: 'user-quizzes', label: 'Practice Quiz', icon: BookOpen },
    { id: 'user-exams', label: 'Mock Exams', icon: GraduationCap },
    { id: 'user-progress', label: 'My Progress', icon: BarChart3 },
  ];
  const adminNav = [
    { id: 'admin-dashboard', label: 'Dashboard', icon: Home },
    { id: 'admin-providers', label: 'LLM Providers', icon: Server, badge: 5 },
    { id: 'admin-settings', label: 'Runtime Settings', icon: SettingsIcon },
    { id: 'admin-tiers', label: 'Subscription Tiers', icon: CreditCard },
    { id: 'admin-security', label: 'Security', icon: Shield },
    { id: 'admin-users', label: 'Users', icon: Users },
    { id: 'admin-audit', label: 'Audit Log', icon: FileText },
  ];
  const nav = mode === 'admin' ? adminNav : userNav;

  const switchMode = (m) => {
    setMode(m);
    setView(m === 'admin' ? 'admin-dashboard' : 'user-dashboard');
  };

  return (
    <div className="min-h-screen bg-slate-50 flex">
      <aside className="w-60 bg-white border-r border-slate-200 flex flex-col flex-shrink-0">
        <div className="p-5 border-b border-slate-200">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 bg-gradient-to-br from-indigo-600 to-purple-600 rounded-lg flex items-center justify-center shadow-sm">
              <Brain className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="font-bold text-slate-900 text-sm">CPMAI Prep</div>
              <div className="text-xs text-slate-500">Exam Platform</div>
            </div>
          </div>
        </div>
        <div className="p-3 border-b border-slate-200">
          <div className="bg-slate-100 rounded-lg p-1 flex">
            <button onClick={() => switchMode('user')}
              className={"flex-1 px-2 py-1.5 text-xs font-medium rounded-md transition " + (mode === 'user' ? 'bg-white shadow-sm text-slate-900' : 'text-slate-500')}>
              Learner
            </button>
            <button onClick={() => switchMode('admin')}
              className={"flex-1 px-2 py-1.5 text-xs font-medium rounded-md transition " + (mode === 'admin' ? 'bg-white shadow-sm text-slate-900' : 'text-slate-500')}>
              Admin
            </button>
          </div>
        </div>
        <nav className="flex-1 p-3 space-y-0.5 overflow-y-auto">
          {nav.map(item => {
            const Icon = item.icon;
            const active = view === item.id;
            return (
              <button key={item.id} onClick={() => setView(item.id)}
                className={"w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition " + (active ? 'bg-indigo-50 text-indigo-700 font-medium' : 'text-slate-600 hover:bg-slate-50')}>
                <Icon className="w-4 h-4" />
                <span className="flex-1 text-left">{item.label}</span>
                {item.badge && (
                  <span className={"text-xs px-1.5 py-0.5 rounded " + (active ? 'bg-indigo-100 text-indigo-700' : 'bg-slate-100 text-slate-600')}>
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
        <div className="p-3 border-t border-slate-200">
          <div className="flex items-center gap-2.5 p-1.5">
            <div className="w-9 h-9 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-full flex items-center justify-center text-white text-xs font-semibold">
              {mode === 'admin' ? 'AD' : 'PS'}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-slate-900 truncate">{mode === 'admin' ? 'Arjun Dixit' : 'Priya Sharma'}</div>
              <div className="text-xs text-slate-500 flex items-center gap-1">
                {mode === 'admin' && <ShieldCheck className="w-3 h-3 text-indigo-600" />}
                {mode === 'admin' ? 'Super Admin' : 'Pro Plan'}
              </div>
            </div>
          </div>
        </div>
      </aside>

      <main className="flex-1 overflow-auto min-w-0">
        {view === 'user-dashboard' && <UserDashboard />}
        {view === 'user-chat' && <AITutor />}
        {view === 'user-quizzes' && <PracticeQuiz />}
        {view === 'user-exams' && <MockExams />}
        {view === 'user-progress' && <UserProgress />}
        {view === 'admin-dashboard' && <AdminDashboard />}
        {view === 'admin-providers' && <LLMProviders />}
        {view === 'admin-settings' && <RuntimeSettings />}
        {view === 'admin-tiers' && <SubscriptionTiers />}
        {view === 'admin-security' && <Security />}
        {view === 'admin-users' && <UsersList />}
        {view === 'admin-audit' && <AuditLog />}
      </main>
    </div>
  );
}

function PageHeader({ title, subtitle, action }) {
  return (
    <div className="flex items-end justify-between mb-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">{title}</h1>
        {subtitle && <p className="text-slate-600 mt-1 text-sm">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

function StatCard({ icon: Icon, label, value, trend, trendColor = 'text-emerald-600' }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5">
      <div className="flex items-center gap-2 text-slate-500 text-xs font-medium mb-3">
        <Icon className="w-4 h-4" />
        {label}
      </div>
      <div className="text-2xl font-bold text-slate-900">{value}</div>
      {trend && <div className={"text-xs mt-1 " + trendColor}>{trend}</div>}
    </div>
  );
}

function Badge({ color, children, dot }) {
  const colors = {
    green: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    yellow: 'bg-amber-50 text-amber-700 border-amber-200',
    red: 'bg-rose-50 text-rose-700 border-rose-200',
    blue: 'bg-blue-50 text-blue-700 border-blue-200',
    indigo: 'bg-indigo-50 text-indigo-700 border-indigo-200',
    purple: 'bg-purple-50 text-purple-700 border-purple-200',
    slate: 'bg-slate-100 text-slate-700 border-slate-200',
  };
  const dots = { green: 'bg-emerald-500', yellow: 'bg-amber-500', red: 'bg-rose-500', slate: 'bg-slate-400' };
  return (
    <span className={"inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-md border font-medium " + colors[color]}>
      {dot && <span className={"w-1.5 h-1.5 rounded-full " + dots[dot]} />}
      {children}
    </span>
  );
}

function UserDashboard() {
  const phases = [
    { name: 'Business Understanding', progress: 88, color: 'bg-emerald-500' },
    { name: 'Data Understanding', progress: 72, color: 'bg-emerald-500' },
    { name: 'Data Preparation', progress: 55, color: 'bg-amber-500' },
    { name: 'Modeling', progress: 64, color: 'bg-amber-500' },
    { name: 'Model Evaluation', progress: 31, color: 'bg-rose-500' },
    { name: 'Model Operationalization', progress: 22, color: 'bg-rose-500' },
  ];
  return (
    <div className="p-8">
      <PageHeader title="Welcome back, Priya 👋" subtitle="You're 78% ready for the CPMAI exam — keep going!" />
      <div className="grid grid-cols-4 gap-4 mb-6">
        <StatCard icon={Award} label="Avg Quiz Score" value="82%" trend="+5% this week" />
        <StatCard icon={GraduationCap} label="Mock Exams" value="4" trend="2 passed" />
        <StatCard icon={Clock} label="Hours Studied" value="47.5" trend="this month" trendColor="text-slate-500" />
        <StatCard icon={TrendingUp} label="Day Streak" value="12 🔥" trend="personal best" />
      </div>
      <div className="grid grid-cols-3 gap-5">
        <div className="col-span-2 bg-white rounded-xl border border-slate-200 p-6">
          <h2 className="font-semibold text-slate-900 mb-5">Topic Mastery — CPMAI 6 Phases</h2>
          <div className="space-y-4">
            {phases.map((p, i) => (
              <div key={i}>
                <div className="flex justify-between text-sm mb-1.5">
                  <span className="text-slate-700 font-medium">{p.name}</span>
                  <span className="text-slate-500">{p.progress}%</span>
                </div>
                <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                  <div className={"h-full " + p.color + " rounded-full"} style={{ width: p.progress + '%' }} />
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-6">
          <h2 className="font-semibold text-slate-900 mb-4">Up Next</h2>
          <div className="space-y-2">
            {[
              { title: 'Mock Exam #5', sub: '60 questions · 90 min', icon: GraduationCap },
              { title: 'Weak Area Drill', sub: 'Model Evaluation · 15 questions', icon: Activity },
              { title: 'Daily Review', sub: '10 spaced-repetition questions', icon: RefreshCw },
            ].map((item, i) => {
              const Icon = item.icon;
              return (
                <div key={i} className="flex items-center gap-3 p-3 rounded-lg hover:bg-slate-50 cursor-pointer border border-transparent hover:border-slate-200 transition">
                  <div className="w-9 h-9 bg-indigo-50 rounded-lg flex items-center justify-center">
                    <Icon className="w-4 h-4 text-indigo-600" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-slate-900">{item.title}</div>
                    <div className="text-xs text-slate-500">{item.sub}</div>
                  </div>
                  <ChevronRight className="w-4 h-4 text-slate-400" />
                </div>
              );
            })}
          </div>
          <button className="w-full mt-3 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700">
            Start Mock Exam #5
          </button>
        </div>
      </div>
    </div>
  );
}

function AITutor() {
  const messages = [
    { role: 'user', text: "What's the difference between Data Understanding and Data Preparation in CPMAI?" },
    { role: 'assistant', intent: 'CONTENT', confidence: 0.94, provider: 'OpenAI GPT-4o', text: 'Great question! In CPMAI methodology, Data Understanding (Phase 2) is about exploring and assessing the data — checking quality, distributions, and whether it can support the business goal you defined in Phase 1. Data Preparation (Phase 3) is the hands-on work: cleaning, transforming, feature engineering, and shaping the data into a form your model can consume.' },
    { role: 'user', text: 'How did I score on my last mock exam, and where am I weakest?' },
    { role: 'assistant', intent: 'INSIGHTS', confidence: 0.88, provider: 'OpenAI GPT-4o', text: 'You scored 76% on Mock Exam #4 (passing is 70%) — solid work. Your weakest area is Model Evaluation (Phase 5), where you got 4 of 12 questions correct. I would recommend the Phase 5 drill set next.' },
  ];
  const intentColors = { CONTENT: 'green', INSIGHTS: 'purple', FAQ: 'blue', ACCOUNT: 'yellow' };
  return (
    <div className="flex flex-col h-screen">
      <div className="px-8 py-5 border-b border-slate-200 bg-white flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900 flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-indigo-600" />AI Tutor
          </h1>
          <p className="text-sm text-slate-500 mt-0.5">Ask anything about CPMAI</p>
        </div>
        <div className="bg-gradient-to-br from-indigo-50 to-purple-50 border border-indigo-200 rounded-xl px-4 py-2.5 flex items-center gap-4">
          <div className="text-right">
            <div className="text-xs text-indigo-700 font-medium uppercase tracking-wide">Daily quota</div>
            <div className="text-sm font-bold text-indigo-900 mt-0.5">7 of 25 used</div>
          </div>
          <div className="w-32">
            <div className="h-2 bg-white rounded-full overflow-hidden border border-indigo-200">
              <div className="h-full bg-gradient-to-r from-indigo-500 to-purple-500" style={{ width: '28%' }} />
            </div>
            <div className="text-xs text-indigo-700 mt-1 flex items-center gap-1">
              <Clock className="w-3 h-3" />Resets in 14h 32m
            </div>
          </div>
        </div>
      </div>
      <div className="px-8 py-2 bg-amber-50 border-b border-amber-200 text-xs text-amber-800 flex items-center gap-2">
        <AlertCircle className="w-3.5 h-3.5" />
        Responses are AI-generated and may be inaccurate. Verify critical information with the official CPMAI handbook.
      </div>
      <div className="flex-1 overflow-auto p-8 space-y-5 bg-slate-50">
        {messages.map((m, i) => m.role === 'user' ? (
          <div key={i} className="flex justify-end">
            <div className="max-w-2xl bg-indigo-600 text-white px-4 py-2.5 rounded-2xl rounded-br-md shadow-sm">
              <p className="text-sm">{m.text}</p>
            </div>
          </div>
        ) : (
          <div key={i} className="flex gap-3">
            <div className="w-8 h-8 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-full flex items-center justify-center">
              <Bot className="w-4 h-4 text-white" />
            </div>
            <div className="max-w-2xl">
              <div className="flex items-center gap-2 mb-1.5">
                <Badge color={intentColors[m.intent]}>{m.intent}</Badge>
                <span className="text-xs text-slate-500">{Math.round(m.confidence * 100)}% confidence · {m.provider}</span>
              </div>
              <div className="bg-white border border-slate-200 px-4 py-3 rounded-2xl rounded-bl-md shadow-sm">
                <p className="text-sm text-slate-700 leading-relaxed">{m.text}</p>
              </div>
            </div>
          </div>
        ))}
      </div>
      <div className="px-8 py-4 border-t border-slate-200 bg-white">
        <div className="flex items-center gap-2 bg-slate-50 rounded-xl px-4 py-3 border border-slate-200">
          <input placeholder="Ask anything about CPMAI..." className="flex-1 bg-transparent outline-none text-sm" />
          <button className="bg-indigo-600 text-white p-2 rounded-lg hover:bg-indigo-700">
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
        <div className="text-xs text-slate-400 mt-2 text-center">18 messages remaining today · Pro plan</div>
      </div>
    </div>
  );
}

function PracticeQuiz() {
  return (
    <div className="p-8">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <Badge color="indigo">Phase 2 · Data Understanding</Badge>
            <h1 className="text-xl font-bold text-slate-900 mt-2">Practice Quiz: Data Quality</h1>
          </div>
          <div className="flex items-center gap-2 bg-white border border-slate-200 rounded-lg px-3 py-1.5">
            <Clock className="w-4 h-4 text-slate-500" />
            <span className="text-sm font-medium text-slate-900 tabular-nums">12:34</span>
          </div>
        </div>
        <div className="flex items-center justify-between text-sm text-slate-500 mb-2">
          <span>Question 5 of 20</span><span>25% complete</span>
        </div>
        <div className="h-1.5 bg-slate-200 rounded-full mb-6 overflow-hidden">
          <div className="h-full bg-indigo-600 rounded-full" style={{ width: '25%' }} />
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-6 mb-4">
          <h2 className="text-lg font-semibold text-slate-900 leading-relaxed mb-6">
            In CPMAI Phase 2, you discover 18% of records have missing values in a key feature.
            What is the <em>most appropriate</em> immediate action?
          </h2>
          <div className="space-y-2">
            {[
              { id: 'a', text: 'Drop all rows with missing values and proceed to modeling.' },
              { id: 'b', text: 'Document the gap, assess impact on the business goal, and decide on a treatment strategy in Phase 3.', selected: true },
              { id: 'c', text: 'Impute the missing values with the column mean immediately.' },
              { id: 'd', text: 'Re-collect the data from the source system before continuing.' },
            ].map(opt => (
              <label key={opt.id} className={"flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition " + (opt.selected ? 'bg-indigo-50 border-indigo-300' : 'bg-white border-slate-200 hover:border-slate-300')}>
                <div className={"w-6 h-6 rounded-full border-2 flex items-center justify-center mt-0.5 font-bold text-xs " + (opt.selected ? 'bg-indigo-600 border-indigo-600 text-white' : 'border-slate-300 text-slate-400')}>
                  {opt.id.toUpperCase()}
                </div>
                <span className="text-sm text-slate-700 leading-relaxed pt-0.5">{opt.text}</span>
              </label>
            ))}
          </div>
        </div>
        <div className="flex items-center justify-between">
          <label className="flex items-center gap-2 text-sm text-slate-600">
            <input type="checkbox" className="rounded border-slate-300" />Mark for review
          </label>
          <div className="flex gap-2">
            <button className="px-4 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50">Previous</button>
            <button className="px-5 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700">Next →</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function MockExams() {
  const exams = [
    { name: 'Mock Exam #1', score: 64, passed: false, date: 'Mar 12', time: '88 min' },
    { name: 'Mock Exam #2', score: 71, passed: true, date: 'Mar 24', time: '85 min' },
    { name: 'Mock Exam #3', score: 68, passed: false, date: 'Apr 04', time: '90 min' },
    { name: 'Mock Exam #4', score: 76, passed: true, date: 'Apr 18', time: '82 min' },
  ];
  return (
    <div className="p-8">
      <PageHeader title="Mock Exams" subtitle="Full-length 60-question simulations under exam conditions" />
      <div className="bg-gradient-to-br from-indigo-600 to-purple-600 rounded-xl p-6 text-white mb-6 flex items-center justify-between">
        <div>
          <div className="text-sm opacity-80 mb-1">Ready for the next attempt?</div>
          <div className="text-2xl font-bold">Mock Exam #5</div>
          <div className="text-sm opacity-80 mt-1">60 questions · 90 minutes · 70% to pass</div>
        </div>
        <button className="px-6 py-3 bg-white text-indigo-600 font-semibold rounded-lg hover:bg-indigo-50">Start Exam →</button>
      </div>
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-200">
          <h2 className="font-semibold text-slate-900">Past Attempts</h2>
        </div>
        <table className="w-full">
          <thead className="bg-slate-50 border-b border-slate-200">
            <tr className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
              <th className="px-6 py-3">Exam</th><th className="px-6 py-3">Score</th>
              <th className="px-6 py-3">Result</th><th className="px-6 py-3">Time</th>
              <th className="px-6 py-3">Date</th><th className="px-6 py-3"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {exams.map((e, i) => (
              <tr key={i} className="hover:bg-slate-50">
                <td className="px-6 py-4 text-sm font-medium text-slate-900">{e.name}</td>
                <td className="px-6 py-4">
                  <div className="flex items-center gap-2">
                    <div className="w-24 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                      <div className={"h-full " + (e.passed ? 'bg-emerald-500' : 'bg-rose-500')} style={{ width: e.score + '%' }} />
                    </div>
                    <span className="text-sm font-medium text-slate-900">{e.score}%</span>
                  </div>
                </td>
                <td className="px-6 py-4">{e.passed ? <Badge color="green" dot="green">Passed</Badge> : <Badge color="red" dot="red">Failed</Badge>}</td>
                <td className="px-6 py-4 text-sm text-slate-600">{e.time}</td>
                <td className="px-6 py-4 text-sm text-slate-600">{e.date}</td>
                <td className="px-6 py-4 text-right">
                  <button className="text-xs text-indigo-600 font-medium hover:text-indigo-700">Review →</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function UserProgress() {
  const data = [
    { week: 'W1', score: 58 }, { week: 'W2', score: 62 }, { week: 'W3', score: 65 },
    { week: 'W4', score: 64 }, { week: 'W5', score: 71 }, { week: 'W6', score: 73 },
    { week: 'W7', score: 76 }, { week: 'W8', score: 82 },
  ];
  return (
    <div className="p-8">
      <PageHeader title="My Progress" subtitle="Your CPMAI journey over time" />
      <div className="grid grid-cols-4 gap-4 mb-6">
        <StatCard icon={TrendingUp} label="Score Trend" value="+24 pts" trend="last 8 weeks" />
        <StatCard icon={Activity} label="Questions Attempted" value="847" />
        <StatCard icon={Award} label="Best Topic" value="BU" trend="88% mastery" />
        <StatCard icon={AlertCircle} label="Weakest Topic" value="EV" trend="31% mastery" trendColor="text-rose-600" />
      </div>
      <div className="bg-white rounded-xl border border-slate-200 p-6">
        <h2 className="font-semibold text-slate-900 mb-4">Average Quiz Score Over Time</h2>
        <ResponsiveContainer width="100%" height={280}>
          <AreaChart data={data}>
            <defs>
              <linearGradient id="g1" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#4f46e5" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#4f46e5" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="week" stroke="#64748b" fontSize={12} />
            <YAxis stroke="#64748b" fontSize={12} domain={[40, 100]} />
            <Tooltip />
            <Area type="monotone" dataKey="score" stroke="#4f46e5" strokeWidth={2} fill="url(#g1)" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function AdminDashboard() {
  const costData = [
    { day: 'Apr 28', openai: 12.4, anthropic: 8.2, azure: 4.1 },
    { day: 'Apr 29', openai: 14.1, anthropic: 7.8, azure: 5.0 },
    { day: 'Apr 30', openai: 15.6, anthropic: 9.4, azure: 4.8 },
    { day: 'May 01', openai: 18.2, anthropic: 10.1, azure: 6.2 },
    { day: 'May 02', openai: 16.8, anthropic: 11.3, azure: 5.4 },
    { day: 'May 03', openai: 19.5, anthropic: 9.8, azure: 7.1 },
    { day: 'May 04', openai: 21.2, anthropic: 12.4, azure: 6.8 },
  ];
  const tierTokens = [{ tier: 'Free', tokens: 18420 }, { tier: 'Pro', tokens: 142300 }, { tier: 'Enterprise', tokens: 89200 }];
  return (
    <div className="p-8">
      <PageHeader title="Admin Dashboard" subtitle="Platform overview · last 24 hours" />
      <div className="grid grid-cols-4 gap-4 mb-6">
        <StatCard icon={Users} label="Active Users" value="1,247" trend="+12% this week" />
        <StatCard icon={DollarSign} label="MRR" value="₹4,82,500" trend="+8.4%" />
        <StatCard icon={MessageSquare} label="AI Requests Today" value="3,891" trend="↑ 14% vs yesterday" />
        <StatCard icon={Zap} label="Avg Cost / Request" value="$0.0042" trend="↓ 6%" />
      </div>
      <div className="grid grid-cols-3 gap-5 mb-6">
        <div className="col-span-2 bg-white rounded-xl border border-slate-200 p-6">
          <div className="flex justify-between items-center mb-4">
            <div>
              <h2 className="font-semibold text-slate-900">AI Costs by Provider</h2>
              <p className="text-xs text-slate-500 mt-0.5">Last 7 days · in USD</p>
            </div>
            <div className="text-right">
              <div className="text-xs text-slate-500">7-day total</div>
              <div className="text-lg font-bold text-slate-900">$224.20</div>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={250}>
            <AreaChart data={costData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="day" stroke="#64748b" fontSize={12} />
              <YAxis stroke="#64748b" fontSize={12} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Area type="monotone" dataKey="openai" name="OpenAI" stackId="1" stroke="#10b981" fill="#10b981" fillOpacity={0.7} />
              <Area type="monotone" dataKey="anthropic" name="Anthropic" stackId="1" stroke="#f59e0b" fill="#f59e0b" fillOpacity={0.7} />
              <Area type="monotone" dataKey="azure" name="Azure" stackId="1" stroke="#4f46e5" fill="#4f46e5" fillOpacity={0.7} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-slate-900">Provider Health</h2>
            <span className="text-xs text-slate-500 flex items-center gap-1">
              <RefreshCw className="w-3 h-3" />auto-checked every 5m
            </span>
          </div>
          <div className="space-y-2">
            <ProviderHealthRow name="OpenAI GPT-4o" status="healthy" latency="412ms" active />
            <ProviderHealthRow name="Anthropic Claude" status="healthy" latency="380ms" />
            <ProviderHealthRow name="Azure OpenAI" status="degraded" latency="1.2s" />
            <ProviderHealthRow name="Ollama (local)" status="offline" latency="—" />
            <ProviderHealthRow name="Stub (testing)" status="healthy" latency="2ms" />
          </div>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-5">
        <div className="bg-white rounded-xl border border-slate-200 p-6">
          <h2 className="font-semibold text-slate-900 mb-4">Tokens Consumed by Tier (Today)</h2>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={tierTokens}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="tier" stroke="#64748b" fontSize={12} />
              <YAxis stroke="#64748b" fontSize={12} />
              <Tooltip />
              <Bar dataKey="tokens" fill="#4f46e5" radius={[8, 8, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-6">
          <h2 className="font-semibold text-slate-900 mb-4">Recent Audit Events</h2>
          <div className="space-y-3">
            <AuditRow action="llm.provider_activated" actor="arjun.d" time="2 min ago" detail="Switched active to OpenAI GPT-4o" />
            <AuditRow action="setting.updated" actor="arjun.d" time="15 min ago" detail="chat.daily_limit.anonymous: 5 → 10" />
            <AuditRow action="user.role_changed" actor="super.admin" time="1 hr ago" detail="reena.k → admin" />
            <AuditRow action="llm.provider_created" actor="arjun.d" time="3 hr ago" detail="Anthropic Claude Sonnet" />
          </div>
        </div>
      </div>
    </div>
  );
}

function ProviderHealthRow({ name, status, latency, active }) {
  const colors = { healthy: 'green', degraded: 'yellow', offline: 'red' };
  return (
    <div className="flex items-center justify-between p-2 -mx-2 rounded-lg hover:bg-slate-50">
      <div className="flex items-center gap-2.5 min-w-0">
        <Badge color={colors[status]} dot={colors[status]} />
        <span className="text-sm font-medium text-slate-900 truncate">{name}</span>
        {active && <Badge color="indigo">active</Badge>}
      </div>
      <span className="text-xs text-slate-500 tabular-nums">{latency}</span>
    </div>
  );
}

function AuditRow({ action, actor, time, detail }) {
  return (
    <div className="text-sm">
      <div className="flex items-center justify-between">
        <code className="text-xs bg-slate-100 px-1.5 py-0.5 rounded font-mono text-slate-700">{action}</code>
        <span className="text-xs text-slate-400">{time}</span>
      </div>
      {detail && <div className="text-xs text-slate-600 mt-1">{detail}</div>}
      <div className="text-xs text-slate-400 mt-0.5">by {actor}</div>
    </div>
  );
}

function LLMProviders() {
  const providers = [
    { id: 1, name: 'OpenAI GPT-4o (prod)', type: 'openai', model: 'gpt-4o', active: true, enabled: true, health: 'healthy', requests: 1842, cost: 24.10, latency: 412, rateLimit: '60/min' },
    { id: 2, name: 'Anthropic Claude', type: 'anthropic', model: 'claude-sonnet-4', fallback: true, enabled: true, health: 'healthy', requests: 124, cost: 3.20, latency: 380, rateLimit: '40/min' },
    { id: 3, name: 'Azure OpenAI', type: 'azure_openai', model: 'gpt-4', enabled: true, health: 'degraded', requests: 0, cost: 0, latency: 1200, rateLimit: '50/min' },
    { id: 4, name: 'Ollama Llama 3', type: 'ollama', model: 'llama3:70b', enabled: false, health: 'offline', requests: 0, cost: 0, latency: null, rateLimit: 'unlimited' },
    { id: 5, name: 'Stub (testing)', type: 'stub', model: 'stub-v1', enabled: true, health: 'healthy', requests: 0, cost: 0, latency: 2, rateLimit: '—' },
  ];
  const healthMap = { healthy: 'green', degraded: 'yellow', offline: 'red' };
  return (
    <div className="p-8">
      <PageHeader
        title="LLM Providers"
        subtitle="Add, configure, and switch active model — no redeploy required"
        action={<button className="flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700"><Plus className="w-4 h-4" />Add Provider</button>}
      />
      <div className="bg-indigo-50 border border-indigo-200 rounded-xl p-4 mb-6 flex items-start gap-3">
        <Sparkles className="w-5 h-5 text-indigo-600 mt-0.5" />
        <div className="text-sm">
          <div className="font-medium text-indigo-900 mb-0.5">Active provider: OpenAI GPT-4o (prod)</div>
          <div className="text-indigo-700">Falls back to Anthropic Claude on failure. Cache TTL 30s — provider switches propagate within seconds.</div>
        </div>
      </div>
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <table className="w-full">
          <thead className="bg-slate-50 border-b border-slate-200">
            <tr className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
              <th className="px-5 py-3">Provider</th><th className="px-5 py-3">Status</th>
              <th className="px-5 py-3">Health</th><th className="px-5 py-3 text-right">Today</th>
              <th className="px-5 py-3">Rate Limit</th><th className="px-5 py-3 text-right">Latency</th>
              <th className="px-5 py-3"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {providers.map(p => (
              <tr key={p.id} className="hover:bg-slate-50">
                <td className="px-5 py-4">
                  <div className="text-sm font-medium text-slate-900">{p.name}</div>
                  <div className="text-xs text-slate-500 mt-0.5 flex items-center gap-1.5">
                    <code className="bg-slate-100 px-1.5 py-0.5 rounded">{p.type}</code><span>·</span>
                    <span>{p.model}</span><span>·</span>
                    <span className="flex items-center gap-1"><Key className="w-3 h-3" />encrypted</span>
                  </div>
                </td>
                <td className="px-5 py-4">
                  <div className="flex flex-col gap-1">
                    {p.active && <Badge color="indigo">● active</Badge>}
                    {p.fallback && <Badge color="purple">fallback</Badge>}
                    {!p.active && !p.fallback && p.enabled && <Badge color="slate">standby</Badge>}
                    {!p.enabled && <Badge color="slate">disabled</Badge>}
                  </div>
                </td>
                <td className="px-5 py-4">
                  <Badge color={healthMap[p.health]} dot={healthMap[p.health]}>{p.health}</Badge>
                </td>
                <td className="px-5 py-4 text-right">
                  <div className="text-sm font-medium text-slate-900 tabular-nums">${p.cost.toFixed(2)}</div>
                  <div className="text-xs text-slate-500 tabular-nums">{p.requests.toLocaleString()} req</div>
                </td>
                <td className="px-5 py-4 text-sm text-slate-600 tabular-nums">{p.rateLimit}</td>
                <td className="px-5 py-4 text-right text-sm text-slate-600 tabular-nums">{p.latency ? p.latency + 'ms' : '—'}</td>
                <td className="px-5 py-4 text-right">
                  <div className="flex items-center justify-end gap-1">
                    <button title="Test" className="p-1.5 text-slate-400 hover:text-indigo-600 hover:bg-indigo-50 rounded"><Activity className="w-4 h-4" /></button>
                    {!p.active && p.enabled && (
                      <button title="Activate" className="p-1.5 text-slate-400 hover:text-emerald-600 hover:bg-emerald-50 rounded"><Power className="w-4 h-4" /></button>
                    )}
                    <button title="Edit" className="p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded"><Edit className="w-4 h-4" /></button>
                    <button title="Delete" className="p-1.5 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded"><Trash2 className="w-4 h-4" /></button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-4 text-xs text-slate-500 flex items-center gap-4">
        <span className="flex items-center gap-1.5"><Key className="w-3 h-3" /> API keys encrypted at rest (Fernet)</span>
        <span>·</span>
        <span className="flex items-center gap-1.5"><RefreshCw className="w-3 h-3" /> Health checks every 5 minutes</span>
      </div>
    </div>
  );
}

function RuntimeSettings() {
  const groups = [
    { group: 'Chat Limits', icon: MessageSquare, desc: 'Daily quotas for AI chat. Changes take effect within 30 seconds.', items: [
      { key: 'chat.daily_limit.anonymous', value: 5, range: '0-1000', desc: 'Max daily AI messages for non-logged-in visitors' },
      { key: 'chat.daily_limit.authenticated', value: 25, range: '0-10000', desc: 'Max daily AI messages for logged-in users' },
      { key: 'chat.cooldown_seconds', value: 2, range: '0-60', desc: 'Minimum seconds between consecutive messages' },
      { key: 'chat.max_input_chars', value: 4000, range: '100-32000', desc: 'Max user message length' },
      { key: 'chat.max_output_chars', value: 4000, range: '100-32000', desc: 'Max model response length' },
    ]},
    { group: 'AI Token Budget', icon: Zap, desc: 'Hard caps to prevent runaway costs.', items: [
      { key: 'chat.tokens_per_day_authenticated', value: 50000, desc: 'Daily token cap per logged-in user' },
    ]},
    { group: 'Authentication', icon: Lock, desc: 'Brute-force protection.', items: [
      { key: 'auth.lockout_threshold', value: 5, range: '1-50', desc: 'Failed login attempts before lockout' },
      { key: 'auth.lockout_minutes', value: 15, range: '1-1440', desc: 'Lockout duration in minutes' },
    ]},
  ];
  return (
    <div className="p-8">
      <PageHeader title="Runtime Settings" subtitle="Hot-reloadable configuration · no restart required" />
      <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-4 mb-6 flex items-start gap-3">
        <CheckCircle2 className="w-5 h-5 text-emerald-600 mt-0.5" />
        <div className="text-sm">
          <div className="font-medium text-emerald-900">Live configuration</div>
          <div className="text-emerald-700">Saved values apply within ~30 seconds across all nodes via Redis pub/sub. Every change is audit-logged.</div>
        </div>
      </div>
      <div className="space-y-5">
        {groups.map(g => {
          const Icon = g.icon;
          return (
            <div key={g.group} className="bg-white rounded-xl border border-slate-200 overflow-hidden">
              <div className="px-6 py-4 border-b border-slate-200 bg-slate-50/50 flex items-center gap-2.5">
                <div className="w-8 h-8 bg-indigo-100 rounded-lg flex items-center justify-center">
                  <Icon className="w-4 h-4 text-indigo-600" />
                </div>
                <div>
                  <h2 className="font-semibold text-slate-900">{g.group}</h2>
                  <p className="text-xs text-slate-500">{g.desc}</p>
                </div>
              </div>
              <div className="divide-y divide-slate-100">
                {g.items.map(item => (
                  <div key={item.key} className="px-6 py-4 flex items-center gap-4">
                    <div className="flex-1 min-w-0">
                      <code className="text-sm font-mono text-slate-800 font-medium">{item.key}</code>
                      <div className="text-xs text-slate-500 mt-0.5">{item.desc}</div>
                    </div>
                    <div className="flex items-center gap-2">
                      {item.range && <span className="text-xs text-slate-400 tabular-nums">{item.range}</span>}
                      <input type="number" defaultValue={item.value} className="w-28 px-3 py-1.5 text-sm font-mono border border-slate-300 rounded-lg text-right tabular-nums" />
                      <button className="p-1.5 text-slate-400 hover:text-emerald-600 hover:bg-emerald-50 rounded"><Check className="w-4 h-4" /></button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SubscriptionTiers() {
  const tiers = [
    { name: 'Free', price: '₹0', priceUnit: 'forever', features: [
      { label: 'Daily AI messages', value: '5' }, { label: 'Practice quizzes / day', value: '3' },
      { label: 'Mock exams / month', value: '1' }, { label: 'Token budget', value: 'N/A' },
      { label: 'Analytics', value: 'Basic' },
    ]},
    { name: 'Pro', price: '₹999', priceUnit: '/ month', popular: true, features: [
      { label: 'Daily AI messages', value: '25' }, { label: 'Practice quizzes / day', value: 'Unlimited' },
      { label: 'Mock exams / month', value: '8' }, { label: 'Token budget', value: '50,000 / day' },
      { label: 'Analytics', value: 'Full + insights' },
    ]},
    { name: 'Enterprise', price: 'Custom', priceUnit: 'contact sales', features: [
      { label: 'Daily AI messages', value: '500' }, { label: 'Practice quizzes / day', value: 'Unlimited' },
      { label: 'Mock exams / month', value: 'Unlimited' }, { label: 'Token budget', value: '1,000,000 / day' },
      { label: 'Analytics', value: 'Full + team dashboard' },
    ]},
  ];
  return (
    <div className="p-8">
      <PageHeader title="Subscription Tiers" subtitle="Configure per-tier limits — drives the chat.daily_limit.tier.* runtime settings" />
      <div className="grid grid-cols-3 gap-5 mb-6">
        {tiers.map(t => (
          <div key={t.name} className={"bg-white rounded-xl border p-6 relative " + (t.popular ? 'border-indigo-300 ring-2 ring-indigo-100' : 'border-slate-200')}>
            {t.popular && <div className="absolute -top-3 left-1/2 -translate-x-1/2"><Badge color="indigo">Most popular</Badge></div>}
            <div className="mb-5">
              <div className="text-sm font-semibold text-slate-500 uppercase tracking-wide">{t.name}</div>
              <div className="mt-2 flex items-baseline gap-1.5">
                <span className="text-3xl font-bold text-slate-900">{t.price}</span>
                <span className="text-sm text-slate-500">{t.priceUnit}</span>
              </div>
            </div>
            <div className="space-y-3 mb-5">
              {t.features.map((f, i) => (
                <div key={i} className="flex items-center justify-between text-sm">
                  <span className="text-slate-600">{f.label}</span>
                  <span className="font-medium text-slate-900">{f.value}</span>
                </div>
              ))}
            </div>
            <button className={"w-full py-2.5 text-sm font-medium rounded-lg flex items-center justify-center gap-1.5 " + (t.popular ? 'bg-indigo-600 text-white hover:bg-indigo-700' : 'bg-slate-100 text-slate-700 hover:bg-slate-200')}>
              <Edit className="w-3.5 h-3.5" />Edit limits
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function Security() {
  return (
    <div className="p-8">
      <PageHeader title="Security" subtitle="Two-factor authentication and encryption key management" />
      <div className="grid grid-cols-2 gap-5">
        <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-200 flex items-center gap-3">
            <div className="w-9 h-9 bg-emerald-100 rounded-lg flex items-center justify-center">
              <Smartphone className="w-4 h-4 text-emerald-600" />
            </div>
            <div className="flex-1">
              <h2 className="font-semibold text-slate-900">Two-Factor Authentication</h2>
              <p className="text-xs text-slate-500">Required for all admin accounts</p>
            </div>
            <Badge color="green" dot="green">enabled</Badge>
          </div>
          <div className="p-6">
            <div className="bg-slate-50 rounded-xl p-5 mb-4 flex items-center gap-5">
              <div className="w-32 h-32 bg-white border-2 border-slate-200 rounded-lg flex items-center justify-center">
                <QrCode className="w-20 h-20 text-slate-800" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-xs text-slate-500 mb-1 font-medium uppercase tracking-wide">TOTP secret</div>
                <code className="text-xs font-mono text-slate-800 break-all bg-white px-2 py-1 rounded border border-slate-200 block">JBSWY3DPEHPK3PXP</code>
                <div className="text-xs text-slate-500 mt-3">Scan with Google Authenticator, Authy, or 1Password.</div>
              </div>
            </div>
            <div className="border border-amber-200 bg-amber-50 rounded-lg p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-semibold text-amber-900">Recovery codes</span>
                <button className="text-xs text-amber-700 font-medium flex items-center gap-1"><Copy className="w-3 h-3" />Copy all</button>
              </div>
              <div className="grid grid-cols-2 gap-1.5 text-xs font-mono text-amber-900">
                {['8FK2-9LMQ', '7XPR-3VBN', '5DTC-1WHJ', '4MGR-8YEK', '6QAU-2RFS', '9HWB-7CTX'].map(c => (
                  <code key={c} className="bg-white border border-amber-200 px-2 py-1 rounded">{c}</code>
                ))}
              </div>
              <p className="text-xs text-amber-700 mt-3">Store these somewhere safe — each works once.</p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-200 flex items-center gap-3">
            <div className="w-9 h-9 bg-indigo-100 rounded-lg flex items-center justify-center">
              <Key className="w-4 h-4 text-indigo-600" />
            </div>
            <div className="flex-1">
              <h2 className="font-semibold text-slate-900">Encryption Key Rotation</h2>
              <p className="text-xs text-slate-500">Re-encrypts all stored API keys under a new master key</p>
            </div>
          </div>
          <div className="p-6 space-y-4">
            <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg">
              <div>
                <div className="text-xs text-slate-500 uppercase tracking-wide font-medium">Current key</div>
                <code className="text-sm font-mono text-slate-800 mt-1 block">k1 · sha256:7f2a…b9d4</code>
              </div>
              <Badge color="green" dot="green">active</Badge>
            </div>
            <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg">
              <div>
                <div className="text-xs text-slate-500 uppercase tracking-wide font-medium">Previous key</div>
                <code className="text-sm font-mono text-slate-800 mt-1 block">k0 · sha256:3b8e…c14a</code>
              </div>
              <Badge color="slate">retired Mar 14</Badge>
            </div>
            <button className="w-full py-2.5 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 flex items-center justify-center gap-2">
              <RefreshCw className="w-4 h-4" />Rotate to new key
            </button>
            <p className="text-xs text-slate-500 text-center">Rotation runs in the background with a 24h overlap window.</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function UsersList() {
  const users = [
    { name: 'Priya Sharma', email: 'priya.s@example.com', tier: 'Pro', role: 'user', status: 'active', joined: 'Mar 12' },
    { name: 'Rahul Verma', email: 'rahul.v@example.com', tier: 'Enterprise', role: 'user', status: 'active', joined: 'Feb 28' },
    { name: 'Reena Krishnan', email: 'reena.k@example.com', tier: 'Pro', role: 'admin', status: 'active', joined: 'Jan 14' },
    { name: 'Sameer Joshi', email: 'sameer.j@example.com', tier: 'Free', role: 'user', status: 'locked', joined: 'Apr 22' },
    { name: 'Arjun Dixit', email: 'arjun.d@example.com', tier: 'Enterprise', role: 'super_admin', status: 'active', joined: 'Jan 02' },
  ];
  const roleColors = { user: 'slate', admin: 'indigo', super_admin: 'purple' };
  return (
    <div className="p-8">
      <PageHeader title="Users" subtitle="1,247 total · 89 added this week" action={
        <div className="flex items-center gap-2 px-3 py-1.5 bg-white border border-slate-200 rounded-lg">
          <Search className="w-4 h-4 text-slate-400" />
          <input placeholder="Search by email…" className="text-sm outline-none bg-transparent w-48" />
        </div>
      } />
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <table className="w-full">
          <thead className="bg-slate-50 border-b border-slate-200">
            <tr className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
              <th className="px-5 py-3">User</th><th className="px-5 py-3">Role</th>
              <th className="px-5 py-3">Tier</th><th className="px-5 py-3">Status</th>
              <th className="px-5 py-3">Joined</th><th className="px-5 py-3"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {users.map(u => (
              <tr key={u.email} className="hover:bg-slate-50">
                <td className="px-5 py-3">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-full flex items-center justify-center text-white text-xs font-medium">
                      {u.name.split(' ').map(n => n[0]).join('')}
                    </div>
                    <div>
                      <div className="text-sm font-medium text-slate-900">{u.name}</div>
                      <div className="text-xs text-slate-500">{u.email}</div>
                    </div>
                  </div>
                </td>
                <td className="px-5 py-3"><Badge color={roleColors[u.role]}>{u.role}</Badge></td>
                <td className="px-5 py-3 text-sm text-slate-600">{u.tier}</td>
                <td className="px-5 py-3">{u.status === 'active' ? <Badge color="green" dot="green">active</Badge> : <Badge color="red" dot="red">locked</Badge>}</td>
                <td className="px-5 py-3 text-sm text-slate-600">{u.joined}</td>
                <td className="px-5 py-3 text-right"><button className="text-xs text-indigo-600 font-medium">View →</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AuditLog() {
  const events = [
    { action: 'llm.provider_activated', actor: 'arjun.d', time: '2 min ago', detail: 'Switched active to OpenAI GPT-4o', color: 'indigo' },
    { action: 'setting.updated', actor: 'arjun.d', time: '15 min ago', detail: 'chat.daily_limit.anonymous: 5 → 10', color: 'blue' },
    { action: 'login.success', actor: 'priya.s@example.com', time: '32 min ago', detail: 'IP 49.207.x.x', color: 'green' },
    { action: 'user.role_changed', actor: 'super.admin', time: '1 hr ago', detail: 'reena.k → admin', color: 'purple' },
    { action: 'login.failed', actor: 'sameer.j@example.com', time: '1 hr ago', detail: 'attempt 5/5 → account locked', color: 'red' },
    { action: 'llm.provider_created', actor: 'arjun.d', time: '3 hr ago', detail: 'Anthropic Claude Sonnet (id: 2)', color: 'indigo' },
    { action: 'payment.success', actor: 'rahul.v@example.com', time: '4 hr ago', detail: 'Pro plan · ₹999 · Razorpay', color: 'green' },
    { action: 'subscription.cancelled', actor: 'mira.t@example.com', time: '6 hr ago', detail: 'Pro plan · self-service', color: 'yellow' },
  ];
  return (
    <div className="p-8">
      <PageHeader title="Audit Log" subtitle="Every sensitive action across the platform" />
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <div className="divide-y divide-slate-100">
          {events.map((e, i) => (
            <div key={i} className="px-6 py-4 hover:bg-slate-50 flex items-center gap-4">
              <Badge color={e.color}>{e.action}</Badge>
              <div className="flex-1 min-w-0">
                <div className="text-sm text-slate-700">{e.detail}</div>
                <div className="text-xs text-slate-500 mt-0.5">by <span className="font-medium">{e.actor}</span></div>
              </div>
              <span className="text-xs text-slate-400">{e.time}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
