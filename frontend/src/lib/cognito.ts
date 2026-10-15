// AWS Cognito integration using the pure-JS SDK (no AWS SDK v3 dependency).
//
// The backend validates the Cognito **ID token** (its `aud` claim equals the
// app client id configured as JWT_AUDIENCE). The access token carries `scope`
// but no `aud`, so it would fail backend verification — we therefore store and
// send the ID token as the bearer, which is what `setAuthToken` manages.

import {
  AuthenticationDetails,
  CognitoUser,
  CognitoUserAttribute,
  CognitoUserPool,
  type CognitoUserSession,
  type ISignUpResult,
} from 'amazon-cognito-identity-js'
import {
  clearAuthToken,
  getAuthToken,
  replaceAuthTokenIfCurrent,
  setAuthToken,
} from '@/lib/auth'

const region = import.meta.env.VITE_COGNITO_REGION
const userPoolId = import.meta.env.VITE_COGNITO_USER_POOL_ID
const clientId = import.meta.env.VITE_COGNITO_CLIENT_ID

if (!userPoolId || !clientId) {
  // Surfaced early during development so misconfiguration is obvious.
  console.warn(
    'Cognito is not configured. Set VITE_COGNITO_USER_POOL_ID and ' +
      'VITE_COGNITO_CLIENT_ID in your .env.',
  )
}

export const userPool = new CognitoUserPool({
  UserPoolId: userPoolId ?? '',
  ClientId: clientId ?? '',
})

export const cognitoRegion = region ?? 'us-east-1'

export interface AuthUser {
  username: string
  email?: string
  sub?: string
}

function cognitoUser(username: string): CognitoUser {
  return new CognitoUser({ Username: username, Pool: userPool })
}

function userFromSession(
  username: string,
  session: CognitoUserSession,
): AuthUser {
  const payload = session.getIdToken().decodePayload()
  return {
    username,
    email: typeof payload.email === 'string' ? payload.email : undefined,
    sub: typeof payload.sub === 'string' ? payload.sub : undefined,
  }
}

/** Sign in with username/email + password. Stores the ID token on success. */
export function signIn(
  username: string,
  password: string,
): Promise<AuthUser> {
  const user = cognitoUser(username)
  // Use USER_PASSWORD_AUTH (plain username/password) rather than SRP. This
  // matches the ALLOW_USER_PASSWORD_AUTH flow enabled on the app client and
  // avoids requiring ALLOW_USER_SRP_AUTH.
  user.setAuthenticationFlowType('USER_PASSWORD_AUTH')
  const details = new AuthenticationDetails({
    Username: username,
    Password: password,
  })

  return new Promise<AuthUser>((resolve, reject) => {
    user.authenticateUser(details, {
      onSuccess: (session) => {
        setAuthToken(session.getIdToken().getJwtToken())
        resolve(userFromSession(username, session))
      },
      onFailure: (err) => reject(normalizeError(err)),
      newPasswordRequired: () => {
        reject(
          new AuthError(
            'NewPasswordRequired',
            'A new password is required for this account. Complete it in the AWS console or reset the password.',
          ),
        )
      },
    })
  })
}

/** Register a new user. Returns whether a confirmation code is required. */
export function signUp(
  email: string,
  password: string,
): Promise<{ userConfirmed: boolean; username: string }> {
  const attributes = [
    new CognitoUserAttribute({ Name: 'email', Value: email }),
  ]

  return new Promise((resolve, reject) => {
    userPool.signUp(email, password, attributes, [], (err, result) => {
      if (err || !result) {
        reject(normalizeError(err))
        return
      }
      const signUpResult = result as ISignUpResult
      resolve({
        userConfirmed: signUpResult.userConfirmed,
        username: signUpResult.user.getUsername(),
      })
    })
  })
}

/** Confirm a signup with the emailed verification code. */
export function confirmSignUp(
  username: string,
  code: string,
): Promise<void> {
  const user = cognitoUser(username)
  return new Promise((resolve, reject) => {
    user.confirmRegistration(code, true, (err) => {
      if (err) {
        reject(normalizeError(err))
        return
      }
      resolve()
    })
  })
}

/** Resend the signup confirmation code. */
export function resendConfirmationCode(username: string): Promise<void> {
  const user = cognitoUser(username)
  return new Promise((resolve, reject) => {
    user.resendConfirmationCode((err) => {
      if (err) {
        reject(normalizeError(err))
        return
      }
      resolve()
    })
  })
}

/** Sign out the current user and clear the stored token. */
export function signOut(): void {
  const current = userPool.getCurrentUser()
  current?.signOut()
  clearAuthToken()
}

/**
 * Restore a session from the Cognito local store (if any). Refreshes the ID
 * token when possible and re-stores it. Resolves to null when not signed in.
 */
export function restoreSession(): Promise<AuthUser | null> {
  const current = userPool.getCurrentUser()
  if (!current) {
    return Promise.resolve(null)
  }
  const tokenAtStart = getAuthToken()
  return new Promise((resolve) => {
    current.getSession(
      (err: Error | null, session: CognitoUserSession | null) => {
        if (err || !session || !session.isValid()) {
          replaceAuthTokenIfCurrent(tokenAtStart, null)
          resolve(null)
          return
        }
        replaceAuthTokenIfCurrent(
          tokenAtStart,
          session.getIdToken().getJwtToken(),
        )
        resolve(userFromSession(current.getUsername(), session))
      },
    )
  })
}

export class AuthError extends Error {
  code: string
  constructor(code: string, message: string) {
    super(message)
    this.name = 'AuthError'
    this.code = code
  }
}

function normalizeError(err: unknown): AuthError {
  if (err && typeof err === 'object') {
    const e = err as { name?: string; code?: string; message?: string }
    const code = e.code ?? e.name ?? 'UnknownError'
    const message = e.message ?? 'Authentication request failed.'
    return new AuthError(code, message)
  }
  return new AuthError('UnknownError', 'Authentication request failed.')
}
