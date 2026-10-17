/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_PLATFORM_API_BASE_URL?: string
  readonly VITE_API_PROXY_TARGET?: string
  readonly VITE_COGNITO_REGION?: string
  readonly VITE_COGNITO_USER_POOL_ID?: string
  readonly VITE_COGNITO_CLIENT_ID?: string
  readonly VITE_OIDC_AUTHORITY?: string
  readonly VITE_OIDC_CLIENT_ID?: string
  readonly VITE_OIDC_REDIRECT_URI?: string
  readonly VITE_OIDC_LOGOUT_URI?: string
  readonly VITE_OIDC_END_SESSION_ENDPOINT?: string
  readonly VITE_OIDC_SCOPES?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
