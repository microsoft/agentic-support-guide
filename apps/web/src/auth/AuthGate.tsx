import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { useIsAuthenticated, useMsal } from "@azure/msal-react";
import { api } from "../api/client";
import type { Principal } from "../api/types";
import { loginRequest } from "./msal";

interface PrincipalState {
  principal: Principal | null;
  /** Districts the caller may act on, already resolved for facilitators. */
  districts: string[];
  signOut: () => void;
}

const PrincipalContext = createContext<PrincipalState>({
  principal: null,
  districts: [],
  signOut: () => {},
});

export { PrincipalContext };

export function usePrincipal(): PrincipalState {
  return useContext(PrincipalContext);
}

function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 p-6">
      <div className="max-w-md space-y-4 rounded-lg border border-slate-800 bg-slate-900 p-8 text-center">
        {children}
      </div>
    </div>
  );
}

function ActionButton({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full rounded border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800"
    >
      {children}
    </button>
  );
}

/**
 * Resolves the caller's districts from `/api/me` and blocks the app until it
 * has them. Rendering the pages first would fire a burst of requests that all
 * fail and read as an outage.
 *
 * Used on both paths: with Entra sign-in, and locally against a backend
 * started with `API_AUTH_MODE=disabled`, which returns a development
 * principal. Asking the API in both cases is what keeps district names out of
 * the UI as constants.
 */
function PrincipalLoader({ children, signOut }: { children: ReactNode; signOut: () => void }) {
  const [principal, setPrincipal] = useState<Principal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    api
      .me()
      .then((me) => {
        if (!cancelled) setPrincipal(me);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  if (error) {
    return (
      <Centered>
        <h1 className="text-lg font-semibold text-slate-100">Cannot reach the API</h1>
        <p className="text-sm text-slate-400">{error}</p>
        {/* Without this the user is stranded here until they refresh, which is
            the normal state for a few seconds after a deploy. */}
        <ActionButton onClick={retry}>Try again</ActionButton>
        <ActionButton onClick={signOut}>Sign out</ActionButton>
      </Centered>
    );
  }

  if (!principal) {
    return (
      <Centered>
        <p className="text-sm text-slate-400">Loading your districts ...</p>
      </Centered>
    );
  }

  if (principal.available_districts.length === 0) {
    return (
      <Centered>
        <h1 className="text-lg font-semibold text-slate-100">No districts assigned</h1>
        <p className="text-sm text-slate-400">
          You are signed in as {principal.display_name}, but no district has been assigned to
          your account. Ask the workshop facilitator to add you to
          <code className="mx-1 text-slate-300">district_assignments</code>.
        </p>
        <ActionButton onClick={signOut}>Sign out</ActionButton>
      </Centered>
    );
  }

  return (
    <PrincipalContext.Provider
      value={{ principal, districts: principal.available_districts, signOut }}
    >
      {children}
    </PrincipalContext.Provider>
  );
}

/** Requires a signed-in Entra account before anything else renders. */
export function AuthGate({ children }: { children: ReactNode }) {
  const { instance } = useMsal();
  const isAuthenticated = useIsAuthenticated();

  if (!isAuthenticated) {
    return (
      <Centered>
        <h1 className="text-lg font-semibold text-slate-100">Agentic Support Guide</h1>
        <p className="text-sm text-slate-400">
          Sign in with your workshop account to continue. Learner data is scoped to the
          districts assigned to you.
        </p>
        <button
          type="button"
          className="w-full rounded bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500"
          onClick={() => void instance.loginRedirect(loginRequest)}
        >
          Sign in
        </button>
      </Centered>
    );
  }

  return (
    <PrincipalLoader signOut={() => void instance.logoutRedirect()}>{children}</PrincipalLoader>
  );
}

/**
 * Local development against a backend started with `API_AUTH_MODE=disabled`.
 * There is no tenant to sign in to, but `/api/me` still answers, so the
 * districts come from the backend's own configuration rather than a constant.
 */
export function UnauthenticatedShell({ children }: { children: ReactNode }) {
  return <PrincipalLoader signOut={() => {}}>{children}</PrincipalLoader>;
}
