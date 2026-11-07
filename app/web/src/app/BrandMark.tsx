/** The Half Life mark (Jessica's logo): four proteins and the links between them. */
export function BrandMark({ className }: { className?: string | undefined }) {
  return (
    <svg className={className} viewBox="0 0 32 32" aria-hidden="true" fill="none">
      <path d="m8 8 17 2-3 16L8 22V8l14 18M25 10 8 22" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="8" cy="8" r="3.5" fill="currentColor" />
      <circle cx="25" cy="10" r="3" fill="currentColor" />
      <circle cx="22" cy="26" r="3.5" fill="currentColor" />
      <circle cx="8" cy="22" r="2.5" fill="currentColor" />
    </svg>
  );
}
