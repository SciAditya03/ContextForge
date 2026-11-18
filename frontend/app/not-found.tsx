import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 px-6 text-center">
      <p className="font-mono text-xs text-subtle">404</p>
      <h1 className="text-xl font-semibold">Page not found</h1>
      <p className="text-sm text-muted">The page or project you are looking for does not exist on this server.</p>
      <Link href="/" className={buttonVariants({ variant: "secondary" })}>
        Back to workspace
      </Link>
    </div>
  );
}
