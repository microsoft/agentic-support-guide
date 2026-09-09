import {
  InteractionRequiredAuthError,
  PublicClientApplication,
  type Configuration,
} from "@azure/msal-browser";
import { setAccessTokenProvider } from "../api/client";

const clientId = import.meta.env.VITE_ENTRA_CLIENT_ID ?? "";
const tenantId = import.meta.env.VITE_ENTRA_TENANT_ID ?? "";
const apiScope = import.meta.env.VITE_API_SCOPE ?? "";

/**
 * Sign-in is only possible when the build was given all three values. A
 * partial config would produce a broken redirect loop that looks like an auth
 * bug, so treat it as unconfigured and let the API's own 401 surface instead.
 */
export const authConfigured = Boolean(clientId && tenantId && apiScope);

const msalConfig: Configuration = {
  auth: {
    clientId,
    authority: `https://login.microsoftonline.com/${tenantId}`,
    redirectUri: window.location.origin,
    postLogoutRedirectUri: window.location.origin,
  },
  cache: {
    // Session storage, not local: on a shared workshop machine a token in
    // localStorage outlives the browser session and the next person inherits it.
    cacheLocation: "sessionStorage",
  },
};

export const msalInstance = new PublicClientApplication(msalConfig);
export const loginRequest = { scopes: [apiScope] };

/**
 * Must complete before React renders: MSAL v5 rejects every call made before
 * `initialize()`, and `handleRedirectPromise` is what converts the code in the
 * URL fragment into a usable account.
 */
export async function initializeAuth(): Promise<void> {
  if (!authConfigured) return;

  await msalInstance.initialize();
  const result = await msalInstance.handleRedirectPromise();
  if (result?.account) {
    msalInstance.setActiveAccount(result.account);
  } else if (!msalInstance.getActiveAccount()) {
    const [existing] = msalInstance.getAllAccounts();
    if (existing) msalInstance.setActiveAccount(existing);
  }

  setAccessTokenProvider(async () => {
    const account = msalInstance.getActiveAccount();
    if (!account) return null;
    try {
      const auth = await msalInstance.acquireTokenSilent({ ...loginRequest, account });
      return auth.accessToken;
    } catch (err) {
      if (err instanceof InteractionRequiredAuthError) {
        // Navigates away. Throwing stops the caller from firing the request
        // anonymously in the moment before the browser leaves the page.
        await msalInstance.acquireTokenRedirect({ ...loginRequest, account });
        throw new Error("Redirecting to sign in.");
      }
      return null;
    }
  });
}
