import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { MsalProvider } from "@azure/msal-react";
import App from "./App";
import { AuthGate, UnauthenticatedShell } from "./auth/AuthGate";
import { authConfigured, initializeAuth, msalInstance } from "./auth/msal";
import "./index.css";

const container = document.getElementById("root");
if (!container) {
  throw new Error("Root container missing from index.html");
}

const root = createRoot(container);

function render() {
  root.render(
    <StrictMode>
      <BrowserRouter>
        {authConfigured ? (
          <MsalProvider instance={msalInstance}>
            <AuthGate>
              <App />
            </AuthGate>
          </MsalProvider>
        ) : (
          <UnauthenticatedShell>
            <App />
          </UnauthenticatedShell>
        )}
      </BrowserRouter>
    </StrictMode>,
  );
}

// Rendering before MSAL finishes initializing would mount the sign-in screen
// over a redirect that is still being processed.
initializeAuth()
  .then(render)
  .catch((err: Error) => {
    container.textContent = `Sign-in failed to initialize: ${err.message}`;
  });
