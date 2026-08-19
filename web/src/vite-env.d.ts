/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Where the API lives. Left unset in development so the value falls back to
   * the relative '/api/v1', which Vite's dev proxy forwards to the local API.
   * In production this is the deployed API's full URL, e.g.
   * https://serviceline-api.onrender.com/api/v1
   *
   * Vite inlines this at BUILD time, so changing it requires a rebuild.
   */
  readonly VITE_API_BASE_URL?: string

  /**
   * 'true' on the public demo deployment. Shows the published demo logins on
   * the sign-in page and the warning about the free tier's cold start. Must
   * stay off anywhere real data lives.
   */
  readonly VITE_DEMO_MODE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
