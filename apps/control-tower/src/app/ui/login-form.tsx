"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { getApps, initializeApp } from "firebase/app";
import {
  getAuth,
  GoogleAuthProvider,
  inMemoryPersistence,
  setPersistence,
  signInWithPopup,
  getMultiFactorResolver,
  TotpMultiFactorGenerator,
  signOut,
  type MultiFactorError,
  type MultiFactorResolver,
  type UserCredential,
} from "firebase/auth";

type Config = { apiKey: string; authDomain: string; projectId: string };

export function LoginForm({ config }: { config: Config | null }) {
  const router = useRouter();
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);
  const [resolver, setResolver] = useState<MultiFactorResolver | null>(null);

  async function finish(credential: UserCredential) {
    const response = await fetch("/api/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ idToken: await credential.user.getIdToken() }),
    });
    await signOut(getAuth());
    if (!response.ok) throw new Error("session_rejected");
    router.replace("/access-status");
    router.refresh();
  }

  async function login() {
    if (!config) return;
    setPending(true);
    setMessage("");
    const auth = getAuth(getApps()[0] ?? initializeApp(config));
    try {
      await setPersistence(auth, inMemoryPersistence);
      const provider = new GoogleAuthProvider();
      provider.setCustomParameters({ prompt: "select_account" });
      await finish(await signInWithPopup(auth, provider));
    } catch (error) {
      if (
        typeof error === "object" &&
        error &&
        "code" in error &&
        error.code === "auth/multi-factor-auth-required"
      ) {
        const next = getMultiFactorResolver(auth, error as MultiFactorError);
        if (
          next.hints.some(
            (hint) => hint.factorId === TotpMultiFactorGenerator.FACTOR_ID,
          )
        )
          setResolver(next);
        else
          setMessage(
            "This sign-in requires an unsupported second factor. Ask the administrator to configure an authenticator app.",
          );
      } else
        setMessage(
          "Sign-in could not be completed. Use your invited Google account and try again.",
        );
    } finally {
      setPending(false);
    }
  }

  async function verify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!resolver) return;
    const code = String(new FormData(event.currentTarget).get("code") ?? "");
    const hint = resolver.hints.find(
      (item) => item.factorId === TotpMultiFactorGenerator.FACTOR_ID,
    );
    if (!hint) return;
    setPending(true);
    setMessage("");
    try {
      await finish(
        await resolver.resolveSignIn(
          TotpMultiFactorGenerator.assertionForSignIn(hint.uid, code),
        ),
      );
    } catch {
      setMessage(
        "Verification failed. Check your authenticator code and try again.",
      );
    } finally {
      setPending(false);
    }
  }

  if (!config)
    return (
      <p className="access-notice">
        Enterprise sign-in is not configured yet. Access remains closed while
        the administrator completes setup.
      </p>
    );
  return (
    <>
      {resolver ? (
        <form onSubmit={verify} className="access-form">
          <label>
            Authenticator code
            <input
              name="code"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]{6}"
              maxLength={6}
              required
            />
          </label>
          <button className="access-button" disabled={pending}>
            Verify and continue
          </button>
        </form>
      ) : (
        <button className="access-button" disabled={pending} onClick={login}>
          {pending ? "Signing in…" : "Continue with Google"}
        </button>
      )}
      {message && (
        <p role="alert" className="access-notice">
          {message}
        </p>
      )}
    </>
  );
}
