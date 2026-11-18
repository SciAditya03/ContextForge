import { useNotes } from "../hooks/useNotes";

export function NoteList() {
  const { data, isLoading } = useNotes();
  if (isLoading) return <p>Loading</p>;
  return (
    <ul>
      {data?.map((n) => (
        <li key={n.id} dangerouslySetInnerHTML={{ __html: n.body }} />
      ))}
    </ul>
  );
}
