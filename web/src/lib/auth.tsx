/**
 * Authentication context.
 *
 * The server is the authority on what a user may do. This context exists to
 * decide what to *render*, never to decide what is *allowed* -- every
 * permission is enforced again in the API. Hiding a button is a courtesy, not a
 * control.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { api, subscribeToAuth, tokens } from './api'
import type { Me, Role, TokenPair } from './types'

interface AuthContextValue {
  me: Me | null
  isLoading: boolean
  isAuthenticated: boolean
  /** True when signed in but no company is selected yet (multi-company users). */
  needsCompanyChoice: boolean
  role: Role | null
  signIn: (pair: TokenPair) => void
  signOut: () => void
  switchCompany: (tenantId: string) => Promise<void>
  can: (...roles: Role[]) => boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

/**
 * Defined once, at module scope, because it is needed two ways: declaratively
 * by the hook below, and imperatively after a company switch.
 */
const ME_QUERY = {
  queryKey: ['me'] as const,
  queryFn: () => api.get<Me>('/auth/me'),
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [hasToken, setHasToken] = useState(() => Boolean(tokens.access()))

  useEffect(
    () => subscribeToAuth(() => setHasToken(Boolean(tokens.access()))),
    [],
  )

  const { data: me, isPending } = useQuery({
    ...ME_QUERY,
    enabled: hasToken,
    retry: false,
    staleTime: 30_000,
  })

  const signIn = useCallback(
    (pair: TokenPair) => {
      tokens.set(pair)
      queryClient.invalidateQueries()
    },
    [queryClient],
  )

  const signOut = useCallback(() => {
    tokens.clear()
    queryClient.clear()
  }, [queryClient])

  const switchCompany = useCallback(
    async (tenantId: string) => {
      const pair = await api.post<TokenPair>('/auth/switch-tenant', {
        tenant_id: tenantId,
      })
      tokens.set(pair)

      // Everything except identity was scoped to the previous company, so drop
      // it outright. Removing rather than invalidating avoids briefly rendering
      // one company's data under another's name.
      //
      // Identity is deliberately EXCLUDED from that removal. queryClient.clear()
      // would take the ['me'] query with it, and a mounted observer whose query
      // has been deleted is orphaned: a later fetch creates a *new* query object
      // that the observer is not attached to, so the component never re-renders.
      // `me` then keeps its pre-switch value, needsCompanyChoice stays true, and
      // Protected bounces every navigation straight back to the chooser -- the
      // switch succeeding silently while the app never notices.
      queryClient.removeQueries({
        predicate: (query) => query.queryKey[0] !== 'me',
      })

      // Refetch in place, so the existing observer receives the result. Awaiting
      // it lets a caller navigate the moment this resolves rather than racing an
      // in-flight request.
      await queryClient.refetchQueries({ queryKey: ['me'], exact: true })
    },
    [queryClient],
  )

  const value = useMemo<AuthContextValue>(() => {
    const role = me?.active_role ?? null
    return {
      me: me ?? null,
      isLoading: hasToken && isPending,
      isAuthenticated: Boolean(hasToken && me),
      needsCompanyChoice: Boolean(me && !me.active_tenant_id),
      role,
      signIn,
      signOut,
      switchCompany,
      can: (...roles: Role[]) => (role ? roles.includes(role) : false),
    }
  }, [me, hasToken, isPending, signIn, signOut, switchCompany])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside an AuthProvider')
  return context
}
