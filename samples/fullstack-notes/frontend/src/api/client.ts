import axios from "axios";

export const api = axios.create({ baseURL: import.meta.env.VITE_API_URL || "" });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

export interface Note {
  id: number;
  body: string;
  shared: boolean;
}

export async function getNotes(): Promise<Note[]> {
  const { data } = await api.get("/api/notes");
  return data;
}

export async function addNote(notebookId: number, body: string): Promise<Note> {
  const { data } = await api.post("/api/notes", { notebookId, body });
  return data;
}

export async function loginUser(email: string, password: string): Promise<string> {
  const { data } = await api.post("/api/auth/login", { email, password });
  localStorage.setItem("token", data.token);
  return data.token;
}

export async function deleteNote(id: number): Promise<void> {
  await api.delete(`/api/notes/${id}`);
}
