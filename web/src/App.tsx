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
import { createPortal } from 'react-dom'

type Status = 'healthy' | 'info' | 'warning' | 'critical' | 'unknown'

type ToastType = 'info' | 'success' | 'error'

type ToastEventDetail = {
  message: string
  type: ToastType
  duration?: number
}

function showToast(
  message: string,
  type: ToastType = 'info',
  duration = 3500,
) {
  window.dispatchEvent(
    new CustomEvent<ToastEventDetail>('ferpek-toast', {
      detail: {
        message,
        type,
        duration,
      },
    }),
  )
}

function GlobalToasts() {
  const [toasts, setToasts] = useState<
    Array<{
      id: number
      message: string
      type: ToastType
    }>
  >([])

  const nextId = useRef(1)

  useEffect(() => {
    function handleToast(event: Event) {
      const customEvent =
        event as CustomEvent<ToastEventDetail>

      const {
        message,
        type = 'info',
        duration = 3500,
      } = customEvent.detail

      const id = nextId.current++

      setToasts((current) => [
        ...current.slice(-2),
        {
          id,
          message,
          type,
        },
      ])

      window.setTimeout(() => {
        setToasts((current) =>
          current.filter((toast) => toast.id !== id),
        )
      }, duration)
    }

    window.addEventListener(
      'ferpek-toast',
      handleToast,
    )

    return () => {
      window.removeEventListener(
        'ferpek-toast',
        handleToast,
      )
    }
  }, [])

  if (toasts.length === 0) {
    return null
  }

  return createPortal(
    <div
      className="global-toast-stack"
      aria-live="polite"
      aria-atomic="false"
    >
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`global-toast ${toast.type}`}
        >
          <div className="global-toast-content">
            <span className="global-toast-indicator" />

            <span>{toast.message}</span>
          </div>

          <button
            type="button"
            className="global-toast-close"
            aria-label="Dismiss notification"
            onClick={() =>
              setToasts((current) =>
                current.filter(
                  (candidate) =>
                    candidate.id !== toast.id,
                ),
              )
            }
          >
            ×
          </button>
        </div>
      ))}
    </div>,
    document.body,
  )
}


type CurrentUser = {
  id: number
  username: string
  display_name: string
  email: string
  auth_type: string
  groups: string[]
  permissions: string[]
}

function hasPermission(
  user: CurrentUser,
  permission: string,
) {
  return user.permissions.includes(permission)
}

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
    document.addEventListener(
      'click',
      hideTooltip,
      true,
    )

    window.addEventListener('scroll', hideTooltip, true)
    window.addEventListener('resize', hideTooltip)

    return () => {
      document.removeEventListener('mouseover', handleMouseOver)
      document.removeEventListener('mouseout', handleMouseOut)
      document.removeEventListener('focusin', handleFocusIn)
      document.removeEventListener('focusout', hideTooltip)
      document.removeEventListener(
        'click',
        hideTooltip,
        true,
      )

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
  allowed: boolean
  server_compatible: boolean
  effective_enabled: boolean
  blocked_reason: string
  overridden: boolean
  capabilities: {
    edit: boolean
    revert: boolean
    delete: boolean
  }
}

function getPackStatus(pack: ApiPack) {
  if (!pack.enabled) {
    return {
      label: "Disabled",
      className: "disabled",
    }
  }

  if (!pack.allowed) {
    return {
      label: "Blocked",
      className: "blocked",
    }
  }

  if (!pack.server_compatible) {
    return {
      label: "Incompatible",
      className: "incompatible",
    }
  }

  return {
    label: "Enabled",
    className: "enabled",
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

  if (value === 'info' || value === 'informational') {
    return 'info'
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
    subtitle: 'Configure your FERPEK Lens instance',
  },
  '/settings/access': {
    title: 'Users & permissions',
    subtitle: 'Manage users, groups and access permissions',
  },
  '/settings/authentication': {
    title: 'Authentication',
    subtitle: 'Configure login providers',
  },
  '/settings/authentication/ldap': {
    title: 'LDAP',
    subtitle: 'Configure LDAP authentication',
  },
}

function Sidebar({
  currentUser,
  onLogout,
}: {
  currentUser: CurrentUser
  onLogout: () => void
}) {
  const canViewHosts = hasPermission(
    currentUser,
    'hosts.view',
  )

  const canViewFindings = hasPermission(
    currentUser,
    'findings.view',
  )

  const canViewLogs = hasPermission(
    currentUser,
    'logs.view',
  )

  const canViewPacks = hasPermission(
    currentUser,
    'packs.view',
  )

  const canViewSettings =
    hasPermission(currentUser, 'settings.view') ||
    hasPermission(currentUser, 'users.view') ||
    hasPermission(currentUser, 'groups.view')

  const [platformVersion, setPlatformVersion] = useState("...")

  const [accountMenuOpen, setAccountMenuOpen] =
    useState(false)

  const accountMenuRef = useRef<HTMLDivElement>(null)
  const location = useLocation()

  const [passwordModalOpen, setPasswordModalOpen] =
    useState(false)
  const [currentPassword, setCurrentPassword] =
    useState('')
  const [newPassword, setNewPassword] =
    useState('')
  const [confirmPassword, setConfirmPassword] =
    useState('')
  const [passwordSaving, setPasswordSaving] =
    useState(false)
  const [passwordError, setPasswordError] =
    useState('')
  const [passwordMessage, setPasswordMessage] =
    useState('')

  useEffect(() => {
    setAccountMenuOpen(false)
  }, [location.pathname])

  useEffect(() => {
    function handleOutsideClick(event: MouseEvent) {
      if (
        accountMenuOpen &&
        accountMenuRef.current &&
        !accountMenuRef.current.contains(event.target as Node)
      ) {
        setAccountMenuOpen(false)
      }
    }

    document.addEventListener('mousedown', handleOutsideClick)

    return () => {
      document.removeEventListener('mousedown', handleOutsideClick)
    }
  }, [accountMenuOpen])

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

  async function handleLogout() {
    try {
      await fetch("/api/v1/auth/logout", {
        method: "POST",
        credentials: "include",
      })
    } catch (err) {
      console.error("Logout failed:", err)
    } finally {
      onLogout()
    }
  }

  function openPasswordModal() {
    setAccountMenuOpen(false)
    setCurrentPassword('')
    setNewPassword('')
    setConfirmPassword('')
    setPasswordError('')
    setPasswordMessage('')
    setPasswordModalOpen(true)
  }

  async function handlePasswordChange(
    event: React.FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault()

    if (newPassword !== confirmPassword) {
      setPasswordMessage('')
      setPasswordError('New passwords do not match.')
      return
    }

    if (newPassword.length < 12) {
      setPasswordMessage('')
      setPasswordError(
        'New password must be at least 12 characters.',
      )
      return
    }

    setPasswordSaving(true)
    setPasswordError('')
    setPasswordMessage('')

    try {
      const response = await fetch(
        '/api/v1/auth/change-password',
        {
          method: 'POST',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            current_password: currentPassword,
            new_password: newPassword,
          }),
        },
      )

      if (!response.ok) {
        let message = 'Could not change password.'

        try {
          const data = await response.json()

          if (typeof data?.detail === 'string') {
            message = data.detail
          }
        } catch {
          // Keep generic message.
        }

        throw new Error(message)
      }

      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      showToast(
        'Password changed successfully.',
        'success',
      )
    } catch (error) {
      setPasswordError(
        error instanceof Error
          ? error.message
          : 'Could not change password.',
      )
    } finally {
      setPasswordSaving(false)
    }
  }

  const [hostCount, setHostCount] = useState(0)
  const [findingCount, setFindingCount] = useState(0)
  const [packCount, setPackCount] = useState(0)

  async function loadSidebarCounts() {
    try {
      if (canViewHosts) {
        const response = await fetch('/api/v1/agents')

        if (response.ok) {
          const agents: ApiAgent[] = await response.json()
          setHostCount(agents.length)
        }
      } else {
        setHostCount(0)
      }

      if (canViewFindings) {
        const response = await fetch(
          '/api/v1/findings?status=open',
        )

        if (response.ok) {
          const findings: ApiFinding[] =
            await response.json()

          setFindingCount(findings.length)
        }
      } else {
        setFindingCount(0)
      }

      if (canViewPacks) {
        const response = await fetch('/api/v1/packs')

        if (response.ok) {
          const packsData = await response.json()

          setPackCount(
            Array.isArray(packsData?.packs)
              ? packsData.packs.length
              : 0,
          )
        }
      } else {
        setPackCount(0)
      }
    } catch (err) {
      console.error(
        'Could not load sidebar counters:',
        err,
      )
    }
  }

  useEffect(() => {
    loadSidebarCounts()

    const timer = window.setInterval(loadSidebarCounts, 5000)

    return () => window.clearInterval(timer)
  }, [])

  return (
    <aside className="sidebar">
      <a
        className="brand"
        href="https://ferpek.com"
        target="_blank"
        rel="noopener noreferrer"
        aria-label="Open ferpek.com"
      >
        <img
          className="brand-logo"
          src="/ferpek_original_sem_nome_laranja_transparente.svg"
          alt=""
        />

        <div className="brand-wordmark">
          <span className="brand-name">FERPEK</span>
          <span className="brand-product">Lens</span>
        </div>
      </a>

      <nav className="navigation">
        <NavLink
          to="/"
          end
          className={({ isActive }) =>
            `nav-item ${isActive ? 'active' : ''}`
          }
        >
                    Overview
        </NavLink>

        {canViewHosts && (
          <NavLink
            to="/systems"
            className={({ isActive }) =>
              `nav-item ${isActive ? 'active' : ''}`
            }
          >
                        Hosts

            {hostCount > 0 && (
              <span className="nav-count host-nav-count">
                {hostCount}
              </span>
            )}
          </NavLink>
        )}

        {canViewFindings && (
          <NavLink
            to="/findings"
            className={({ isActive }) =>
              `nav-item ${isActive ? 'active' : ''}`
            }
          >
                        Findings

            {findingCount > 0 && (
              <span className="nav-count danger">
                {findingCount}
              </span>
            )}
          </NavLink>
        )}

        {canViewLogs && (
          <NavLink
            to="/activity"
            className={({ isActive }) =>
              `nav-item ${isActive ? 'active' : ''}`
            }
          >
                        Activity
          </NavLink>
        )}

        {canViewPacks && (
          <NavLink
            to="/packs"
            className={({ isActive }) =>
              `nav-item ${isActive ? 'active' : ''}`
            }
          >
                        Packs

            {packCount > 0 && (
              <span className="nav-count host-nav-count">
                {packCount}
              </span>
            )}
          </NavLink>
        )}
      </nav>

      <div className="sidebar-bottom">
        <div
          className="sidebar-account"
          ref={accountMenuRef}
        >
          <button
            type="button"
            className={
              accountMenuOpen
                ? 'sidebar-user sidebar-user-button open'
                : 'sidebar-user sidebar-user-button'
            }
            onClick={() =>
              setAccountMenuOpen((current) => !current)
            }
            aria-expanded={accountMenuOpen}
          >
            <div className="sidebar-user-avatar">
              {(currentUser.display_name ||
                currentUser.username)
                .charAt(0)
                .toUpperCase()}
            </div>

            <div className="sidebar-user-info">
              <strong>
                {currentUser.display_name ||
                  currentUser.username}
              </strong>

              <span>
                {currentUser.groups?.[0] ||
                  currentUser.username}
              </span>
            </div>

            <span className="sidebar-account-chevron">
              {accountMenuOpen ? '⌃' : '⌄'}
            </span>
          </button>

          {accountMenuOpen && (
            <div className="sidebar-account-menu">
              {currentUser.auth_type === 'local' && (
                <button
                  type="button"
                  onClick={openPasswordModal}
                >
                  <span className="sidebar-account-icon">
                    <svg
                      viewBox="0 0 24 24"
                      aria-hidden="true"
                    >
                      <path
                        d="M17 9h-1V7a4 4 0 0 0-8 0v2H7a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-8a2 2 0 0 0-2-2Zm-7-2a2 2 0 0 1 4 0v2h-4V7Zm3 9.73V18h-2v-1.27a2 2 0 1 1 2 0Z"
                        fill="currentColor"
                      />
                    </svg>
                  </span>
                  Change password
                </button>
              )}

              <button
                type="button"
                onClick={() => void handleLogout()}
              >
                <span className="sidebar-account-icon">
                  <svg
                    viewBox="0 0 24 24"
                    aria-hidden="true"
                  >
                    <path
                      d="M13 5h-2V3h8v18h-8v-2h6V5h-4Zm-2.6 3.4L9 7l-5 5 5 5 1.4-1.4L7.8 13H15v-2H7.8l2.6-2.6Z"
                      fill="currentColor"
                    />
                  </svg>
                </span>
                Sign out
              </button>
            </div>
          )}
        </div>

        {canViewSettings && (
          <NavLink
            to="/settings"
            className={({ isActive }) =>
              `nav-item ${isActive ? 'active' : ''}`
            }
          >
            <span className="nav-icon">⚙</span>
            Settings
          </NavLink>
        )}

        <div className="version">FERPEK v{platformVersion}</div>
      </div>

      {passwordModalOpen &&
        createPortal(
          <div
            className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              setPasswordModalOpen(false)
            }
          }}
        >
          <div className="modal account-password-modal">
            <div className="modal-header">
              <div>
                <h2>Change password</h2>
                <p>
                  Change the password for @{currentUser.username}.
                </p>
              </div>

              <button
                type="button"
                className="modal-close"
                onClick={() =>
                  setPasswordModalOpen(false)
                }
                disabled={passwordSaving}
              >
                ×
              </button>
            </div>

            <form
              className="access-user-form"
              onSubmit={handlePasswordChange}
            >
              <label>
                <span>Current password</span>

                <input
                  type="password"
                  value={currentPassword}
                  required
                  autoComplete="current-password"
                  onChange={(event) =>
                    setCurrentPassword(
                      event.target.value,
                    )
                  }
                />
              </label>

              <label>
                <span>New password</span>

                <input
                  type="password"
                  value={newPassword}
                  minLength={12}
                  maxLength={256}
                  required
                  autoComplete="new-password"
                  onChange={(event) =>
                    setNewPassword(
                      event.target.value,
                    )
                  }
                />
              </label>

              <label>
                <span>Confirm new password</span>

                <input
                  type="password"
                  value={confirmPassword}
                  minLength={12}
                  maxLength={256}
                  required
                  autoComplete="new-password"
                  onChange={(event) =>
                    setConfirmPassword(
                      event.target.value,
                    )
                  }
                />
              </label>

              {passwordError && (
                <div className="modal-error">
                  {passwordError}
                </div>
              )}

              {passwordMessage && (
                <div className="account-password-success">
                  {passwordMessage}
                </div>
              )}

              <div className="modal-actions">
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() =>
                    setPasswordModalOpen(false)
                  }
                  disabled={passwordSaving}
                >
                  Cancel
                </button>

                <button
                  type="submit"
                  className="secondary-button"
                  disabled={passwordSaving}
                >
                  {passwordSaving
                    ? 'Changing...'
                    : 'Change password'}
                </button>
              </div>
            </form>
          </div>
        </div>,
          document.body,
        )}
    </aside>
  )
}

function Overview({
  currentUser,
}: {
  currentUser: CurrentUser
}) {
  const canViewHosts = hasPermission(
    currentUser,
    'hosts.view',
  )

  const canViewFindings = hasPermission(
    currentUser,
    'findings.view',
  )

  const canViewLogs = hasPermission(
    currentUser,
    'logs.view',
  )

  const [agents, setAgents] = useState<ApiAgent[]>([])
  const [apiFindings, setApiFindings] = useState<ApiFinding[]>([])
  const [recentActivity, setRecentActivity] =
    useState<ApiRelevantEvent[]>([])

  async function loadOverview() {
    try {
      if (canViewHosts) {
        const agentsResponse = await fetch(
          '/api/v1/agents',
        )

        if (!agentsResponse.ok) {
          throw new Error(
            'Could not load host overview data',
          )
        }

        setAgents(await agentsResponse.json())
      } else {
        setAgents([])
      }

      if (canViewFindings) {
        const findingsResponse = await fetch(
          '/api/v1/findings?status=open',
        )

        if (!findingsResponse.ok) {
          throw new Error(
            'Could not load findings overview data',
          )
        }

        setApiFindings(
          await findingsResponse.json(),
        )
      } else {
        setApiFindings([])
      }

      if (canViewLogs) {
        const activityResponse = await fetch(
          '/api/v1/relevant?limit=3',
        )

        if (!activityResponse.ok) {
          throw new Error(
            'Could not load recent activity',
          )
        }

        setRecentActivity(
          await activityResponse.json(),
        )
      } else {
        setRecentActivity([])
      }
    } catch (err) {
      console.error('Could not load overview:', err)
    }
  }

  useEffect(() => {
    loadOverview()

    const timer = window.setInterval(loadOverview, 5000)

    return () => window.clearInterval(timer)
  }, [canViewHosts, canViewFindings, canViewLogs])

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
      {!canViewHosts && !canViewFindings ? (
        <section>
          <div className="panel">
            <div className="empty-state">
              Your account has limited access to this
              FERPEK Lens instance.
            </div>
          </div>
        </section>
      ) : (
      <section className="status-section">
        <div className="section-heading">
          <div>
            <h2>Infrastructure status</h2>
            <p>Current state of monitored hosts</p>
          </div>

          <span className="last-update">Updated automatically</span>
        </div>

        <div className="stats-grid">
          {canViewHosts && (
            <div className="stat-card">
              <div className="stat-label">Hosts</div>
              <div className="stat-value">{agents.length}</div>
              <div className="stat-detail">
                <StatusDiamond
                  status={
                    onlineHosts > 0
                      ? 'healthy'
                      : 'unknown'
                  }
                />
                {onlineHosts} online
              </div>
            </div>
          )}

          {canViewFindings && (
            <div className="stat-card critical-card">
              <div className="stat-label">Critical</div>
              <div className="stat-value">
                {criticalCount}
              </div>
              <div className="stat-detail critical-text">
                <StatusDiamond
                  status={
                    criticalCount > 0
                      ? 'critical'
                      : 'healthy'
                  }
                />
                {criticalCount > 0
                  ? 'Needs attention'
                  : 'No critical findings'}
              </div>
            </div>
          )}

          {canViewFindings && (
            <div className="stat-card">
              <div className="stat-label">Warnings</div>
              <div className="stat-value">
                {warningCount}
              </div>
              <div className="stat-detail warning-text">
                <StatusDiamond
                  status={
                    warningCount > 0
                      ? 'warning'
                      : 'healthy'
                  }
                />
                {warningCount > 0
                  ? 'Open findings'
                  : 'No warnings'}
              </div>
            </div>
          )}

          {canViewHosts && (
            <div className="stat-card">
              <div className="stat-label">Healthy</div>
              <div className="stat-value">
                {healthyHosts}
              </div>
              <div className="stat-detail muted">
                Hosts without open findings
              </div>
            </div>
          )}
        </div>
      </section>
      )}

      {canViewFindings && (
      <section className="findings-section">
        <div className="section-heading">
          <div>
            <h2>Needs attention</h2>
            <p>Open findings ordered by severity</p>
          </div>

          <NavLink
            className="text-button"
            to="/findings"
          >
            View findings →
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
            apiFindings.slice(0, 3).map((finding) => (
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
      )}

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

        {canViewLogs && (
          <div className="panel">
            <div className="panel-header">
              <div>
                <h2>Recent activity</h2>
                <p>Latest relevant events</p>
              </div>

              <NavLink
                className="text-button"
                to="/activity"
              >
                View activity →
              </NavLink>
            </div>

            {recentActivity.length === 0 ? (
              <div className="empty-state">
                No recent activity.
              </div>
            ) : (
              recentActivity.map((event) => (
                <div className="activity-row" key={event.id}>
                  <StatusDiamond
                    status={findingStatus(event.severity)}
                  />

                  <div>
                    <strong>{event.title}</strong>
                    <span>
                      {event.hostname} ·{' '}
                      {event.service || event.pack_id}
                    </span>
                  </div>

                  <time>{formatAge(event.event_time)}</time>
                </div>
              ))
            )}
          </div>
        )}
      </section>
    </>
  )
}

function Systems({
  currentUser,
}: {
  currentUser: CurrentUser
}) {
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
  const [hostSearch, setHostSearch] = useState('')
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
    if (
      !sourcesHost ||
      !hasPermission(currentUser, 'hosts.manage')
    ) {
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

  const normalizedHostSearch =
    hostSearch.trim().toLowerCase()

  const visibleAgents =
    normalizedHostSearch === ''
      ? agents
      : agents.filter((agent) => {
          const haystack = [
            agent.hostname,
            agent.os_name ?? '',
            agent.os_version ?? '',
            agent.machine_type ?? '',
            agent.agent_version ?? '',
          ]
            .join(' ')
            .toLowerCase()

          return haystack.includes(
            normalizedHostSearch,
          )
        })

  return (
    <section>
      <div className="section-heading hosts-heading">
        <div>
          <h2>
            Monitored hosts: {agents.length}
          </h2>

          <p>
            Physical machines and virtual machines monitored by FERPEK
          </p>
        </div>

        <div className="hosts-toolbar">
          <input
            className="hosts-search"
            type="search"
            placeholder="Search hosts..."
            value={hostSearch}
            onChange={(event) =>
              setHostSearch(event.target.value)
            }
            aria-label="Search hosts"
          />

          {hasPermission(
            currentUser,
            'hosts.manage',
          ) && (
            <button
              className="primary-button action-button"
              onClick={createEnrollment}
            >
              + Add host
            </button>
          )}
        </div>
      </div>

      <div className="hosts-flat-list">
        {agents.length === 0 ? (
          <div className="empty-state">
            No hosts have been enrolled yet.
          </div>
        ) : visibleAgents.length === 0 ? (
          <div className="empty-state">
            No hosts match your search.
          </div>
        ) : (
          visibleAgents.map((agent) => (
            <div
              className={`system-row large-row host-status-${agentStatus(agent)}`}
              key={agent.id}
            >
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

                  {hasPermission(
                    currentUser,
                    'hosts.delete',
                  ) && (
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
                  )}
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
                          !hasPermission(
                            currentUser,
                            'hosts.manage',
                          ) ||
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
                          !hasPermission(
                            currentUser,
                            'hosts.manage',
                          ) ||
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



function HostDetail({
  currentUser,
}: {
  currentUser: CurrentUser
}) {
  type HostTab =
    | 'overview'
    | 'logs'
    | 'findings'
    | 'packs'
    | 'sources'

  type LogMode = 'relevant' | 'raw'

  type HostPackSource = {
    source_id: string
    detected: boolean
    source_type: string
    source_value: string
    checked_at: number
  }

  type HostPackConfigurationField = {
    id: string
    label: string
    type:
      | 'text'
      | 'path'
      | 'number'
      | 'boolean'
      | 'select'
      | 'secret'
    required?: boolean
    options?: Array<
      | string
      | {
          value: string
          label?: string
        }
    >
  }

  type HostPackConfigurationSource = {
    source_id: string
    fields: HostPackConfigurationField[]
  }

  type HostPack = {
    id: string
    name: string
    version: string
    origin: string
    category: {
      id: string
      label: string
    }
    globally_enabled: boolean
    allowed: boolean
    server_compatible: boolean
    agent_compatible: boolean
    platform_supported: boolean
    assigned: boolean
    enabled: boolean
    config: Record<string, unknown>
    configuration_schema: HostPackConfigurationSource[]
    discovery_status:
      | 'detected'
      | 'configured'
      | 'needs_configuration'
      | 'unavailable'
      | 'unknown'
    can_activate: boolean
    activation_reason: string | null
    discovery_checked_at: number | null
    detected_sources: HostPackSource[]
  }

  type HostPackResponse = {
    agent_id: number
    packs: HostPack[]
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
  const [hostFindingStatus, setHostFindingStatus] =
    useState<'open' | 'resolved' | 'all'>('open')
  const [resolvingHostFinding, setResolvingHostFinding] =
    useState<number | null>(null)
  const [sources, setSources] = useState<LogSource[]>([])
  const [sourceDrafts, setSourceDrafts] = useState<LogSource[]>([])
  const [hostPacks, setHostPacks] = useState<HostPack[]>([])
  const [hostPacksError, setHostPacksError] = useState('')
  const [hostPackChanging, setHostPackChanging] =
    useState<string | null>(null)
  const [configuringHostPack, setConfiguringHostPack] =
    useState<HostPack | null>(null)
  const [hostPackConfigDraft, setHostPackConfigDraft] =
    useState<Record<string, Record<string, unknown>>>({})
  const [hostPackConfigSaving, setHostPackConfigSaving] =
    useState(false)
  const [hostPackConfigError, setHostPackConfigError] =
    useState('')
  const [hostPackFilter, setHostPackFilter] =
    useState<'all' | 'active' | 'available' | 'unavailable'>('all')
  const [hostPackSearch, setHostPackSearch] = useState('')
  const [sourcesDirty, setSourcesDirty] = useState(false)
  const [savingSources, setSavingSources] = useState(false)
  const [sourcesSaveMessage, setSourcesSaveMessage] = useState('')
  const [sourcesSaveError, setSourcesSaveError] = useState('')

  const [activeTab, setActiveTab] = useState<HostTab>('overview')
  const [logMode, setLogMode] = useState<LogMode>('relevant')
  const [selectedSource, setSelectedSource] = useState<string>('all')
  const [sourceMenuOpen, setSourceMenuOpen] = useState(false)

  const [loading, setLoading] = useState(true)

  const activeHostPacks = hostPacks.filter(
    (pack) =>
      pack.enabled &&
      pack.can_activate,
  )

  const latestRelevantActivity =
    relevantApiEvents.length > 0
      ? Math.max(
          ...relevantApiEvents.map(
            (event) => event.event_time,
          ),
        )
      : null

  const criticalHostFindings = findings.filter(
    (finding) =>
      finding.status === 'open' &&
      findingStatus(finding.severity) === 'critical',
  )

  const warningHostFindings = findings.filter(
    (finding) =>
      finding.status === 'open' &&
      findingStatus(finding.severity) === 'warning',
  )

  const availableHostPacks = hostPacks.filter(
    (pack) =>
      !(pack.enabled && pack.can_activate) &&
      pack.discovery_status !== 'unavailable',
  )

  const unavailableHostPacks = hostPacks.filter(
    (pack) =>
      pack.discovery_status === 'unavailable',
  )

  const normalizedHostPackSearch =
    hostPackSearch.trim().toLowerCase()

  const filteredHostPacks = hostPacks
    .filter((pack) => {
      const active =
        pack.enabled &&
        pack.can_activate

      const unavailable =
        pack.discovery_status === 'unavailable'

      const available =
        !active &&
        !unavailable

      if (
        hostPackFilter === 'active' &&
        !active
      ) {
        return false
      }

      if (
        hostPackFilter === 'available' &&
        !available
      ) {
        return false
      }

      if (
        hostPackFilter === 'unavailable' &&
        !unavailable
      ) {
        return false
      }

      if (!normalizedHostPackSearch) {
        return true
      }

      const category =
        pack.category?.label ?? ''

      return (
        pack.name
          .toLowerCase()
          .includes(normalizedHostPackSearch) ||
        pack.id
          .toLowerCase()
          .includes(normalizedHostPackSearch) ||
        category
          .toLowerCase()
          .includes(normalizedHostPackSearch)
      )
    })
    .sort((left, right) => {
      const leftActive =
        left.enabled &&
        left.can_activate

      const rightActive =
        right.enabled &&
        right.can_activate

      const rank = (pack: HostPack) => {
        if (
          pack.discovery_status ===
          'needs_configuration'
        ) {
          return 0
        }

        if (
          !pack.enabled &&
          pack.can_activate
        ) {
          return 1
        }

        if (
          pack.enabled &&
          pack.can_activate
        ) {
          return 2
        }

        if (
          pack.discovery_status ===
          'unavailable'
        ) {
          return 3
        }

        return 4
      }

      const rankDifference =
        rank(left) - rank(right)

      if (rankDifference !== 0) {
        return rankDifference
      }

      if (
        leftActive !== rightActive
      ) {
        return leftActive ? -1 : 1
      }

      return left.name.localeCompare(
        right.name,
      )
    })

  const visibleHostFindings = findings.filter(
    (finding) =>
      hostFindingStatus === 'all' ||
      finding.status === hostFindingStatus,
  )

  function renderHostPackRow(pack: HostPack) {
    const active =
      pack.enabled &&
      pack.can_activate

    let statusLabel = 'Legacy'

    if (pack.discovery_status === 'detected') {
      statusLabel = 'Detected automatically'
    } else if (
      pack.discovery_status === 'configured'
    ) {
      statusLabel = 'Configured manually'
    } else if (
      pack.discovery_status ===
      'needs_configuration'
    ) {
      statusLabel = 'Needs configuration'
    } else if (
      pack.discovery_status === 'unavailable'
    ) {
      statusLabel = 'Unavailable'
    }

    return (
      <div
        className={`host-pack-row ${
          pack.discovery_status === 'unavailable'
            ? 'unavailable'
            : ''
        }`}
        key={pack.id}
      >
        <div className="host-pack-main">
          <div className="host-pack-title">
            <strong>{pack.name}</strong>

            <span className="host-pack-version">
              v{pack.version}
            </span>

            {pack.category?.label && (
              <span className="host-pack-category">
                {pack.category.label}
              </span>
            )}
          </div>

          <div className="host-pack-status">
            <span
              className={`host-pack-state ${
                pack.discovery_status
              }`}
            >
              {statusLabel}
            </span>

            {pack.detected_sources
              .filter(
                (source) => source.detected,
              )
              .map((source) => (
                <span
                  className="host-pack-source"
                  key={source.source_id}
                >
                  {source.source_type === 'journal'
                    ? `Journald · ${source.source_value}`
                    : source.source_value}
                </span>
              ))}
          </div>
        </div>

        <div className="host-pack-side">
          <span
            className={`host-pack-active ${
              active ? 'active' : 'inactive'
            }`}
          >
            {active ? 'Active' : 'Inactive'}
          </span>

          {hasPermission(
            currentUser,
            'hosts.manage',
          ) && (
            <div className="host-pack-actions">
              {pack.configuration_schema.length > 0 && (
                <button
                  type="button"
                  className="host-icon-button pack-state-action tooltip"
                  data-tooltip="Configure"
                  disabled={
                    hostPackChanging === pack.id
                  }
                  onClick={() =>
                    openHostPackConfig(pack)
                  }
                >
                  ⚙
                </button>
              )}

              <button
                type="button"
                className={`host-icon-button pack-state-action tooltip ${
                  active ? 'disable' : 'enable'
                }`}
                data-tooltip={
                  active
                    ? 'Disable pack'
                    : pack.can_activate
                      ? 'Activate pack'
                      : pack.discovery_status ===
                          'needs_configuration'
                        ? 'Configure this pack first'
                        : 'Pack unavailable'
                }
                disabled={
                  hostPackChanging === pack.id ||
                  (!active && !pack.can_activate)
                }
                onClick={() =>
                  void setHostPackEnabled(
                    pack,
                    !active,
                  )
                }
              >
                {hostPackChanging === pack.id
                  ? '…'
                  : '⏻'}
              </button>
            </div>
          )}
        </div>
      </div>
    )
  }


  async function loadHostData() {
    try {
      const [
        agentsResponse,
        eventsResponse,
        relevantResponse,
        findingsResponse,
        sourcesResponse,
        packsResponse,
      ] = await Promise.all([
        fetch('/api/v1/agents'),
        fetch(`/api/v1/events?agent_id=${agentId}&limit=200`),
        fetch(`/api/v1/relevant?agent_id=${agentId}&limit=200`),
        fetch(`/api/v1/findings?agent_id=${agentId}&limit=200`),
        fetch(`/api/v1/agents/${agentId}/sources`),
        fetch(`/api/v1/agents/${agentId}/packs`),
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

      if (packsResponse.ok) {
        const packsData: HostPackResponse =
          await packsResponse.json()

        setHostPacks(packsData.packs)
        setHostPacksError('')
      } else {
        setHostPacksError(
          `Could not load packs (${packsResponse.status}).`,
        )
      }

      setSourceDrafts((current) =>
        current.length === 0 ? sourcesData : current,
      )

      if (currentAgent) {
        setFindings(findingsData)
      } else {
        setFindings([])
      }
    } catch (err) {
      console.error('Could not load host details:', err)
    } finally {
      setLoading(false)
    }
  }

  function openHostPackConfig(pack: HostPack) {
    const currentSources =
      pack.config &&
      typeof pack.config === 'object' &&
      !Array.isArray(pack.config) &&
      typeof pack.config.sources === 'object' &&
      pack.config.sources !== null &&
      !Array.isArray(pack.config.sources)
        ? pack.config.sources as Record<
            string,
            Record<string, unknown>
          >
        : {}

    setHostPackConfigDraft(
      JSON.parse(
        JSON.stringify(currentSources),
      ),
    )
    setHostPackConfigError('')
    setConfiguringHostPack(pack)
  }

  function setHostPackConfigValue(
    sourceId: string,
    fieldId: string,
    value: unknown,
  ) {
    setHostPackConfigDraft((current) => ({
      ...current,
      [sourceId]: {
        ...(current[sourceId] ?? {}),
        [fieldId]: value,
      },
    }))
  }

  async function saveHostPackConfig() {
    if (
      !configuringHostPack ||
      !hasPermission(currentUser, 'hosts.manage')
    ) {
      return
    }

    for (
      const source
      of configuringHostPack.configuration_schema
    ) {
      for (const field of source.fields) {
        if (!field.required) {
          continue
        }

        const value =
          hostPackConfigDraft[source.source_id]?.[
            field.id
          ]

        const missing =
          value === undefined ||
          value === null ||
          value === ''

        if (missing) {
          setHostPackConfigError(
            `${field.label} is required.`,
          )
          return
        }
      }
    }

    setHostPackConfigSaving(true)
    setHostPackConfigError('')

    try {
      const existingConfig =
        configuringHostPack.config &&
        typeof configuringHostPack.config === 'object' &&
        !Array.isArray(configuringHostPack.config)
          ? configuringHostPack.config
          : {}

      const response = await fetch(
        `/api/v1/agents/${agentId}/packs/${encodeURIComponent(
          configuringHostPack.id,
        )}`,
        {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            enabled:
              configuringHostPack.enabled &&
              configuringHostPack.can_activate,
            config: {
              ...existingConfig,
              sources: hostPackConfigDraft,
            },
          }),
        },
      )

      if (!response.ok) {
        let detail = `Server returned ${response.status}`

        try {
          const body = await response.json()

          if (typeof body?.detail === 'string') {
            detail = body.detail
          }
        } catch {
          // Keep generic error.
        }

        throw new Error(detail)
      }

      const packName = configuringHostPack.name

      setConfiguringHostPack(null)
      await loadHostData()

      showToast(
        `${packName} configuration saved.`,
        'success',
      )
    } catch (err) {
      setHostPackConfigError(
        err instanceof Error
          ? err.message
          : 'Could not configure pack.',
      )
    } finally {
      setHostPackConfigSaving(false)
    }
  }


  async function setHostPackEnabled(
    pack: HostPack,
    enabled: boolean,
  ) {
    if (!hasPermission(currentUser, 'hosts.manage')) {
      return
    }

    setHostPackChanging(pack.id)
    setHostPacksError('')

    try {
      const response = await fetch(
        `/api/v1/agents/${agentId}/packs/${encodeURIComponent(
          pack.id,
        )}`,
        {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            enabled,
            config: pack.config ?? {},
          }),
        },
      )

      if (!response.ok) {
        let detail = `Server returned ${response.status}`

        try {
          const body = await response.json()

          if (typeof body?.detail === 'string') {
            detail = body.detail
          }
        } catch {
          // Keep generic error.
        }

        throw new Error(detail)
      }

      await loadHostData()

      showToast(
        enabled
          ? `${pack.name} activated.`
          : `${pack.name} disabled.`,
        'success',
      )
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message
          : 'Could not update pack.'

      showToast(
        message,
        'error',
      )
    } finally {
      setHostPackChanging(null)
    }
  }


  async function resolveHostFinding(
    findingId: number,
  ) {
    if (
      !hasPermission(
        currentUser,
        'findings.resolve',
      )
    ) {
      return
    }

    setResolvingHostFinding(findingId)

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

      await loadHostData()
    } catch (err) {
      console.error(
        'Could not resolve host finding:',
        err,
      )
    } finally {
      setResolvingHostFinding(null)
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
    if (!hasPermission(currentUser, 'hosts.manage')) {
      return
    }

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
    if (!hasPermission(currentUser, 'hosts.manage')) {
      return
    }
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
      showToast(
        'No changes to save.',
        'info',
      )
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
      showToast(
        'Changes saved.',
        'success',
      )
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
            <strong>{activeHostPacks.length}</strong>
            <span>Active packs</span>
          </div>
        </div>
      </div>

      <div className="host-tabs">
        {(['overview', 'logs', 'findings', 'packs'] as const).map(
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
                <h2>System</h2>
                <p>Host information</p>
              </div>
            </div>

            <div className="host-property">
              <span>Operating system</span>
              <strong>{agent.os_name || 'Unknown'}</strong>
            </div>

            <div className="host-property">
              <span>Machine</span>
              <strong>{agent.machine_type || 'Unknown'}</strong>
            </div>

            <div className="host-property">
              <span>Agent</span>
              <strong>{agent.agent_version || 'Unknown'}</strong>
            </div>

            <div className="host-property">
              <span>Last check-in</span>
              <strong>
                {agent.last_seen
                  ? formatAge(agent.last_seen)
                  : 'Never'}
              </strong>
            </div>
          </div>

          <div className="panel">
            <div className="panel-header">
              <div>
                <h2>Activity</h2>
                <p>Current FERPEK activity</p>
              </div>
            </div>

            <div className="host-property">
              <span>Relevant activity</span>
              <strong>{relevantApiEvents.length}</strong>
            </div>

            <div className="host-property">
              <span>Latest activity</span>
              <strong>
                {latestRelevantActivity
                  ? formatAge(latestRelevantActivity)
                  : 'None'}
              </strong>
            </div>

            <div className="host-property">
              <span>Critical findings</span>
              <strong>{criticalHostFindings.length}</strong>
            </div>

            <div className="host-property">
              <span>Warning findings</span>
              <strong>{warningHostFindings.length}</strong>
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

              <div className="host-source-dropdown">
                <button
                  type="button"
                  className={`host-source-trigger ${
                    sourceMenuOpen ? 'open' : ''
                  }`}
                  onClick={() =>
                    setSourceMenuOpen((open) => !open)
                  }
                  aria-haspopup="listbox"
                  aria-expanded={sourceMenuOpen}
                >
                  <span>
                    {selectedSource === 'all'
                      ? 'All sources'
                      : sources.find(
                          (source) =>
                            source.source_key === selectedSource,
                        )?.name ?? selectedSource}
                  </span>

                  <span className="host-source-chevron">
                    {sourceMenuOpen ? '⌃' : '⌄'}
                  </span>
                </button>

                {sourceMenuOpen && (
                  <div
                    className="host-source-menu"
                    role="listbox"
                  >
                    <button
                      type="button"
                      className={`host-source-option ${
                        selectedSource === 'all'
                          ? 'selected'
                          : ''
                      }`}
                      onClick={() => {
                        setSelectedSource('all')
                        setSourceMenuOpen(false)
                      }}
                    >
                      All sources
                    </button>

                    {sources
                      .filter((source) => source.send_events)
                      .map((source) => (
                        <button
                          type="button"
                          key={source.source_key}
                          className={`host-source-option ${
                            selectedSource === source.source_key
                              ? 'selected'
                              : ''
                          }`}
                          onClick={() => {
                            setSelectedSource(source.source_key)
                            setSourceMenuOpen(false)
                          }}
                        >
                          {source.name}
                        </button>
                      ))}
                  </div>
                )}
              </div>
            </div>

            <span className="live-indicator">
              Live
            </span>
          </div>

          <div className="host-log-panel">
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
        <div className="host-findings-list">
          <div className="host-findings-toolbar">
            <div className="finding-filter-group">
              <span className="finding-filter-label">
                Status
              </span>

              <div className="filter-buttons">
                {(['open', 'resolved', 'all'] as const).map(
                  (status) => (
                    <button
                      type="button"
                      className={`filter-button ${
                        hostFindingStatus === status
                          ? 'selected'
                          : ''
                      }`}
                      key={status}
                      onClick={() =>
                        setHostFindingStatus(status)
                      }
                    >
                      {status}
                    </button>
                  ),
                )}
              </div>
            </div>
          </div>

          {visibleHostFindings.length === 0 ? (
            <div className="host-findings-empty">
              {findings.length === 0
                ? 'No findings for this host.'
                : `No ${hostFindingStatus} findings for this host.`}
            </div>
          ) : (
            visibleHostFindings.map((finding) => (
              <article
                className={`host-finding-row ${findingStatus(
                  finding.severity,
                )}`}
                key={finding.id}
              >
                <div className="host-finding-main">
                  <div className="host-finding-meta">
                    <span
                      className={`severity ${findingStatus(
                        finding.severity,
                      )}`}
                    >
                      {finding.severity}
                    </span>

                    <span>{finding.service}</span>

                    <span className="separator">
                      ·
                    </span>

                    <span>
                      {finding.status === 'resolved'
                        ? 'Resolved'
                        : 'Open'}
                    </span>

                    {finding.status === 'resolved' &&
                      finding.resolved_at && (
                        <>
                          <span className="separator">
                            ·
                          </span>

                          <span>
                            {formatAge(
                              finding.resolved_at,
                            )}
                          </span>
                        </>
                      )}
                  </div>

                  <h3>{finding.title}</h3>

                  {finding.detail && (
                    <p>{finding.detail}</p>
                  )}

                  <div className="finding-stats">
                    <span>
                      <strong>First seen</strong>
                      {finding.first_seen
                        ? formatAge(
                            finding.first_seen,
                          )
                        : '—'}
                    </span>

                    <span>
                      <strong>Last seen</strong>
                      {finding.last_seen
                        ? formatAge(
                            finding.last_seen,
                          )
                        : '—'}
                    </span>

                    <span>
                      <strong>Detections</strong>
                      {finding.detection_count ?? 1}
                    </span>
                  </div>
                </div>

                <div className="finding-host-side">
                  {finding.status === 'open' &&
                    hasPermission(
                      currentUser,
                      'findings.resolve',
                    ) && (
                      <button
                        className="resolve-button"
                        disabled={
                          resolvingHostFinding ===
                          finding.id
                        }
                        onClick={() =>
                          void resolveHostFinding(
                            finding.id,
                          )
                        }
                      >
                        {resolvingHostFinding ===
                        finding.id
                          ? 'Resolving...'
                          : 'Resolve'}
                      </button>
                    )}
                </div>
              </article>
            ))
          )}
        </div>
      )}

      {activeTab === 'packs' && (
        <div className="host-packs">
          <div className="host-packs-header">
            <div>
              <h3>Monitoring packs</h3>
              <p>
                Packs available for this host and their
                current state.
              </p>
            </div>
          </div>

          {hostPacksError && (
            <div className="modal-error">
              {hostPacksError}
            </div>
          )}

          <div className="host-pack-toolbar">
            <div className="filter-buttons">
              {(
                [
                  ['all', 'All', hostPacks.length],
                  [
                    'active',
                    'Active',
                    activeHostPacks.length,
                  ],
                  [
                    'available',
                    'Available',
                    availableHostPacks.length,
                  ],
                  [
                    'unavailable',
                    'Unavailable',
                    unavailableHostPacks.length,
                  ],
                ] as const
              ).map(
                ([value, label, count]) => (
                  <button
                    type="button"
                    key={value}
                    className={`filter-button ${
                      hostPackFilter === value
                        ? 'selected'
                        : ''
                    }`}
                    onClick={() =>
                      setHostPackFilter(value)
                    }
                  >
                    {label}
                    <span className="host-pack-filter-count">
                      {count}
                    </span>
                  </button>
                ),
              )}
            </div>

            <input
              type="search"
              className="host-pack-search"
              placeholder="Search packs..."
              value={hostPackSearch}
              onChange={(event) =>
                setHostPackSearch(
                  event.target.value,
                )
              }
            />
          </div>

          <div className="host-pack-list">
            {hostPacks.length === 0 ? (
              <div className="empty-state">
                No packs are available for this host.
              </div>
            ) : filteredHostPacks.length === 0 ? (
              <div className="host-pack-empty">
                No packs match this view.
              </div>
            ) : (
              filteredHostPacks.map(
                renderHostPackRow,
              )
            )}
          </div>
        </div>
      )}

      {configuringHostPack && (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (
              event.target === event.currentTarget &&
              !hostPackConfigSaving
            ) {
              setConfiguringHostPack(null)
            }
          }}
        >
          <div className="modal host-pack-config-modal">
            <div className="modal-header">
              <div>
                <h2>Configure {configuringHostPack.name}</h2>
                <p>
                  Configure this pack for this host.
                </p>
              </div>

              <button
                type="button"
                className="modal-close"
                disabled={hostPackConfigSaving}
                onClick={() =>
                  setConfiguringHostPack(null)
                }
              >
                ×
              </button>
            </div>

            <div className="host-pack-config-fields">
              {configuringHostPack.configuration_schema.map(
                (source) => (
                  <div
                    className="host-pack-config-source"
                    key={source.source_id}
                  >
                    {configuringHostPack.configuration_schema
                      .length > 1 && (
                      <div className="host-pack-config-source-title">
                        {source.source_id}
                      </div>
                    )}

                    {source.fields.map((field) => {
                      const value =
                        hostPackConfigDraft[
                          source.source_id
                        ]?.[field.id]

                      if (field.type === 'boolean') {
                        return (
                          <label
                            className="host-pack-config-field boolean"
                            key={field.id}
                          >
                            <span>{field.label}</span>

                            <input
                              type="checkbox"
                              checked={Boolean(value)}
                              onChange={(event) =>
                                setHostPackConfigValue(
                                  source.source_id,
                                  field.id,
                                  event.target.checked,
                                )
                              }
                            />
                          </label>
                        )
                      }

                      if (field.type === 'select') {
                        return (
                          <label
                            className="host-pack-config-field"
                            key={field.id}
                          >
                            <span>
                              {field.label}
                              {field.required ? ' *' : ''}
                            </span>

                            <select
                              value={String(value ?? '')}
                              required={field.required}
                              onChange={(event) =>
                                setHostPackConfigValue(
                                  source.source_id,
                                  field.id,
                                  event.target.value,
                                )
                              }
                            >
                              <option value="">
                                Select...
                              </option>

                              {(field.options ?? []).map(
                                (option) => {
                                  const optionValue =
                                    typeof option === 'string'
                                      ? option
                                      : option.value

                                  const optionLabel =
                                    typeof option === 'string'
                                      ? option
                                      : option.label ??
                                        option.value

                                  return (
                                    <option
                                      key={optionValue}
                                      value={optionValue}
                                    >
                                      {optionLabel}
                                    </option>
                                  )
                                },
                              )}
                            </select>
                          </label>
                        )
                      }

                      return (
                        <label
                          className="host-pack-config-field"
                          key={field.id}
                        >
                          <span>
                            {field.label}
                            {field.required ? ' *' : ''}
                          </span>

                          <input
                            type={
                              field.type === 'secret'
                                ? 'password'
                                : field.type === 'number'
                                  ? 'number'
                                  : 'text'
                            }
                            value={String(value ?? '')}
                            required={field.required}
                            onChange={(event) =>
                              setHostPackConfigValue(
                                source.source_id,
                                field.id,
                                field.type === 'number'
                                  ? event.target.value === ''
                                    ? ''
                                    : Number(
                                        event.target.value,
                                      )
                                  : event.target.value,
                              )
                            }
                          />
                        </label>
                      )
                    })}
                  </div>
                ),
              )}
            </div>

            {hostPackConfigError && (
              <div className="modal-error">
                {hostPackConfigError}
              </div>
            )}

            <div className="modal-actions">
              <button
                type="button"
                className="secondary-button"
                disabled={hostPackConfigSaving}
                onClick={() =>
                  setConfiguringHostPack(null)
                }
              >
                Cancel
              </button>

              <button
                type="button"
                className="primary-button"
                disabled={hostPackConfigSaving}
                onClick={() =>
                  void saveHostPackConfig()
                }
              >
                {hostPackConfigSaving
                  ? 'Saving...'
                  : 'Save'}
              </button>
            </div>
          </div>
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

          {hasPermission(
            currentUser,
            'hosts.manage',
          ) && (
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
            )}
          </div>
      )}

    </section>
  )
}


function Findings({
  currentUser,
}: {
  currentUser: CurrentUser
}) {
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
          <div className="findings-empty-state">
            No findings detected.
          </div>
        ) : (
          findingGroups.map((group) => {
            const representative =
              group.findings[0]

            return (
              <article
                className={`finding-group ${group.severity}`}
                key={group.patternId}
              >
                <div className="finding-group-header">
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
                          {finding.status === 'resolved' ? (
                            <div className="finding-resolved-state">
                              <strong>Resolved</strong>

                              {finding.resolved_at && (
                                <span>
                                  {formatAge(
                                    finding.resolved_at,
                                  )}
                                </span>
                              )}
                            </div>
                          ) : (
                            hasPermission(
                              currentUser,
                              'findings.resolve',
                            ) && (
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
                            )
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
  const [filterEvents, setFilterEvents] = useState<ApiRelevantEvent[]>([])

  const [search, setSearch] = useState('')
  const [hostFilter, setHostFilter] = useState('all')
  const [serviceFilter, setServiceFilter] = useState('all')
  const [severityFilter, setSeverityFilter] = useState('all')
  const [rangeFilter, setRangeFilter] = useState('24h')

  const [customFrom, setCustomFrom] = useState('')
  const [customTo, setCustomTo] = useState('')

  async function loadFilterOptions() {
    try {
      const response = await fetch(
        '/api/v1/relevant?limit=500',
      )

      if (!response.ok) {
        throw new Error(`Server returned ${response.status}`)
      }

      setFilterEvents(await response.json())
    } catch (err) {
      console.error(
        'Could not load activity filter options:',
        err,
      )
    }
  }

  async function loadEvents() {
    try {
      const params = new URLSearchParams()

      params.set('limit', '500')

      if (hostFilter !== 'all') {
        params.set('agent_id', hostFilter)
      }

      if (serviceFilter !== 'all') {
        params.set('service', serviceFilter)
      }

      if (severityFilter !== 'all') {
        params.set('severity', severityFilter)
      }

      if (search.trim()) {
        params.set('search', search.trim())
      }

      const now = Math.floor(Date.now() / 1000)

      if (rangeFilter === '1h') {
        params.set(
          'since',
          String(now - 60 * 60),
        )
      }

      if (rangeFilter === '24h') {
        params.set(
          'since',
          String(now - 24 * 60 * 60),
        )
      }

      if (rangeFilter === '7d') {
        params.set(
          'since',
          String(now - 7 * 24 * 60 * 60),
        )
      }

      if (rangeFilter === 'custom') {
        if (customFrom) {
          params.set(
            'since',
            String(
              Math.floor(
                new Date(customFrom).getTime() / 1000,
              ),
            ),
          )
        }

        if (customTo) {
          params.set(
            'until',
            String(
              Math.floor(
                new Date(customTo).getTime() / 1000,
              ),
            ),
          )
        }
      }

      const response = await fetch(
        `/api/v1/relevant?${params.toString()}`,
      )

      if (!response.ok) {
        throw new Error(`Server returned ${response.status}`)
      }

      setEvents(await response.json())
    } catch (err) {
      console.error('Could not load activity:', err)
    }
  }

  useEffect(() => {
    void loadFilterOptions()

    const timer = window.setInterval(
      () => void loadFilterOptions(),
      30000,
    )

    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    void loadEvents()

    const timer = window.setInterval(
      () => void loadEvents(),
      5000,
    )

    return () => window.clearInterval(timer)
  }, [
    hostFilter,
    serviceFilter,
    severityFilter,
    rangeFilter,
    customFrom,
    customTo,
    search,
  ])

  const hosts = Array.from(
    new Map(
      filterEvents.map((event) => [
        event.agent_id,
        {
          id: event.agent_id,
          hostname: event.hostname,
        },
      ]),
    ).values(),
  ).sort((a, b) =>
    a.hostname.localeCompare(b.hostname),
  )

  const services = Array.from(
    new Set(
      filterEvents
        .map((event) => event.service)
        .filter(Boolean),
    ),
  ).sort((a, b) =>
    a.localeCompare(b),
  )

  return (
    <section className="activity-page">
      <div className="section-heading activity-heading">
        <div>
          <h2>Activity</h2>
          <p>
            Relevant events across monitored infrastructure
          </p>
        </div>
      </div>

      <div className="activity-toolbar">
        <input
          className="activity-search"
          type="search"
          placeholder="Search activity..."
          value={search}
          onChange={(event) =>
            setSearch(event.target.value)
          }
        />

        <select
          className="activity-filter"
          value={hostFilter}
          onChange={(event) =>
            setHostFilter(event.target.value)
          }
        >
          <option value="all">All hosts</option>

          {hosts.map((host) => (
            <option
              key={host.id}
              value={String(host.id)}
            >
              {host.hostname}
            </option>
          ))}
        </select>

        <select
          className="activity-filter"
          value={serviceFilter}
          onChange={(event) =>
            setServiceFilter(event.target.value)
          }
        >
          <option value="all">All services</option>

          {services.map((service) => (
            <option
              key={service}
              value={service}
            >
              {service}
            </option>
          ))}
        </select>

        <select
          className="activity-filter"
          value={severityFilter}
          onChange={(event) =>
            setSeverityFilter(event.target.value)
          }
        >
          <option value="all">All severities</option>
          <option value="critical">Critical</option>
          <option value="warning">Warning</option>
          <option value="info">Info</option>
        </select>

        <select
          className="activity-filter activity-range"
          value={rangeFilter}
          onChange={(event) =>
            setRangeFilter(event.target.value)
          }
        >
          <option value="1h">Last hour</option>
          <option value="24h">Last 24 hours</option>
          <option value="7d">Last 7 days</option>
          <option value="all">All retained</option>
          <option value="custom">Custom range</option>
        </select>
      </div>

      {rangeFilter === 'custom' && (
        <div className="activity-custom-range">
          <label>
            <span>From</span>
            <input
              type="datetime-local"
              value={customFrom}
              onChange={(event) =>
                setCustomFrom(event.target.value)
              }
            />
          </label>

          <label>
            <span>To</span>
            <input
              type="datetime-local"
              value={customTo}
              onChange={(event) =>
                setCustomTo(event.target.value)
              }
            />
          </label>
        </div>
      )}

      <div className="activity-list">
        {events.length === 0 ? (
          <div className="activity-empty">
            No relevant activity for the selected filters.
          </div>
        ) : (
          events.map((event) => (
            <article
              className={`activity-event ${findingStatus(
                event.severity,
              )}`}
              key={event.id}
            >
              <time className="activity-time">
                {formatAge(event.event_time)}
              </time>

              <div className="activity-event-main">
                <div className="activity-event-meta">
                  <strong>{event.hostname}</strong>

                  <span>·</span>

                  <span>
                    {event.service || event.pack_id}
                  </span>

                  <span
                    className={`severity ${findingStatus(
                      event.severity,
                    )}`}
                  >
                    {event.severity}
                  </span>
                </div>

                <h3>{event.title}</h3>

                {event.detail && (
                  <p>{event.detail}</p>
                )}

                <span className="activity-source">
                  {event.source_key}
                </span>
              </div>
            </article>
          ))
        )}
      </div>
    </section>
  )
}

function Packs({
  currentUser,
}: {
  currentUser: CurrentUser
}) {
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
    if (
      !hasPermission(currentUser, 'packs.manage') ||
      packStateChanging
    ) {
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

      showToast(
        `${pack.name} ${enabled ? "enabled" : "disabled"}.`,
        'info',
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
    if (
      !hasPermission(currentUser, 'packs.manage') ||
      !file ||
      packInstalling
    ) {
      return
    }

    setPackInstalling(true)
    setPackInstallError("")

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

      showToast(
        data?.id
          ? `Pack ${data.id} installed successfully.`
          : "Pack installed successfully.",
        'success',
      )
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
    if (
      !hasPermission(currentUser, 'packs.manage') ||
      !revertPack ||
      packReverting
    ) {
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

      showToast(
        `${packName} reverted to the official version.`,
        'success',
      )
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
    if (
      !hasPermission(currentUser, 'packs.manage') ||
      !deletePack ||
      packDeleting
    ) {
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

      showToast(
        `${packName} deleted successfully.`,
        'success',
      )
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
    if (!hasPermission(currentUser, 'packs.manage')) {
      return
    }

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
    if (
      !hasPermission(currentUser, 'packs.manage') ||
      !editPack
    ) {
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
    if (
      !hasPermission(currentUser, 'packs.manage') ||
      !editPack ||
      !editPackValidated
    ) {
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

      showToast(
        "Pack saved successfully.",
        'success',
      )

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
            on this FERPEK Lens instance.
          </p>
        </div>

        {hasPermission(
          currentUser,
          'packs.manage',
        ) && (
          <label
            className={
              packInstalling
                ? "primary-button action-button pack-install-button disabled"
                : "primary-button action-button pack-install-button"
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
        )}
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

      {hasPermission(
        currentUser,
        'packs.manage',
      ) && packInstallError && (
        <div className="pack-page-error">
          {packInstallError}
        </div>
      )}

      <div className="packs-page">
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
                <div className="pack-main">
                  <div className="pack-title-row">
                    <strong>{pack.name}</strong>

                    <span className="pack-version">
                      v{pack.version}
                    </span>

                    <span
                      className={`pack-status-text ${
                        getPackStatus(pack).className
                      }`}
                      title={
                        pack.blocked_reason === "policy"
                          ? "Blocked by pack policy"
                          : pack.blocked_reason ===
                              "server_incompatible"
                            ? "Not compatible with this FERPEK Server version"
                            : undefined
                      }
                    >
                      {getPackStatus(pack).label}
                    </span>

                    {pack.overridden && (
                      <span className="pack-local-override">
                        Local override
                      </span>
                    )}
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
                  {hasPermission(
                    currentUser,
                    'packs.manage',
                  ) && (
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
                        : "⏻"}
                    </button>
                  )}

                  <button
                    className="host-icon-button tooltip"
                    data-tooltip="View pack"
                    aria-label={`View ${pack.name}`}
                    onClick={() => void openPackViewer(pack)}
                  >
                    👁
                  </button>

                  {hasPermission(
                    currentUser,
                    'packs.manage',
                  ) && (
                    <button
                      className="host-icon-button tooltip"
                      data-tooltip="Edit pack"
                      aria-label={`Edit ${pack.name}`}
                      onClick={() => setEditPackWarning(pack)}
                    >
                      ✎
                    </button>
                  )}

                  {pack.overridden &&
                    hasPermission(
                      currentUser,
                      'packs.manage',
                    ) && (
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

                  {pack.capabilities?.delete &&
                    hasPermission(
                      currentUser,
                      'packs.manage',
                    ) && (
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
                from this FERPEK Lens instance.
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
                className="danger-button"
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
                className="primary-button"
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
                  v{editPack.version} · Changes are local to this FERPEK Lens instance
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
                className="primary-button"
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


type ApiUserAccount = {
  id: number
  username: string
  display_name: string | null
  email: string | null
  auth_type: string
  enabled: boolean
  created_at: number
  updated_at: number
  last_login_at: number | null
  groups: string[]
}

type ApiAccessGroup = {
  id: number
  name: string
  description: string | null
  builtin: boolean
  member_count: number
  permissions: string[]
  created_at: number
  updated_at: number
}

type ApiAccessPermission = {
  id: number
  permission_key: string
  description: string | null
}


function AccessPage({
  currentUser,
}: {
  currentUser: CurrentUser
}) {
  const canViewUsers = hasPermission(
    currentUser,
    'users.view',
  )

  const canManageUsers = hasPermission(
    currentUser,
    'users.manage',
  )

  const canViewGroups = hasPermission(
    currentUser,
    'groups.view',
  )

  const canManageGroups = hasPermission(
    currentUser,
    'groups.manage',
  )

  const [activeTab, setActiveTab] =
    useState<'users' | 'groups'>(
      canViewUsers ? 'users' : 'groups',
    )

  const [users, setUsers] = useState<ApiUserAccount[]>([])
  const [groups, setGroups] = useState<ApiAccessGroup[]>([])
  const [permissions, setPermissions] =
    useState<ApiAccessPermission[]>([])

  const [userSearch, setUserSearch] = useState('')
  const [userStatusFilter, setUserStatusFilter] =
    useState<'active' | 'disabled' | 'all'>('active')
  const [userAuthFilter, setUserAuthFilter] =
    useState<'all' | 'local' | 'ldap'>('all')

  const [groupModalOpen, setGroupModalOpen] =
    useState(false)
  const [editingGroup, setEditingGroup] =
    useState<ApiAccessGroup | null>(null)

  const [groupName, setGroupName] = useState('')
  const [groupDescription, setGroupDescription] =
    useState('')
  const [groupPermissionKeys, setGroupPermissionKeys] =
    useState<string[]>([])

  const [permissionSearch, setPermissionSearch] =
    useState('')

  const [groupSaving, setGroupSaving] = useState(false)
  const [groupSaveError, setGroupSaveError] =
    useState('')

  const [groupDeleting, setGroupDeleting] = useState(false)
  const [deleteGroupConfirmOpen, setDeleteGroupConfirmOpen] =
    useState(false)

  const [usersLoading, setUsersLoading] = useState(canViewUsers)
  const [groupsLoading, setGroupsLoading] = useState(canViewGroups)

  const [usersError, setUsersError] = useState('')
  const [groupsError, setGroupsError] = useState('')

  const [userModalOpen, setUserModalOpen] = useState(false)
  const [editingUser, setEditingUser] =
    useState<ApiUserAccount | null>(null)

  const [userUsername, setUserUsername] = useState('')
  const [userDisplayName, setUserDisplayName] = useState('')
  const [userEmail, setUserEmail] = useState('')
  const [userPassword, setUserPassword] = useState('')
  const [userEnabled, setUserEnabled] = useState(true)
  const [userGroupIds, setUserGroupIds] =
    useState<number[]>([])

  const [groupPickerOpen, setGroupPickerOpen] =
    useState(false)

  const [userSaving, setUserSaving] = useState(false)
  const [userSaveError, setUserSaveError] = useState('')

  const [userDeleting, setUserDeleting] = useState(false)
  const [deleteUserConfirmOpen, setDeleteUserConfirmOpen] =
    useState(false)

  const filteredUsers = users.filter((user) => {
    const search = userSearch.trim().toLowerCase()

    const matchesSearch =
      search.length === 0 ||
      user.username.toLowerCase().includes(search) ||
      (user.display_name ?? '').toLowerCase().includes(search) ||
      (user.email ?? '').toLowerCase().includes(search) ||
      user.groups.some((group) =>
        group.toLowerCase().includes(search),
      )

    const matchesStatus =
      userStatusFilter === 'all' ||
      (userStatusFilter === 'active' && user.enabled) ||
      (userStatusFilter === 'disabled' && !user.enabled)

    const matchesAuth =
      userAuthFilter === 'all' ||
      user.auth_type === userAuthFilter

    return matchesSearch && matchesStatus && matchesAuth
  })

  async function loadUsers() {
    if (!canViewUsers) {
      return
    }

    setUsersError('')

    try {
      const response = await fetch('/api/v1/users')

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      const data = await response.json()

      setUsers(
        Array.isArray(data?.users)
          ? data.users
          : [],
      )
    } catch {
      setUsersError('Could not load users.')
    } finally {
      setUsersLoading(false)
    }
  }

  async function loadGroups() {
    if (!canViewGroups) {
      return
    }

    setGroupsError('')

    try {
      const response = await fetch('/api/v1/groups')

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      const data = await response.json()

      setGroups(
        Array.isArray(data?.groups)
          ? data.groups
          : [],
      )
    } catch {
      setGroupsError('Could not load groups.')
    } finally {
      setGroupsLoading(false)
    }
  }

  async function loadPermissions() {
    if (!canViewGroups) {
      return
    }

    try {
      const response = await fetch('/api/v1/permissions')

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      const data = await response.json()

      setPermissions(
        Array.isArray(data?.permissions)
          ? data.permissions
          : [],
      )
    } catch {
      setPermissions([])
    }
  }

  useEffect(() => {
    void loadUsers()
    void loadGroups()
    void loadPermissions()
  }, [])

  function openNewUser() {
    if (!canManageUsers) {
      return
    }

    setEditingUser(null)
    setUserUsername('')
    setUserDisplayName('')
    setUserEmail('')
    setUserPassword('')
    setUserEnabled(true)
    setUserGroupIds([])
    setGroupPickerOpen(false)
    setUserSaveError('')
    setUserModalOpen(true)
  }

  function openEditUser(user: ApiUserAccount) {
    if (!canManageUsers) {
      return
    }

    setEditingUser(user)
    setUserUsername(user.username)
    setUserDisplayName(user.display_name || '')
    setUserEmail(user.email || '')
    setUserPassword('')
    setUserEnabled(user.enabled)

    const selectedGroupIds = groups
      .filter((group) =>
        user.groups.includes(group.name),
      )
      .map((group) => group.id)

    setUserGroupIds(selectedGroupIds)
    setGroupPickerOpen(false)
    setUserSaveError('')
    setUserModalOpen(true)
  }

  function toggleUserGroup(groupId: number) {
    const administratorsGroup = groups.find(
      (group) => group.name === 'Administrators',
    )

    const administratorsId = administratorsGroup?.id

    setUserGroupIds((current) => {
      const isSelected = current.includes(groupId)

      if (groupId === administratorsId) {
        return isSelected
          ? []
          : administratorsId !== undefined
            ? [administratorsId]
            : current
      }

      if (
        administratorsId !== undefined &&
        current.includes(administratorsId)
      ) {
        return current
      }

      return isSelected
        ? current.filter((id) => id !== groupId)
        : [...current, groupId]
    })
  }

  async function deleteUser() {
    if (
      !canManageUsers ||
      editingUser === null ||
      editingUser.id === currentUser.id
    ) {
      return
    }

    setUserDeleting(true)
    setUserSaveError('')

    try {
      const response = await fetch(
        `/api/v1/users/${editingUser.id}`,
        {
          method: 'DELETE',
        },
      )

      if (!response.ok) {
        let message = 'Could not delete user.'

        try {
          const data = await response.json()

          if (typeof data?.detail === 'string') {
            message = data.detail
          }
        } catch {
          // Keep generic message.
        }

        throw new Error(message)
      }

      setDeleteUserConfirmOpen(false)
      setUserModalOpen(false)
      setEditingUser(null)

      await loadUsers()
      await loadGroups()
    } catch (error) {
      setDeleteUserConfirmOpen(false)

      setUserSaveError(
        error instanceof Error
          ? error.message
          : 'Could not delete user.',
      )
    } finally {
      setUserDeleting(false)
    }
  }


  async function saveUser(
    event: React.FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault()

    if (!canManageUsers) {
      return
    }

    setUserSaving(true)
    setUserSaveError('')

    try {
      const isEditing = editingUser !== null

      const payload: Record<string, unknown> = {
        group_ids: userGroupIds,
      }

      if (isEditing) {
        payload.enabled = userEnabled

        if (editingUser?.auth_type === 'local') {
          payload.username = userUsername
          payload.display_name = userDisplayName
          payload.email = userEmail

          if (userPassword.length > 0) {
            payload.password = userPassword
          }
        }
      } else {
        payload.username = userUsername
        payload.display_name = userDisplayName
        payload.email = userEmail
        payload.password = userPassword
      }

      const response = await fetch(
        isEditing
          ? `/api/v1/users/${editingUser.id}`
          : '/api/v1/users',
        {
          method: isEditing ? 'PATCH' : 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(payload),
        },
      )

      if (!response.ok) {
        let message = 'Could not save user.'

        try {
          const data = await response.json()

          if (typeof data?.detail === 'string') {
            message = data.detail
          }
        } catch {
          // Keep generic message.
        }

        throw new Error(message)
      }

      setUserModalOpen(false)
      setEditingUser(null)
      await loadUsers()
      await loadGroups()
    } catch (error) {
      setUserSaveError(
        error instanceof Error
          ? error.message
          : 'Could not save user.',
      )
    } finally {
      setUserSaving(false)
    }
  }

  function openNewGroup() {
    if (!canManageGroups) {
      return
    }

    setEditingGroup(null)
    setGroupName('')
    setGroupDescription('')
    setGroupPermissionKeys([])
    setPermissionSearch('')
    setGroupSaveError('')
    setGroupModalOpen(true)
  }

  function openEditGroup(group: ApiAccessGroup) {
    if (!canManageGroups || group.builtin) {
      return
    }

    setEditingGroup(group)
    setGroupName(group.name)
    setGroupDescription(group.description || '')
    setGroupPermissionKeys([...group.permissions])
    setPermissionSearch('')
    setGroupSaveError('')
    setGroupModalOpen(true)
  }

  function permissionLabel(permissionKey: string) {
    const labels: Record<string, string> = {
      'users.view': 'View users',
      'users.manage': 'Manage users',

      'groups.view': 'View groups',
      'groups.manage': 'Manage groups',

      'hosts.view': 'View hosts',
      'hosts.manage': 'Manage hosts',
      'hosts.delete': 'Delete hosts',

      'findings.view': 'View findings',
      'findings.resolve': 'Resolve findings',

      'logs.view': 'View logs',

      'packs.view': 'View packs',
      'packs.manage': 'Manage packs',

      'settings.view': 'View settings',
      'settings.manage': 'Manage settings',
      'settings.auth_manage': 'Manage authentication',
    }

    return labels[permissionKey] ?? permissionKey
  }

  function toggleGroupPermission(permissionKey: string) {
    setGroupPermissionKeys((current) =>
      current.includes(permissionKey)
        ? current.filter(
            (key) => key !== permissionKey,
          )
        : [...current, permissionKey],
    )
  }

  async function deleteGroup() {
    if (
      !canManageGroups ||
      editingGroup === null ||
      editingGroup.builtin
    ) {
      return
    }

    setGroupDeleting(true)
    setGroupSaveError('')

    try {
      const response = await fetch(
        `/api/v1/groups/${editingGroup.id}`,
        {
          method: 'DELETE',
        },
      )

      if (!response.ok) {
        let message = 'Could not delete group.'

        try {
          const data = await response.json()

          if (typeof data?.detail === 'string') {
            message = data.detail
          }
        } catch {
          // Keep generic message.
        }

        throw new Error(message)
      }

      setDeleteGroupConfirmOpen(false)
      setGroupModalOpen(false)
      setEditingGroup(null)

      await loadGroups()
      await loadUsers()
    } catch (error) {
      setDeleteGroupConfirmOpen(false)

      setGroupSaveError(
        error instanceof Error
          ? error.message
          : 'Could not delete group.',
      )
    } finally {
      setGroupDeleting(false)
    }
  }


  async function saveGroup(
    event: React.FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault()

    if (!canManageGroups) {
      return
    }

    setGroupSaving(true)
    setGroupSaveError('')

    try {
      const isEditing = editingGroup !== null

      const response = await fetch(
        isEditing
          ? `/api/v1/groups/${editingGroup.id}`
          : '/api/v1/groups',
        {
          method: isEditing ? 'PATCH' : 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            name: groupName,
            description: groupDescription,
            permissions: groupPermissionKeys,
          }),
        },
      )

      if (!response.ok) {
        let message = 'Could not save group.'

        try {
          const data = await response.json()

          if (typeof data?.detail === 'string') {
            message = data.detail
          }
        } catch {
          // Keep generic message.
        }

        throw new Error(message)
      }

      setGroupModalOpen(false)
      setEditingGroup(null)

      await loadGroups()
    } catch (error) {
      setGroupSaveError(
        error instanceof Error
          ? error.message
          : 'Could not save group.',
      )
    } finally {
      setGroupSaving(false)
    }
  }


  return (
    <section className="access-page">
      <NavLink
        to="/settings"
        className="back-link"
      >
        ← Settings
      </NavLink>

      <div className="section-heading access-heading">
        <div>
          <h2>Access</h2>
          <p>
            Manage users, groups and permissions.
          </p>
        </div>

        {activeTab === 'users' &&
          canManageUsers && (
            <button
              type="button"
              className="primary-button action-button"
              onClick={openNewUser}
            >
              + Add user
            </button>
          )}

        {activeTab === 'groups' &&
          canManageGroups && (
            <button
              type="button"
              className="primary-button action-button"
              onClick={openNewGroup}
            >
              + Add group
            </button>
          )}
      </div>

      <div className="access-tabs">
        {canViewUsers && (
          <button
            type="button"
            className={
              activeTab === 'users'
                ? 'access-tab active'
                : 'access-tab'
            }
            onClick={() => setActiveTab('users')}
          >
            Users
          </button>
        )}

        {canViewGroups && (
          <button
            type="button"
            className={
              activeTab === 'groups'
                ? 'access-tab active'
                : 'access-tab'
            }
            onClick={() => setActiveTab('groups')}
          >
            Groups
          </button>
        )}
      </div>

      {activeTab === 'users' && canViewUsers && (
        <>
          <div className="access-users-toolbar">
            <input
              type="search"
              value={userSearch}
              onChange={(event) =>
                setUserSearch(event.target.value)
              }
              placeholder="Search users..."
              aria-label="Search users"
            />

            <select
              value={userStatusFilter}
              onChange={(event) =>
                setUserStatusFilter(
                  event.target.value as
                    | 'active'
                    | 'disabled'
                    | 'all',
                )
              }
              aria-label="Filter users by status"
            >
              <option value="active">Active</option>
              <option value="disabled">Disabled</option>
              <option value="all">All statuses</option>
            </select>

            <select
              value={userAuthFilter}
              onChange={(event) =>
                setUserAuthFilter(
                  event.target.value as
                    | 'all'
                    | 'local'
                    | 'ldap',
                )
              }
              aria-label="Filter users by authentication"
            >
              <option value="all">All authentication</option>
              <option value="local">Local</option>
              <option value="ldap">LDAP</option>
            </select>
          </div>

          <div className="panel access-list-panel">
            {usersLoading ? (
              <div className="empty-state">
                Loading users...
              </div>
            ) : usersError ? (
              <div className="modal-error">
                {usersError}
              </div>
            ) : users.length === 0 ? (
              <div className="empty-state">
                No users found.
              </div>
            ) : filteredUsers.length === 0 ? (
              <div className="empty-state">
                No users match the current filters.
              </div>
            ) : (
              <div className="access-list">
                {filteredUsers.map((user) => (
                <div
                  className="access-list-row"
                  key={user.id}
                >
                  <div className="access-user-main">
                    <div className="access-avatar">
                      {(user.display_name ||
                        user.username)
                        .charAt(0)
                        .toUpperCase()}
                    </div>

                    <div>
                      <strong>
                        {user.display_name ||
                          user.username}
                      </strong>

                      <span>
                        @{user.username}
                      </span>
                    </div>
                  </div>

                  <div className="access-list-meta">
                    <span className="access-auth-type">
                      {user.auth_type}
                    </span>

                    <span>
                      {user.groups.length > 0
                        ? user.groups.join(', ')
                        : 'No group'}
                    </span>

                    <span
                      className={
                        user.enabled
                          ? 'access-status enabled'
                          : 'access-status disabled'
                      }
                    >
                      {user.enabled
                        ? 'Enabled'
                        : 'Disabled'}
                    </span>

                    {canManageUsers && (
                      <button
                        type="button"
                        className="secondary-button compact-button"
                        onClick={() =>
                          openEditUser(user)
                        }
                      >
                        Edit
                      </button>
                    )}
                  </div>
                </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {activeTab === 'groups' && canViewGroups && (
        <div className="panel access-list-panel">
          {groupsLoading ? (
            <div className="empty-state">
              Loading groups...
            </div>
          ) : groupsError ? (
            <div className="modal-error">
              {groupsError}
            </div>
          ) : groups.length === 0 ? (
            <div className="empty-state">
              No groups found.
            </div>
          ) : (
            <div className="access-list">
              {groups.map((group) => (
                <div
                  className="access-group-row"
                  key={group.id}
                >
                  <div className="access-group-heading">
                    <div className="access-group-title-block">
                      <div className="access-group-title">
                        <strong>{group.name}</strong>

                        {group.builtin && (
                          <span className="access-builtin">
                            Built-in
                          </span>
                        )}
                      </div>

                      <div className="access-group-meta">
                        {group.description && (
                          <span>{group.description}</span>
                        )}

                        {group.description && (
                          <span aria-hidden="true">·</span>
                        )}

                        <span>
                          {group.member_count}{' '}
                          {group.member_count === 1
                            ? 'member'
                            : 'members'}
                        </span>
                      </div>
                    </div>

                    {canManageGroups &&
                      !group.builtin && (
                        <button
                          type="button"
                          className="secondary-button compact-button"
                          onClick={() =>
                            openEditGroup(group)
                          }
                        >
                          Edit
                        </button>
                      )}
                  </div>

                  {group.builtin ? (
                    <div className="access-group-full-access">
                      <span>Full access to FERPEK</span>
                      <small>
                        {group.permissions.length} permissions
                      </small>
                    </div>
                  ) : (
                    <div className="permission-chips access-group-permissions">
                      {group.permissions.length === 0 ? (
                        <span className="access-group-no-permissions">
                          No permissions assigned
                        </span>
                      ) : (
                        group.permissions.map(
                          (permission) => (
                            <span
                              className="permission-chip"
                              key={permission}
                              title={permission}
                            >
                              {permissionLabel(permission)}
                            </span>
                          ),
                        )
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {groupModalOpen && (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              setGroupModalOpen(false)
            }
          }}
        >
          <div className="modal access-group-modal">
            <div className="modal-header">
              <div>
                <h2>
                  {editingGroup
                    ? 'Edit group'
                    : 'Add group'}
                </h2>

                <p>
                  {editingGroup
                    ? `Manage ${editingGroup.name}.`
                    : 'Create a FERPEK access group.'}
                </p>
              </div>

              <button
                type="button"
                className="modal-close"
                onClick={() =>
                  setGroupModalOpen(false)
                }
                disabled={groupSaving}
              >
                ×
              </button>
            </div>

            <form
              className="access-user-form"
              onSubmit={saveGroup}
            >
              <label>
                <span>Group name</span>

                <input
                  type="text"
                  value={groupName}
                  minLength={1}
                  maxLength={128}
                  required
                  disabled={editingUser?.auth_type === 'ldap'}
                  onChange={(event) =>
                    setGroupName(event.target.value)
                  }
                />
              </label>

              <label>
                <span>Description</span>

                <input
                  type="text"
                  value={groupDescription}
                  maxLength={500}
                  placeholder="Optional"
                  onChange={(event) =>
                    setGroupDescription(
                      event.target.value,
                    )
                  }
                />
              </label>

              <div className="access-form-section">
                <div className="access-permissions-heading">
                  <div>
                    <span className="access-form-label">
                      Permissions
                    </span>

                    <small>
                      Select what members of this group
                      can access or change.
                    </small>
                  </div>

                  <span>
                    {groupPermissionKeys.length}
                    {' '}selected
                  </span>
                </div>

                <div className="access-permission-search">
                  <input
                    type="search"
                    value={permissionSearch}
                    placeholder="Search permissions..."
                    onChange={(event) =>
                      setPermissionSearch(
                        event.target.value,
                      )
                    }
                  />
                </div>

                <div className="access-permission-list">
                  {permissions
                    .filter((permission) => {
                      const query =
                        permissionSearch
                          .trim()
                          .toLowerCase()

                      if (!query) {
                        return true
                      }

                      return (
                        permissionLabel(
                          permission.permission_key,
                        )
                          .toLowerCase()
                          .includes(query) ||
                        permission.permission_key
                          .toLowerCase()
                          .includes(query) ||
                        (permission.description || '')
                          .toLowerCase()
                          .includes(query)
                      )
                    })
                    .map((permission) => (
                    <label
                      className="access-permission-option"
                      key={permission.permission_key}
                    >
                      <input
                        type="checkbox"
                        checked={groupPermissionKeys.includes(
                          permission.permission_key,
                        )}
                        onChange={() =>
                          toggleGroupPermission(
                            permission.permission_key,
                          )
                        }
                      />

                      <div>
                        <strong>
                          {permissionLabel(
                            permission.permission_key,
                          )}
                        </strong>

                        <span className="access-permission-key">
                          {permission.permission_key}
                        </span>

                        {permission.description && (
                          <span>
                            {permission.description}
                          </span>
                        )}
                      </div>
                    </label>
                  ))}
                </div>
              </div>

              {groupSaveError && (
                <div className="modal-error">
                  {groupSaveError}
                </div>
              )}

              <div className="modal-actions access-user-modal-actions">
                <div>
                  {editingGroup &&
                    !editingGroup.builtin && (
                      <button
                        type="button"
                        className="danger-button"
                        onClick={() =>
                          setDeleteGroupConfirmOpen(true)
                        }
                        disabled={
                          groupSaving || groupDeleting
                        }
                      >
                        Delete group
                      </button>
                    )}
                </div>

                <div className="access-user-modal-primary-actions">
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={() =>
                      setGroupModalOpen(false)
                    }
                    disabled={
                      groupSaving || groupDeleting
                    }
                  >
                    Cancel
                  </button>

                  <button
                    type="submit"
                    className="secondary-button"
                    disabled={
                      groupSaving || groupDeleting
                    }
                  >
                    {groupSaving
                      ? 'Saving...'
                      : editingGroup
                        ? 'Save changes'
                        : 'Create group'}
                  </button>
                </div>
              </div>
            </form>
          </div>
        </div>
      )}

      {deleteGroupConfirmOpen && editingGroup && (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              setDeleteGroupConfirmOpen(false)
            }
          }}
        >
          <div className="modal delete-user-modal">
            <div className="modal-header">
              <div>
                <h2>Delete group</h2>
                <p>
                  Permanently remove {editingGroup.name}
                  {' '}from FERPEK.
                </p>
              </div>

              <button
                type="button"
                className="modal-close"
                onClick={() =>
                  setDeleteGroupConfirmOpen(false)
                }
                disabled={groupDeleting}
              >
                ×
              </button>
            </div>

            <div className="delete-user-warning">
              {editingGroup.member_count > 0 ? (
                <>
                  {editingGroup.member_count}{' '}
                  {editingGroup.member_count === 1
                    ? 'user is'
                    : 'users are'} currently assigned to
                  this group. Their accounts will remain,
                  but this group membership will be removed.
                </>
              ) : (
                <>
                  This group has no members. Its permissions
                  and configuration will be permanently
                  removed.
                </>
              )}
            </div>

            <div className="modal-actions">
              <button
                type="button"
                className="secondary-button"
                onClick={() =>
                  setDeleteGroupConfirmOpen(false)
                }
                disabled={groupDeleting}
              >
                Cancel
              </button>

              <button
                type="button"
                className="danger-button"
                onClick={() => void deleteGroup()}
                disabled={groupDeleting}
              >
                {groupDeleting
                  ? 'Deleting...'
                  : 'Delete group'}
              </button>
            </div>
          </div>
        </div>
      )}

      {userModalOpen && (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              setUserModalOpen(false)
            }
          }}
        >
          <div className="modal access-user-modal">
            <div className="modal-header">
              <div>
                <h2>
                  {editingUser
                    ? 'Edit user'
                    : 'Add user'}
                </h2>

                <p>
                  {editingUser
                    ? `Manage @${editingUser.username}.`
                    : 'Create a local FERPEK account.'}
                </p>
              </div>

              <button
                type="button"
                className="modal-close"
                onClick={() =>
                  setUserModalOpen(false)
                }
              >
                ×
              </button>
            </div>

            <form
              className="access-user-form"
              onSubmit={saveUser}
            >
              <label>
                <span>Username</span>

                <input
                  type="text"
                  value={userUsername}
                  minLength={3}
                  maxLength={64}
                  pattern="[A-Za-z0-9._-]+"
                  required
                  onChange={(event) =>
                    setUserUsername(
                      event.target.value,
                    )
                  }
                />
              </label>

              <label>
                <span>Display name</span>

                <input
                  type="text"
                  value={userDisplayName}
                  maxLength={128}
                  disabled={editingUser?.auth_type === 'ldap'}
                  onChange={(event) =>
                    setUserDisplayName(
                      event.target.value,
                    )
                  }
                />
              </label>

              <label>
                <span>Email</span>

                <input
                  type="email"
                  value={userEmail}
                  maxLength={254}
                  disabled={editingUser?.auth_type === 'ldap'}
                  onChange={(event) =>
                    setUserEmail(
                      event.target.value,
                    )
                  }
                />
              </label>

              {editingUser?.auth_type === 'ldap' ? (
                <div className="access-form-section">
                  <span className="access-form-label">
                    Authentication
                  </span>

                  <div className="access-auth-provider">
                    <strong>LDAP</strong>
                    <span>
                      Identity and password are managed by the
                      directory.
                    </span>
                  </div>
                </div>
              ) : (
                <label>
                  <span>
                    {editingUser
                      ? 'New password'
                      : 'Password'}
                  </span>

                  <input
                    type="password"
                    value={userPassword}
                    minLength={12}
                    maxLength={256}
                    required={!editingUser}
                    autoComplete="new-password"
                    placeholder={
                      editingUser
                        ? 'Leave blank to keep current password'
                        : ''
                    }
                    onChange={(event) =>
                      setUserPassword(
                        event.target.value,
                      )
                    }
                  />
                </label>
              )}

              {canViewGroups && (
                <div className="access-form-section">
                  <span className="access-form-label">
                    Groups
                  </span>

                  <div className="access-selected-groups">
                    {userGroupIds.length === 0 ? (
                      <span className="access-no-groups">
                        No groups assigned
                      </span>
                    ) : (
                      userGroupIds.map((groupId) => {
                        const group = groups.find(
                          (candidate) =>
                            candidate.id === groupId,
                        )

                        if (!group) {
                          return null
                        }

                        return (
                          <span
                            className="access-group-chip"
                            key={group.id}
                          >
                            {group.name}

                            <button
                              type="button"
                              aria-label={`Remove ${group.name}`}
                              onClick={() =>
                                toggleUserGroup(group.id)
                              }
                            >
                              ×
                            </button>
                          </span>
                        )
                      })
                    )}

                    <div className="access-group-picker">
                      <button
                        type="button"
                        className="secondary-button compact-button"
                        onClick={() =>
                          setGroupPickerOpen(
                            (current) => !current,
                          )
                        }
                      >
                        + Add group
                      </button>

                      {groupPickerOpen && (
                        <div className="access-group-menu">
                          {groups.filter(
                            (group) =>
                              !userGroupIds.includes(
                                group.id,
                              ),
                          ).length === 0 ? (
                            <span className="access-group-menu-empty">
                              No groups available
                            </span>
                          ) : (
                            groups
                              .filter(
                                (group) =>
                                  !userGroupIds.includes(
                                    group.id,
                                  ),
                              )
                              .map((group) => {
                                const administratorsSelected =
                                  groups.some(
                                    (candidate) =>
                                      candidate.name ===
                                        'Administrators' &&
                                      userGroupIds.includes(
                                        candidate.id,
                                      ),
                                  )

                                const disabled =
                                  administratorsSelected &&
                                  group.name !==
                                    'Administrators'

                                return (
                                  <button
                                    type="button"
                                    className="access-group-menu-item"
                                    key={group.id}
                                    disabled={disabled}
                                    onClick={() => {
                                      toggleUserGroup(
                                        group.id,
                                      )
                                      setGroupPickerOpen(false)
                                    }}
                                  >
                                    <strong>
                                      {group.name}
                                    </strong>

                                    {group.description && (
                                      <span>
                                        {group.description}
                                      </span>
                                    )}
                                  </button>
                                )
                              })
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {editingUser && (
                <div className="access-form-section">
                  <span className="access-form-label">
                    Account status
                  </span>

                  <label className="access-enabled-option">
                    <input
                      type="checkbox"
                      checked={userEnabled}
                      disabled={
                        editingUser.id ===
                        currentUser.id
                      }
                      onChange={(event) =>
                        setUserEnabled(
                          event.target.checked,
                        )
                      }
                    />

                    <span>
                      Enabled
                    </span>
                  </label>

                  {editingUser.id ===
                    currentUser.id && (
                    <span className="access-form-help">
                      You cannot disable your own account.
                    </span>
                  )}
                </div>
              )}

              {userSaveError && (
                <div className="modal-error">
                  {userSaveError}
                </div>
              )}

              <div className="modal-actions access-user-modal-actions">
                <div>
                  {editingUser &&
                    editingUser.auth_type === 'local' &&
                    editingUser.id !== currentUser.id && (
                      <button
                        type="button"
                        className="danger-button"
                        onClick={() =>
                          setDeleteUserConfirmOpen(true)
                        }
                        disabled={
                          userSaving || userDeleting
                        }
                      >
                        Delete user
                      </button>
                    )}
                </div>

                <div className="access-user-modal-primary-actions">
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={() =>
                      setUserModalOpen(false)
                    }
                    disabled={
                      userSaving || userDeleting
                    }
                  >
                    Cancel
                  </button>

                  <button
                    type="submit"
                    className="primary-button"
                    disabled={
                      userSaving || userDeleting
                    }
                  >
                    {userSaving
                      ? 'Saving...'
                      : editingUser
                        ? 'Save changes'
                        : 'Create user'}
                  </button>
                </div>
              </div>
            </form>
          </div>
        </div>
      )}
      {deleteUserConfirmOpen && editingUser && (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              setDeleteUserConfirmOpen(false)
            }
          }}
        >
          <div className="modal delete-user-modal">
            <div className="modal-header">
              <div>
                <h2>Delete user</h2>
                <p>
                  Permanently remove @{editingUser.username}
                  {' '}from FERPEK.
                </p>
              </div>

              <button
                type="button"
                className="modal-close"
                onClick={() =>
                  setDeleteUserConfirmOpen(false)
                }
                disabled={userDeleting}
              >
                ×
              </button>
            </div>

            <div className="delete-user-warning">
              This action cannot be undone. The account,
              group memberships and active sessions will be
              removed.
            </div>

            <div className="modal-actions">
              <button
                type="button"
                className="secondary-button"
                onClick={() =>
                  setDeleteUserConfirmOpen(false)
                }
                disabled={userDeleting}
              >
                Cancel
              </button>

              <button
                type="button"
                className="danger-button"
                onClick={() => void deleteUser()}
                disabled={userDeleting}
              >
                {userDeleting
                  ? 'Deleting...'
                  : 'Delete user'}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}


function AuthenticationPage() {
  const [ldapStatus, setLdapStatus] = useState<
    'loading' | 'not-configured' | 'configured' | 'enabled'
  >('loading')

  useEffect(() => {
    async function loadLDAPStatus() {
      try {
        const response = await fetch(
          '/api/v1/settings/authentication/ldap',
          {
            credentials: 'include',
          },
        )

        if (!response.ok) {
          setLdapStatus('not-configured')
          return
        }

        const data = await response.json()

        if (data.enabled) {
          setLdapStatus('enabled')
        } else if (
          data.host ||
          data.base_dn ||
          data.bind_password_configured
        ) {
          setLdapStatus('configured')
        } else {
          setLdapStatus('not-configured')
        }
      } catch {
        setLdapStatus('not-configured')
      }
    }

    void loadLDAPStatus()
  }, [])

  const ldapStatusLabel =
    ldapStatus === 'enabled'
      ? 'Enabled'
      : ldapStatus === 'configured'
        ? 'Configured'
        : ldapStatus === 'loading'
          ? 'Loading...'
          : 'Not configured'

  return (
    <section className="settings-page">
      <div className="settings-content">
        <NavLink
          to="/settings"
          className="host-back-link"
        >
          ← Settings
        </NavLink>

        <div className="settings-group">
          <div className="settings-group-heading">
            <h2>Authentication providers</h2>
            <p>
              Configure how users sign in to this FERPEK Lens instance.
            </p>
          </div>

          <div className="panel settings-list-panel">
            <div className="settings-list-row">
              <div>
                <h3>Local authentication</h3>
                <p>
                  FERPEK Lens local accounts remain available for
                  administration and recovery.
                </p>
              </div>

              <span className="auth-provider-status enabled">
                Enabled
              </span>
            </div>

            <NavLink
              to="/settings/authentication/ldap"
              className="settings-list-row settings-navigation-row"
            >
              <div>
                <h3>Directory authentication</h3>
                <p>
                  Authenticate users with LDAP or Microsoft Active Directory.
                </p>
              </div>

              <div className="auth-provider-side">
                <span
                  className={`auth-provider-status ${
                    ldapStatus === 'enabled' ? 'enabled' : ''
                  }`}
                >
                  {ldapStatusLabel}
                </span>

                <span className="settings-row-arrow">
                  ›
                </span>
              </div>
            </NavLink>
          </div>
        </div>

        <div className="auth-break-glass-note">
          <strong>Local recovery access</strong>
          <span>
            Local administrator accounts remain available even when
            an external authentication provider is enabled.
          </span>
        </div>
      </div>
    </section>
  )
}


function LDAPSettingsPage() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)

  const [enabled, setEnabled] = useState(false)
  const [providerType, setProviderType] =
    useState<'ldap' | 'active_directory'>('ldap')
  const [host, setHost] = useState('')
  const [port, setPort] = useState(389)
  const [security, setSecurity] = useState('plain')
  const [baseDn, setBaseDn] = useState('')
  const [bindDn, setBindDn] = useState('')
  const [bindPassword, setBindPassword] = useState('')
  const [
    bindPasswordConfigured,
    setBindPasswordConfigured,
  ] = useState(false)
  const [userSearchBase, setUserSearchBase] = useState('')
  const [userFilter, setUserFilter] =
    useState('(uid={username})')
  const [usernameAttribute, setUsernameAttribute] =
    useState('uid')

  const [availableGroups, setAvailableGroups] = useState<
    Array<{
      id: number
      name: string
      builtin: boolean
    }>
  >([])

  const [groupMappings, setGroupMappings] = useState<
    Array<{
      directoryGroup: string
      groupId: number | ''
    }>
  >([])

  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const [testUsername, setTestUsername] = useState('')
  const [testPassword, setTestPassword] = useState('')
  const [testUserLoading, setTestUserLoading] = useState(false)
  const [testUserMessage, setTestUserMessage] = useState('')
  const [testUserError, setTestUserError] = useState('')
  const [testUserResult, setTestUserResult] = useState<{
    username: string
    display_name: string
    email: string
    dn: string
    groups?: string[]
  } | null>(null)

  useEffect(() => {
    async function loadLDAPSettings() {
      try {
        const response = await fetch(
          '/api/v1/settings/authentication/ldap',
          {
            credentials: 'include',
          },
        )

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`)
        }

        const data = await response.json()

        setEnabled(Boolean(data.enabled))
        setProviderType(
          data.provider_type === 'active_directory'
            ? 'active_directory'
            : 'ldap',
        )
        setHost(data.host ?? '')
        setPort(Number(data.port ?? 389))
        setSecurity(data.security ?? 'plain')
        setBaseDn(data.base_dn ?? '')
        setBindDn(data.bind_dn ?? '')
        setBindPasswordConfigured(
          Boolean(data.bind_password_configured),
        )
        setUserSearchBase(data.user_search_base ?? '')
        setUserFilter(
          data.user_filter ?? '(uid={username})',
        )
        setUsernameAttribute(
          data.username_attribute ?? 'uid',
        )

        setAvailableGroups(
          Array.isArray(data.available_groups)
            ? data.available_groups
            : [],
        )

        const loadedMappings =
          data.group_mappings &&
          typeof data.group_mappings === 'object'
            ? Object.entries(data.group_mappings)
            : []

        setGroupMappings(
          loadedMappings.map(
            ([directoryGroup, groupId]) => ({
              directoryGroup,
              groupId:
                typeof groupId === 'number'
                  ? groupId
                  : Number(groupId),
            }),
          ),
        )
      } catch {
        setError('Could not load LDAP settings.')
      } finally {
        setLoading(false)
      }
    }

    void loadLDAPSettings()
  }, [])

  async function testLDAPConnection() {
    setTesting(true)
    setMessage('')
    setError('')

    const payload: Record<string, unknown> = {
      enabled,
      provider_type: providerType,
      host,
      port,
      security,
      base_dn: baseDn,
      bind_dn: bindDn,
      user_search_base: userSearchBase,
      user_filter: userFilter,
      username_attribute: usernameAttribute,
    }

    if (bindPassword) {
      payload.bind_password = bindPassword
    }

    try {
      const response = await fetch(
        '/api/v1/settings/authentication/ldap/test',
        {
          method: 'POST',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(payload),
        },
      )

      const data = await response
        .json()
        .catch(() => null)

      if (!response.ok) {
        throw new Error(
          typeof data?.detail === 'string'
            ? data.detail
            : providerType === 'active_directory'
              ? 'Active Directory connection failed.'
              : 'LDAP connection failed.',
        )
      }

      showToast(
        data?.message ||
          (providerType === 'active_directory'
            ? 'Active Directory connection successful.'
            : 'LDAP connection successful.'),
        'success',
      )
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'LDAP connection failed.',
      )
    } finally {
      setTesting(false)
    }
  }


  async function testLDAPUser() {
    if (!testUsername.trim() || !testPassword) {
      setTestUserResult(null)
      setTestUserMessage('')
      setTestUserError(
        'Enter a username and password to test authentication.',
      )
      return
    }

    setTestUserLoading(true)
    setTestUserResult(null)
    setTestUserMessage('')
    setTestUserError('')

    try {
      const response = await fetch(
        '/api/v1/settings/authentication/ldap/test-user',
        {
          method: 'POST',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            username: testUsername.trim(),
            password: testPassword,
          }),
        },
      )

      const data = await response
        .json()
        .catch(() => null)

      if (!response.ok) {
        throw new Error(
          typeof data?.detail === 'string'
            ? data.detail
            : 'LDAP user authentication failed.',
        )
      }

      setTestUserResult(data.user ?? null)
      showToast(
        data?.message ||
          'LDAP user authentication successful.',
        'success',
      )
      setTestPassword('')
    } catch (err) {
      setTestUserError(
        err instanceof Error
          ? err.message
          : 'LDAP user authentication failed.',
      )
    } finally {
      setTestUserLoading(false)
    }
  }


  async function saveLDAPSettings(
    event: React.FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault()

    setSaving(true)
    setMessage('')
    setError('')

    const serializedGroupMappings =
      providerType === 'active_directory'
        ? Object.fromEntries(
            groupMappings
              .filter(
                (mapping) =>
                  mapping.directoryGroup.trim() &&
                  mapping.groupId !== '',
              )
              .map((mapping) => [
                mapping.directoryGroup.trim(),
                Number(mapping.groupId),
              ]),
          )
        : {}

    const payload: Record<string, unknown> = {
      enabled,
      provider_type: providerType,
      host,
      port,
      security,
      base_dn: baseDn,
      bind_dn: bindDn,
      user_search_base: userSearchBase,
      user_filter: userFilter,
      username_attribute: usernameAttribute,
      group_mappings: serializedGroupMappings,
    }

    if (bindPassword) {
      payload.bind_password = bindPassword
    }

    try {
      const response = await fetch(
        '/api/v1/settings/authentication/ldap',
        {
          method: 'PUT',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(payload),
        },
      )

      if (!response.ok) {
        let detail = 'Could not save LDAP settings.'

        try {
          const data = await response.json()

          if (typeof data?.detail === 'string') {
            detail = data.detail
          }
        } catch {
          // Keep generic message.
        }

        throw new Error(detail)
      }

      const data = await response.json()

      setBindPassword('')
      setBindPasswordConfigured(
        Boolean(data.bind_password_configured),
      )

      showToast(
        providerType === 'active_directory'
          ? 'Active Directory settings saved.'
          : 'LDAP settings saved.',
        'success',
      )
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Could not save LDAP settings.',
      )
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="settings-page">
      <div className="settings-content">
        <NavLink
          to="/settings/authentication"
          className="host-back-link"
        >
          ← Authentication
        </NavLink>

        <div className="settings-group">
          <div className="settings-group-heading">
            <h2>Directory authentication</h2>
            <p>
              Connect FERPEK Lens to an LDAP directory or Microsoft
              Active Directory for user authentication.
            </p>
          </div>

          {loading ? (
            <div className="panel ldap-settings-card">
              <p className="ldap-loading">
                Loading LDAP settings...
              </p>
            </div>
          ) : (
            <>
              <form
                className="panel ldap-settings-card"
                onSubmit={saveLDAPSettings}
              >
              <div className="ldap-field-stack">
                <label className="ldap-field">
                  <span>Directory type</span>
                  <select
                    value={providerType}
                    onChange={(event) => {
                      const nextProvider =
                        event.target.value === 'active_directory'
                          ? 'active_directory'
                          : 'ldap'

                      setProviderType(nextProvider)

                      if (nextProvider === 'active_directory') {
                        setUserFilter(
                          '(|(sAMAccountName={username})(userPrincipalName={username}))',
                        )
                        setUsernameAttribute('sAMAccountName')
                      } else {
                        setUserFilter('(uid={username})')
                        setUsernameAttribute('uid')
                      }

                      setMessage('')
                      setError('')
                      setTestUserResult(null)
                      setTestUserMessage('')
                      setTestUserError('')
                    }}
                  >
                    <option value="ldap">
                      Generic LDAP
                    </option>
                    <option value="active_directory">
                      Microsoft Active Directory
                    </option>
                  </select>

                  <small>
                    {providerType === 'active_directory'
                      ? 'Uses Microsoft Active Directory conventions.'
                      : 'Uses standard LDAP directory conventions.'}
                  </small>
                </label>
              </div>

              <div className="ldap-setting-row ldap-enabled-row">
                <div>
                  <strong>
                    {providerType === 'active_directory'
                      ? 'Active Directory authentication'
                      : 'LDAP authentication'}
                  </strong>
                  <span>
                    Allow users to authenticate using this directory.
                  </span>
                </div>

                <label className="setting-switch">
                  <input
                    type="checkbox"
                    checked={enabled}
                    onChange={(event) =>
                      setEnabled(event.target.checked)
                    }
                  />
                  <span className="setting-switch-track" />
                </label>
              </div>

              <div className="ldap-form-grid">
                <label className="ldap-field ldap-field-grow">
                  <span>Host</span>
                  <input
                    value={host}
                    onChange={(event) =>
                      setHost(event.target.value)
                    }
                    placeholder={
                      providerType === 'active_directory'
                        ? 'dc01.example.com'
                        : 'ldap.example.com'
                    }
                  />
                </label>

                <label className="ldap-field ldap-port-field">
                  <span>Port</span>
                  <input
                    type="number"
                    min="1"
                    max="65535"
                    value={port}
                    onChange={(event) =>
                      setPort(Number(event.target.value))
                    }
                  />
                </label>

                <label className="ldap-field ldap-security-field">
                  <span>Security</span>
                  <select
                    value={security}
                    onChange={(event) => {
                      const nextSecurity = event.target.value
                      const previousSecurity = security

                      setSecurity(nextSecurity)

                      const previousDefaultPort =
                        previousSecurity === 'ldaps'
                          ? 636
                          : 389

                      if (port === previousDefaultPort) {
                        setPort(
                          nextSecurity === 'ldaps'
                            ? 636
                            : 389,
                        )
                      }
                    }}
                  >
                    <option value="plain">Plain LDAP</option>
                    <option value="starttls">StartTLS</option>
                    <option value="ldaps">LDAPS</option>
                  </select>
                </label>
              </div>

              <div className="ldap-field-stack">
                <label className="ldap-field">
                  <span>Base DN</span>
                  <input
                    value={baseDn}
                    onChange={(event) =>
                      setBaseDn(event.target.value)
                    }
                    placeholder={
                      providerType === 'active_directory'
                        ? 'DC=example,DC=com'
                        : 'dc=example,dc=com'
                    }
                  />
                </label>

                <label className="ldap-field">
                  <span>Bind DN</span>
                  <input
                    value={bindDn}
                    onChange={(event) =>
                      setBindDn(event.target.value)
                    }
                    placeholder={
                      providerType === 'active_directory'
                        ? 'CN=svc-ferpek,OU=Service Accounts,DC=example,DC=com'
                        : 'cn=service,dc=example,dc=com'
                    }
                  />
                </label>

                <label className="ldap-field">
                  <span>Bind password</span>
                  <input
                    type="password"
                    autoComplete="new-password"
                    value={bindPassword}
                    onChange={(event) =>
                      setBindPassword(event.target.value)
                    }
                    placeholder={
                      bindPasswordConfigured
                        ? 'Password already configured'
                        : 'Enter bind password'
                    }
                  />

                  <small>
                    {bindPasswordConfigured
                      ? 'Leave blank to keep the current password.'
                      : 'Stored encrypted by FERPEK.'}
                  </small>
                </label>
              </div>

              <div className="ldap-subsection">
                <div className="ldap-subsection-heading">
                  <strong>User lookup</strong>
                  <span>
                    Define how FERPEK Lens locates directory users.
                  </span>
                </div>

                <div className="ldap-field-stack">
                  <label className="ldap-field">
                    <span>User search base</span>
                    <input
                      value={userSearchBase}
                      onChange={(event) =>
                        setUserSearchBase(event.target.value)
                      }
                      placeholder={
                        providerType === 'active_directory'
                          ? 'OU=Users,DC=example,DC=com'
                          : 'ou=users,dc=example,dc=com'
                      }
                    />
                  </label>

                  <label className="ldap-field">
                    <span>User filter</span>
                    <input
                      value={userFilter}
                      onChange={(event) =>
                        setUserFilter(event.target.value)
                      }
                      placeholder={
                      providerType === 'active_directory'
                        ? '(|(sAMAccountName={username})(userPrincipalName={username}))'
                        : '(uid={username})'
                    }
                    />
                    <small>
                      Use {'{username}'} where the login name should
                      be inserted.
                    </small>
                  </label>

                  <label className="ldap-field">
                    <span>Username attribute</span>
                    <input
                      value={usernameAttribute}
                      onChange={(event) =>
                        setUsernameAttribute(event.target.value)
                      }
                      placeholder={
                      providerType === 'active_directory'
                        ? 'sAMAccountName'
                        : 'uid'
                    }
                    />
                  </label>
                </div>
              </div>

              {providerType === 'active_directory' && (
                <div className="ldap-subsection ldap-group-mapping-section">
                  <div className="ldap-group-mapping-header">
                    <div className="ldap-subsection-heading">
                      <strong>Group mappings</strong>
                      <span>
                        Map Active Directory groups to FERPEK access groups.
                        Memberships are synchronized when users sign in.
                      </span>
                    </div>

                    <button
                      type="button"
                      className="secondary-button ldap-group-mapping-add"
                      onClick={() =>
                        setGroupMappings((current) => [
                          ...current,
                          {
                            directoryGroup: '',
                            groupId: '',
                          },
                        ])
                      }
                    >
                      + Add mapping
                    </button>
                  </div>

                  <div className="ldap-group-mapping-list">
                    {groupMappings.length === 0 ? (
                      <div className="ldap-group-mapping-empty">
                        No group mappings configured.
                      </div>
                    ) : (
                      groupMappings.map((mapping, index) => (
                        <div
                          className="ldap-group-mapping-row"
                          key={index}
                        >
                          <label className="ldap-field">
                            <span>Active Directory group DN</span>
                            <input
                              value={mapping.directoryGroup}
                              onChange={(event) => {
                                const value = event.target.value

                                setGroupMappings((current) =>
                                  current.map((candidate, candidateIndex) =>
                                    candidateIndex === index
                                      ? {
                                          ...candidate,
                                          directoryGroup: value,
                                        }
                                      : candidate,
                                  ),
                                )
                              }}
                              placeholder="CN=FERPEK-Admins,OU=Groups,DC=example,DC=com"
                            />
                          </label>

                          <label className="ldap-field">
                            <span>FERPEK group</span>
                            <select
                              value={mapping.groupId}
                              onChange={(event) => {
                                const value = event.target.value

                                setGroupMappings((current) =>
                                  current.map((candidate, candidateIndex) =>
                                    candidateIndex === index
                                      ? {
                                          ...candidate,
                                          groupId: value
                                            ? Number(value)
                                            : '',
                                        }
                                      : candidate,
                                  ),
                                )
                              }}
                            >
                              <option value="">
                                Select group...
                              </option>

                              {availableGroups.map((group) => (
                                <option
                                  value={group.id}
                                  key={group.id}
                                >
                                  {group.name}
                                  {group.builtin
                                    ? ' (built-in)'
                                    : ''}
                                </option>
                              ))}
                            </select>
                          </label>

                          <button
                            type="button"
                            className="secondary-button ldap-group-mapping-remove"
                            aria-label="Remove group mapping"
                            onClick={() =>
                              setGroupMappings((current) =>
                                current.filter(
                                  (_, candidateIndex) =>
                                    candidateIndex !== index,
                                ),
                              )
                            }
                          >
                            ×
                          </button>
                        </div>
                      ))
                    )}
                  </div>

                </div>
              )}

              <div className="ldap-subsection ldap-test-user-section">
                <div className="ldap-subsection-heading">
                  <strong>Test user</strong>
                  <span>
                    Verify that FERPEK Lens can find and authenticate
                    a directory user.
                  </span>
                </div>

                <div className="ldap-test-user-grid">
                  <label className="ldap-field">
                    <span>Username</span>
                    <input
                      value={testUsername}
                      onChange={(event) =>
                        setTestUsername(event.target.value)
                      }
                      placeholder="alice"
                      autoComplete="off"
                    />
                  </label>

                  <label className="ldap-field">
                    <span>Password</span>
                    <input
                      type="password"
                      value={testPassword}
                      onChange={(event) =>
                        setTestPassword(event.target.value)
                      }
                      placeholder="User password"
                      autoComplete="new-password"
                    />
                  </label>

                  <button
                    type="button"
                    className="secondary-button ldap-test-user-button"
                    onClick={() => void testLDAPUser()}
                    disabled={testUserLoading}
                  >
                    {testUserLoading
                      ? 'Testing...'
                      : 'Test user'}
                  </button>
                </div>

                {(testUserMessage ||
                  testUserError ||
                  testUserResult) && (
                  <div className="ldap-test-user-result">
                    {testUserMessage && (
                      <p className="save-message">
                        {testUserMessage}
                      </p>
                    )}

                    {testUserError && (
                      <p className="save-error">
                        {testUserError}
                      </p>
                    )}

                    {testUserResult && (
                      <div className="ldap-test-user-details">
                        <strong>
                          {testUserResult.display_name ||
                            testUserResult.username}
                        </strong>

                        <span>
                          {testUserResult.username}
                          {testUserResult.email
                            ? ` · ${testUserResult.email}`
                            : ''}
                        </span>

                        <small>
                          {testUserResult.dn}
                        </small>
                      </div>
                    )}
                  </div>
                )}
              </div>

            </form>

              <div className="ldap-actions ldap-actions-outside">
                <div>
                  {message && (
                    <p className="save-message">{message}</p>
                  )}

                  {error && (
                    <p className="save-error">{error}</p>
                  )}
                </div>

                <div className="ldap-action-buttons">
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={() => void testLDAPConnection()}
                    disabled={testing || saving}
                  >
                    {testing
                      ? 'Testing...'
                      : 'Test connection'}
                  </button>

                  <button
                    type="button"
                    className="secondary-button settings-save-button"
                    disabled={saving || testing}
                    onClick={() => {
                      const form = document.querySelector(
                        '.ldap-settings-card',
                      ) as HTMLFormElement | null

                      form?.requestSubmit()
                    }}
                  >
                    {saving ? 'Saving...' : 'Save changes'}
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  )
}

function Settings({
  currentUser,
  theme,
  onThemeChange,
}: {
  currentUser: CurrentUser
  theme: ThemePreference
  onThemeChange: (theme: ThemePreference) => void
}) {
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
    if (!hasPermission(currentUser, 'settings.manage')) {
      return
    }

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

      showToast(
        "Pack settings saved.",
        'success',
      )
    } catch (error) {
      showToast(
        "Could not save pack settings.",
        'error',
      )
    } finally {
      setPackSettingsSaving(false)
    }
  }


  async function saveRetentionSettings() {
    if (!hasPermission(currentUser, 'settings.manage')) {
      return
    }

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

      showToast(
        "Retention settings saved.",
        'success',
      )
    } catch (error) {
      showToast(
        "Could not save retention settings.",
        'error',
      )
    } finally {
      setRetentionSaving(false)
    }
  }

  return (
    <section className="settings-page">
      <div className="settings-content">
        <div className="settings-sections">

          <div className="settings-group">
            <div className="settings-group-heading">
              <h2>General</h2>
              <p>General FERPEK configuration and appearance.</p>
            </div>

            <div className="panel settings-list-panel">
              <div className="settings-list-row">
                <div>
                  <h3>Appearance</h3>
                  <p>Choose how FERPEK looks on this browser.</p>
                </div>

                <div className="theme-segmented">
                  {(['light', 'dark', 'system'] as ThemePreference[]).map(
                    (option) => (
                      <button
                        type="button"
                        key={option}
                        className={
                          theme === option
                            ? 'active'
                            : ''
                        }
                        onClick={() =>
                          onThemeChange(option)
                        }
                      >
                        {option.charAt(0).toUpperCase() +
                          option.slice(1)}
                      </button>
                    ),
                  )}
                </div>
              </div>

              {hasPermission(currentUser, 'settings.view') && (
                <>
                  <div className="settings-list-row settings-navigation-row">
                    <div>
                      <h3>Server</h3>
                      <p>
                        Server identity, URL and connectivity settings.
                      </p>
                    </div>

                    {hasPermission(
                      currentUser,
                      'settings.manage',
                    ) && (
                      <span className="settings-row-arrow">
                        ›
                      </span>
                    )}
                  </div>

                  <div className="settings-list-row settings-navigation-row">
                    <div>
                      <h3>Agents</h3>
                      <p>
                        Enrollment and agent configuration.
                      </p>
                    </div>

                    {hasPermission(
                      currentUser,
                      'settings.manage',
                    ) && (
                      <span className="settings-row-arrow">
                        ›
                      </span>
                    )}
                  </div>

                  <div className="settings-list-row settings-navigation-row">
                    <div>
                      <h3>Detection</h3>
                      <p>
                        Patterns and finding behaviour.
                      </p>
                    </div>

                    {hasPermission(
                      currentUser,
                      'settings.manage',
                    ) && (
                      <span className="settings-row-arrow">
                        ›
                      </span>
                    )}
                  </div>
                </>
              )}
            </div>
          </div>

          {(hasPermission(currentUser, 'users.view') ||
            hasPermission(currentUser, 'groups.view') ||
            hasPermission(
              currentUser,
              'settings.auth_manage',
            )) && (
            <div className="settings-group">
              <div className="settings-group-heading">
                <h2>Access &amp; authentication</h2>
                <p>
                  Users, permissions and authentication providers.
                </p>
              </div>

              <div className="panel settings-list-panel">
                {(hasPermission(currentUser, 'users.view') ||
                  hasPermission(currentUser, 'groups.view')) && (
                  <NavLink
                    to="/settings/access"
                    className="settings-list-row settings-navigation-row"
                  >
                    <div>
                      <h3>Users &amp; permissions</h3>
                      <p>
                        Manage users, groups and access permissions.
                      </p>
                    </div>

                    <span className="settings-row-arrow">
                      ›
                    </span>
                  </NavLink>
                )}

                {hasPermission(
                  currentUser,
                  'settings.auth_manage',
                ) && (
                  <NavLink
                    to="/settings/authentication"
                    className="settings-list-row settings-navigation-row"
                  >
                    <div>
                      <h3>Authentication</h3>
                      <p>
                        Configure local, LDAP and Active Directory login.
                      </p>
                    </div>

                    <span className="settings-row-arrow">
                      ›
                    </span>
                  </NavLink>
                )}
              </div>
            </div>
          )}

        <div className="settings-group">
          <div className="settings-group-heading">
            <h2>Packs</h2>
            <p>
              Control which pack sources this FERPEK Lens instance may use.
            </p>
          </div>

          <div className="panel setting-card pack-management-card">

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
                    disabled={
                      !hasPermission(
                        currentUser,
                        'settings.manage',
                      )
                    }
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
                    disabled={
                      !hasPermission(
                        currentUser,
                        'settings.manage',
                      )
                    }
                    onChange={(event) =>
                      setAllowLocalPacks(
                        event.target.checked,
                      )
                    }
                  />
                  <span className="setting-switch-track" />
                </label>
              </div>

            </>
          )}
          </div>

          {!packSettingsLoading && (
            <div className="pack-management-actions settings-section-actions">
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

              {hasPermission(
                currentUser,
                'settings.manage',
              ) && (
                <button
                  className="secondary-button settings-save-button"
                  onClick={() =>
                    void savePackSettings()
                  }
                  disabled={packSettingsSaving}
                >
                  {packSettingsSaving
                    ? "Saving..."
                    : "Save changes"}
                </button>
              )}
            </div>
          )}
        </div>

        <div className="settings-group">
          <div className="settings-group-heading">
            <h2>Data retention</h2>
            <p>
              Control how long FERPEK Lens keeps historical data.
            </p>
          </div>

          <div className="panel setting-card retention-card">

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
                    disabled={
                      !hasPermission(
                        currentUser,
                        'settings.manage',
                      )
                    }
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
                    disabled={
                      !hasPermission(
                        currentUser,
                        'settings.manage',
                      )
                    }
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
                    disabled={
                      !hasPermission(
                        currentUser,
                        'settings.manage',
                      )
                    }
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

            </>
          )}
          </div>

          {!retentionLoading && (
            <div className="retention-actions settings-section-actions">
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

              {hasPermission(
                currentUser,
                'settings.manage',
              ) && (
                <button
                  className="secondary-button settings-save-button"
                  onClick={() =>
                    void saveRetentionSettings()
                  }
                  disabled={retentionSaving}
                >
                  {retentionSaving
                    ? "Saving..."
                    : "Save changes"}
                </button>
              )}
            </div>
          )}
        </div>
      </div>
      </div>
    </section>
  )
}

function AccessDenied() {
  return (
    <section>
      <div className="panel">
        <div className="empty-state">
          You do not have permission to access this page.
        </div>
      </div>
    </section>
  )
}


function RequirePermission({
  currentUser,
  permission,
  children,
}: {
  currentUser: CurrentUser
  permission: string
  children: React.ReactNode
}) {
  if (!hasPermission(currentUser, permission)) {
    return <AccessDenied />
  }

  return <>{children}</>
}


type ThemePreference =
  | 'system'
  | 'light'
  | 'dark'


function Layout({
  currentUser,
  onLogout,
}: {
  currentUser: CurrentUser
  onLogout: () => void
}) {
  const location = useLocation()

  const themeStorageKey = `ferpek-theme:${currentUser.id}`

  const [theme, setTheme] = useState<ThemePreference>(() => {
    const stored = localStorage.getItem(themeStorageKey)

    if (
      stored === 'light' ||
      stored === 'dark' ||
      stored === 'system'
    ) {
      return stored
    }

    return 'system'
  })

  useEffect(() => {
    const media = window.matchMedia(
      '(prefers-color-scheme: dark)',
    )

    function applyTheme() {
      const effectiveTheme =
        theme === 'system'
          ? media.matches
            ? 'dark'
            : 'light'
          : theme

      document.documentElement.dataset.theme =
        effectiveTheme
    }

    applyTheme()
    localStorage.setItem(
      themeStorageKey,
      theme,
    )

    if (theme === 'system') {
      media.addEventListener('change', applyTheme)

      return () => {
        media.removeEventListener('change', applyTheme)
      }
    }
  }, [theme, themeStorageKey])
  const info = location.pathname.startsWith('/systems/')
    ? {
        title: 'Host',
        subtitle: 'Logs, findings and monitoring sources',
      }
    : pageInfo[location.pathname] ?? pageInfo['/']

  return (
    <div className="app">
      <GlobalTooltip />
      <Sidebar
        currentUser={currentUser}
        onLogout={onLogout}
      />

      <main className="main">
        <header className="topbar">
          <div>
            <h1>{info.title}</h1>
            <p>{info.subtitle}</p>
          </div>

          <div className="topbar-actions" />
        </header>

        <div className="content">
          <Routes>
            <Route
              path="/"
              element={
                <Overview currentUser={currentUser} />
              }
            />
            <Route
              path="/systems"
              element={
                <RequirePermission
                  currentUser={currentUser}
                  permission="hosts.view"
                >
                  <Systems currentUser={currentUser} />
                </RequirePermission>
              }
            />
            <Route
              path="/systems/:id"
              element={
                <RequirePermission
                  currentUser={currentUser}
                  permission="hosts.view"
                >
                  <HostDetail currentUser={currentUser} />
                </RequirePermission>
              }
            />
            <Route
              path="/findings"
              element={
                <RequirePermission
                  currentUser={currentUser}
                  permission="findings.view"
                >
                  <Findings currentUser={currentUser} />
                </RequirePermission>
              }
            />
            <Route
              path="/activity"
              element={
                <RequirePermission
                  currentUser={currentUser}
                  permission="logs.view"
                >
                  <Activity />
                </RequirePermission>
              }
            />
            <Route
              path="/packs"
              element={
                <RequirePermission
                  currentUser={currentUser}
                  permission="packs.view"
                >
                  <Packs currentUser={currentUser} />
                </RequirePermission>
              }
            />
            <Route
              path="/settings"
              element={
                hasPermission(currentUser, 'settings.view') ||
                hasPermission(currentUser, 'users.view') ||
                hasPermission(currentUser, 'groups.view') ? (
                  <Settings
                    currentUser={currentUser}
                    theme={theme}
                    onThemeChange={setTheme}
                  />
                ) : (
                  <AccessDenied />
                )
              }
            />

            {(hasPermission(currentUser, 'users.view') ||
              hasPermission(currentUser, 'groups.view')) && (
              <Route
                path="/settings/access"
                element={
                  <AccessPage currentUser={currentUser} />
                }
              />
            )}

            {hasPermission(
              currentUser,
              'settings.auth_manage',
            ) && (
              <>
                <Route
                  path="/settings/authentication"
                  element={<AuthenticationPage />}
                />

                <Route
                  path="/settings/authentication/ldap"
                  element={<LDAPSettingsPage />}
                />
              </>
            )}
          </Routes>
        </div>
      </main>
    </div>
  )
}

type AuthMode =
  | 'loading'
  | 'setup'
  | 'login'
  | 'authenticated'

function FerpekAuthBrand() {
  return (
    <div className="auth-brand">
      <img
        className="auth-brand-logo"
        src="/ferpek_original_sem_nome_laranja_transparente.svg"
        alt=""
      />

      <div className="auth-brand-wordmark">
        <strong>FERPEK</strong>
        <span>Lens</span>
      </div>
    </div>
  )
}

function LoginScreen({
  onAuthenticated,
}: {
  onAuthenticated: () => void
}) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(
    event: React.FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault()

    setError('')
    setSubmitting(true)

    try {
      const response = await fetch('/api/v1/auth/login', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          username,
          password,
        }),
      })

      if (!response.ok) {
        setError('Invalid username or password.')
        return
      }

      onAuthenticated()
    } catch {
      setError('Unable to contact the FERPEK Lens server.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-panel">
        <FerpekAuthBrand />

        <div className="auth-heading">
          <h1>Sign in</h1>
          <p>Sign in to your FERPEK Lens instance.</p>
        </div>

        <form
          className="auth-form"
          onSubmit={handleSubmit}
        >
          <label>
            <span>Username</span>
            <input
              autoFocus
              autoComplete="username"
              value={username}
              onChange={(event) =>
                setUsername(event.target.value)
              }
              required
            />
          </label>

          <label>
            <span>Password</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) =>
                setPassword(event.target.value)
              }
              required
            />
          </label>

          {error && (
            <div className="auth-error">
              {error}
            </div>
          )}

          <button
            className={`auth-submit ${
              username.trim() && password
                ? 'primary-button'
                : 'auth-submit-disabled'
            }`}
            type="submit"
            disabled={
              submitting ||
              !username.trim() ||
              !password
            }
          >
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}

function InitialSetupScreen({
  onAuthenticated,
}: {
  onAuthenticated: () => void
}) {
  const [username, setUsername] = useState('admin')
  const [displayName, setDisplayName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(
    event: React.FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault()

    setError('')

    if (password.length < 12) {
      setError(
        'Password must contain at least 12 characters.',
      )
      return
    }

    if (password !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }

    setSubmitting(true)

    try {
      const setupResponse = await fetch(
        '/api/v1/auth/setup',
        {
          method: 'POST',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            username,
            display_name: displayName,
            email,
            password,
          }),
        },
      )

      if (!setupResponse.ok) {
        const data = await setupResponse
          .json()
          .catch(() => null)

        setError(
          data?.detail ||
            'Unable to complete FERPEK Lens setup.',
        )
        return
      }

      const loginResponse = await fetch(
        '/api/v1/auth/login',
        {
          method: 'POST',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            username,
            password,
          }),
        },
      )

      if (!loginResponse.ok) {
        setError(
          'Setup completed, but automatic sign-in failed.',
        )
        return
      }

      onAuthenticated()
    } catch {
      setError('Unable to contact the FERPEK Lens server.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-panel auth-panel-setup">
        <FerpekAuthBrand />

        <div className="auth-heading">
          <h1>Set up FERPEK</h1>
          <p>
            Create the first administrator account for
            this FERPEK Lens instance.
          </p>
        </div>

        <form
          className="auth-form"
          onSubmit={handleSubmit}
        >
          <label>
            <span>Username</span>
            <input
              autoFocus
              autoComplete="username"
              value={username}
              onChange={(event) =>
                setUsername(event.target.value)
              }
              required
            />
          </label>

          <label>
            <span>Display name</span>
            <input
              value={displayName}
              onChange={(event) =>
                setDisplayName(event.target.value)
              }
            />
          </label>

          <label>
            <span>Email</span>
            <input
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) =>
                setEmail(event.target.value)
              }
            />
          </label>

          <label>
            <span>Password</span>
            <input
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(event) =>
                setPassword(event.target.value)
              }
              required
            />
          </label>

          <label>
            <span>Confirm password</span>
            <input
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(event) =>
                setConfirmPassword(event.target.value)
              }
              required
            />
          </label>

          <p className="auth-password-hint">
            Minimum 12 characters.
          </p>

          {error && (
            <div className="auth-error">
              {error}
            </div>
          )}

          <button
            className="primary-button auth-submit"
            type="submit"
            disabled={submitting}
          >
            {submitting
              ? 'Creating administrator…'
              : 'Create administrator'}
          </button>
        </form>
      </div>
    </div>
  )
}

function AuthGate() {
  const navigate = useNavigate()

  const [mode, setMode] =
    useState<AuthMode>('loading')

  const [currentUser, setCurrentUser] =
    useState<CurrentUser | null>(null)

  useEffect(() => {
    if (mode !== 'authenticated') {
      return
    }

    const originalFetch = window.fetch.bind(window)

    window.fetch = async (...args) => {
      const response = await originalFetch(...args)

      if (response.status === 401) {
        setCurrentUser(null)
        setMode('login')
        navigate('/', { replace: true })
      }

      return response
    }

    return () => {
      window.fetch = originalFetch
    }
  }, [mode, navigate])

  async function completeAuthentication() {
    try {
      const response = await fetch(
        '/api/v1/auth/me',
        {
          credentials: 'include',
        },
      )

      if (!response.ok) {
        setCurrentUser(null)
        setMode('login')
        return
      }

      const user: CurrentUser = await response.json()

      setCurrentUser(user)
      setMode('authenticated')
      navigate('/', { replace: true })
    } catch {
      setCurrentUser(null)
      setMode('login')
    }
  }

  useEffect(() => {
    let cancelled = false

    async function checkAuthentication() {
      try {
        const setupResponse = await fetch(
          '/api/v1/auth/setup',
          {
            credentials: 'include',
          },
        )

        if (!setupResponse.ok) {
          throw new Error('Setup status request failed')
        }

        const setup = await setupResponse.json()

        if (cancelled) {
          return
        }

        if (setup.setup_required) {
          setMode('setup')
          return
        }

        const sessionResponse = await fetch(
          '/api/v1/auth/me',
          {
            credentials: 'include',
          },
        )

        if (cancelled) {
          return
        }

        if (sessionResponse.ok) {
          const user: CurrentUser =
            await sessionResponse.json()

          if (cancelled) {
            return
          }

          setCurrentUser(user)
          setMode('authenticated')
        } else {
          setCurrentUser(null)
          setMode('login')
        }
      } catch {
        if (!cancelled) {
          setMode('login')
        }
      }
    }

    checkAuthentication()

    return () => {
      cancelled = true
    }
  }, [])

  if (mode === 'loading') {
    return (
      <div className="auth-page">
        <div className="auth-loading">
          <FerpekAuthBrand />
          <span>Loading FERPEK Lens…</span>
        </div>
      </div>
    )
  }

  if (mode === 'setup') {
    return (
      <InitialSetupScreen
        onAuthenticated={() =>
          void completeAuthentication()
        }
      />
    )
  }

  if (mode === 'login') {
    return (
      <LoginScreen
        onAuthenticated={() =>
          void completeAuthentication()
        }
      />
    )
  }

  if (!currentUser) {
    return null
  }

  return (
    <Layout
      currentUser={currentUser}
      onLogout={() => {
        navigate('/', { replace: true })
        setCurrentUser(null)
        setMode('login')
      }}
    />
  )
}

function App() {
  return (
    <BrowserRouter>
      <GlobalToasts />
      <AuthGate />
    </BrowserRouter>
  )
}

export default App
