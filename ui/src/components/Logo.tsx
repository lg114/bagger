interface LogoProps {
  className?: string;
  "aria-label"?: string;
}

export default function Logo({ className, "aria-label": ariaLabel }: LogoProps) {
  return (
    <svg
      viewBox="0 0 1024 1024"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-label={ariaLabel ?? "bagger"}
      role="img"
    >
      <title>bagger</title>
      <desc>AI Coding Agent Data Collector — a bag gathering conversation bubbles.</desc>
      <g
        fill="none"
        stroke="currentColor"
        strokeWidth="36"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <line x1="212" y1="526" x2="812" y2="526" />
        <polyline points="232,526 792,526 672,866 352,866 232,526" />
      </g>
      <g fill="currentColor" stroke="none">
        <circle cx="512" cy="196" r="38" />
        <circle cx="392" cy="286" r="38" />
        <circle cx="632" cy="286" r="38" />
      </g>
    </svg>
  );
}
