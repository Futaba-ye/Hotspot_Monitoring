import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

const labels = { verified: '已核实', pending: '待核实', suspicious: '疑似误传' }
const views = [
  ['overview', '总览', '◈'],
  ['monitors', '监控任务', '◎'],
  ['alerts', '提醒收件箱', '◉'],
  ['settings', '连接状态', '⚙'],
]

async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers },
  })
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`
    try {
      const body = await response.json()
      detail = typeof body.detail === 'string' ? body.detail : detail
    } catch { /* 服务器可能未返回 JSON */ }
    throw new Error(detail)
  }
  if (response.status === 204) return null
  return response.json()
}

function dateText(value) {
  if (!value) return '尚未运行'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(date)
}

function Logo() {
  return <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>
}

function Radar() {
  return <div className="radar" aria-hidden="true">
    <span className="radar-ring ring-one" /><span className="radar-ring ring-two" />
    <span className="radar-ring ring-three" /><span className="radar-cross cross-h" />
    <span className="radar-cross cross-v" /><span className="radar-sweep" />
    <span className="radar-center" /><span className="radar-dot dot-one" />
    <span className="radar-dot dot-two" /><span className="radar-dot dot-three" />
  </div>
}

function Badge({ status }) {
  return <span className={`badge badge-${status}`}><span className="badge-dot" />{labels[status] || status}</span>
}

function EventCard({ event, index }) {
  const [expanded, setExpanded] = useState(false)
  return <article className={`event-card status-${event.status}`}>
    <div className="event-index">{String(index + 1).padStart(2, '0')}</div>
    <div className="event-main">
      <div className="event-topline"><Badge status={event.status} /><span>{event.rule_kind === 'keyword' ? '关键词命中' : '领域发现'}</span><span className="topline-separator">/</span><span>{dateText(event.updated_at)}</span></div>
      <h3>{event.title}</h3>
      <p className="event-summary">{event.summary}</p>
      <div className="event-footer">
        <span className="event-query">#{event.rule_query}</span>
        <span className="source-count">{event.evidence.length} 条来源证据</span>
        <button className="text-button" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>{expanded ? '收起证据 ↑' : '查看证据 ↗'}</button>
      </div>
      {expanded && <div className="evidence-panel">
        <p className="evidence-reason"><strong>核实说明</strong>{event.reason}</p>
        {event.evidence.map((item) => <a className="evidence-link" href={item.source_url} target="_blank" rel="noopener noreferrer" key={item.source_url}>
          <span className="evidence-source">{item.source}</span><span>{item.title}</span><span aria-hidden="true">↗</span>
        </a>)}
      </div>}
    </div>
    <div className="heat-box"><span>热度</span><strong>{event.heat}</strong><span className="heat-track"><i style={{ width: `${event.heat}%` }} /></span></div>
  </article>
}

function RuleCard({ rule, onToggle, onDelete, onScan, onUpdate, busy }) {
  const [editing, setEditing] = useState(false)
  const [query, setQuery] = useState(rule.query)
  const [interval, setIntervalValue] = useState(rule.interval_minutes)
  const [error, setError] = useState('')
  const save = async (event) => {
    event.preventDefault()
    try { await onUpdate(rule.id, { query: query.trim(), interval_minutes: Number(interval) }); setEditing(false); setError('') }
    catch (err) { setError(err.message) }
  }
  return <article className={`rule-card ${rule.enabled ? '' : 'rule-disabled'}`}>
    <div className="rule-type">{rule.kind === 'keyword' ? '精准监控 / KEYWORD' : '领域雷达 / TOPIC'}<span className={rule.enabled ? 'live-pill' : 'paused-pill'}>{rule.enabled ? '运行中' : '已暂停'}</span></div>
    {editing ? <form className="edit-rule" onSubmit={save}><label>监控内容<input value={query} onChange={(e) => setQuery(e.target.value)} minLength="2" maxLength="120" required /></label><label>扫描周期（分钟）<input type="number" value={interval} min="5" max="1440" onChange={(e) => setIntervalValue(e.target.value)} required /></label><div><button type="submit">保存修改</button><button type="button" onClick={() => setEditing(false)}>取消</button></div>{error && <p className="form-error">{error}</p>}</form> : <><h3>{rule.query}</h3><p>每 {rule.interval_minutes} 分钟扫描一次 · 上次 {dateText(rule.last_run_at)}</p></>}
    {rule.last_error && <div className="rule-error" title={rule.last_error}>⚠ {rule.last_error}</div>}
    {!editing && <div className="rule-actions">
      <button onClick={() => onScan(rule.id)} disabled={busy}>{busy ? '扫描中…' : '立即扫描 ↗'}</button>
      <button onClick={() => setEditing(true)}>编辑</button>
      <button onClick={() => onToggle(rule)}>{rule.enabled ? '暂停' : '启用'}</button>
      <button className="delete-button" onClick={() => onDelete(rule)}>删除</button>
    </div>}
  </article>
}

function NewRule({ onCreate, busy }) {
  const [kind, setKind] = useState('keyword')
  const [query, setQuery] = useState('')
  const [interval, setIntervalValue] = useState(5)
  const [error, setError] = useState('')
  const selectKind = (next) => { setKind(next); setIntervalValue(next === 'keyword' ? 5 : 30) }
  const submit = async (event) => {
    event.preventDefault()
    setError('')
    try {
      await onCreate({ kind, query: query.trim(), interval_minutes: Number(interval) })
      setQuery('')
    } catch (err) { setError(err.message) }
  }
  return <form className="new-rule" onSubmit={submit}>
    <div className="section-kicker">01 / 新建监控</div>
    <h2>你想追踪什么<span>？</span></h2>
    <p className="form-intro">输入具体事件关键词，或圈定一个持续变化的领域。</p>
    <div className="kind-options">
      <button type="button" className={kind === 'keyword' ? 'selected' : ''} onClick={() => selectKind('keyword')}><span>◎</span><strong>关键词提醒</strong><small>出现并核实后通知</small></button>
      <button type="button" className={kind === 'topic' ? 'selected' : ''} onClick={() => selectKind('topic')}><span>◈</span><strong>领域发现</strong><small>持续发掘新热点</small></button>
    </div>
    <label className="form-label" htmlFor="rule-query">监控内容</label>
    <input id="rule-query" value={query} onChange={(e) => setQuery(e.target.value)} minLength="2" maxLength="120" required placeholder={kind === 'keyword' ? '例如：GPT-6 发布' : '例如：AI 编程'} />
    <div className="form-bottom"><label htmlFor="rule-interval">扫描周期 <input id="rule-interval" type="number" min="5" max="1440" value={interval} onChange={(e) => setIntervalValue(e.target.value)} /> 分钟</label><button className="primary-button" type="submit" disabled={busy}>{busy ? '创建中…' : '开始监控 ↗'}</button></div>
    {error && <p className="form-error">{error}</p>}
  </form>
}

function Connection({ name, ready, detail }) {
  return <div className="connection"><div><span className={`connection-light ${ready ? 'ready' : ''}`} /><strong>{name}</strong><small>{detail}</small></div><span className={`connection-state ${ready ? 'ready' : ''}`}>{ready ? '已配置' : '待配置'}</span></div>
}

export default function App() {
  const [view, setView] = useState('overview')
  const [status, setStatus] = useState(null)
  const [rules, setRules] = useState([])
  const [events, setEvents] = useState([])
  const [notifications, setNotifications] = useState([])
  const [filter, setFilter] = useState('all')
  const [selectedRule, setSelectedRule] = useState('all')
  const [sortBy, setSortBy] = useState('recent')
  const [busyRule, setBusyRule] = useState(null)
  const [creating, setCreating] = useState(false)
  const [toast, setToast] = useState('')
  const [loadError, setLoadError] = useState('')
  const latestAlertId = useRef(null)

  const refresh = useCallback(async () => {
    try {
      const [nextStatus, nextRules, nextEvents, nextNotifications] = await Promise.all([
        api('/status'), api('/rules'), api('/events'), api('/notifications'),
      ])
      if (latestAlertId.current !== null && nextNotifications.some((item) => item.id > latestAlertId.current)) {
        setToast('收到新的已核实热点提醒，请查看收件箱')
      }
      latestAlertId.current = Math.max(0, ...nextNotifications.map((item) => item.id))
      setStatus(nextStatus); setRules(nextRules); setEvents(nextEvents); setNotifications(nextNotifications)
      setLoadError('')
    } catch (error) { setLoadError(error.message) }
  }, [])

  useEffect(() => { refresh(); const timer = setInterval(refresh, 10000); return () => clearInterval(timer) }, [refresh])
  useEffect(() => { if (!toast) return; const timer = setTimeout(() => setToast(''), 5000); return () => clearTimeout(timer) }, [toast])

  const shownEvents = useMemo(() => events
    .filter((event) => (filter === 'all' || event.status === filter) && (selectedRule === 'all' || event.rule_id === Number(selectedRule)))
    .sort((a, b) => sortBy === 'heat' ? b.heat - a.heat || b.updated_at.localeCompare(a.updated_at) : b.updated_at.localeCompare(a.updated_at)), [events, filter, selectedRule, sortBy])
  const verifiedCount = events.filter((event) => event.status === 'verified').length
  const activeRules = rules.filter((rule) => rule.enabled).length

  const createRule = async (body) => {
    setCreating(true)
    try { await api('/rules', { method: 'POST', body: JSON.stringify(body) }); await refresh(); setToast('监控已创建，后台即将开始扫描') }
    finally { setCreating(false) }
  }
  const toggleRule = async (rule) => {
    try { await api(`/rules/${rule.id}`, { method: 'PATCH', body: JSON.stringify({ enabled: !rule.enabled }) }); await refresh() }
    catch (error) { setToast(error.message) }
  }
  const updateRule = async (id, values) => {
    await api(`/rules/${id}`, { method: 'PATCH', body: JSON.stringify(values) })
    await refresh()
    setToast('监控任务已更新')
  }
  const deleteRule = async (rule) => {
    if (!window.confirm(`删除“${rule.query}”及其历史结果？`)) return
    try { await api(`/rules/${rule.id}`, { method: 'DELETE' }); await refresh(); setToast('监控已删除') }
    catch (error) { setToast(error.message) }
  }
  const scanRule = async (id) => {
    setBusyRule(id)
    try { const result = await api(`/rules/${id}/scan`, { method: 'POST' }); await refresh(); setToast(result.message) }
    catch (error) { setToast(error.message) }
    finally { setBusyRule(null) }
  }
  const markRead = async (id) => {
    try { await api(`/notifications/${id}/read`, { method: 'POST' }); await refresh() }
    catch (error) { setToast(error.message) }
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <button className="brand" onClick={() => setView('overview')}><Logo /><span>脉冲台<small>PULSE DESK</small></span></button>
      <div className="sidebar-label">工作台 / 01</div>
      <nav aria-label="主导航">{views.map(([key, name, icon]) => <button key={key} className={view === key ? 'active' : ''} onClick={() => setView(key)}><span className="nav-icon">{icon}</span>{name}{key === 'alerts' && status?.unread > 0 && <b>{status.unread}</b>}</button>)}</nav>
      <div className="sidebar-bottom"><div className="signal-animation"><span /><span /><span /><span /><span /></div><strong>保持敏锐。</strong><small>信息出现时，先你一步。</small><span className="version">LOCAL / V 0.1</span></div>
    </aside>

    <main className="main">
      <header className="topbar"><div className="breadcrumb">脉冲台 <span>/</span> {views.find(([key]) => key === view)?.[1]}</div><div className="topbar-right"><span className="clock-label">本机监控</span><span className="online-indicator">{loadError ? '连接中断' : '系统在线'}</span><button onClick={refresh} title="刷新">↻</button></div></header>
      {loadError && <div className="global-error">无法连接后端：{loadError}。请确认服务已启动。<button onClick={refresh}>重试</button></div>}

      {view === 'overview' && <>
        <section className="hero"><div className="hero-copy"><div className="eyebrow"><span className="eyebrow-line" /> INFORMATION INTELLIGENCE / 2026</div><h1>追踪变化<span className="hero-period">.</span><br /><em>先于热度</em>抵达。</h1><p>从网页、新闻与 X 汇集线索。让 AI 识别真正相关的变化，让证据决定何时提醒你。</p><button className="hero-cta" onClick={() => setView('monitors')}>建立你的监控 <span>↗</span></button></div><Radar /><div className="hero-coordinate">SIGNAL AREA / 39°54′N</div></section>
        <section className="metric-row"><div className="metric"><span>01 / 运行中的监控</span><strong>{String(activeRules).padStart(2, '0')}</strong><small>持续扫描中</small></div><div className="metric"><span>02 / 捕获的线索</span><strong>{String(status?.events ?? 0).padStart(2, '0')}</strong><small>跨来源汇集</small></div><div className="metric"><span>03 / 已核实事件</span><strong>{String(verifiedCount).padStart(2, '0')}</strong><small>达到证据门槛</small></div><div className="metric accent-metric"><span>04 / 待查看提醒</span><strong>{String(status?.unread ?? 0).padStart(2, '0')}</strong><button onClick={() => setView('alerts')}>查看收件箱 ↗</button></div></section>
        <section className="content-section"><div className="section-heading"><div><span className="section-kicker">实时观察 / LIVE FEED</span><h2>最新捕获</h2></div><div className="filter-tabs">{[['all', '全部'], ['verified', '已核实'], ['pending', '待核实'], ['suspicious', '疑似误传']].map(([key, name]) => <button className={filter === key ? 'selected' : ''} onClick={() => setFilter(key)} key={key}>{name}</button>)}</div></div>
          <div className="event-controls"><label>监控范围 <select value={selectedRule} onChange={(event) => setSelectedRule(event.target.value)}><option value="all">全部监控</option>{rules.map((rule) => <option value={rule.id} key={rule.id}>{rule.kind === 'topic' ? '领域 · ' : '关键词 · '}{rule.query}</option>)}</select></label><label>排序方式 <select value={sortBy} onChange={(event) => setSortBy(event.target.value)}><option value="recent">最新优先</option><option value="heat">热度优先</option></select></label></div>
          {shownEvents.length ? <div className="event-list">{shownEvents.slice(0, 20).map((event, index) => <EventCard event={event} index={index} key={event.id} />)}</div> : <div className="empty-state"><div className="empty-orbit">◌</div><strong>{events.length ? '该分类暂无结果' : '雷达还没有捕获到线索'}</strong><p>{events.length ? '切换筛选条件查看其他事件。' : '建立监控后，系统会自动从多个来源寻找变化。'}</p><button onClick={() => setView('monitors')}>前往监控任务 ↗</button></div>}</section>
      </>}

      {view === 'monitors' && <><section className="page-heading"><span className="section-kicker">MONITOR CONTROL / 02</span><h1>定义你的<span>关注范围。</span></h1><p>一个具体关键词，或一片持续变化的领域。</p></section><div className="monitor-layout"><NewRule onCreate={createRule} busy={creating} /><section className="rule-list"><div className="section-heading compact"><div><span className="section-kicker">正在追踪</span><h2>{rules.length} 个监控任务</h2></div></div>{rules.length ? rules.map((rule) => <RuleCard key={rule.id} rule={rule} onToggle={toggleRule} onDelete={deleteRule} onScan={scanRule} onUpdate={updateRule} busy={busyRule === rule.id} />) : <div className="empty-inline">暂无监控任务。创建第一个任务，开始寻找信号。</div>}</section></div></>}

      {view === 'alerts' && <><section className="page-heading"><span className="section-kicker">SIGNAL INBOX / 03</span><h1>重要变化<span>，不遗漏。</span></h1><p>只有达到核实门槛的关键词事件，才会进入这里。</p></section><section className="inbox-section">{notifications.length ? notifications.map((item) => <article className={`alert-card ${item.read_at ? '' : 'unread'}`} key={item.id}><span className="alert-icon">↗</span><div><div className="alert-meta">{item.read_at ? '已读' : '新提醒'} · {dateText(item.created_at)} · 邮件{item.email_status}</div><h3>{item.title}</h3><p>{item.summary}</p>{events.find((event) => event.id === item.event_id)?.evidence.map((evidence) => <a key={evidence.source_url} className="alert-evidence" href={evidence.source_url} target="_blank" rel="noopener noreferrer">{evidence.source} ↗</a>)}{item.email_error && <small className="mail-error">邮件失败：{item.email_error}</small>}</div>{!item.read_at && <button onClick={() => markRead(item.id)}>标记已读</button>}</article>) : <div className="empty-state"><div className="empty-orbit">◉</div><strong>收件箱安静如常</strong><p>已核实的关键词事件会出现在这里。</p></div>}</section></>}

      {view === 'settings' && <><section className="page-heading"><span className="section-kicker">SYSTEM STATUS / 04</span><h1>每一条信号<span>，都可追溯。</span></h1><p>配置由本机环境文件读取，密钥不会出现在浏览器中。</p></section><section className="settings-grid"><div className="settings-card"><div className="section-kicker">服务连接 / CONNECTORS</div><h2>连接状态</h2><Connection name="OpenRouter AI" ready={status?.ai_configured} detail={status?.model || '结构化判读'} /><Connection name="X · twitterapi.io" ready={status?.x_configured} detail="最新推文搜索" /><Connection name="SMTP 邮件" ready={status?.email_configured} detail="已核实事件通知" /><p className="settings-note">未配置 AI 时不会将线索标记为已核实。配置后请重启后端服务。</p></div><div className="settings-card"><div className="section-kicker">采集记录 / SOURCES</div><h2>来源运行情况</h2>{status?.sources?.length ? status.sources.map((source) => <div className="source-health" key={source.source}><div><strong>{source.source}</strong><small>{dateText(source.checked_at)} · {source.result_count} 条候选</small></div><span className={source.error ? 'health-error' : 'health-ok'}>{source.error ? '异常' : '正常'}</span>{source.error && <p>{source.error}</p>}</div>) : <p className="settings-note">尚无采集记录。创建监控后自动开始扫描。</p>}</div></section></>}
      <footer className="footer"><span>脉冲台 / PULSE DESK</span><span>让消息有来源，让提醒有依据。</span><span>LOCAL SYSTEM · 2026</span></footer>
    </main>
    {toast && <div className="toast" role="status">{toast}<button onClick={() => setToast('')}>×</button></div>}
  </div>
}
