import React, { useState } from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LoginForm } from "./components/LoginForm";
import { NoteList } from "./components/NoteList";

const queryClient = new QueryClient();

function App() {
  const [loggedIn, setLoggedIn] = useState(Boolean(localStorage.getItem("token")));
  return loggedIn ? <NoteList /> : <LoginForm onDone={() => setLoggedIn(true)} />;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <QueryClientProvider client={queryClient}>
    <App />
  </QueryClientProvider>
);
