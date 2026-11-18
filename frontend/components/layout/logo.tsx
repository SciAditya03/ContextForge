export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden className="shrink-0">
      <defs>
        <linearGradient id="cf-ember" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#f6b24a" />
          <stop offset="1" stopColor="#c2410c" />
        </linearGradient>
      </defs>
      <rect x="1" y="1" width="30" height="30" rx="8" fill="url(#cf-ember)" />
      {/* stacked context layers being forged into one */}
      <path d="M8 11.5h16M8 16h11M8 20.5h7" stroke="#1a1206" strokeWidth="2.4" strokeLinecap="round" />
      <path d="M22.5 17.5l2.2 2.2-2.2 2.2-2.2-2.2z" fill="#1a1206" />
    </svg>
  );
}
