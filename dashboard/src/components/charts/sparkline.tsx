"use client";

/** Tiny inline trend line for stat cards. Pure SVG (no Recharts overhead for
 * a 1cm chart). Color follows the trend unless an explicit color is given. */

export function Sparkline({
  data,
  width = 96,
  height = 28,
  color,
  className,
}: {
  data: number[];
  width?: number;
  height?: number;
  color?: string;
  className?: string;
}) {
  if (data.length < 2) {
    return <div style={{ width, height }} className={className} aria-hidden />;
  }

  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const stepX = width / (data.length - 1);
  const pad = 2;
  const usable = height - pad * 2;

  const points = data.map((v, i) => {
    const x = i * stepX;
    const y = pad + usable - ((v - min) / span) * usable;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const stroke = color ?? (data[data.length - 1] >= data[0] ? "var(--gain)" : "var(--loss)");

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      fill="none"
      className={className}
      role="img"
      aria-label="trend sparkline"
    >
      <polyline
        points={points.join(" ")}
        stroke={stroke}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
