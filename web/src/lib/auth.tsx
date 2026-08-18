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

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [hasToken, setHasToken] = useState(() => Boolean(tokens.access()))

  useEffect(
    () => subscribeToAuth(() => setHasToken(Boolean(tokens.access()))),
    [],
  )

  const { data: me, isPending } = useQuery({
    queryKey: ['me'],
    queryFn: () => api.get<Me>('/auth/me'),
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
      // Every cached query is scoped to the previous company, so all of it is
      // stale. Clearing rather than invalidating avoids briefly rendering one
      // company's data under another's name.
      queryClient.clear()
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
