'use client';

import { useState, useEffect, useRef } from 'react';
import { 
  Play, Square, Shield, Clock, CheckCircle2, ExternalLink, 
  AlertTriangle, RefreshCw, Terminal, User, Briefcase, 
  MapPin, DollarSign, Database, Globe, Sparkles, ChevronRight,
  Filter, Search, ArrowUpRight
} from 'lucide-react';

export default function Dashboard() {
  const [stats, setStats] = useState({
    total_applied: 0,
    today_applied: 0,
    daily_safe_limit: 45,
    remaining_today: 45,
    external_redirects: 0,
    failed_attempts: 0,
    needs_user_input: 0
  });

  const [botState, setBotState] = useState({
    is_running: false,
    status: 'IDLE',
    countdown_remaining: 0,
    today_applied: 0,
    daily_limit: 45,
    current_job: {},
    recent_logs: []
  });

  const [chromeStatus, setChromeStatus] = useState({ connected: false });
  const [applications, setApplications] = useState([]);
  const [activeTab, setActiveTab] = useState('ALL');
  const [searchTerm, setSearchTerm] = useState('');
  
  // Controls Form
  const [keyword, setKeyword] = useState('All Target Roles (Auto-Cycle)');
  const [location, setLocation] = useState('Dubai, Qatar, Mumbai, Pune, Remote');
  const [naukriLocations, setNaukriLocations] = useState('Mumbai, Pune, Remote');
  const [linkedinLocations, setLinkedinLocations] = useState('Dubai, Qatar, Mumbai, Pune, Remote');
  const [naukrigulfLocations, setNaukrigulfLocations] = useState('Qatar, Dubai, UAE, Saudi Arabia, Remote');
  const [experience, setExperience] = useState(5);
  const [platform, setPlatform] = useState('ALL'); // 'ALL' | 'NAUKRI' | 'LINKEDIN' | 'NAUKRIGULF'
  const [platformFilter, setPlatformFilter] = useState('ALL'); // 'ALL' | 'NAUKRI' | 'LINKEDIN' | 'NAUKRIGULF'
  const [loadingAction, setLoadingAction] = useState(false);
  const [profileModal, setProfileModal] = useState(false);
  const [profileData, setProfileData] = useState(null);
  
  // Autonomous Configuration Modal
  const [configModal, setConfigModal] = useState(false);
  const [agentConfig, setAgentConfig] = useState(null);
  const [savingConfig, setSavingConfig] = useState(false);

  // Poll status & stats every 2 seconds
  useEffect(() => {
    fetchStats();
    fetchStatus();
    fetchApplications();
    fetchChromeStatus();
    fetchProfile();
    fetchConfig();

    const interval = setInterval(() => {
      fetchStatus();
      fetchStats();
    }, 2000);

    const appInterval = setInterval(() => {
      fetchApplications();
    }, 10000);

    return () => {
      clearInterval(interval);
      clearInterval(appInterval);
    };
  }, []);

  const fetchConfig = async () => {
    try {
      const res = await fetch('/api/config');
      if (res.ok) {
        const data = await res.json();
        setAgentConfig(data);
      }
    } catch (e) {
      console.error("Error fetching config:", e);
    }
  };

  const handleSaveConfig = async (newConfig) => {
    setSavingConfig(true);
    try {
      const res = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newConfig)
      });
      if (res.ok) {
        const data = await res.json();
        setAgentConfig(data.config);
        alert("Autonomous settings saved and persisted!");
      }
    } catch (e) {
      alert("Error saving configuration");
    } finally {
      setSavingConfig(false);
    }
  };

  const fetchStatus = async () => {
    try {
      const res = await fetch('/api/status');
      if (res.ok) {
        const data = await res.json();
        setBotState(data);
      }
    } catch (e) {
      console.error("Error fetching status:", e);
    }
  };

  const fetchStats = async () => {
    try {
      const res = await fetch('/api/stats');
      if (res.ok) {
        const data = await res.json();
        setStats(data);
      }
    } catch (e) {
      console.error("Error fetching stats:", e);
    }
  };

  const fetchApplications = async () => {
    try {
      const res = await fetch('/api/applications?limit=100');
      if (res.ok) {
        const data = await res.json();
        setApplications(data);
      }
    } catch (e) {
      console.error("Error fetching apps:", e);
    }
  };

  const fetchChromeStatus = async () => {
    try {
      const res = await fetch('/api/check-chrome');
      if (res.ok) {
        const data = await res.json();
        setChromeStatus(data);
      }
    } catch (e) {
      console.error("Error checking chrome:", e);
    }
  };

  const fetchProfile = async () => {
    try {
      const res = await fetch('/api/profile');
      if (res.ok) {
        const data = await res.json();
        setProfileData(data);
      }
    } catch (e) {
      console.error("Error fetching profile:", e);
    }
  };

  const handleStart = async () => {
    setLoadingAction(true);
    try {
      const activeLoc = platform === 'NAUKRI' ? naukriLocations : platform === 'LINKEDIN' ? linkedinLocations : platform === 'NAUKRIGULF' ? naukrigulfLocations : `${naukriLocations}, ${linkedinLocations}, ${naukrigulfLocations}`;
      const res = await fetch('/api/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          keyword, 
          location: activeLoc,
          naukri_locations: naukriLocations,
          linkedin_locations: linkedinLocations,
          naukrigulf_locations: naukrigulfLocations,
          experience: parseInt(experience), 
          platform 
        })
      });
      const data = await res.json();
      if (!res.ok) {
        alert(data.detail || "Failed to start agent");
      }
      fetchStatus();
    } catch (e) {
      alert("Error starting agent. Ensure backend is running!");
    } finally {
      setLoadingAction(false);
    }
  };

  const handleStop = async () => {
    setLoadingAction(true);
    try {
      await fetch('/api/stop', { method: 'POST' });
      fetchStatus();
    } catch (e) {
      console.error("Error stopping agent:", e);
    } finally {
      setLoadingAction(false);
    }
  };

  // Filtered applications
  const filteredApps = applications.filter(app => {
    const matchesSearch = 
      app.job_title?.toLowerCase().includes(searchTerm.toLowerCase()) ||
      app.company_name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (app.location && app.location.toLowerCase().includes(searchTerm.toLowerCase()));

    if (!matchesSearch) return false;

    // Platform filter
    const appPlatform = (app.platform || 'NAUKRI').toUpperCase();
    if (platformFilter !== 'ALL' && appPlatform !== platformFilter) return false;

    if (activeTab === 'ALL') return true;
    if (activeTab === 'APPLIED') return app.status === 'APPLIED' || app.status === 'APPLICATION_CONFIRMED';
    if (activeTab === 'REDIRECT_REVIEW') return app.status === 'REDIRECT_REVIEW' || app.status === 'APPLICATION_PENDING_CONFIRMATION';
    if (activeTab === 'NEEDS_USER_INPUT') return app.status === 'NEEDS_USER_INPUT';
    if (activeTab === 'SKIPPED') return app.status === 'SKIPPED' || app.status === 'APPLICATION_SKIPPED';
    if (activeTab === 'FAILED') return app.status === 'FAILED' || app.status === 'APPLICATION_FAILED';
    return true;
  });

  const formatCountdown = (secs) => {
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  return (
    <div className="min-h-screen bg-[#070b12] text-slate-100 p-4 md:p-8">
      {/* Top Header */}
      <header className="max-w-7xl mx-auto flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-slate-800">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-tr from-teal-500 to-emerald-400 flex items-center justify-center text-slate-950 font-bold shadow-lg shadow-teal-500/20">
            <Sparkles className="w-6 h-6" />
          </div>
          <div>
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-2xl font-bold tracking-tight text-white">Multi-Platform Job Copilot</h1>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1">
                <Sparkles className="w-3 h-3 text-emerald-400" /> Autonomous
              </span>
              <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-blue-500/10 text-blue-400 border border-blue-500/20 flex items-center gap-1">
                🔷 Naukri.com + 🟦 LinkedIn
              </span>
              <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20">
                📍 Mumbai &amp; Qatar
              </span>
            </div>
            <p className="text-sm text-slate-400">
              Candidate: <span className="text-slate-200 font-medium">{profileData?.name || 'Abdul Razzaque Shaikh'}</span> • {profileData?.designation || 'Senior Full Stack Developer (5+ Years)'}
            </p>
          </div>
        </div>

        {/* Integration Badges */}
        <div className="flex items-center flex-wrap gap-2.5 text-xs font-mono">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-900 border border-slate-800">
            <Database className="w-3.5 h-3.5 text-teal-400" />
            <span className="text-slate-300">MySQL:</span>
            <span className="text-emerald-400 font-semibold">Active</span>
          </div>

          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-xl border ${
            chromeStatus.connected 
              ? 'bg-emerald-950/40 border-emerald-500/30 text-emerald-300' 
              : 'bg-amber-950/40 border-amber-500/30 text-amber-300'
          }`}>
            <Globe className="w-3.5 h-3.5" />
            <span>Chrome (9222):</span>
            <span className="font-semibold">{chromeStatus.connected ? 'Connected' : 'Waiting for Launch'}</span>
          </div>

          <button 
            onClick={() => { fetchConfig(); setConfigModal(true); }}
            className="px-3 py-1.5 rounded-xl bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 transition flex items-center gap-1.5 font-sans font-medium"
          >
            <Shield className="w-3.5 h-3.5" />
            Autonomous Config
          </button>

          <button 
            onClick={() => setProfileModal(true)}
            className="px-3 py-1.5 rounded-xl bg-teal-500/10 hover:bg-teal-500/20 text-teal-300 border border-teal-500/30 transition flex items-center gap-1.5 font-sans font-medium"
          >
            <User className="w-3.5 h-3.5" />
            Profile & CTC
          </button>
        </div>
      </header>

      {/* Main Container */}
      <main className="max-w-7xl mx-auto mt-6 space-y-6">
        
        {/* Anti-Ban & Cooldown Banner */}
        {botState.status === 'COOLDOWN' && (
          <div className="p-4 rounded-2xl bg-teal-950/40 border border-teal-500/40 flex items-center justify-between glow-active">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-teal-500/20 flex items-center justify-center text-teal-400">
                <Clock className="w-5 h-5 animate-spin" />
              </div>
              <div>
                <h4 className="font-semibold text-teal-300 text-sm">Safe Human Break in Progress (2-3 Minutes Rule)</h4>
                <p className="text-xs text-teal-400/80">Simulating realistic reading time to ensure your Naukri account is completely safe from detection.</p>
              </div>
            </div>
            <div className="text-right">
              <span className="text-xs uppercase tracking-wider text-teal-400 font-semibold block">Next Apply In</span>
              <span className="text-2xl font-mono font-bold text-white tracking-widest">{formatCountdown(botState.countdown_remaining)}</span>
            </div>
          </div>
        )}

        {/* Top 4 Metrics Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Card 1: Daily Safe Quotas */}
          <div className="glass-card p-5 rounded-2xl relative overflow-hidden">
            <div className="flex items-center justify-between text-slate-400">
              <span className="text-xs font-semibold uppercase tracking-wider">Today's Platform Quotas</span>
              <Shield className="w-4 h-4 text-teal-400" />
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-2xl font-extrabold text-white">{stats.today_applied || 0}</span>
              <span className="text-xs text-slate-400 font-medium">/ 135 Safe Total</span>
            </div>
            {/* Separate Platform Progress Badges (45 Quota Each) */}
            <div className="mt-3 space-y-2 text-[11px]">
              <div>
                <div className="flex justify-between items-center text-slate-300 mb-0.5">
                  <span className="flex items-center gap-1 text-cyan-400 font-medium"><span>🔷</span> Naukri</span>
                  <span className="font-mono font-semibold">{stats.today_naukri || 0} / 45</span>
                </div>
                <div className="w-full bg-slate-800 rounded-full h-1 overflow-hidden">
                  <div className="bg-cyan-400 h-full rounded-full transition-all duration-500" style={{ width: `${Math.min(100, ((stats.today_naukri || 0) / 45) * 100)}%` }} />
                </div>
              </div>

              <div>
                <div className="flex justify-between items-center text-slate-300 mb-0.5">
                  <span className="flex items-center gap-1 text-blue-400 font-medium"><span>🟦</span> LinkedIn</span>
                  <span className="font-mono font-semibold">{stats.today_linkedin || 0} / 45</span>
                </div>
                <div className="w-full bg-slate-800 rounded-full h-1 overflow-hidden">
                  <div className="bg-blue-400 h-full rounded-full transition-all duration-500" style={{ width: `${Math.min(100, ((stats.today_linkedin || 0) / 45) * 100)}%` }} />
                </div>
              </div>

              <div>
                <div className="flex justify-between items-center text-slate-300 mb-0.5">
                  <span className="flex items-center gap-1 text-emerald-400 font-medium"><span>🌐</span> NaukriGulf</span>
                  <span className="font-mono font-semibold">{stats.today_naukrigulf || 0} / 45</span>
                </div>
                <div className="w-full bg-slate-800 rounded-full h-1 overflow-hidden">
                  <div className="bg-emerald-400 h-full rounded-full transition-all duration-500" style={{ width: `${Math.min(100, ((stats.today_naukrigulf || 0) / 45) * 100)}%` }} />
                </div>
              </div>
            </div>
          </div>

          {/* Card 2: Total Applied */}
          <div className="glass-card p-5 rounded-2xl">
            <div className="flex items-center justify-between text-slate-400">
              <span className="text-xs font-semibold uppercase tracking-wider">Confirmed Submissions</span>
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-3xl font-extrabold text-emerald-400">{stats.total_applied}</span>
              <span className="text-xs text-slate-400">Total Confirmed</span>
            </div>
            <div className="mt-3 flex flex-col gap-1 text-[11px]">
              <span className="text-cyan-400 font-medium">🔷 Naukri: {stats.naukri_applied ?? stats.total_applied}</span>
              <span className="text-blue-400 font-medium">🟦 LinkedIn: {stats.linkedin_applied ?? 0}</span>
              <span className="text-emerald-400 font-medium">🌐 NaukriGulf: {stats.naukrigulf_applied ?? 0}</span>
            </div>
          </div>

          {/* Card 3: External Company Sites */}
          <div className="glass-card p-5 rounded-2xl">
            <div className="flex items-center justify-between text-slate-400">
              <span className="text-xs font-semibold uppercase tracking-wider">External Company Portals</span>
              <ExternalLink className="w-4 h-4 text-amber-400" />
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-3xl font-extrabold text-amber-400">{stats.external_redirects}</span>
              <span className="text-xs text-slate-400">Saved for Review</span>
            </div>
            <p className="mt-3 text-xs text-slate-400">Direct careers pages saved to prevent bot getting stuck</p>
          </div>

          {/* Card 4: Agent Status */}
          <div className="glass-card p-5 rounded-2xl">
            <div className="flex items-center justify-between text-slate-400">
              <span className="text-xs font-semibold uppercase tracking-wider">Agent Engine Status</span>
              <div className={`w-2.5 h-2.5 rounded-full ${botState.is_running ? 'bg-emerald-400 animate-ping' : 'bg-slate-600'}`} />
            </div>
            <div className="mt-2">
              <span className={`text-xl font-bold uppercase tracking-wide ${
                botState.status === 'APPLYING' ? 'text-teal-400' :
                botState.status === 'COOLDOWN' ? 'text-amber-400' :
                botState.status === 'SEARCHING' ? 'text-indigo-400' :
                botState.status === 'LIMIT_REACHED' ? 'text-rose-400' : 'text-slate-300'
              }`}>
                {botState.status}
              </span>
            </div>
            <p className="mt-3 text-xs text-slate-400 truncate">
              {botState.current_job?.company 
                ? `Active: ${botState.current_job.company}` 
                : 'Ready to run safe workflow'}
            </p>
          </div>
        </div>

        {/* Control Box & Live Console Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          
          {/* Controls Form */}
          <div className="glass-card p-6 rounded-2xl space-y-5">
            <div className="flex items-center justify-between">
              <h3 className="font-bold text-white flex items-center gap-2">
                <Briefcase className="w-4 h-4 text-teal-400" />
                Target Job Preferences
              </h3>
              <span className="text-xs text-slate-500 font-mono">Profile Config</span>
            </div>

            <div className="space-y-4">
              {/* Target Platforms Option */}
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="text-xs font-semibold text-slate-200 flex items-center gap-1.5">
                    <Globe className="w-3.5 h-3.5 text-teal-400" />
                    Target Job Boards
                  </label>
                  <span className="text-[10px] text-teal-400 font-medium">Multi-Platform</span>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  <button
                    type="button"
                    onClick={() => setPlatform('ALL')}
                    className={`py-2 px-2 rounded-xl border text-xs font-bold flex flex-col items-center justify-center gap-1 transition ${
                      platform === 'ALL'
                        ? 'bg-gradient-to-r from-teal-500/20 to-blue-500/20 border-teal-400 text-teal-200 shadow-md shadow-teal-500/10'
                        : 'bg-slate-900/80 border-slate-800 text-slate-400 hover:border-slate-700 hover:text-slate-200'
                    }`}
                  >
                    <span className="flex items-center gap-1 text-[11px]">
                      <span>🌐</span> All 3 Boards
                    </span>
                    <span className="text-[10px] font-normal text-slate-400">Naukri + LI + Gulf</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setPlatform('NAUKRI')}
                    className={`py-2 px-2 rounded-xl border text-xs font-bold flex flex-col items-center justify-center gap-1 transition ${
                      platform === 'NAUKRI'
                        ? 'bg-cyan-500/20 border-cyan-400 text-cyan-200 shadow-md shadow-cyan-500/10'
                        : 'bg-slate-900/80 border-slate-800 text-slate-400 hover:border-slate-700 hover:text-slate-200'
                    }`}
                  >
                    <span className="flex items-center gap-1 text-[11px]">
                      <span>🔷</span> Naukri.com
                    </span>
                    <span className="text-[10px] font-normal text-slate-400">India (45 Quota)</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setPlatform('LINKEDIN')}
                    className={`py-2 px-2 rounded-xl border text-xs font-bold flex flex-col items-center justify-center gap-1 transition ${
                      platform === 'LINKEDIN'
                        ? 'bg-blue-500/20 border-blue-400 text-blue-200 shadow-md shadow-blue-500/10'
                        : 'bg-slate-900/80 border-slate-800 text-slate-400 hover:border-slate-700 hover:text-slate-200'
                    }`}
                  >
                    <span className="flex items-center gap-1 text-[11px]">
                      <span>🟦</span> LinkedIn
                    </span>
                    <span className="text-[10px] font-normal text-slate-400">Global (45 Quota)</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setPlatform('NAUKRIGULF')}
                    className={`py-2 px-2 rounded-xl border text-xs font-bold flex flex-col items-center justify-center gap-1 transition ${
                      platform === 'NAUKRIGULF'
                        ? 'bg-emerald-500/20 border-emerald-400 text-emerald-200 shadow-md shadow-emerald-500/10'
                        : 'bg-slate-900/80 border-slate-800 text-slate-400 hover:border-slate-700 hover:text-slate-200'
                    }`}
                  >
                    <span className="flex items-center gap-1 text-[11px]">
                      <span>🌐</span> NaukriGulf
                    </span>
                    <span className="text-[10px] font-normal text-slate-400">Gulf (45 Quota)</span>
                  </button>
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="text-xs font-medium text-slate-300">Target Role / Positions</label>
                  <span className="text-[10px] text-teal-400 font-medium">Click to select role</span>
                </div>
                
                {/* Role Quick Selector Pills */}
                <div className="flex flex-wrap gap-1.5 mb-2.5">
                  {[
                    { id: 'all', label: '⚡ All Roles (Auto-Cycle)', value: 'All Target Roles (Auto-Cycle)' },
                    { id: 'mern', label: 'MERN Stack', value: 'MERN Stack Developer' },
                    { id: 'node', label: 'Node.js', value: 'Node.js Developer' },
                    { id: 'react', label: 'React.js', value: 'React Developer' },
                    { id: 'next', label: 'Next.js', value: 'Next.js Developer' },
                    { id: 'fullstack', label: 'Full Stack', value: 'Full Stack Developer' },
                  ].map((role) => {
                    const isActive = keyword === role.value || (role.id === 'all' && (keyword.includes('All') || keyword.includes('Auto-Cycle')));
                    return (
                      <button
                        key={role.id}
                        type="button"
                        onClick={() => setKeyword(role.value)}
                        className={`text-xs px-2.5 py-1 rounded-lg border font-medium transition-all ${
                          isActive
                            ? 'bg-teal-500/20 text-teal-300 border-teal-500/50 shadow-sm shadow-teal-500/10'
                            : 'bg-slate-900/80 text-slate-400 border-slate-800 hover:border-slate-700 hover:text-slate-200'
                        }`}
                      >
                        {role.label}
                      </button>
                    );
                  })}
                </div>

                <input 
                  type="text" 
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-900 border border-slate-800 text-sm focus:border-teal-500 focus:outline-none transition"
                  placeholder="e.g. All Target Roles (Auto-Cycle) or custom keyword"
                />

                {(keyword.includes('All') || keyword.includes('Auto-Cycle')) && (
                  <div className="mt-2 flex items-center gap-2 p-2.5 rounded-lg bg-teal-500/10 border border-teal-500/20 text-[11px] text-teal-300 leading-snug">
                    <Sparkles className="w-3.5 h-3.5 text-teal-400 shrink-0" />
                    <span>Auto-cycle active: Bot will cycle through <strong>MERN</strong>, <strong>Node.js</strong>, <strong>React.js</strong>, <strong>Next.js</strong>, &amp; <strong>Full Stack</strong> positions sequentially.</span>
                  </div>
                )}
              </div>

              {/* Location Controls Configured Per Platform */}
              <div className="space-y-3">
                {(platform === 'ALL' || platform === 'NAUKRI') && (
                  <div className="p-3 rounded-xl bg-cyan-950/20 border border-cyan-500/20 space-y-1.5">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-cyan-300 flex items-center gap-1.5">
                        <span>🔷</span> Naukri.com Locations
                      </span>
                      <span className="text-[10px] text-cyan-400 font-mono">India Only</span>
                    </div>
                    <div className="flex gap-1.5">
                      <input 
                        type="text" 
                        value={naukriLocations}
                        onChange={(e) => setNaukriLocations(e.target.value)}
                        className="flex-1 px-3 py-1.5 rounded-lg bg-slate-900/90 border border-slate-800 text-xs text-slate-200 focus:border-cyan-400 focus:outline-none transition"
                        placeholder="Mumbai, Pune, Remote"
                      />
                      <button
                        type="button"
                        onClick={() => setNaukriLocations('Mumbai, Pune, Remote')}
                        className="text-[10px] px-2 py-1 rounded bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 hover:bg-cyan-500/20"
                      >
                        Reset
                      </button>
                    </div>
                    <p className="text-[10px] text-slate-400">Targeting: <strong>Mumbai</strong>, <strong>Pune</strong>, &amp; <strong>Remote</strong> (Gulf blocked on Naukri)</p>
                  </div>
                )}

                {(platform === 'ALL' || platform === 'LINKEDIN') && (
                  <div className="p-3 rounded-xl bg-blue-950/20 border border-blue-500/20 space-y-1.5">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-blue-300 flex items-center gap-1.5">
                        <span>🟦</span> LinkedIn Locations
                      </span>
                      <span className="text-[10px] text-blue-400 font-mono">India + Qatar + Dubai</span>
                    </div>
                    <div className="flex gap-1.5">
                      <input 
                        type="text" 
                        value={linkedinLocations}
                        onChange={(e) => setLinkedinLocations(e.target.value)}
                        className="flex-1 px-3 py-1.5 rounded-lg bg-slate-900/90 border border-slate-800 text-xs text-slate-200 focus:border-blue-400 focus:outline-none transition"
                        placeholder="Dubai, Qatar, Mumbai, Pune, Remote"
                      />
                      <button
                        type="button"
                        onClick={() => setLinkedinLocations('Dubai, Qatar, Mumbai, Pune, Remote')}
                        className="text-[10px] px-2 py-1 rounded bg-blue-500/10 border border-blue-500/30 text-blue-300 hover:bg-blue-500/20"
                      >
                        Reset
                      </button>
                    </div>
                    <p className="text-[10px] text-slate-400">Targeting: <strong>Pune</strong>, <strong>Mumbai</strong>, <strong>Qatar</strong>, &amp; <strong>Remote</strong> (Auto-attaches Qatar CV for Qatar)</p>
                  </div>
                )}

                {(platform === 'ALL' || platform === 'NAUKRIGULF') && (
                  <div className="p-3 rounded-xl bg-emerald-950/20 border border-emerald-500/20 space-y-1.5">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-emerald-300 flex items-center gap-1.5">
                        <span>🌐</span> NaukriGulf Locations
                      </span>
                      <span className="text-[10px] text-emerald-400 font-mono">Gulf / Middle East</span>
                    </div>
                    <div className="flex gap-1.5">
                      <input 
                        type="text" 
                        value={naukrigulfLocations}
                        onChange={(e) => setNaukrigulfLocations(e.target.value)}
                        className="flex-1 px-3 py-1.5 rounded-lg bg-slate-900/90 border border-slate-800 text-xs text-slate-200 focus:border-emerald-400 focus:outline-none transition"
                        placeholder="Qatar, Dubai, UAE, Saudi Arabia, Remote"
                      />
                      <button
                        type="button"
                        onClick={() => setNaukrigulfLocations('Qatar, Dubai, UAE, Saudi Arabia, Remote')}
                        className="text-[10px] px-2 py-1 rounded bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/20"
                      >
                        Reset
                      </button>
                    </div>
                    <p className="text-[10px] text-slate-400">Targeting: <strong>Qatar</strong>, <strong>Dubai</strong>, <strong>UAE</strong>, &amp; <strong>Saudi Arabia</strong> (Auto-uses Qatar Profile &amp; Resume)</p>
                  </div>
                )}

                <div className="pt-1">
                  <label className="text-xs font-medium text-slate-300 block mb-1.5">Experience (Years)</label>
                  <input 
                    type="number" 
                    value={experience}
                    onChange={(e) => setExperience(e.target.value)}
                    className="w-full px-3.5 py-2 rounded-xl bg-slate-900 border border-slate-800 text-sm focus:border-teal-500 focus:outline-none transition"
                  />
                </div>
              </div>

              {/* Anti-Ban Safety Notice */}
              <div className="p-3 rounded-xl bg-slate-900/60 border border-slate-800/80 text-xs text-slate-400 space-y-1">
                <div className="flex items-center gap-1.5 text-teal-400 font-medium">
                  <Shield className="w-3.5 h-3.5" />
                  <span>Enforced Safety Settings:</span>
                </div>
                <p>• Max 45 applications/day strictly capped.</p>
                <p>• Mandatory 2-3 minute pause after each application.</p>
                <p>• Human mouse wheel & jitter scrolling enabled.</p>
              </div>

              {/* Start / Stop Buttons */}
              <div className="pt-2 flex gap-3">
                {!botState.is_running ? (
                  <button 
                    onClick={handleStart}
                    disabled={loadingAction || stats.today_applied >= 45}
                    className="flex-1 py-3 px-4 rounded-xl bg-gradient-to-r from-teal-500 to-emerald-500 hover:from-teal-600 hover:to-emerald-600 text-slate-950 font-bold text-sm flex items-center justify-center gap-2 shadow-lg shadow-teal-500/20 transition disabled:opacity-50"
                  >
                    <Play className="w-4 h-4 fill-current" />
                    Start Safe Auto-Apply
                  </button>
                ) : (
                  <button 
                    onClick={handleStop}
                    disabled={loadingAction}
                    className="flex-1 py-3 px-4 rounded-xl bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border border-rose-500/40 font-bold text-sm flex items-center justify-center gap-2 transition"
                  >
                    <Square className="w-4 h-4 fill-current" />
                    Pause Agent
                  </button>
                )}
              </div>

              {/* Chrome Launch Help */}
              {!chromeStatus.connected && (
                <div className="p-3 rounded-xl bg-amber-950/20 border border-amber-500/30 text-xs text-amber-200">
                  <span className="font-semibold block mb-1">Launch Chrome First:</span>
                  Aapke project folder mein <code className="text-amber-400 font-mono">start_chrome_debug.bat</code> banaya gaya hai. Usko double-click karein taake Chrome debugging port 9222 par start ho jaye!
                </div>
              )}
            </div>
          </div>

          {/* Live Activity Stream Terminal */}
          <div className="lg:col-span-2 glass-card p-6 rounded-2xl flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between pb-3 border-b border-slate-800">
                <div className="flex items-center gap-2 text-white font-bold text-sm">
                  <Terminal className="w-4 h-4 text-teal-400" />
                  Live Activity & Safety Stream
                </div>
                <span className="text-xs font-mono text-slate-500">FastAPI & Playwright Logs</span>
              </div>

              <div className="mt-4 space-y-2 h-72 overflow-y-auto pr-2 font-mono text-xs">
                {botState.recent_logs && botState.recent_logs.length > 0 ? (
                  botState.recent_logs.map((log, idx) => (
                    <div key={idx} className="flex items-start gap-2.5 leading-relaxed">
                      <span className="text-slate-500 shrink-0">[{log.timestamp}]</span>
                      <span className={
                        log.level === 'SUCCESS' ? 'text-emerald-400 font-medium' :
                        log.level === 'WARNING' ? 'text-amber-400' :
                        log.level === 'ERROR' ? 'text-rose-400 font-bold' :
                        'text-slate-300'
                      }>
                        {log.message}
                      </span>
                    </div>
                  ))
                ) : (
                  <div className="h-full flex items-center justify-center text-slate-500">
                    No recent activity. Click "Start Safe Auto-Apply" to launch the agent.
                  </div>
                )}
              </div>
            </div>

            <div className="pt-3 border-t border-slate-800/80 flex items-center justify-between text-xs text-slate-400">
              <span className="flex items-center gap-1.5">
                <Shield className="w-3.5 h-3.5 text-teal-400" />
                Anti-Detection Stealth Active
              </span>
              <button 
                onClick={fetchStatus}
                className="hover:text-teal-400 flex items-center gap-1 transition"
              >
                <RefreshCw className="w-3 h-3" /> Refresh
              </button>
            </div>
          </div>
        </div>

        {/* Applications History Section */}
        <div className="glass-card rounded-2xl overflow-hidden">
          {/* Table Header & Tabs */}
          <div className="p-5 border-b border-slate-800 flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-bold text-white text-base">Application History & Audit Log</h3>
                {/* Platform filter pills */}
                <div className="flex items-center gap-1 bg-slate-950 p-0.5 rounded-lg border border-slate-800 text-[10px]">
                  <button
                    onClick={() => setPlatformFilter('ALL')}
                    className={`px-2 py-0.5 rounded font-medium transition ${platformFilter === 'ALL' ? 'bg-teal-500/30 text-teal-300 font-bold' : 'text-slate-400'}`}
                  >
                    All Boards
                  </button>
                  <button
                    onClick={() => setPlatformFilter('NAUKRI')}
                    className={`px-2 py-0.5 rounded font-medium transition ${platformFilter === 'NAUKRI' ? 'bg-cyan-500/30 text-cyan-300 font-bold' : 'text-slate-400'}`}
                  >
                    🔷 Naukri
                  </button>
                  <button
                    onClick={() => setPlatformFilter('LINKEDIN')}
                    className={`px-2 py-0.5 rounded font-medium transition ${platformFilter === 'LINKEDIN' ? 'bg-blue-500/30 text-blue-300 font-bold' : 'text-slate-400'}`}
                  >
                    🟦 LinkedIn
                  </button>
                  <button
                    onClick={() => setPlatformFilter('NAUKRIGULF')}
                    className={`px-2 py-0.5 rounded font-medium transition ${platformFilter === 'NAUKRIGULF' ? 'bg-emerald-500/30 text-emerald-300 font-bold' : 'text-slate-400'}`}
                  >
                    🌐 NaukriGulf
                  </button>
                </div>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">Stored persistently in MySQL database across all 3 platforms (Naukri, LinkedIn, NaukriGulf)</p>
            </div>

            {/* Tabs */}
            <div className="flex items-center gap-1 bg-slate-900/80 p-1 rounded-xl border border-slate-800 text-xs">
              <button
                onClick={() => setActiveTab('ALL')}
                className={`px-3 py-1.5 rounded-lg transition font-medium ${activeTab === 'ALL' ? 'bg-teal-500 text-slate-950 font-bold' : 'text-slate-400 hover:text-white'}`}
              >
                All ({applications.length})
              </button>
              <button
                onClick={() => setActiveTab('APPLIED')}
                className={`px-3 py-1.5 rounded-lg transition font-medium ${activeTab === 'APPLIED' ? 'bg-teal-500 text-slate-950 font-bold' : 'text-slate-400 hover:text-white'}`}
              >
                ✅ Applied ({stats.total_applied})
              </button>
              <button
                onClick={() => setActiveTab('REDIRECT_REVIEW')}
                className={`px-3 py-1.5 rounded-lg transition font-medium ${activeTab === 'REDIRECT_REVIEW' ? 'bg-amber-500 text-slate-950 font-bold' : 'text-slate-400 hover:text-white'}`}
              >
                ⭐ External Review ({stats.external_redirects})
              </button>
              <button
                onClick={() => setActiveTab('NEEDS_USER_INPUT')}
                className={`px-3 py-1.5 rounded-lg transition font-medium ${activeTab === 'NEEDS_USER_INPUT' ? 'bg-amber-500 text-slate-950 font-bold' : 'text-slate-400 hover:text-white'}`}
              >
                ❓ Needs Input ({stats.needs_user_input || 0})
              </button>
              <button
                onClick={() => setActiveTab('FAILED')}
                className={`px-3 py-1.5 rounded-lg transition font-medium ${activeTab === 'FAILED' ? 'bg-rose-500 text-slate-950 font-bold' : 'text-slate-400 hover:text-white'}`}
              >
                ⚠️ Failed ({stats.failed_attempts})
              </button>
              <button
                onClick={() => setActiveTab('SKIPPED')}
                className={`px-3 py-1.5 rounded-lg transition font-medium ${activeTab === 'SKIPPED' ? 'bg-slate-700 text-white font-bold' : 'text-slate-400 hover:text-white'}`}
              >
                Skipped
              </button>
            </div>

            {/* Search Input */}
            <div className="relative">
              <Search className="w-4 h-4 text-slate-500 absolute left-3 top-2.5" />
              <input 
                type="text" 
                placeholder="Search company or title..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="pl-9 pr-4 py-1.5 bg-slate-900 border border-slate-800 rounded-xl text-xs text-slate-200 focus:outline-none focus:border-teal-500 transition w-56"
              />
            </div>
          </div>

          {/* Table */}
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-900/60 text-slate-400 font-semibold border-b border-slate-800">
                <tr>
                  <th className="py-3 px-3 text-center w-12 text-slate-400">Sr No</th>
                  <th className="py-3 px-4">Platform</th>
                  <th className="py-3 px-4">Job Title & Role</th>
                  <th className="py-3 px-4">Company</th>
                  <th className="py-3 px-4">Location</th>
                  <th className="py-3 px-4">AI Match</th>
                  <th className="py-3 px-4">Apply Type & Status</th>
                  <th className="py-3 px-4">Applied Date/Time</th>
                  <th className="py-3 px-4 text-right">Action / Link</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {filteredApps.length > 0 ? (
                  filteredApps.map((app, index) => (
                    <tr key={app.id} className="hover:bg-slate-800/30 transition">
                      <td className="py-3 px-3 text-center text-slate-400 font-mono font-semibold text-xs">
                        {index + 1}
                      </td>
                      <td className="py-3 px-4">
                        {(app.platform || 'NAUKRI').toUpperCase() === 'LINKEDIN' ? (
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-500/15 text-blue-400 border border-blue-500/30 inline-flex items-center gap-1">
                            <span>🟦</span> LinkedIn
                          </span>
                        ) : (app.platform || '').toUpperCase() === 'NAUKRIGULF' ? (
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 inline-flex items-center gap-1">
                            <span>🌐</span> NaukriGulf
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-cyan-500/15 text-cyan-400 border border-cyan-500/30 inline-flex items-center gap-1">
                            <span>🔷</span> Naukri
                          </span>
                        )}
                      </td>
                      <td className="py-3 px-4 font-medium text-white max-w-xs truncate">
                        {app.job_title}
                        {app.experience_req && (
                          <span className="block text-[10px] text-slate-400 font-normal">Exp: {app.experience_req}</span>
                        )}
                      </td>
                      <td className="py-3 px-4 text-slate-300 font-medium">{app.company_name}</td>
                      <td className="py-3 px-4">
                        <span className={`px-2 py-0.5 rounded-md text-[10px] font-medium ${
                          (app.location || '').toLowerCase().includes('qatar') || (app.location || '').toLowerCase().includes('doha')
                            ? 'bg-amber-500/10 text-amber-300 border border-amber-500/20'
                            : 'bg-slate-800/80 text-slate-300'
                        }`}>
                          📍 {app.location || 'Mumbai / Remote'}
                        </span>
                      </td>
                      <td className="py-3 px-4">
                        <span className={`px-2 py-0.5 rounded-full text-[11px] font-semibold ${
                          (app.match_score || 85) >= 80 ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' :
                          (app.match_score || 85) >= 65 ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' :
                          'bg-slate-800 text-slate-400'
                        }`}>
                          {app.match_score || 85}%
                        </span>
                      </td>
                      <td className="py-3 px-4">
                        {(app.status === 'APPLIED' || app.status === 'APPLICATION_CONFIRMED') && (
                          <span className="px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 inline-flex items-center gap-1">
                            <CheckCircle2 className="w-3 h-3" /> Direct Applied
                          </span>
                        )}
                        {(app.status === 'REDIRECT_REVIEW' || app.status === 'APPLICATION_PENDING_CONFIRMATION') && (
                          <span className="px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20 inline-flex items-center gap-1">
                            <ExternalLink className="w-3 h-3" /> External Site
                          </span>
                        )}
                        {app.status === 'NEEDS_USER_INPUT' && (
                          <div>
                            <span className="px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20 inline-flex items-center gap-1">
                              <AlertTriangle className="w-3 h-3 text-amber-400" /> Needs Input
                            </span>
                            {app.failure_reason && (
                              <span className="block text-[10px] text-amber-400/80 mt-0.5 max-w-[140px] truncate" title={app.failure_reason}>
                                {app.failure_reason}
                              </span>
                            )}
                          </div>
                        )}
                        {(app.status === 'SKIPPED' || app.status === 'APPLICATION_SKIPPED') && (
                          <span className="px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-slate-800 text-slate-400 inline-flex items-center gap-1">
                            Skipped
                          </span>
                        )}
                        {(app.status === 'FAILED' || app.status === 'APPLICATION_FAILED') && (
                          <div>
                            <span className="px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20">
                              Failed
                            </span>
                            {app.failure_reason && (
                              <span className="block text-[10px] text-rose-400/80 mt-0.5 max-w-[140px] truncate" title={app.failure_reason}>
                                {app.failure_reason}
                              </span>
                            )}
                          </div>
                        )}
                      </td>
                      <td className="py-3 px-4 text-slate-400 font-mono text-[11px]">
                        {app.applied_at ? new Date(app.applied_at).toLocaleString() : 'Just now'}
                      </td>
                      <td className="py-3 px-4 text-right">
                        {app.job_url ? (
                          <a 
                            href={app.job_url} 
                            target="_blank" 
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-teal-400 hover:text-teal-300 font-medium transition"
                          >
                            <span>Open</span>
                            <ArrowUpRight className="w-3.5 h-3.5" />
                          </a>
                        ) : (
                          <span className="text-slate-600">-</span>
                        )}
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan="9" className="py-12 text-center text-slate-500">
                      No applications recorded in this tab yet. Start the agent to apply!
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </main>

      {/* Profile Modal */}
      {profileModal && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="glass-card max-w-lg w-full p-6 rounded-2xl space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <h3 className="font-bold text-white text-base flex items-center gap-2">
                <User className="w-4 h-4 text-teal-400" />
                Candidate Profile & Screening Answers
              </h3>
              <button 
                onClick={() => setProfileModal(false)}
                className="text-slate-400 hover:text-white"
              >
                ✕
              </button>
            </div>

            <div className="space-y-3 text-xs max-h-[70vh] overflow-y-auto pr-1">
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <span className="text-slate-400 block text-[11px]">Full Name</span>
                  <span className="text-white font-medium">{profileData?.name}</span>
                </div>
                <div>
                  <span className="text-slate-400 block text-[11px]">Date of Birth</span>
                  <span className="text-teal-400 font-semibold">{profileData?.dob || '19/11/1999'}</span>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <span className="text-slate-400 block text-[11px]">Email</span>
                  <span className="text-white font-medium">{profileData?.email}</span>
                </div>
                <div>
                  <span className="text-slate-400 block text-[11px]">Phone</span>
                  <span className="text-white font-medium">{profileData?.phone}</span>
                </div>
              </div>

              <div className="p-2.5 rounded-xl bg-slate-900 border border-slate-800">
                <span className="text-slate-400 block text-[11px]">Highest Qualification &amp; University</span>
                <span className="text-white font-semibold">{profileData?.highest_qualification || 'BSC Computer Science'}</span>
                <span className="text-slate-400 text-[11px] block">{profileData?.university || 'BAMU University, India'} ({profileData?.graduation_year || '2021'})</span>
              </div>

              <div className="p-2.5 rounded-xl bg-teal-500/10 border border-teal-500/20 flex items-center justify-between">
                <div>
                  <span className="text-teal-400 font-semibold block text-[11px]">Active Resume for Auto-Upload</span>
                  <span className="text-white text-xs font-mono">{profileData?.resume_filename || 'Abdul Razzaque India.pdf'}</span>
                </div>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-teal-500 text-slate-950">Ready</span>
              </div>

              <div className="grid grid-cols-2 gap-3 pt-1">
                <div className="p-2.5 rounded-xl bg-slate-900 border border-slate-800">
                  <span className="text-slate-400 block text-[11px]">Current CTC</span>
                  <span className="text-white font-bold text-sm">₹{profileData?.current_ctc_lpa} LPA</span>
                  <span className="text-slate-500 text-[10px] block">Fixed: ₹12,00,000 INR/Year</span>
                </div>
                <div className="p-2.5 rounded-xl bg-slate-900 border border-slate-800">
                  <span className="text-slate-400 block text-[11px]">Expected CTC</span>
                  <span className="text-emerald-400 font-bold text-sm">₹{profileData?.expected_ctc_lpa} LPA</span>
                  <span className="text-slate-500 text-[10px] block">INR (₹) / Annual</span>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="p-2.5 rounded-xl bg-slate-900 border border-slate-800">
                  <span className="text-slate-400 block text-[11px]">Total Experience</span>
                  <span className="text-white font-semibold">5+ Years (Senior)</span>
                </div>
                <div className="p-2.5 rounded-xl bg-slate-900 border border-slate-800">
                  <span className="text-slate-400 block text-[11px]">Notice Period</span>
                  <span className="text-white font-semibold">{profileData?.notice_period_days || 30} Days (1 Month)</span>
                </div>
              </div>

              <div className="p-2.5 rounded-xl bg-slate-900 border border-slate-800">
                <span className="text-slate-400 block text-[11px]">Location</span>
                <span className="text-white font-medium">{profileData?.current_location || 'Kurla, Mumbai, India'}</span>
                <span className="text-slate-500 text-[10px] block">Preferred: Mumbai / Remote / Pune</span>
              </div>

              <div className="p-2.5 rounded-xl bg-slate-900 border border-slate-800">
                <span className="text-slate-400 block text-[11px]">Key Skills</span>
                <span className="text-slate-300">
                  React.js, Next.js, Node.js, Express, MongoDB, MySQL, PostgreSQL, TypeScript, Redis, Kafka, Docker, AWS
                </span>
              </div>
            </div>

            <button 
              onClick={() => setProfileModal(false)}
              className="w-full py-2.5 rounded-xl bg-teal-500 hover:bg-teal-600 text-slate-950 font-bold text-xs transition"
            >
              Close Window
            </button>
          </div>
        </div>
      )}

      {/* Autonomous Permissions & Configuration Modal */}
      {configModal && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-950 border border-slate-800 rounded-2xl max-w-lg w-full p-6 space-y-4 shadow-2xl relative max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-indigo-500/20 text-indigo-400 flex items-center justify-center">
                  <Shield className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="font-bold text-white text-sm">Autonomous Mode Configuration</h3>
                  <p className="text-[11px] text-slate-400">Persistent permissions stored in agent_config.json</p>
                </div>
              </div>
              <button 
                onClick={() => setConfigModal(false)}
                className="text-slate-400 hover:text-white text-lg font-bold px-2"
              >
                ✕
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <div className="p-3 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-[11px] text-indigo-300">
                <span>⚡ <strong>Autonomous Execution:</strong> Routine operations authorized below execute automatically across application restarts without repeated approval prompts.</span>
              </div>

              {/* Authorized Routine Permissions */}
              <div className="space-y-2">
                <h4 className="font-semibold text-slate-200 text-xs">Authorized Routine Actions</h4>
                {[
                  { key: 'auto_search', label: 'Auto Job Search & Cycling', desc: 'Automatically search target roles on job portals' },
                  { key: 'auto_inspect_jobs', label: 'Auto Job Inspection & Scoring', desc: 'Open listings and evaluate profile compatibility' },
                  { key: 'auto_fill_forms', label: 'Auto Fill Application Forms', desc: 'Pre-fill candidate info from verified profile' },
                  { key: 'auto_upload_resume', label: 'Auto Attach Candidate Resume', desc: 'Attach verified PDF resume to file upload inputs' },
                  { key: 'auto_answer_screening', label: 'Auto Answer Screening Questions', desc: 'Answer known questions using candidate profile & AI' },
                  { key: 'auto_submit_direct', label: 'Auto Submit Direct Applications', desc: 'Submit completed direct applications automatically' },
                  { key: 'auto_submit_company_portal', label: 'Auto Submit Company Career Portals', desc: 'Submit external company portal forms when verified' },
                ].map(item => (
                  <label key={item.key} className="flex items-start gap-3 p-2.5 rounded-xl bg-slate-900 border border-slate-800 hover:border-slate-700 cursor-pointer transition">
                    <input 
                      type="checkbox"
                      checked={agentConfig?.permissions?.[item.key] ?? true}
                      onChange={(e) => {
                        const updated = {
                          ...agentConfig,
                          permissions: {
                            ...(agentConfig?.permissions || {}),
                            [item.key]: e.target.checked
                          }
                        };
                        setAgentConfig(updated);
                      }}
                      className="mt-0.5 rounded text-teal-500 focus:ring-teal-400 bg-slate-800 border-slate-700"
                    />
                    <div>
                      <span className="font-semibold text-white block">{item.label}</span>
                      <span className="text-[11px] text-slate-400">{item.desc}</span>
                    </div>
                  </label>
                ))}
              </div>

              {/* Safety Boundaries */}
              <div className="space-y-2 pt-2 border-t border-slate-800">
                <h4 className="font-semibold text-slate-200 text-xs">Enforced Safety Boundaries</h4>
                <div className="p-3 rounded-xl bg-slate-900 border border-slate-800 text-[11px] space-y-1.5 text-slate-300">
                  <div className="flex items-center gap-2 text-emerald-400 font-medium">
                    <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                    <span>Block all payments, application fees &amp; subscriptions</span>
                  </div>
                  <div className="flex items-center gap-2 text-emerald-400 font-medium">
                    <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                    <span>Block card numbers, bank accounts &amp; national IDs (SSN/Aadhaar/PAN)</span>
                  </div>
                  <div className="flex items-center gap-2 text-emerald-400 font-medium">
                    <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                    <span>Never fabricate salary, qualifications, or unrecorded personal facts</span>
                  </div>
                  <div className="flex items-center gap-2 text-emerald-400 font-medium">
                    <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                    <span>Unknown mandatory questions flagged as NEEDS_USER_INPUT (tabs kept open)</span>
                  </div>
                  <div className="flex items-center gap-2 text-emerald-400 font-medium">
                    <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                    <span>Immediate cancellation when user clicks Stop</span>
                  </div>
                </div>
              </div>
            </div>

            <div className="flex gap-3 pt-2">
              <button 
                onClick={() => handleSaveConfig(agentConfig)}
                disabled={savingConfig}
                className="flex-1 py-2.5 rounded-xl bg-indigo-500 hover:bg-indigo-600 text-white font-bold text-xs transition disabled:opacity-50"
              >
                {savingConfig ? "Saving..." : "Save & Persist Configuration"}
              </button>
              <button 
                onClick={() => setConfigModal(false)}
                className="py-2.5 px-4 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 font-semibold text-xs transition"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
