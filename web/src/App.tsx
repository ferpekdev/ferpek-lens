import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import {
  BrowserRouter,
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from 'react-router-dom'
import './App.css'

type Status = 'healthy' | 'warning' | 'critical' | 'unknown'

function StatusDiamond({ status }: { status: Status }) {
  return <span className={`status-diamond ${status}`} />
}

function GlobalTooltip() {
  const tooltipRef = useRef<HTMLDivElement>(null)

  const [tooltip, setTooltip] = useState<{
    text: string
    targetX: number
    y: number
    placement: 'top' | 'bottom'
  } | null>(null)

  const [position, setPosition] = useState<{
    x: number
    arrowX: number
  } | null>(null)

  useEffect(() => {
    function showTooltip(target: EventTarget | null) {
      if (!(target instanceof Element)) {
        return
      }

      const element = target.closest<HTMLElement>(
        '[data-tooltip]',
      )

      if (!element) {
        return
      }

      const text = element.dataset.tooltip

      if (!text) {
        return
      }

      const rect = element.getBoundingClientRect()
      const placement =
        rect.top < 70 ? 'bottom' : 'top'

      setPosition(null)

      setTooltip({
        text,
        targetX: rect.left + rect.width / 2,
        y:
          placement === 'top'
            ? rect.top - 9
            : rect.bottom + 9,
        placement,
      })
    }

    function handleMouseOver(event: MouseEvent) {
      showTooltip(event.target)
    }

    function handleMouseOut(event: MouseEvent) {
      if (!(event.target instanceof Element)) {
        return
      }

      const element = event.target.closest('[data-tooltip]')

      if (!element) {
        return
      }

      const related = event.relatedTarget

      if (
        related instanceof Node &&
        element.contains(related)
      ) {
        return
      }

      setTooltip(null)
      setPosition(null)
    }

    function handleFocusIn(event: FocusEvent) {
      showTooltip(event.target)
    }

    function hideTooltip() {
      setTooltip(null)
      setPosition(null)
    }

    document.addEventListener('mouseover', handleMouseOver)
    document.addEventListener('mouseout', handleMouseOut)
    document.addEventListener('focusin', handleFocusIn)
    document.addEventListener('focusout', hideTooltip)

    window.addEventListener('scroll', hideTooltip, true)
    window.addEventListener('resize', hideTooltip)

    return () => {
      document.removeEventListener('mouseover', handleMouseOver)
      document.removeEventListener('mouseout', handleMouseOut)
      document.removeEventListener('focusin', handleFocusIn)
      document.removeEventListener('focusout', hideTooltip)

      window.removeEventListener('scroll', hideTooltip, true)
      window.removeEventListener('resize', hideTooltip)
    }
  }, [])

  useLayoutEffect(() => {
    if (!tooltip || !tooltipRef.current) {
      return
    }

    const width = tooltipRef.current.offsetWidth
    const padding = 12

    const minX = padding + width / 2
    const maxX = window.innerWidth - padding - width / 2

    const x = Math.min(
      Math.max(tooltip.targetX, minX),
      maxX,
    )

    setPosition({
      x,
      arrowX: tooltip.targetX - x,
    })
  }, [tooltip])

  if (!tooltip) {
    return null
  }

  return (
    <div
      ref={tooltipRef}
      className={`global-tooltip ${tooltip.placement}`}
      style={{
        left: position?.x ?? tooltip.targetX,
        top: tooltip.y,
        visibility: position ? 'visible' : 'hidden',
        '--tooltip-arrow-x': `${
          position?.arrowX ?? 0
        }px`,
      } as Record<string, string | number>}
      role="tooltip"
    >
      {tooltip.text}
    </div>
  )
}


type ApiFinding = {
  id: number
  agent_id: number
  pattern_id: string
  hostname: string
  service: string
  severity: string
  title: string
  detail: string
  suggest: string
  source_line: string
  received_at: number
  status: string
  group_key: string
  first_seen: number | null
  last_seen: number | null
  detection_count: number
  resolved_at: number | null
}

type ApiAgent = {
  id: number
  hostname: string
  enrolled_at: number
  last_seen: number | null
  os_name: string | null
  os_version: string | null
  agent_version: string | null
  machine_type: string | null
  critical_count: number
  warning_count: number
}

type ApiPack = {
  id: string
  name: string
  version: string
  author: string
  description: string
  origin: string
  category: {
    id: string
    label: string
  }
  sources: string[]
  compatibility: Record<string, string>
  rule_count: number
  installed: boolean
  enabled: boolean
  overridden: boolean
  capabilities: {
    edit: boolean
    revert: boolean
    delete: boolean
  }
}

type ApiEvent = {
  id: number
  hostname: string
  source_key: string
  event_time: number
  service: string
  severity: string
  message: string
  metadata: string | null
  received_at: number
}


type ApiRelevantEvent = {
  id: number
  agent_id: number
  hostname: string
  source_key: string
  event_time: number
  pack_id: string
  rule_id: string
  service: string
  severity: string
  title: string
  detail: string
  fields: string
  source_message: string
  received_at: number
}

function findingStatus(severity: string): Status {
  const value = severity.toLowerCase()

  if (value === 'crit' || value === 'critical') {
    return 'critical'
  }

  if (value === 'warn' || value === 'warning') {
    return 'warning'
  }

  return 'unknown'
}

function formatAge(timestamp: number) {
  const seconds = Math.max(
    0,
    Math.floor(Date.now() / 1000) - timestamp,
  )

  if (seconds < 60) {
    return `${seconds}s ago`
  }

  const minutes = Math.floor(seconds / 60)

  if (minutes < 60) {
    return `${minutes}m ago`
  }

  const hours = Math.floor(minutes / 60)

  if (hours < 24) {
    return `${hours}h ago`
  }

  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

const pageInfo: Record<string, { title: string; subtitle: string }> = {
  '/': {
    title: 'Overview',
    subtitle: 'Infrastructure health and recent findings',
  },
  '/systems': {
    title: 'Hosts',
    subtitle: 'Hosts monitored by FERPEK',
  },
  '/findings': {
    title: 'Findings',
    subtitle: 'Detected infrastructure problems',
  },
  '/activity': {
    title: 'Activity',
    subtitle: 'Recent infrastructure events',
  },
  '/packs': {
    title: 'Packs',
    subtitle: 'Detection and interpretation packs',
  },
  '/settings': {
    title: 'Settings',
    subtitle: 'Configure your FERPEK instance',
  },
}

function Sidebar() {
  const [platformVersion, setPlatformVersion] = useState("...")

  useEffect(() => {
    fetch("/health")
      .then((response) => response.json())
      .then((data) => {
        if (data?.version) {
          setPlatformVersion(String(data.version))
        }
      })
      .catch(() => {
        setPlatformVersion("unknown")
      })
  }, [])

  const [hostCount, setHostCount] = useState(0)
  const [findingCount, setFindingCount] = useState(0)
  const [packCount, setPackCount] = useState(0)

  async function loadSidebarCounts() {
    try {
      const [agentsResponse, findingsResponse, packsResponse] =
        await Promise.all([
          fetch('/api/v1/agents'),
          fetch('/api/v1/findings?status=open'),
          fetch('/api/v1/packs'),
        ])

      if (
        !agentsResponse.ok ||
        !findingsResponse.ok ||
        !packsResponse.ok
      ) {
        throw new Error('Could not load sidebar counters')
      }

      const agents: ApiAgent[] = await agentsResponse.json()
      const findings: ApiFinding[] = await findingsResponse.json()
      const packsData = await packsResponse.json()

      setHostCount(agents.length)
      setFindingCount(findings.length)
      setPackCount(
        Array.isArray(packsData?.packs)
          ? packsData.packs.length
          : 0,
      )
    } catch (err) {
      console.error('Could not load sidebar counters:', err)
    }
  }

  useEffect(() => {
    loadSidebarCounts()

    const timer = window.setInterval(loadSidebarCounts, 5000)

    return () => window.clearInterval(timer)
  }, [])

  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">◇</div>

        <div>
          <div className="brand-name">FERPEK</div>
          <div className="brand-subtitle">LENS</div>
        </div>
      </div>

      <nav className="navigation">
        <NavLink
          to="/"
          end
          className={({ isActive }) =>
            `nav-item ${isActive ? 'active' : ''}`
          }
        >
          <span className="nav-icon">⌂</span>
          Overview
        </NavLink>

        <NavLink
          to="/systems"
          className={({ isActive }) =>
            `nav-item ${isActive ? 'active' : ''}`
          }
        >
          <span className="nav-icon">▣</span>
          Hosts

          {hostCount > 0 && (
            <span className="nav-count host-nav-count">
              {hostCount}
            </span>
          )}
        </NavLink>

        <NavLink
          to="/findings"
          className={({ isActive }) =>
            `nav-item ${isActive ? 'active' : ''}`
          }
        >
          <span className="nav-icon">◇</span>
          Findings

          {findingCount > 0 && (
            <span className="nav-count danger">
              {findingCount}
            </span>
          )}
        </NavLink>

        <NavLink
          to="/activity"
          className={({ isActive }) =>
            `nav-item ${isActive ? 'active' : ''}`
          }
        >
          <span className="nav-icon">≡</span>
          Activity
        </NavLink>

        <NavLink
          to="/packs"
          className={({ isActive }) =>
            `nav-item ${isActive ? 'active' : ''}`
          }
        >
          <span className="nav-icon">◇</span>
          Packs

          {packCount > 0 && (
            <span className="nav-count host-nav-count">
              {packCount}
            </span>
          )}
        </NavLink>
      </nav>

      <div className="sidebar-bottom">
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            `nav-item ${isActive ? 'active' : ''}`
          }
        >
          <span className="nav-icon">⚙</span>
          Settings
        </NavLink>

        <div className="version">FERPEK v{platformVersion}</div>
      </div>
    </aside>
  )
}

function Overview() {
  const [agents, setAgents] = useState<ApiAgent[]>([])
  const [apiFindings, setApiFindings] = useState<ApiFinding[]>([])

  async function loadOverview() {
    try {
      const [agentsResponse, findingsResponse] = await Promise.all([
        fetch('/api/v1/agents'),
        fetch('/api/v1/findings?status=open'),
      ])

      if (!agentsResponse.ok || !findingsResponse.ok) {
        throw new Error('Could not load overview data')
      }

      setAgents(await agentsResponse.json())
      setApiFindings(await findingsResponse.json())
    } catch (err) {
      console.error('Could not load overview:', err)
    }
  }

  useEffect(() => {
    loadOverview()

    const timer = window.setInterval(loadOverview, 5000)
    return () => window.clearInterval(timer)
  }, [])

  const criticalCount = apiFindings.filter(
    (finding) => findingStatus(finding.severity) === 'critical',
  ).length

  const warningCount = apiFindings.filter(
    (finding) => findingStatus(finding.severity) === 'warning',
  ).length

  const now = Math.floor(Date.now() / 1000)

  const onlineHosts = agents.filter(
    (agent) =>
      agent.last_seen !== null &&
      now - agent.last_seen <= 60,
  ).length

  const healthyHosts = agents.filter(
    (agent) =>
      agent.last_seen !== null &&
      now - agent.last_seen <= 60 &&
      agent.critical_count === 0 &&
      agent.warning_count === 0,
  ).length

  return (
    <>
      <section className="status-section">
        <div className="section-heading">
          <div>
            <h2>Infrastructure status</h2>
            <p>Current state of monitored hosts</p>
          </div>

          <span className="last-update">Updated automatically</span>
        </div>

        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-label">Hosts</div>
            <div className="stat-value">{agents.length}</div>
            <div className="stat-detail">
              <StatusDiamond
                status={onlineHosts > 0 ? 'healthy' : 'unknown'}
              />
              {onlineHosts} online
            </div>
          </div>

          <div className="stat-card critical-card">
            <div className="stat-label">Critical</div>
            <div className="stat-value">{criticalCount}</div>
            <div className="stat-detail critical-text">
              <StatusDiamond
                status={criticalCount > 0 ? 'critical' : 'healthy'}
              />
              {criticalCount > 0 ? 'Needs attention' : 'No critical findings'}
            </div>
          </div>

          <div className="stat-card">
            <div className="stat-label">Warnings</div>
            <div className="stat-value">{warningCount}</div>
            <div className="stat-detail warning-text">
              <StatusDiamond
                status={warningCount > 0 ? 'warning' : 'healthy'}
              />
              {warningCount > 0 ? 'Open findings' : 'No warnings'}
            </div>
          </div>

          <div className="stat-card">
            <div className="stat-label">Healthy</div>
            <div className="stat-value">{healthyHosts}</div>
            <div className="stat-detail muted">
              Hosts without open findings
            </div>
          </div>
        </div>
      </section>

      <section className="findings-section">
        <div className="section-heading">
          <div>
            <h2>Needs attention</h2>
            <p>Open findings ordered by severity</p>
          </div>

          <NavLink
            className="secondary-button compact-button"
            to="/findings"
          >
            View findings
          </NavLink>
        </div>

        <div className="findings-list">
          {apiFindings.length === 0 ? (
            <div className="panel">
              <div className="empty-state">
                No open findings detected.
              </div>
            </div>
          ) : (
            apiFindings.slice(0, 5).map((finding) => (
              <article className="finding" key={finding.id}>
                <div className="finding-status">
                  <StatusDiamond
                    status={findingStatus(finding.severity)}
                  />
                </div>

                <div className="finding-main">
                  <div className="finding-meta">
                    <span
                      className={`severity ${findingStatus(
                        finding.severity,
                      )}`}
                    >
                      {finding.severity}
                    </span>

                    <span>{finding.hostname}</span>
                    <span className="separator">/</span>
                    <span>{finding.service}</span>
                  </div>

                  <h3>{finding.title}</h3>
                  <p>{finding.detail}</p>
                </div>

                <div className="finding-side">
                  <span>
                  {formatAge(
                    finding.last_seen ?? finding.received_at,
                  )}
                </span>
                  <NavLink to="/findings">Investigate →</NavLink>
                </div>
              </article>
            ))
          )}
        </div>
      </section>

      <section className="bottom-grid">
        <div className="panel">
          <div className="panel-header">
            <div>
              <h2>Hosts</h2>
              <p>Monitored infrastructure</p>
            </div>

            <NavLink className="text-button" to="/systems">
              View hosts →
            </NavLink>
          </div>

          {agents.length === 0 ? (
            <div className="empty-state">
              No hosts enrolled.
            </div>
          ) : (
            agents.slice(0, 5).map((agent) => (
              <div className="system-row" key={agent.id}>
                <StatusDiamond
                  status={
                    agent.critical_count > 0
                      ? 'critical'
                      : agent.warning_count > 0
                        ? 'warning'
                        : agent.last_seen &&
                            now - agent.last_seen <= 60
                          ? 'healthy'
                          : 'unknown'
                  }
                />

                <div className="system-info">
                  <strong>{agent.hostname}</strong>
                  <span>
                    {agent.os_name || 'Operating system unknown'}{agent.os_version ? ` ${agent.os_version}` : ''}
                  </span>
                </div>

                <div className="system-findings">
                  {agent.critical_count > 0 && (
                    <span className="critical-text">
                      {agent.critical_count} critical
                    </span>
                  )}

                  {agent.warning_count > 0 && (
                    <span>
                      {agent.warning_count} warnings
                    </span>
                  )}

                  {agent.critical_count === 0 &&
                    agent.warning_count === 0 && (
                      <span>No open findings</span>
                    )}
                </div>
              </div>
            ))
          )}
        </div>

        <div className="panel">
          <div className="panel-header">
            <div>
              <h2>Recent activity</h2>
              <p>Latest detected findings</p>
            </div>
          </div>

          {apiFindings.length === 0 ? (
            <div className="empty-state">
              No recent findings.
            </div>
          ) : (
            apiFindings.slice(0, 3).map((finding) => (
              <div className="activity-row" key={finding.id}>
                <StatusDiamond
                  status={findingStatus(finding.severity)}
                />

                <div>
                  <strong>{finding.title}</strong>
                  <span>
                    {finding.hostname} · {finding.service}
                  </span>
                </div>

                <time>{formatAge(finding.received_at)}</time>
              </div>
            ))
          )}
        </div>
      </section>
    </>
  )
}

function Systems() {
  const navigate = useNavigate()

  type Agent = {
    id: number
    hostname: string
    enrolled_at: number
    last_seen: number | null
    os_name: string | null
    os_version: string | null
    agent_version: string | null
    machine_type: string | null
    critical_count: number
    warning_count: number
  }

  type EnrolledAgent = {
    id: number
    hostname: string
    os_name: string | null
    os_version: string | null
    agent_version: string | null
    last_seen: number | null
  }

  type LogSource = {
    id: number
    agent_id: number
    source_key: string
    name: string
    source_type: string
    path: string
    unit: string
    enabled: boolean
    send_events: boolean
    discovered: boolean
  }

  const [agents, setAgents] = useState<Agent[]>([])
  const [showAddHost, setShowAddHost] = useState(false)
  const [enrollmentToken, setEnrollmentToken] = useState('')
  const [expiresIn, setExpiresIn] = useState(0)
  const [enrollmentStatus, setEnrollmentStatus] = useState<
    'waiting' | 'enrolled' | 'expired' | 'used'
  >('waiting')
  const [enrolledAgent, setEnrolledAgent] =
    useState<EnrolledAgent | null>(null)

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  const [hostToDelete, setHostToDelete] = useState<Agent | null>(null)
  const [deletingHost, setDeletingHost] = useState(false)
  const [deleteError, setDeleteError] = useState('')

  const [sourcesHost, setSourcesHost] = useState<Agent | null>(null)
  const [logSources, setLogSources] = useState<LogSource[]>([])
  const [sourcesLoading] = useState(false)
  const [sourcesError, setSourcesError] = useState('')
  const [updatingSource, setUpdatingSource] = useState<string | null>(null)

  async function loadAgents() {
    try {
      const response = await fetch('/api/v1/agents')

      if (!response.ok) {
        throw new Error(`Server returned ${response.status}`)
      }

      const data = await response.json()
      setAgents(data)
    } catch (err) {
      console.error('Could not load hosts:', err)
    }
  }

  useEffect(() => {
    loadAgents()

    const timer = window.setInterval(loadAgents, 5000)

    return () => window.clearInterval(timer)
  }, [])

  async function createEnrollment() {
    setShowAddHost(true)
    setLoading(true)
    setError('')
    setEnrollmentToken('')
    setEnrollmentStatus('waiting')
    setEnrolledAgent(null)
    setCopied(false)

    try {
      const response = await fetch('/api/v1/enrollment-tokens', {
        method: 'POST',
      })

      if (!response.ok) {
        throw new Error(`Server returned ${response.status}`)
      }

      const data = await response.json()

      setEnrollmentToken(data.token)
      setExpiresIn(data.expires_in)
    } catch (err) {
      console.error(err)
      setError('Could not create an enrollment token.')
    } finally {
      setLoading(false)
    }
  }

  async function copyCommand() {
    const command =
      `curl -fsSL http://${window.location.hostname}:8000/install-agent.sh | ` +
      `sudo bash -s -- --server http://${window.location.hostname}:8000 ` +
      `--token ${enrollmentToken}`

    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(command)
      } else {
        const textarea = document.createElement('textarea')
        textarea.value = command
        textarea.style.position = 'fixed'
        textarea.style.opacity = '0'

        document.body.appendChild(textarea)
        textarea.focus()
        textarea.select()

        const success = document.execCommand('copy')

        document.body.removeChild(textarea)

        if (!success) {
          throw new Error('Copy command failed')
        }
      }

      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch (err) {
      console.error('Could not copy command:', err)
      setError('Could not copy the install command.')
    }
  }

  useEffect(() => {
    if (
      !showAddHost ||
      !enrollmentToken ||
      enrollmentStatus !== 'waiting'
    ) {
      return
    }

    let cancelled = false

    async function checkEnrollment() {
      try {
        const response = await fetch(
          '/api/v1/enrollment-tokens/status',
          {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({
              token: enrollmentToken,
            }),
          },
        )

        if (!response.ok) {
          throw new Error(`Server returned ${response.status}`)
        }

        const data = await response.json()

        if (cancelled) {
          return
        }

        if (data.status === 'enrolled') {
          setEnrollmentStatus('enrolled')
          setEnrolledAgent(data.agent)
          await loadAgents()
          return
        }

        if (data.status === 'used') {
          setEnrollmentStatus('used')
          setExpiresIn(0)
          return
        }

        if (data.status === 'expired') {
          setEnrollmentStatus('expired')
          setExpiresIn(0)
          return
        }

        if (typeof data.expires_in === 'number') {
          setExpiresIn(data.expires_in)
        }
      } catch (err) {
        console.error('Enrollment status check failed:', err)
      }
    }

    checkEnrollment()

    const timer = window.setInterval(checkEnrollment, 2000)

    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [showAddHost, enrollmentToken, enrollmentStatus])

  useEffect(() => {
    if (
      !showAddHost ||
      enrollmentStatus !== 'waiting' ||
      expiresIn <= 0
    ) {
      return
    }

    const timer = window.setInterval(() => {
      setExpiresIn((current) => Math.max(0, current - 1))
    }, 1000)

    return () => window.clearInterval(timer)
  }, [showAddHost, enrollmentStatus, expiresIn])

  const minutes = Math.floor(expiresIn / 60)
  const seconds = expiresIn % 60

  const installCommand = enrollmentToken
    ? `curl -fsSL http://${window.location.hostname}:8000/install-agent.sh | sudo bash -s -- --server http://${window.location.hostname}:8000 --token ${enrollmentToken}`
    : ''

  async function deleteHost() {
    if (!hostToDelete) {
      return
    }

    setDeletingHost(true)
    setDeleteError('')

    try {
      const response = await fetch(`/api/v1/agents/${hostToDelete.id}`, {
        method: 'DELETE',
      })

      if (!response.ok) {
        throw new Error(`Server returned ${response.status}`)
      }

      setHostToDelete(null)
      await loadAgents()
    } catch (err) {
      console.error(err)
      setDeleteError('Could not delete the host.')
    } finally {
      setDeletingHost(false)
    }
  }

  async function updateLogSource(
    source: LogSource,
    field: 'enabled' | 'send_events',
    value: boolean,
  ) {
    if (!sourcesHost) {
      return
    }

    setUpdatingSource(source.source_key)
    setSourcesError('')

    let enabled = source.enabled
    let sendEvents = source.send_events

    if (field === 'enabled') {
      enabled = value

      if (!value) {
        sendEvents = false
      }
    }

    if (field === 'send_events') {
      sendEvents = value

      if (value) {
        enabled = true
      }
    }

    const params = new URLSearchParams()

    params.set('enabled', String(enabled))
    params.set('send_events', String(sendEvents))

    try {
      const response = await fetch(
        `/api/v1/agents/${sourcesHost.id}/sources/${encodeURIComponent(
          source.source_key,
        )}?${params.toString()}`,
        {
          method: 'PATCH',
        },
      )

      if (!response.ok) {
        throw new Error(`Server returned ${response.status}`)
      }

      setLogSources((current) =>
        current.map((item) =>
          item.source_key === source.source_key
            ? {
                ...item,
                enabled,
                send_events: sendEvents,
              }
            : item,
        ),
      )
    } catch (err) {
      console.error('Could not update source:', err)
      setSourcesError('Could not update log source.')
    } finally {
      setUpdatingSource(null)
    }
  }

  function agentStatus(agent: Agent): Status {
    if (agent.critical_count > 0) {
      return 'critical'
    }

    if (agent.warning_count > 0) {
      return 'warning'
    }

    if (!agent.last_seen) {
      return 'unknown'
    }

    const now = Math.floor(Date.now() / 1000)

    if (now - agent.last_seen > 60) {
      return 'unknown'
    }

    return 'healthy'
  }

  function closeModal() {
    setShowAddHost(false)
    setEnrollmentToken('')
    setEnrolledAgent(null)
    setEnrollmentStatus('waiting')
    setError('')
  }

  return (
    <section>
      <div className="section-heading">
        <div>
          <h2>
            Monitored hosts: {agents.length}
          </h2>
          <p>Physical machines and virtual machines monitored by FERPEK</p>
        </div>

        <button className="primary-button" onClick={createEnrollment}>
          + Add host
        </button>
      </div>

      <div className="panel">
        {agents.length === 0 ? (
          <div className="empty-state">
            No hosts have been enrolled yet.
          </div>
        ) : (
          agents.map((agent) => (
            <div className="system-row large-row" key={agent.id}>
              <StatusDiamond status={agentStatus(agent)} />

              <div className="system-info">
                <div className="host-title-line">
                  <strong>{agent.hostname}</strong>

                  <span className="host-inline-meta">
                    <span>
                      {agent.os_name || 'Operating system unknown'}
                    </span>

                    {agent.machine_type && (
                      <>
                        <span className="host-meta-divider">/</span>
                        <span>
                          {agent.machine_type
                            .replace('virtual:', '')
                            .toUpperCase()}
                        </span>
                      </>
                    )}

                    {agent.agent_version && (
                      <>
                        <span className="host-meta-divider">/</span>
                        <span>Agent v{agent.agent_version}</span>
                      </>
                    )}
                  </span>
                </div>
              </div>

              <div className="system-findings">
                {agent.critical_count > 0 && (
                  <span className="critical-text">
                    {agent.critical_count} critical
                  </span>
                )}

                {agent.warning_count > 0 && (
                  <span>
                    {agent.warning_count}{' '}
                    {agent.warning_count === 1 ? 'warning' : 'warnings'}
                  </span>
                )}

                {agent.critical_count === 0 &&
                  agent.warning_count === 0 && (
                    <span>No open findings</span>
                  )}
                <div className="host-actions">
                  <button
                    className="host-icon-button tooltip"
                    data-tooltip="View host"
                    aria-label={`View ${agent.hostname}`}
                    onClick={() => navigate(`/systems/${agent.id}`)}
                  >
                    👁
                  </button>

                  <button
                    className="host-icon-button danger tooltip"
                    data-tooltip="Delete host"
                    aria-label={`Delete ${agent.hostname}`}
                    onClick={() => {
                      setDeleteError('')
                      setHostToDelete(agent)
                    }}
                  >
                    <svg
                      className="delete-icon"
                      viewBox="0 0 24 24"
                      aria-hidden="true"
                    >
                      <path d="M4 7h16" />
                      <path d="M9 7V4h6v3" />
                      <path d="M6.5 7l1 13h9l1-13" />
                      <path d="M10 11v5" />
                      <path d="M14 11v5" />
                    </svg>
                  </button>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
      {sourcesHost && (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              setSourcesHost(null)
            }
          }}
        >
          <div className="modal sources-modal">
            <div className="modal-header">
              <div>
                <h2>Log sources</h2>
                <p>
                  Configure monitoring for {sourcesHost.hostname}.
                </p>
              </div>

              <button
                className="modal-close"
                onClick={() => setSourcesHost(null)}
              >
                ×
              </button>
            </div>

            <div className="sources-explanation">
              <p>
                <strong>Monitor</strong> allows FERPEK to analyse this
                source and generate findings.
              </p>
              <p>
                <strong>Log Explorer</strong> also sends matching events
                to the FERPEK Server for inspection.
              </p>
            </div>

            {sourcesLoading && (
              <div className="enrollment-state">
                <StatusDiamond status="unknown" />
                Loading log sources...
              </div>
            )}

            {sourcesError && (
              <div className="modal-error">{sourcesError}</div>
            )}

            {!sourcesLoading && logSources.length > 0 && (
              <div className="sources-table">
                <div className="sources-table-header">
                  <span>Source</span>
                  <span>Monitor</span>
                  <span>Log Explorer</span>
                </div>

                {logSources.map((source) => (
                  <div
                    className="source-row"
                    key={source.source_key}
                  >
                    <div className="source-description">
                      <div>
                        <strong>{source.name}</strong>

                        {source.discovered && (
                          <span className="source-badge">
                            Discovered
                          </span>
                        )}
                      </div>

                      <span>
                        {source.source_type === 'file' && source.path
                          ? source.path
                          : source.source_key}
                      </span>
                    </div>

                    <label className="toggle">
                      <input
                        type="checkbox"
                        checked={source.enabled}
                        disabled={
                          updatingSource === source.source_key
                        }
                        onChange={(event) =>
                          updateLogSource(
                            source,
                            'enabled',
                            event.target.checked,
                          )
                        }
                      />

                      <span className="toggle-track">
                        <span className="toggle-knob" />
                      </span>
                    </label>

                    <label className="toggle">
                      <input
                        type="checkbox"
                        checked={source.send_events}
                        disabled={
                          updatingSource === source.source_key
                        }
                        onChange={(event) =>
                          updateLogSource(
                            source,
                            'send_events',
                            event.target.checked,
                          )
                        }
                      />

                      <span className="toggle-track">
                        <span className="toggle-knob" />
                      </span>
                    </label>
                  </div>
                ))}
              </div>
            )}

            <div className="sources-note">
              Configuration changes are picked up automatically by the
              FERPEK Agent.
            </div>
          </div>
        </div>
      )}

      {hostToDelete && (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !deletingHost) {
              setHostToDelete(null)
            }
          }}
        >
          <div className="modal delete-host-modal">
            <div className="modal-header">
              <div>
                <h2>Delete host?</h2>
                <p>{hostToDelete.hostname}</p>
              </div>

              <button
                className="modal-close"
                disabled={deletingHost}
                onClick={() => setHostToDelete(null)}
              >
                ×
              </button>
            </div>

            <div className="pack-edit-warning">
              <strong>This host will be removed</strong>

              <p>
                This will permanently remove the host and all associated
                findings, events and log sources from FERPEK.
              </p>

              <p className="pack-edit-validation">
                The FERPEK Agent installed on the host will not be
                uninstalled.
              </p>
            </div>

            {deleteError && (
              <div className="modal-error pack-editor-feedback">
                {deleteError}
              </div>
            )}

            <div className="modal-actions">
              <button
                className="secondary-button"
                disabled={deletingHost}
                onClick={() => setHostToDelete(null)}
              >
                Cancel
              </button>

              <button
                className="danger-button"
                disabled={deletingHost}
                onClick={deleteHost}
              >
                {deletingHost ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}

      {showAddHost && (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              closeModal()
            }
          }}
        >
          <div className="modal">
            <div className="modal-header">
              <div>
                <h2>Add host</h2>
                <p>Install FERPEK Agent on a Linux host.</p>
              </div>

              <button className="modal-close" onClick={closeModal}>
                ×
              </button>
            </div>

            <div className="platform-row">
              <div className="platform-icon">◇</div>

              <div>
                <strong>Linux</strong>
                <span>Debian, Ubuntu and other Linux distributions</span>
              </div>
            </div>

            {loading && (
              <div className="enrollment-state">
                <StatusDiamond status="unknown" />
                Generating secure enrollment token...
              </div>
            )}

            {error && <div className="modal-error">{error}</div>}

            {enrollmentToken && enrollmentStatus === 'waiting' && (
              <>
                <div className="install-step">
                  <div className="step-number">1</div>

                  <div>
                    <strong>Run this command on the host</strong>
                    <p>
                      Run as a user with sudo privileges. FERPEK will detect
                      the hostname automatically.
                    </p>
                  </div>
                </div>

                <div className="command-box">
                  <code>{installCommand}</code>

                  <button onClick={copyCommand}>
                    {copied ? 'Copied' : 'Copy'}
                  </button>
                </div>

                <div className="waiting-box">
                  <div>
                    <StatusDiamond status="warning" />
                  </div>

                  <div>
                    <strong>Waiting for agent</strong>
                    <span>
                      Enrollment token expires in{' '}
                      {minutes}:{seconds.toString().padStart(2, '0')}
                    </span>
                  </div>
                </div>

                <div className="modal-note">
                  The enrollment token can only be used once. After
                  enrollment, this host receives its own agent key.
                </div>
              </>
            )}

            {enrollmentToken && enrollmentStatus === 'enrolled' && (
              <>
                <div className="waiting-box enrollment-success">
                  <div>
                    <StatusDiamond status="healthy" />
                  </div>

                  <div>
                    <strong>Host connected</strong>
                    <span>
                      FERPEK Agent enrolled successfully.
                    </span>
                  </div>
                </div>

                {enrolledAgent && (
                  <div className="connected-host">
                    <strong>{enrolledAgent.hostname}</strong>

                    <span>
                      {enrolledAgent.os_name || 'Linux'}
                    </span>

                    {enrolledAgent.agent_version && (
                      <span>
                        FERPEK Agent {enrolledAgent.agent_version}
                      </span>
                    )}
                  </div>
                )}

                <div className="modal-actions">
                  <button
                    className="primary-button"
                    onClick={closeModal}
                  >
                    Done
                  </button>
                </div>
              </>
            )}

            {enrollmentToken && enrollmentStatus === 'used' && (
              <>
                <div className="waiting-box">
                  <div>
                    <StatusDiamond status="unknown" />
                  </div>

                  <div>
                    <strong>Enrollment token already used</strong>
                    <span>
                      This token cannot be used to enroll another host.
                    </span>
                  </div>
                </div>

                <div className="modal-actions">
                  <button
                    className="primary-button"
                    onClick={createEnrollment}
                  >
                    Generate new token
                  </button>
                </div>
              </>
            )}

            {enrollmentToken && enrollmentStatus === 'expired' && (
              <>
                <div className="waiting-box">
                  <div>
                    <StatusDiamond status="unknown" />
                  </div>

                  <div>
                    <strong>Enrollment token expired</strong>
                    <span>
                      Generate a new token to add this host.
                    </span>
                  </div>
                </div>

                <div className="modal-actions">
                  <button
                    className="primary-button"
                    onClick={createEnrollment}
                  >
                    Generate new token
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </section>
  )
}



function HostDetail() {
  type HostTab = 'overview' | 'logs' | 'findings' | 'sources'
  type LogMode = 'relevant' | 'raw'

  type LogSource = {
    id: number
    agent_id: number
    source_key: string
    name: string
    source_type: string
    path: string
    unit: string
    enabled: boolean
    send_events: boolean
    discovered: boolean
  }

  const sourceGroups = [
    {
      id: 'authentication',
      name: 'Authentication',
      description: 'Login, SSH, sudo and authentication activity.',
      members: ['authentication', 'auth-file'],
    },
    {
      id: 'system-logs',
      name: 'System logs',
      description: 'General operating system logging.',
      members: ['journal-system', 'syslog-file'],
    },
    {
      id: 'system-services',
      name: 'System services',
      description: 'Focused operating system event streams.',
      members: ['kernel', 'cron', 'service-errors'],
    },
    {
      id: 'mail',
      name: 'Mail',
      description: 'Mail transport and delivery logs.',
      members: ['mail-file'],
    },
    {
      id: 'web',
      name: 'Web servers',
      description: 'HTTP access and error logs.',
      members: [
        'apache-access',
        'apache-error',
        'nginx-access',
        'nginx-error',
      ],
    },
    {
      id: 'security',
      name: 'Security',
      description: 'Security and protection services.',
      members: ['fail2ban'],
    },
  ]

  const sourceAlternatives = [
    {
      preferred: 'authentication',
      alternative: 'auth-file',
    },
    {
      preferred: 'journal-system',
      alternative: 'syslog-file',
    },
  ]

  function sourceRole(sourceKey: string) {
    const preferred = sourceAlternatives.find(
      (item) => item.preferred === sourceKey,
    )

    if (preferred) {
      return 'Preferred'
    }

    const alternative = sourceAlternatives.find(
      (item) => item.alternative === sourceKey,
    )

    if (alternative) {
      return 'Alternative'
    }

    return null
  }

  function sourceHasConflict(sourceKey: string) {
    const pair = sourceAlternatives.find(
      (item) =>
        item.preferred === sourceKey ||
        item.alternative === sourceKey,
    )

    if (!pair) {
      return false
    }

    const preferred = sourceDrafts.find(
      (source) => source.source_key === pair.preferred,
    )

    const alternative = sourceDrafts.find(
      (source) => source.source_key === pair.alternative,
    )

    return Boolean(
      preferred?.enabled &&
      alternative?.enabled,
    )
  }

  const { id } = useParams()
  const navigate = useNavigate()

  const agentId = Number(id)

  const [agent, setAgent] = useState<ApiAgent | null>(null)
  const [events, setEvents] = useState<ApiEvent[]>([])
  const [relevantApiEvents, setRelevantApiEvents] = useState<ApiRelevantEvent[]>([])
  const [findings, setFindings] = useState<ApiFinding[]>([])
  const [sources, setSources] = useState<LogSource[]>([])
  const [sourceDrafts, setSourceDrafts] = useState<LogSource[]>([])
  const [sourcesDirty, setSourcesDirty] = useState(false)
  const [savingSources, setSavingSources] = useState(false)
  const [sourcesSaveMessage, setSourcesSaveMessage] = useState('')
  const [sourcesSaveError, setSourcesSaveError] = useState('')

  const [activeTab, setActiveTab] = useState<HostTab>('overview')
  const [logMode, setLogMode] = useState<LogMode>('relevant')
  const [selectedSource, setSelectedSource] = useState<string>('all')

  const [loading, setLoading] = useState(true)

  async function loadHostData() {
    try {
      const [
        agentsResponse,
        eventsResponse,
        relevantResponse,
        findingsResponse,
        sourcesResponse,
      ] = await Promise.all([
        fetch('/api/v1/agents'),
        fetch(`/api/v1/events?agent_id=${agentId}&limit=200`),
        fetch(`/api/v1/relevant?agent_id=${agentId}&limit=200`),
        fetch('/api/v1/findings?limit=200'),
        fetch(`/api/v1/agents/${agentId}/sources`),
      ])

      if (!agentsResponse.ok) {
        throw new Error(`Agents returned ${agentsResponse.status}`)
      }

      if (!eventsResponse.ok) {
        throw new Error(`Events returned ${eventsResponse.status}`)
      }

      if (!relevantResponse.ok) {
        throw new Error(`Relevant returned ${relevantResponse.status}`)
      }

      if (!findingsResponse.ok) {
        throw new Error(`Findings returned ${findingsResponse.status}`)
      }

      if (!sourcesResponse.ok) {
        throw new Error(`Sources returned ${sourcesResponse.status}`)
      }

      const agentsData: ApiAgent[] = await agentsResponse.json()
      const currentAgent =
        agentsData.find((item) => item.id === agentId) ?? null

      const eventsData: ApiEvent[] = await eventsResponse.json()
      const relevantData: ApiRelevantEvent[] = await relevantResponse.json()
      const findingsData: ApiFinding[] = await findingsResponse.json()
      const sourcesData: LogSource[] = await sourcesResponse.json()

      setAgent(currentAgent)
      setEvents(eventsData)
      setRelevantApiEvents(relevantData)
      setSources(sourcesData)

      setSourceDrafts((current) =>
        current.length === 0 ? sourcesData : current,
      )

      if (currentAgent) {
        setFindings(
          findingsData.filter(
            (finding) => finding.hostname === currentAgent.hostname,
          ),
        )
      } else {
        setFindings([])
      }
    } catch (err) {
      console.error('Could not load host details:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadHostData()

    const timer = window.setInterval(loadHostData, 3000)

    return () => window.clearInterval(timer)
  }, [agentId])

  function changeSourceDraft(
    sourceKey: string,
    field: 'enabled' | 'send_events',
    value: boolean,
  ) {
    setSourceDrafts((current) =>
      current.map((source) => {
        if (source.source_key !== sourceKey) {
          return source
        }

        let enabled = source.enabled
        let sendEvents = source.send_events

        if (field === 'enabled') {
          enabled = value

          if (!value) {
            sendEvents = false
          }
        }

        if (field === 'send_events') {
          sendEvents = value

          if (value) {
            enabled = true
          }
        }

        return {
          ...source,
          enabled,
          send_events: sendEvents,
        }
      }),
    )

    setSourcesDirty(true)
    setSourcesSaveMessage('')
    setSourcesSaveError('')
  }

  async function saveSourceChanges() {
    const changed = sourceDrafts.filter((draft) => {
      const original = sources.find(
        (source) => source.source_key === draft.source_key,
      )

      return (
        original &&
        (
          original.enabled !== draft.enabled ||
          original.send_events !== draft.send_events
        )
      )
    })

    if (changed.length === 0) {
      setSourcesDirty(false)
      setSourcesSaveMessage('No changes to save.')
      return
    }

    setSavingSources(true)
    setSourcesSaveMessage('')
    setSourcesSaveError('')

    try {
      for (const source of changed) {
        const params = new URLSearchParams()

        params.set('enabled', String(source.enabled))
        params.set('send_events', String(source.send_events))

        const response = await fetch(
          `/api/v1/agents/${agentId}/sources/${encodeURIComponent(
            source.source_key,
          )}?${params.toString()}`,
          {
            method: 'PATCH',
          },
        )

        if (!response.ok) {
          throw new Error(
            `${source.name} returned ${response.status}`,
          )
        }
      }

      setSources(sourceDrafts)
      setSourcesDirty(false)
      setSourcesSaveMessage('Changes saved.')
    } catch (err) {
      console.error('Could not save source changes:', err)
      setSourcesSaveError(
        'Could not save all source changes.',
      )
    } finally {
      setSavingSources(false)
    }
  }

  if (loading && !agent) {
    return (
      <section>
        <div className="panel">
          <div className="empty-state">Loading host...</div>
        </div>
      </section>
    )
  }

  if (!agent) {
    return (
      <section>
        <div className="panel">
          <div className="empty-state">Host not found.</div>
        </div>
      </section>
    )
  }

  const now = Math.floor(Date.now() / 1000)
  const online = Boolean(
    agent.last_seen && now - agent.last_seen <= 60,
  )

  const hostSources = sources.filter((source) => source.enabled)

  const sourceEvents = events.filter((event) => {
    if (
      selectedSource !== 'all' &&
      event.source_key !== selectedSource
    ) {
      return false
    }

    return true
  })

  const relevantEvents = relevantApiEvents.filter((event) => {
    if (
      selectedSource !== 'all' &&
      event.source_key !== selectedSource
    ) {
      return false
    }

    return true
  })

  const openFindings = findings.filter(
    (finding) => finding.status === 'open',
  )

  return (
    <section className="host-detail">
      <button
        className="host-back-button"
        onClick={() => navigate('/systems')}
      >
        ← Hosts
      </button>

      <div className="host-detail-header">
        <div className="host-identity">
          <div className="host-title-line">
            <StatusDiamond status={online ? 'healthy' : 'unknown'} />
            <h2>{agent.hostname}</h2>
          </div>

          <div className="host-detail-meta">
            <span className="host-meta-pill">
              {agent.os_name || 'Operating system unknown'}
            </span>

            {agent.machine_type && (
              <span className="host-meta-pill">
                {agent.machine_type
                  .replace('virtual:', '')
                  .toUpperCase()}
              </span>
            )}

            {agent.agent_version && (
              <span className="host-meta-pill">
                Agent {agent.agent_version}
              </span>
            )}

            <span
              className={`host-meta-pill host-status-pill ${
                online ? 'online' : 'offline'
              }`}
            >
              <span className="host-status-dot" />
              {online ? 'Online' : 'Offline'}
            </span>
          </div>
        </div>

        <div className="host-summary">
          <div className="host-summary-stat">
            <strong>{openFindings.length}</strong>
            <span>Open findings</span>
          </div>

          <div className="host-summary-stat">
            <strong>{hostSources.length}</strong>
            <span>Monitored sources</span>
          </div>
        </div>
      </div>

      <div className="host-tabs">
        {(['overview', 'logs', 'findings', 'sources'] as const).map(
          (tab) => (
            <button
              key={tab}
              className={`host-tab ${
                activeTab === tab ? 'selected' : ''
              }`}
              onClick={() => setActiveTab(tab)}
            >
              {tab}
            </button>
          ),
        )}
      </div>

      {activeTab === 'overview' && (
        <div className="host-overview-grid">
          <div className="panel">
            <div className="panel-header">
              <div>
                <h2>Host status</h2>
                <p>Current monitoring state</p>
              </div>
            </div>

            <div className="host-property">
              <span>Status</span>
              <strong>{online ? 'Online' : 'Offline'}</strong>
            </div>

            <div className="host-property">
              <span>Operating system</span>
              <strong>{agent.os_name || 'Unknown'}</strong>
            </div>

            <div className="host-property">
              <span>Agent</span>
              <strong>{agent.agent_version || 'Unknown'}</strong>
            </div>

            <div className="host-property">
              <span>Machine</span>
              <strong>{agent.machine_type || 'Unknown'}</strong>
            </div>
          </div>

          <div className="panel">
            <div className="panel-header">
              <div>
                <h2>Monitoring</h2>
                <p>Current FERPEK coverage</p>
              </div>
            </div>

            <div className="host-property">
              <span>Open findings</span>
              <strong>{openFindings.length}</strong>
            </div>

            <div className="host-property">
              <span>Enabled sources</span>
              <strong>{hostSources.length}</strong>
            </div>

            <div className="host-property">
              <span>Recent events</span>
              <strong>{events.length}</strong>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'logs' && (
        <>
          <div className="host-log-toolbar">
            <div className="finding-filter-group">
              <span className="finding-filter-label">View</span>

              <div className="filter-buttons">
                {(['relevant', 'raw'] as const).map((mode) => (
                  <button
                    key={mode}
                    className={`filter-button ${
                      logMode === mode ? 'selected' : ''
                    }`}
                    onClick={() => setLogMode(mode)}
                  >
                    {mode}
                  </button>
                ))}
              </div>
            </div>

            <div className="finding-filter-group">
              <span className="finding-filter-label">Source</span>

              <select
                className="host-source-select"
                value={selectedSource}
                onChange={(event) =>
                  setSelectedSource(event.target.value)
                }
              >
                <option value="all">All sources</option>

                {sources
                  .filter((source) => source.send_events)
                  .map((source) => (
                    <option
                      key={source.source_key}
                      value={source.source_key}
                    >
                      {source.name}
                    </option>
                  ))}
              </select>
            </div>

            <span className="live-indicator">
              <StatusDiamond status="healthy" />
              Live
            </span>
          </div>

          <div className="panel host-log-panel">
            {logMode === 'relevant' ? (
              relevantEvents.length === 0 ? (
                <div className="empty-state">
                  No relevant events right now.
                </div>
              ) : (
                relevantEvents.map((relevant) => (
                  <div
                    className="host-log-row"
                    key={relevant.id}
                  >
                    <StatusDiamond
                      status={findingStatus(relevant.severity)}
                    />

                    <div className="host-log-content">
                      <strong>{relevant.title}</strong>

                      {relevant.detail && (
                        <span>{relevant.detail}</span>
                      )}

                      <span>
                        {relevant.service || relevant.pack_id}
                        {' · '}
                        {relevant.source_key}
                      </span>
                    </div>

                    <time>{formatAge(relevant.event_time)}</time>
                  </div>
                ))
              )
            ) : sourceEvents.length === 0 ? (
              <div className="empty-state">
                No log events received.
              </div>
            ) : (
              sourceEvents.map((event) => (
                <div
                  className="host-log-row raw"
                  key={event.id}
                >
                  <StatusDiamond status="unknown" />

                  <div className="host-log-content">
                    <code>{event.message}</code>

                    <span>
                      {event.source_key}
                      {event.service
                        ? ` · ${event.service}`
                        : ''}
                    </span>
                  </div>

                  <time>{formatAge(event.event_time)}</time>
                </div>
              ))
            )}
          </div>
        </>
      )}

      {activeTab === 'findings' && (
        <div className="findings-list">
          {findings.length === 0 ? (
            <div className="panel">
              <div className="empty-state">
                No findings for this host.
              </div>
            </div>
          ) : (
            findings.map((finding) => (
              <article
                className="finding"
                key={finding.id}
              >
                <div className="finding-status">
                  <StatusDiamond
                    status={findingStatus(finding.severity)}
                  />
                </div>

                <div className="finding-main">
                  <div className="finding-meta">
                    <span
                      className={`severity ${findingStatus(
                        finding.severity,
                      )}`}
                    >
                      {finding.severity}
                    </span>

                    <span>{finding.service}</span>
                    <span className="separator">/</span>
                    <span>{finding.status}</span>
                  </div>

                  <h3>{finding.title}</h3>
                  <p>{finding.detail}</p>
                </div>

                <div className="finding-side">
                  <span>{formatAge(finding.received_at)}</span>
                </div>
              </article>
            ))
          )}
        </div>
      )}

      {activeTab === 'sources' && (
        <div className="host-sources-config">
          <div className="host-source-groups">
            {sourceGroups.map((group) => {
              const groupSources = sourceDrafts.filter(
                (source) =>
                  group.members.includes(source.source_key),
              )

              if (groupSources.length === 0) {
                return null
              }

              return (
                <div
                  className="panel host-source-group"
                  key={group.id}
                >
                  <div className="host-source-group-header">
                    <div>
                      <h3>{group.name}</h3>
                      <p>{group.description}</p>
                    </div>

                    <div className="host-source-column-labels">
                      <span>Monitor</span>
                      <span>Log Explorer</span>
                    </div>
                  </div>

                  {groupSources.map((source) => {
                    const role = sourceRole(source.source_key)
                    const conflict = sourceHasConflict(
                      source.source_key,
                    )

                    return (
                      <div
                        className="host-source-config-row"
                        key={source.source_key}
                      >
                        <div className="source-description">
                          <div>
                            <strong>{source.name}</strong>

                            {role && (
                              <span
                                className={`source-role ${
                                  role === 'Preferred'
                                    ? 'preferred'
                                    : 'alternative'
                                }`}
                              >
                                {role}
                              </span>
                            )}

                            {source.discovered && !role && (
                              <span className="source-badge">
                                Discovered
                              </span>
                            )}
                          </div>

                          <span>
                            {source.source_type === 'file' &&
                            source.path
                              ? source.path
                              : source.source_type === 'journal'
                                ? 'Journald'
                                : source.source_key}
                          </span>

                          {conflict && (
                            <span className="source-conflict-warning">
                              Multiple sources in this family are
                              enabled. Duplicate events may be
                              received.
                            </span>
                          )}
                        </div>

                        <label className="toggle">
                          <input
                            type="checkbox"
                            checked={source.enabled}
                            disabled={savingSources}
                            onChange={(event) =>
                              changeSourceDraft(
                                source.source_key,
                                'enabled',
                                event.target.checked,
                              )
                            }
                          />

                          <span className="toggle-track">
                            <span className="toggle-knob" />
                          </span>
                        </label>

                        <label className="toggle">
                          <input
                            type="checkbox"
                            checked={source.send_events}
                            disabled={savingSources}
                            onChange={(event) =>
                              changeSourceDraft(
                                source.source_key,
                                'send_events',
                                event.target.checked,
                              )
                            }
                          />

                          <span className="toggle-track">
                            <span className="toggle-knob" />
                          </span>
                        </label>
                      </div>
                    )
                  })}
                </div>
              )
            })}

            {sourceDrafts.some(
              (source) =>
                !sourceGroups.some((group) =>
                  group.members.includes(source.source_key),
                ),
            ) && (
              <div className="panel host-source-group">
                <div className="host-source-group-header">
                  <div>
                    <h3>Other</h3>
                    <p>Additional discovered log sources.</p>
                  </div>

                  <div className="host-source-column-labels">
                    <span>Monitor</span>
                    <span>Log Explorer</span>
                  </div>
                </div>

                {sourceDrafts
                  .filter(
                    (source) =>
                      !sourceGroups.some((group) =>
                        group.members.includes(
                          source.source_key,
                        ),
                      ),
                  )
                  .map((source) => (
                    <div
                      className="host-source-config-row"
                      key={source.source_key}
                    >
                      <div className="source-description">
                        <div>
                          <strong>{source.name}</strong>

                          {source.discovered && (
                            <span className="source-badge">
                              Discovered
                            </span>
                          )}
                        </div>

                        <span>
                          {source.path ||
                            source.source_key}
                        </span>
                      </div>

                      <label className="toggle">
                        <input
                          type="checkbox"
                          checked={source.enabled}
                          disabled={savingSources}
                          onChange={(event) =>
                            changeSourceDraft(
                              source.source_key,
                              'enabled',
                              event.target.checked,
                            )
                          }
                        />

                        <span className="toggle-track">
                          <span className="toggle-knob" />
                        </span>
                      </label>

                      <label className="toggle">
                        <input
                          type="checkbox"
                          checked={source.send_events}
                          disabled={savingSources}
                          onChange={(event) =>
                            changeSourceDraft(
                              source.source_key,
                              'send_events',
                              event.target.checked,
                            )
                          }
                        />

                        <span className="toggle-track">
                          <span className="toggle-knob" />
                        </span>
                      </label>
                    </div>
                  ))}
              </div>
            )}
          </div>

          <div className="host-source-savebar">
            <div>
              {sourcesSaveError && (
                <span className="source-save-error">
                  {sourcesSaveError}
                </span>
              )}

              {sourcesSaveMessage && (
                <span className="source-save-success">
                  {sourcesSaveMessage}
                </span>
              )}

              {sourcesDirty &&
                !sourcesSaveError &&
                !sourcesSaveMessage && (
                  <span className="source-save-pending">
                    Unsaved changes
                  </span>
                )}
            </div>

            <button
              className="primary-button"
              disabled={!sourcesDirty || savingSources}
              onClick={saveSourceChanges}
            >
              {savingSources ? 'Saving...' : 'Save changes'}
            </button>
          </div>
        </div>
      )}

    </section>
  )
}


function Findings() {
  const [filter, setFilter] =
    useState<'all' | Status>('all')

  const [statusFilter, setStatusFilter] =
    useState<'open' | 'resolved' | 'all'>('open')

  const [apiFindings, setApiFindings] =
    useState<ApiFinding[]>([])

  const [resolvingFinding, setResolvingFinding] =
    useState<number | null>(null)

  async function loadFindings() {
    try {
      const url =
        statusFilter === 'all'
          ? '/api/v1/findings'
          : `/api/v1/findings?status=${statusFilter}`

      const response = await fetch(url)

      if (!response.ok) {
        throw new Error(
          `Server returned ${response.status}`,
        )
      }

      setApiFindings(await response.json())
    } catch (err) {
      console.error(
        'Could not load findings:',
        err,
      )
    }
  }

  useEffect(() => {
    void loadFindings()

    const timer = window.setInterval(
      loadFindings,
      5000,
    )

    return () => window.clearInterval(timer)
  }, [statusFilter])

  async function resolveFinding(
    findingId: number,
  ) {
    setResolvingFinding(findingId)

    try {
      const response = await fetch(
        `/api/v1/findings/${findingId}/resolve`,
        {
          method: 'POST',
        },
      )

      if (!response.ok) {
        throw new Error(
          `Server returned ${response.status}`,
        )
      }

      await loadFindings()
    } catch (err) {
      console.error(
        'Could not resolve finding:',
        err,
      )
    } finally {
      setResolvingFinding(null)
    }
  }

  const visibleFindings =
    filter === 'all'
      ? apiFindings
      : apiFindings.filter(
          (finding) =>
            findingStatus(finding.severity) ===
            filter,
        )

  const findingGroups = Array.from(
    visibleFindings.reduce(
      (groups, finding) => {
        const current =
          groups.get(finding.pattern_id) ?? []

        current.push(finding)
        groups.set(finding.pattern_id, current)

        return groups
      },
      new Map<string, ApiFinding[]>(),
    ),
  )
    .map(([patternId, findings]) => {
      const sorted = [...findings].sort(
        (a, b) =>
          (b.last_seen ?? b.received_at) -
          (a.last_seen ?? a.received_at),
      )

      const hostCount = new Set(
        sorted.map((finding) => finding.agent_id),
      ).size

      const severity: Status =
        sorted.some(
          (finding) =>
            findingStatus(finding.severity) ===
            'critical',
        )
          ? 'critical'
          : sorted.some(
                (finding) =>
                  findingStatus(
                    finding.severity,
                  ) === 'warning',
              )
            ? 'warning'
            : 'unknown'

      return {
        patternId,
        findings: sorted,
        hostCount,
        severity,
        latest:
          sorted[0]?.last_seen ??
          sorted[0]?.received_at ??
          0,
      }
    })
    .sort((a, b) => b.latest - a.latest)

  return (
    <section>
      <div className="section-heading">
        <div>
          <h2>Findings</h2>
          <p>
            Significant patterns detected across
            your infrastructure
          </p>
        </div>

        <div className="finding-toolbar">
          <div className="finding-filter-group">
            <span className="finding-filter-label">
              Status
            </span>

            <div className="filter-buttons">
              {(
                [
                  'open',
                  'resolved',
                  'all',
                ] as const
              ).map((value) => (
                <button
                  key={value}
                  className={`filter-button ${
                    statusFilter === value
                      ? 'selected'
                      : ''
                  }`}
                  onClick={() =>
                    setStatusFilter(value)
                  }
                >
                  {value}
                </button>
              ))}
            </div>
          </div>

          <div className="finding-filter-group">
            <span className="finding-filter-label">
              Severity
            </span>

            <div className="filter-buttons">
              {(
                [
                  'all',
                  'critical',
                  'warning',
                ] as const
              ).map((value) => (
                <button
                  key={value}
                  className={`filter-button ${
                    filter === value
                      ? 'selected'
                      : ''
                  }`}
                  onClick={() =>
                    setFilter(value)
                  }
                >
                  {value}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="finding-groups">
        {findingGroups.length === 0 ? (
          <div className="panel">
            <div className="empty-state">
              No findings detected.
            </div>
          </div>
        ) : (
          findingGroups.map((group) => {
            const representative =
              group.findings[0]

            return (
              <article
                className="panel finding-group"
                key={group.patternId}
              >
                <div className="finding-group-header">
                  <StatusDiamond
                    status={group.severity}
                  />

                  <div className="finding-group-heading">
                    <div className="finding-group-title">
                      <h3>
                        {representative.title}
                      </h3>

                      <span className="finding-group-service">
                        {representative.service}
                      </span>
                    </div>

                    <div className="finding-group-summary">
                      <span>
                        {group.hostCount}{' '}
                        {group.hostCount === 1
                          ? 'host'
                          : 'hosts'}
                      </span>

                      <span className="separator">
                        ·
                      </span>

                      <span>
                        {group.findings.length}{' '}
                        {group.findings.length === 1
                          ? 'finding'
                          : 'findings'}
                      </span>

                      <span className="separator">
                        ·
                      </span>

                      <span>
                        Last seen{' '}
                        {formatAge(group.latest)}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="finding-group-hosts">
                  {group.findings.map(
                    (finding) => (
                      <div
                        className="finding-host-row"
                        key={finding.id}
                      >
                        <div className="finding-host-main">
                          <div className="finding-host-meta">
                            <strong>
                              {finding.hostname}
                            </strong>

                            <span
                              className={`severity ${findingStatus(
                                finding.severity,
                              )}`}
                            >
                              {finding.severity}
                            </span>
                          </div>

                          <p>{finding.detail}</p>

                          <div className="finding-stats">
                            <span>
                              <strong>
                                First seen
                              </strong>
                              {finding.first_seen
                                ? formatAge(
                                    finding.first_seen,
                                  )
                                : '—'}
                            </span>

                            <span>
                              <strong>
                                Last seen
                              </strong>
                              {finding.last_seen
                                ? formatAge(
                                    finding.last_seen,
                                  )
                                : '—'}
                            </span>

                            <span>
                              <strong>
                                Detections
                              </strong>
                              {finding.detection_count ??
                                1}
                            </span>
                          </div>

                          {finding.suggest && (
                            <div className="suggestion">
                              <span>
                                Suggested action
                              </span>
                              {finding.suggest}
                            </div>
                          )}
                        </div>

                        <div className="finding-host-side">
                          {finding.status ===
                            'open' && (
                            <button
                              className="resolve-button"
                              disabled={
                                resolvingFinding ===
                                finding.id
                              }
                              onClick={() =>
                                void resolveFinding(
                                  finding.id,
                                )
                              }
                            >
                              {resolvingFinding ===
                              finding.id
                                ? 'Resolving...'
                                : 'Resolve'}
                            </button>
                          )}
                        </div>
                      </div>
                    ),
                  )}
                </div>
              </article>
            )
          })
        )}
      </div>
    </section>
  )
}


function Activity() {
  const [events, setEvents] = useState<ApiRelevantEvent[]>([])

  async function loadEvents() {
    try {
      const response = await fetch('/api/v1/relevant?limit=100')

      if (!response.ok) {
        throw new Error(`Server returned ${response.status}`)
      }

      setEvents(await response.json())
    } catch (err) {
      console.error('Could not load activity:', err)
    }
  }

  useEffect(() => {
    loadEvents()

    const timer = window.setInterval(loadEvents, 5000)
    return () => window.clearInterval(timer)
  }, [])

  return (
    <section>
      <div className="section-heading">
        <div>
          <h2>Recent activity</h2>
          <p>Relevant events detected across monitored hosts</p>
        </div>
      </div>

      <div className="panel">
        {events.length === 0 ? (
          <div className="empty-state">
            No recent activity.
          </div>
        ) : (
          events.map((event) => (
            <div className="activity-row" key={event.id}>
              <StatusDiamond
                status={findingStatus(event.severity)}
              />

              <div>
                <strong>{event.title}</strong>

                {event.detail && (
                  <span>{event.detail}</span>
                )}

                <span>
                  {event.hostname}
                  {' · '}
                  {event.source_key}
                  {' · '}
                  {event.pack_id}
                </span>
              </div>

              <time>{formatAge(event.event_time)}</time>
            </div>
          ))
        )}
      </div>
    </section>
  )
}

function Packs() {
  const [packs, setPacks] = useState<ApiPack[]>([])
  const [loading, setLoading] = useState(true)
  const [packSearch, setPackSearch] = useState("")

  const [viewPack, setViewPack] = useState<ApiPack | null>(null)
  const [editPackWarning, setEditPackWarning] = useState<ApiPack | null>(null)
  const [editPack, setEditPack] = useState<ApiPack | null>(null)
  const [editPackFiles, setEditPackFiles] = useState<string[]>([])
  const [editPackContents, setEditPackContents] = useState<Record<string, string>>({})
  const [selectedEditFile, setSelectedEditFile] = useState("")
  const [editPackLoading, setEditPackLoading] = useState(false)
  const [editPackError, setEditPackError] = useState("")
  const [editPackMessage, setEditPackMessage] = useState("")
  const [editPackValidated, setEditPackValidated] = useState(false)
  const [editPackSaving, setEditPackSaving] = useState(false)
  const [packNotice, setPackNotice] = useState("")
  const [packInstallError, setPackInstallError] = useState("")
  const [packInstalling, setPackInstalling] = useState(false)
  const [packStateChanging, setPackStateChanging] = useState<string | null>(null)
  const [revertPack, setRevertPack] = useState<ApiPack | null>(null)
  const [packReverting, setPackReverting] = useState(false)
  const [packRevertError, setPackRevertError] = useState("")
  const [deletePack, setDeletePack] = useState<ApiPack | null>(null)
  const [packDeleting, setPackDeleting] = useState(false)
  const [packDeleteError, setPackDeleteError] = useState("")
  const [packFiles, setPackFiles] = useState<string[]>([])
  const [selectedPackFile, setSelectedPackFile] = useState("")
  const [packFileContent, setPackFileContent] = useState("")
  const [packViewLoading, setPackViewLoading] = useState(false)
  const [packViewError, setPackViewError] = useState("")

  useEffect(() => {
    async function loadPacks() {
      try {
        const response = await fetch("/api/v1/packs")

        if (!response.ok) {
          throw new Error(
            `HTTP ${response.status}`,
          )
        }

        const data = await response.json()

        setPacks(
          Array.isArray(data?.packs)
            ? data.packs
            : [],
        )
      } catch (error) {
        console.error(
          "Could not load packs:",
          error,
        )
      } finally {
        setLoading(false)
      }
    }

    void loadPacks()
  }, [])

  async function setPackEnabled(
    pack: ApiPack,
    enabled: boolean,
  ) {
    if (packStateChanging) {
      return
    }

    setPackStateChanging(pack.id)
    setPackInstallError("")

    try {
      const response = await fetch(
        `/api/v1/packs/${encodeURIComponent(pack.id)}/state`,
        {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            enabled,
          }),
        },
      )

      if (!response.ok) {
        const text = await response.text()

        throw new Error(
          text || `HTTP ${response.status}`,
        )
      }

      setPacks((current) =>
        current.map((item) =>
          item.id === pack.id
            ? {
                ...item,
                enabled,
              }
            : item,
        ),
      )

      setPackNotice(
        `${pack.name} ${enabled ? "enabled" : "disabled"}.`,
      )

      window.setTimeout(
        () => setPackNotice(""),
        3000,
      )
    } catch (error) {
      setPackInstallError(
        error instanceof Error
          ? error.message
          : "Could not change pack state.",
      )
    } finally {
      setPackStateChanging(null)
    }
  }


  async function installPackFile(
    file: File | null,
    input: HTMLInputElement,
  ) {
    if (!file || packInstalling) {
      return
    }

    setPackInstalling(true)
    setPackInstallError("")
    setPackNotice("")

    try {
      if (!file.name.toLowerCase().endsWith(".pack")) {
        throw new Error("Please select a .pack file.")
      }

      const formData = new FormData()
      formData.append("file", file)

      const response = await fetch(
        "/api/v1/packs/install",
        {
          method: "POST",
          body: formData,
        },
      )

      const contentType =
        response.headers.get("content-type") || ""

      const data = contentType.includes("application/json")
        ? await response.json()
        : null

      if (!response.ok) {
        throw new Error(
          data?.detail ||
            `Could not install pack (HTTP ${response.status}).`,
        )
      }

      const packsResponse = await fetch("/api/v1/packs")

      if (!packsResponse.ok) {
        throw new Error(
          "Pack installed, but the pack list could not be refreshed.",
        )
      }

      const packsData = await packsResponse.json()

      setPacks(
        Array.isArray(packsData?.packs)
          ? packsData.packs
          : [],
      )

      setPackNotice(
        data?.id
          ? `Pack ${data.id} installed successfully.`
          : "Pack installed successfully.",
      )

      window.setTimeout(() => {
        setPackNotice("")
      }, 3000)
    } catch (error) {
      setPackInstallError(
        error instanceof Error
          ? error.message
          : "Could not install pack.",
      )
    } finally {
      input.value = ""
      setPackInstalling(false)
    }
  }

  async function revertPackToOfficial() {
    if (!revertPack || packReverting) {
      return
    }

    setPackReverting(true)
    setPackRevertError("")

    try {
      const response = await fetch(
        `/api/v1/packs/${revertPack.id}/revert`,
        {
          method: "POST",
        },
      )

      const contentType =
        response.headers.get("content-type") || ""

      const data = contentType.includes("application/json")
        ? await response.json()
        : null

      if (!response.ok) {
        throw new Error(
          data?.detail ||
            `Could not revert pack (HTTP ${response.status}).`,
        )
      }

      const packsResponse = await fetch("/api/v1/packs")

      if (!packsResponse.ok) {
        throw new Error(
          "Pack reverted, but the pack list could not be refreshed.",
        )
      }

      const packsData = await packsResponse.json()

      setPacks(
        Array.isArray(packsData?.packs)
          ? packsData.packs
          : [],
      )

      const packName = revertPack.name

      setRevertPack(null)

      setPackNotice(
        `${packName} reverted to the official version.`,
      )

      window.setTimeout(() => {
        setPackNotice("")
      }, 3000)
    } catch (error) {
      setPackRevertError(
        error instanceof Error
          ? error.message
          : "Could not revert pack.",
      )
    } finally {
      setPackReverting(false)
    }
  }

  async function deleteInstalledPack() {
    if (!deletePack || packDeleting) {
      return
    }

    setPackDeleting(true)
    setPackDeleteError("")

    try {
      const response = await fetch(
        `/api/v1/packs/${deletePack.id}`,
        {
          method: "DELETE",
        },
      )

      const contentType =
        response.headers.get("content-type") || ""

      const data = contentType.includes("application/json")
        ? await response.json()
        : null

      if (!response.ok) {
        throw new Error(
          data?.detail ||
            `Could not delete pack (HTTP ${response.status}).`,
        )
      }

      const packsResponse = await fetch("/api/v1/packs")

      if (!packsResponse.ok) {
        throw new Error(
          "Pack deleted, but the pack list could not be refreshed.",
        )
      }

      const packsData = await packsResponse.json()

      setPacks(
        Array.isArray(packsData?.packs)
          ? packsData.packs
          : [],
      )

      const packName = deletePack.name

      setDeletePack(null)

      setPackNotice(
        `${packName} deleted successfully.`,
      )

      window.setTimeout(() => {
        setPackNotice("")
      }, 3000)
    } catch (error) {
      setPackDeleteError(
        error instanceof Error
          ? error.message
          : "Could not delete pack.",
      )
    } finally {
      setPackDeleting(false)
    }
  }

  async function loadPackFile(
    packId: string,
    filePath: string,
  ) {
    setPackViewLoading(true)
    setPackViewError("")

    try {
      const response = await fetch(
        `/api/v1/packs/${packId}/files/${filePath}`,
      )

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      const data = await response.json()

      setSelectedPackFile(filePath)
      setPackFileContent(data.content || "")
    } catch (error) {
      setPackViewError("Could not load pack file.")
    } finally {
      setPackViewLoading(false)
    }
  }

  async function openPackViewer(pack: ApiPack) {
    setViewPack(pack)
    setPackFiles([])
    setSelectedPackFile("")
    setPackFileContent("")
    setPackViewError("")
    setPackViewLoading(true)

    try {
      const response = await fetch(
        `/api/v1/packs/${pack.id}/files`,
      )

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      const data = await response.json()
      const files = Array.isArray(data?.files)
        ? data.files
        : []

      setPackFiles(files)

      const firstFile = files.includes("manifest.yaml")
        ? "manifest.yaml"
        : files[0]

      if (firstFile) {
        await loadPackFile(
          pack.id,
          firstFile,
        )
      } else {
        setPackViewLoading(false)
      }
    } catch (error) {
      setPackViewError("Could not load pack files.")
      setPackViewLoading(false)
    }
  }

  async function openPackEditor(pack: ApiPack) {
    setEditPackWarning(null)
    setEditPack(pack)
    setEditPackFiles([])
    setEditPackContents({})
    setSelectedEditFile("")
    setEditPackError("")
    setEditPackMessage("")
    setEditPackValidated(false)
    setEditPackLoading(true)

    try {
      const response = await fetch(
        `/api/v1/packs/${pack.id}/files`,
      )

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      const data = await response.json()
      const files: string[] = Array.isArray(data?.files)
        ? data.files
        : []

      const contents: Record<string, string> = {}

      await Promise.all(
        files.map(async (filePath) => {
          const fileResponse = await fetch(
            `/api/v1/packs/${pack.id}/files/${filePath}`,
          )

          if (!fileResponse.ok) {
            throw new Error(`HTTP ${fileResponse.status}`)
          }

          const fileData = await fileResponse.json()
          contents[filePath] = fileData.content || ""
        }),
      )

      setEditPackFiles(files)
      setEditPackContents(contents)

      setSelectedEditFile(
        files.includes("manifest.yaml")
          ? "manifest.yaml"
          : files[0] || "",
      )
    } catch (error) {
      console.error(error)
      setEditPackError("Could not load pack editor.")
    } finally {
      setEditPackLoading(false)
    }
  }

  async function validateEditedPack() {
    if (!editPack) {
      return
    }

    setEditPackError("")
    setEditPackMessage("")
    setEditPackValidated(false)

    try {
      const response = await fetch(
        `/api/v1/packs/${editPack.id}/validate`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            files: editPackContents,
          }),
        },
      )

      const contentType =
        response.headers.get("content-type") || ""

      const data = contentType.includes("application/json")
        ? await response.json()
        : null

      if (!response.ok) {
        throw new Error(
          data?.detail ||
            `Server error while validating the pack (HTTP ${response.status}).`,
        )
      }

      setEditPackValidated(true)
      setEditPackMessage(
        "Validation successful. The pack is ready to save.",
      )
    } catch (error) {
      setEditPackError(
        error instanceof Error
          ? error.message
          : "Pack validation failed.",
      )
    }
  }

  async function saveEditedPack() {
    if (!editPack || !editPackValidated) {
      return
    }

    setEditPackSaving(true)
    setEditPackError("")
    setEditPackMessage("")

    try {
      const response = await fetch(
        `/api/v1/packs/${editPack.id}/files`,
        {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            files: editPackContents,
          }),
        },
      )

      const contentType =
        response.headers.get("content-type") || ""

      const data = contentType.includes("application/json")
        ? await response.json()
        : null

      if (!response.ok) {
        throw new Error(
          data?.detail ||
            `Server error while saving the pack (HTTP ${response.status}).`,
        )
      }

      const packsResponse = await fetch("/api/v1/packs")

      if (packsResponse.ok) {
        const packsData = await packsResponse.json()

        setPacks(
          Array.isArray(packsData?.packs)
            ? packsData.packs
            : [],
        )
      }

      setPackNotice("Pack saved successfully.")
      window.setTimeout(() => {
        setPackNotice("")
      }, 3000)

      setEditPack(null)
    } catch (error) {
      setEditPackError(
        error instanceof Error
          ? error.message
          : "Could not save pack.",
      )
    } finally {
      setEditPackSaving(false)
    }
  }

  const normalizedPackSearch =
    packSearch.trim().toLowerCase()

  const filteredPacks = packs.filter((pack) => {
    if (!normalizedPackSearch) {
      return true
    }

    const searchable = [
      pack.id,
      pack.name,
      pack.description,
      pack.origin,
      pack.category?.id,
      pack.category?.label,
      pack.overridden ? "local override" : "",
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()

    return searchable.includes(normalizedPackSearch)
  })

  return (
    <section>
      <div className="section-heading">
        <div>
          <h2>
            Packs
            <span className="packs-heading-count">
              {packs.length}
            </span>
          </h2>
          <p>
            Detection and interpretation packs installed
            on this FERPEK instance.
          </p>
        </div>

        <label
          className={
            packInstalling
              ? "secondary-button pack-install-button disabled"
              : "secondary-button pack-install-button"
          }
        >
          {packInstalling ? "Installing..." : "Install pack"}

          <input
            type="file"
            accept=".pack"
            disabled={packInstalling}
            onChange={(event) =>
              void installPackFile(
                event.currentTarget.files?.[0] || null,
                event.currentTarget,
              )
            }
          />
        </label>
      </div>

      <div className="pack-tabs">
        <button className="filter-button selected">
          Installed
        </button>

        <button
          className="filter-button"
          disabled
        >
          Available
        </button>

        <button
          className="filter-button"
          disabled
        >
          Updates
        </button>

        <input
          className="pack-search-input"
          type="search"
          placeholder="Search installed packs..."
          value={packSearch}
          onChange={(event) =>
            setPackSearch(event.target.value)
          }
        />
      </div>

      {packNotice && (
        <div className="pack-page-notice">
          {packNotice}
        </div>
      )}

      {packInstallError && (
        <div className="pack-page-error">
          {packInstallError}
        </div>
      )}

      <div className="panel packs-page">
        {loading ? (
          <div className="empty-state">
            Loading packs...
          </div>
        ) : filteredPacks.length === 0 ? (
          <div className="empty-state">
            No packs installed.
          </div>
        ) : (
          <div className="packs-list">
            {filteredPacks.map((pack) => (
              <div
                className="pack-row"
                key={pack.id}
              >
                <span
                  className={`pack-state-indicator ${
                    pack.enabled
                      ? "enabled"
                      : "disabled"
                  }`}
                  aria-label={
                    pack.enabled
                      ? "Pack enabled"
                      : "Pack disabled"
                  }
                />

                <div className="pack-main">
                  <div className="pack-title-row">
                    <strong>{pack.name}</strong>

                    <span className="pack-version">
                      v{pack.version}
                    </span>
                  </div>

                  <p>{pack.description}</p>

                  <div className="pack-meta">
                    <span>{pack.category.label}</span>
                    <span>·</span>
                    <span>
                      {pack.origin === "official"
                        ? "Official"
                        : pack.origin}
                    </span>

                    {pack.overridden && (
                      <>
                        <span>·</span>
                        <span>Local override</span>
                      </>
                    )}

                    <span>·</span>
                    <span>
                      {pack.rule_count}{" "}
                      {pack.rule_count === 1
                        ? "rule"
                        : "rules"}
                    </span>
                  </div>
                </div>

                <div className="pack-row-actions">
                  <button
                    className={`host-icon-button pack-state-action tooltip ${
                      pack.enabled
                        ? "disable"
                        : "enable"
                    }`}
                    type="button"
                    disabled={packStateChanging === pack.id}
                    data-tooltip={
                      pack.enabled
                        ? "Disable pack"
                        : "Enable pack"
                    }
                    aria-label={
                      pack.enabled
                        ? `Disable ${pack.name}`
                        : `Enable ${pack.name}`
                    }
                    onClick={() =>
                      void setPackEnabled(
                        pack,
                        !pack.enabled,
                      )
                    }
                  >
                    {packStateChanging === pack.id
                      ? "…"
                      : pack.enabled
                        ? "×"
                        : "✓"}
                  </button>

                  <button
                    className="host-icon-button tooltip"
                    data-tooltip="View pack"
                    aria-label={`View ${pack.name}`}
                    onClick={() => void openPackViewer(pack)}
                  >
                    👁
                  </button>

                  <button
                    className="host-icon-button tooltip"
                    data-tooltip="Edit pack"
                    aria-label={`Edit ${pack.name}`}
                    onClick={() => setEditPackWarning(pack)}
                  >
                    ✎
                  </button>

                  {pack.overridden && (
                    <button
                      className="host-icon-button tooltip"
                      data-tooltip="Revert to official"
                      aria-label={`Revert ${pack.name} to official`}
                      onClick={() => {
                        setPackRevertError("")
                        setRevertPack(pack)
                      }}
                    >
                      ↶
                    </button>
                  )}

                  {pack.capabilities?.delete && (
                    <button
                      className="host-icon-button tooltip"
                      data-tooltip="Delete pack"
                      aria-label={`Delete ${pack.name}`}
                      onClick={() => {
                        setPackDeleteError("")
                        setDeletePack(pack)
                      }}
                    >
                      <svg
                        className="delete-icon"
                        viewBox="0 0 24 24"
                        aria-hidden="true"
                      >
                        <path d="M4 7h16" />
                        <path d="M9 7V4h6v3" />
                        <path d="M6.5 7l1 13h9l1-13" />
                        <path d="M10 11v5" />
                        <path d="M14 11v5" />
                      </svg>
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {deletePack && (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (
              event.target === event.currentTarget &&
              !packDeleting
            ) {
              setDeletePack(null)
            }
          }}
        >
          <div className="modal delete-host-modal">
            <div className="modal-header">
              <div>
                <h2>Delete pack?</h2>
                <p>{deletePack.name}</p>
              </div>

              <button
                className="modal-close"
                disabled={packDeleting}
                onClick={() => setDeletePack(null)}
              >
                ×
              </button>
            </div>

            <div className="pack-edit-warning">
              <strong>This pack will be removed</strong>

              <p>
                This will permanently remove {deletePack.name}
                from this FERPEK instance.
              </p>

              <p className="pack-edit-validation">
                This action only applies to installed packs.
                Built-in official packs cannot be deleted.
              </p>
            </div>

            {packDeleteError && (
              <div className="modal-error pack-editor-feedback">
                {packDeleteError}
              </div>
            )}

            <div className="modal-actions">
              <button
                className="secondary-button"
                disabled={packDeleting}
                onClick={() => setDeletePack(null)}
              >
                Cancel
              </button>

              <button
                className="secondary-button"
                disabled={packDeleting}
                onClick={() => void deleteInstalledPack()}
              >
                {packDeleting ? "Deleting..." : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}

      {revertPack && (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (
              event.target === event.currentTarget &&
              !packReverting
            ) {
              setRevertPack(null)
            }
          }}
        >
          <div className="modal delete-host-modal">
            <div className="modal-header">
              <div>
                <h2>Revert to official pack?</h2>
                <p>{revertPack.name}</p>
              </div>

              <button
                className="modal-close"
                disabled={packReverting}
                onClick={() => setRevertPack(null)}
              >
                ×
              </button>
            </div>

            <div className="pack-edit-warning">
              <strong>Local changes will be removed</strong>

              <p>
                This will remove the local override for {revertPack.name}
                and restore the built-in official version.
              </p>

              <p className="pack-edit-validation">
                The official built-in pack will not be deleted.
              </p>
            </div>

            {packRevertError && (
              <div className="modal-error pack-editor-feedback">
                {packRevertError}
              </div>
            )}

            <div className="modal-actions">
              <button
                className="secondary-button"
                disabled={packReverting}
                onClick={() => setRevertPack(null)}
              >
                Cancel
              </button>

              <button
                className="secondary-button"
                disabled={packReverting}
                onClick={() => void revertPackToOfficial()}
              >
                {packReverting ? "Reverting..." : "Revert"}
              </button>
            </div>
          </div>
        </div>
      )}

      {editPackWarning && (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              setEditPackWarning(null)
            }
          }}
        >
          <div className="modal delete-host-modal">
            <div className="modal-header">
              <div>
                <h2>Edit pack</h2>
                <p>{editPackWarning.name}</p>
              </div>

              <button
                className="modal-close"
                onClick={() => setEditPackWarning(null)}
              >
                ×
              </button>
            </div>

            <div className="pack-edit-warning">
              <strong>Advanced pack editing</strong>

              <p>
                Editing a pack changes how FERPEK interprets logs
                and generates Findings.
              </p>

              <ul>
                <li>Invalid rules may break log interpretation.</li>
                <li>Overly broad rules may generate incorrect results.</li>
                <li>Incorrect rules may cause important detections to be missed.</li>
              </ul>

              <p className="pack-edit-validation">
                FERPEK will validate the pack before applying changes.
              </p>
            </div>

            <div className="modal-actions">
              <button
                className="secondary-button"
                onClick={() => setEditPackWarning(null)}
              >
                Cancel
              </button>

              <button
                className="secondary-button"
                onClick={() =>
                  void openPackEditor(editPackWarning)
                }
              >
                Continue
              </button>
            </div>
          </div>
        </div>
      )}

      {editPack && (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (
              event.target === event.currentTarget &&
              !editPackSaving
            ) {
              setEditPack(null)
            }
          }}
        >
          <div className="modal pack-view-modal">
            <div className="modal-header">
              <div>
                <h2>Edit {editPack.name}</h2>
                <p>
                  v{editPack.version} · Changes are local to this FERPEK instance
                </p>
              </div>

              <button
                className="modal-close"
                disabled={editPackSaving}
                onClick={() => setEditPack(null)}
              >
                ×
              </button>
            </div>

            <div className="pack-view-body">
              <div className="pack-file-list">
                {editPackFiles.map((filePath) => (
                  <button
                    key={filePath}
                    className={
                      filePath === selectedEditFile
                        ? "pack-file-button selected"
                        : "pack-file-button"
                    }
                    onClick={() =>
                      setSelectedEditFile(filePath)
                    }
                  >
                    {filePath}
                  </button>
                ))}
              </div>

              <div className="pack-editor-pane">
                {editPackLoading ? (
                  <div className="empty-state">
                    Loading editor...
                  </div>
                ) : (
                  <textarea
                    className="pack-editor-textarea"
                    spellCheck={false}
                    value={
                      editPackContents[selectedEditFile] || ""
                    }
                    onChange={(event) => {
                      setEditPackContents((current) => ({
                        ...current,
                        [selectedEditFile]: event.target.value,
                      }))
                      setEditPackValidated(false)
                      setEditPackMessage("")
                      setEditPackError("")
                    }}
                  />
                )}
              </div>
            </div>

            {editPackError && (
              <div className="modal-error pack-editor-feedback">
                {editPackError}
              </div>
            )}

            {editPackMessage && (
              <div className="pack-editor-success">
                {editPackMessage}
              </div>
            )}

            <div className="modal-actions">
              <button
                className="secondary-button"
                disabled={editPackSaving}
                onClick={() => setEditPack(null)}
              >
                Cancel
              </button>

              <button
                className="secondary-button"
                disabled={editPackLoading || editPackSaving}
                onClick={() => void validateEditedPack()}
              >
                Validate
              </button>

              <button
                className="secondary-button"
                disabled={
                  !editPackValidated ||
                  editPackLoading ||
                  editPackSaving
                }
                onClick={() => void saveEditedPack()}
              >
                {editPackSaving ? "Saving..." : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}

      {viewPack && (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              setViewPack(null)
            }
          }}
        >
          <div className="modal pack-view-modal">
            <div className="modal-header">
              <div>
                <h2>{viewPack.name}</h2>
                <p>
                  v{viewPack.version} · {viewPack.origin}
                </p>
              </div>

              <button
                className="modal-close"
                onClick={() => setViewPack(null)}
              >
                ×
              </button>
            </div>

            <div className="pack-view-body">
              <div className="pack-file-list">
                {packFiles.map((filePath) => (
                  <button
                    key={filePath}
                    className={
                      filePath === selectedPackFile
                        ? "pack-file-button selected"
                        : "pack-file-button"
                    }
                    onClick={() =>
                      void loadPackFile(
                        viewPack.id,
                        filePath,
                      )
                    }
                  >
                    {filePath}
                  </button>
                ))}
              </div>

              <div className="pack-file-viewer">
                {packViewLoading ? (
                  <div className="empty-state">
                    Loading file...
                  </div>
                ) : packViewError ? (
                  <div className="modal-error">
                    {packViewError}
                  </div>
                ) : (
                  <pre>{packFileContent}</pre>
                )}
              </div>
            </div>

            <div className="modal-actions">
              <button
                className="secondary-button"
                onClick={() => setViewPack(null)}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}


function Settings() {
  const [
    allowCommunityPacks,
    setAllowCommunityPacks,
  ] = useState(false)

  const [
    allowLocalPacks,
    setAllowLocalPacks,
  ] = useState(true)

  const [packSettingsLoading, setPackSettingsLoading] =
    useState(true)

  const [packSettingsSaving, setPackSettingsSaving] =
    useState(false)

  const [packSettingsMessage, setPackSettingsMessage] =
    useState("")

  const [packSettingsError, setPackSettingsError] =
    useState("")

  const [eventRetentionDays, setEventRetentionDays] = useState(14)
  const [relevantRetentionDays, setRelevantRetentionDays] = useState(30)
  const [
    resolvedFindingRetentionDays,
    setResolvedFindingRetentionDays,
  ] = useState(90)

  const [retentionLoading, setRetentionLoading] = useState(true)
  const [retentionSaving, setRetentionSaving] = useState(false)
  const [retentionMessage, setRetentionMessage] = useState("")
  const [retentionError, setRetentionError] = useState("")

  useEffect(() => {
    async function loadPackSettings() {
      try {
        const response = await fetch(
          "/api/v1/settings/packs",
        )

        if (!response.ok) {
          throw new Error(
            `HTTP ${response.status}`,
          )
        }

        const data = await response.json()

        setAllowCommunityPacks(
          Boolean(data.allow_community_packs),
        )

        setAllowLocalPacks(
          Boolean(data.allow_local_packs),
        )
      } catch (error) {
        setPackSettingsError(
          "Could not load pack settings.",
        )
      } finally {
        setPackSettingsLoading(false)
      }
    }

    void loadPackSettings()
  }, [])

  useEffect(() => {
    async function loadRetentionSettings() {
      try {
        const response = await fetch(
          "/api/v1/settings/retention",
        )

        if (!response.ok) {
          throw new Error(
            `HTTP ${response.status}`,
          )
        }

        const data = await response.json()

        setEventRetentionDays(
          Number(data.event_retention_days),
        )

        setRelevantRetentionDays(
          Number(data.relevant_retention_days),
        )

        setResolvedFindingRetentionDays(
          Number(
            data.resolved_finding_retention_days,
          ),
        )
      } catch (error) {
        setRetentionError(
          "Could not load retention settings.",
        )
      } finally {
        setRetentionLoading(false)
      }
    }

    void loadRetentionSettings()
  }, [])

  async function savePackSettings() {
    setPackSettingsSaving(true)
    setPackSettingsMessage("")
    setPackSettingsError("")

    try {
      const response = await fetch(
        "/api/v1/settings/packs",
        {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            allow_community_packs:
              allowCommunityPacks,
            allow_local_packs:
              allowLocalPacks,
          }),
        },
      )

      if (!response.ok) {
        throw new Error(
          `HTTP ${response.status}`,
        )
      }

      setPackSettingsMessage(
        "Pack settings saved.",
      )
    } catch (error) {
      setPackSettingsError(
        "Could not save pack settings.",
      )
    } finally {
      setPackSettingsSaving(false)
    }
  }


  async function saveRetentionSettings() {
    setRetentionSaving(true)
    setRetentionMessage("")
    setRetentionError("")

    try {
      const response = await fetch(
        "/api/v1/settings/retention",
        {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            event_retention_days:
              eventRetentionDays,
            relevant_retention_days:
              relevantRetentionDays,
            resolved_finding_retention_days:
              resolvedFindingRetentionDays,
          }),
        },
      )

      if (!response.ok) {
        throw new Error(
          `HTTP ${response.status}`,
        )
      }

      setRetentionMessage(
        "Retention settings saved.",
      )
    } catch (error) {
      setRetentionError(
        "Could not save retention settings.",
      )
    } finally {
      setRetentionSaving(false)
    }
  }

  return (
    <section>
      <div className="section-heading">
        <div>
          <h2>FERPEK settings</h2>
          <p>Configuration for this FERPEK instance</p>
        </div>
      </div>

      <div className="settings-sections">
        <div className="panel core-settings-panel">
          <div className="core-setting-row">
            <div>
              <h3>Server</h3>
              <p>Server identity, URL and connectivity settings.</p>
            </div>

            <button className="secondary-button">
              Configure
            </button>
          </div>

          <div className="core-setting-row">
            <div>
              <h3>Agents</h3>
              <p>Enrollment and agent configuration.</p>
            </div>

            <button className="secondary-button">
              Configure
            </button>
          </div>

          <div className="core-setting-row">
            <div>
              <h3>Detection</h3>
              <p>Patterns and finding behaviour.</p>
            </div>

            <button className="secondary-button">
              Configure
            </button>
          </div>
        </div>

        <div className="panel setting-card pack-management-card">
          <div>
            <h3>Pack management</h3>
            <p>
              Control which pack sources this FERPEK instance may use.
            </p>
          </div>

          {packSettingsLoading ? (
            <p>Loading pack settings...</p>
          ) : (
            <>
              <div className="pack-setting-row">
                <div>
                  <strong>Official packs</strong>
                  <span>
                    Maintained and distributed by FERPEK.
                  </span>
                </div>

                <span className="pack-setting-fixed">
                  Always enabled
                </span>
              </div>

              <div className="pack-setting-row">
                <div>
                  <strong>Community packs</strong>
                  <span>
                    Reviewed before publication, but maintained by third-party authors.
                  </span>
                </div>

                <label className="setting-switch">
                  <input
                    type="checkbox"
                    checked={allowCommunityPacks}
                    onChange={(event) =>
                      setAllowCommunityPacks(
                        event.target.checked,
                      )
                    }
                  />
                  <span className="setting-switch-track" />
                </label>
              </div>

              <div className="pack-setting-row">
                <div>
                  <strong>Local / private packs</strong>
                  <span>
                    Allow packs installed locally or distributed privately.
                  </span>
                </div>

                <label className="setting-switch">
                  <input
                    type="checkbox"
                    checked={allowLocalPacks}
                    onChange={(event) =>
                      setAllowLocalPacks(
                        event.target.checked,
                      )
                    }
                  />
                  <span className="setting-switch-track" />
                </label>
              </div>

              <div className="pack-management-actions">
                <div>
                  {packSettingsMessage && (
                    <p className="save-message">
                      {packSettingsMessage}
                    </p>
                  )}

                  {packSettingsError && (
                    <p className="save-error">
                      {packSettingsError}
                    </p>
                  )}
                </div>

                <button
                  className="secondary-button"
                  onClick={() =>
                    void savePackSettings()
                  }
                  disabled={packSettingsSaving}
                >
                  {packSettingsSaving
                    ? "Saving..."
                    : "Save changes"}
                </button>
              </div>
            </>
          )}
        </div>

        <div className="panel setting-card retention-card">
          <h3>Retention</h3>
          <p>
            Control how long FERPEK keeps historical data.
          </p>

          {retentionLoading ? (
            <p>Loading retention settings...</p>
          ) : (
            <>
              <div className="retention-field">
                <label htmlFor="event-retention">
                  Raw logs
                </label>

                <div className="retention-input-row">
                  <input
                    id="event-retention"
                    type="number"
                    min="1"
                    max="3650"
                    value={eventRetentionDays}
                    onChange={(event) =>
                      setEventRetentionDays(
                        Number(event.target.value),
                      )
                    }
                  />
                  <span>days</span>
                </div>
              </div>

              <div className="retention-field">
                <label htmlFor="relevant-retention">
                  Relevant activity
                </label>

                <div className="retention-input-row">
                  <input
                    id="relevant-retention"
                    type="number"
                    min="1"
                    max="3650"
                    value={relevantRetentionDays}
                    onChange={(event) =>
                      setRelevantRetentionDays(
                        Number(event.target.value),
                      )
                    }
                  />
                  <span>days</span>
                </div>
              </div>

              <div className="retention-field">
                <label htmlFor="finding-retention">
                  Resolved findings
                </label>

                <div className="retention-input-row">
                  <input
                    id="finding-retention"
                    type="number"
                    min="1"
                    max="3650"
                    value={
                      resolvedFindingRetentionDays
                    }
                    onChange={(event) =>
                      setResolvedFindingRetentionDays(
                        Number(event.target.value),
                      )
                    }
                  />
                  <span>days</span>
                </div>
              </div>

              <div className="retention-field">
                <label>Open findings</label>
                <span>Keep indefinitely</span>
              </div>

              <div className="retention-actions">
                <div>
                  {retentionMessage && (
                    <p className="save-message">
                      {retentionMessage}
                    </p>
                  )}

                  {retentionError && (
                    <p className="save-error">
                      {retentionError}
                    </p>
                  )}
                </div>

                <button
                  className="secondary-button"
                  onClick={() =>
                    void saveRetentionSettings()
                  }
                  disabled={retentionSaving}
                >
                  {retentionSaving
                    ? "Saving..."
                    : "Save changes"}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  )
}

function Layout() {
  const location = useLocation()

  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    return localStorage.getItem('ferpek-theme') === 'light'
      ? 'light'
      : 'dark'
  })

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('ferpek-theme', theme)
  }, [theme])
  const info = location.pathname.startsWith('/systems/')
    ? {
        title: 'Host',
        subtitle: 'Logs, findings and monitoring sources',
      }
    : pageInfo[location.pathname] ?? pageInfo['/']

  return (
    <div className="app">
      <GlobalTooltip />
      <Sidebar />

      <main className="main">
        <header className="topbar">
          <div>
            <h1>{info.title}</h1>
            <p>{info.subtitle}</p>
          </div>

          <div className="topbar-actions">
            <button
              className="theme-toggle tooltip"
              data-tooltip={
                theme === 'dark'
                  ? 'Switch to light mode'
                  : 'Switch to dark mode'
              }
              aria-label={
                theme === 'dark'
                  ? 'Switch to light mode'
                  : 'Switch to dark mode'
              }
              onClick={() =>
                setTheme((current) =>
                  current === 'dark' ? 'light' : 'dark'
                )
              }
            >
              {theme === 'dark' ? '☀' : '◐'}
            </button>

          </div>
        </header>

        <div className="content">
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/systems" element={<Systems />} />
            <Route path="/systems/:id" element={<HostDetail />} />
            <Route path="/findings" element={<Findings />} />
            <Route path="/activity" element={<Activity />} />
            <Route path="/packs" element={<Packs />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </div>
      </main>
    </div>
  )
}

function App() {
  return (
    <BrowserRouter>
      <Layout />
    </BrowserRouter>
  )
}

export default App
