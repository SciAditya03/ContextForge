import { useState } from "react";
import { loginUser } from "../api/client";

export function LoginForm({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    await loginUser(email, password);
    onDone();
  }
  return (
    <form onSubmit={submit}>
      <input value={email} onChange={(e) => setEmail(e.target.value)} />
      <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
      <button type="submit">Log in</button>
    </form>
  );
}
