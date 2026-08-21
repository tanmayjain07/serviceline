import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'

import Layout from './components/Layout'
import { Spinner } from './components/ui'
import { useAuth } from './lib/auth'
import type { Role } from './lib/types'

import AcceptInvite from './pages/AcceptInvite'
import AuditLog from './pages/AuditLog'
import ChooseCompany from './pages/ChooseCompany'
import Login from './pages/Login'
import CustomerDetail from './pages/CustomerDetail'
import Customers from './pages/Customers'
import DispatchBoard from './pages/DispatchBoard'
import JobDetail from './pages/JobDetail'
import Jobs from './pages/Jobs'
import Overview from './pages/Overview'
import Settings from './pages/Settings'
import Signup from './pages/Signup'
import Team from './pages/Team'

function FullPageSpinner() {
  return (
    <div className="grid min-h-screen place-items-center text-slate-400">
      <Spinner className="h-8 w-8" />
    </div>
  )
}

/**
 * Gate for authenticated routes.
 *
 * `roles` decides what to render, not what is permitted -- the API re-checks
 * every one of these on the server. If this component were deleted entirely,
 * nothing would become accessible; the UI would just get uglier.
 */
function Protected({ roles, children }: { roles?: Role[]; children: ReactNode }) {
  const { isAuthenticated, isLoading, needsCompanyChoice, role } = useAuth()
  const location = useLocation()

  if (isLoading) return <FullPageSpinner />
  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  if (needsCompanyChoice) return <Navigate to="/choose-company" replace />
  if (roles && role && !roles.includes(role)) return <Navigate to="/" replace />

  return <>{children}</>
}

function PublicOnly({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading, needsCompanyChoice } = useAuth()
  if (isLoading) return <FullPageSpinner />
  if (isAuthenticated) {
    return <Navigate to={needsCompanyChoice ? '/choose-company' : '/'} replace />
  }
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      <Route
        path="/login"
        element={
          <PublicOnly>
            <Login />
          </PublicOnly>
        }
      />
      <Route
        path="/signup"
        element={
          <PublicOnly>
            <Signup />
          </PublicOnly>
        }
      />
      {/* Reachable while signed out or signed in -- someone may follow an invite
          link while already logged into another company. */}
      <Route path="/accept-invite" element={<AcceptInvite />} />
      <Route path="/choose-company" element={<ChooseCompany />} />

      <Route
        element={
          <Protected>
            <Layout />
          </Protected>
        }
      >
        <Route path="/" element={<Overview />} />
        <Route
          path="/jobs"
          element={
            <Protected roles={['owner', 'dispatcher', 'technician', 'accountant']}>
              <Jobs />
            </Protected>
          }
        />
        <Route
          path="/jobs/:jobId"
          element={
            <Protected roles={['owner', 'dispatcher', 'technician', 'accountant']}>
              <JobDetail />
            </Protected>
          }
        />
        <Route
          path="/dispatch"
          element={
            <Protected roles={['owner', 'dispatcher']}>
              <DispatchBoard />
            </Protected>
          }
        />
        <Route
          path="/customers"
          element={
            <Protected roles={['owner', 'dispatcher', 'accountant']}>
              <Customers />
            </Protected>
          }
        />
        <Route
          path="/customers/:customerId"
          element={
            <Protected roles={['owner', 'dispatcher', 'accountant']}>
              <CustomerDetail />
            </Protected>
          }
        />
        <Route
          path="/team"
          element={
            <Protected roles={['owner', 'dispatcher', 'accountant']}>
              <Team />
            </Protected>
          }
        />
        <Route
          path="/settings"
          element={
            <Protected roles={['owner']}>
              <Settings />
            </Protected>
          }
        />
        <Route
          path="/audit-log"
          element={
            <Protected roles={['owner']}>
              <AuditLog />
            </Protected>
          }
        />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
