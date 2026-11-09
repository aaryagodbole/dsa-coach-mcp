import type { CalibrationBin } from "../types";
import { percent } from "./format";

const SIZE = 180;
const PAD = 28;
const scale = (v: number) => PAD + v * (SIZE - 2 * PAD);

export function Calibration({ bins }: { bins: CalibrationBin[] }) {
  const total = bins.reduce((n, b) => n + b.reviews, 0);
  return (
    <section>
      <h2>Calibration · predicted recall vs how often you recalled</h2>
      {total === 0 ? (
        <p className="empty">Review a problem twice to see this.</p>
      ) : (
        <div className="calibration">
          <svg viewBox={`0 0 ${SIZE} ${SIZE}`} width={SIZE} height={SIZE} role="img"
               aria-label="Predicted recall against actual recall">
            <line x1={scale(0)} y1={SIZE - scale(0)} x2={scale(1)} y2={SIZE - scale(1)}
                  stroke="var(--line-strong)" strokeDasharray="4 3" />
            <line x1={scale(0)} y1={SIZE - scale(0)} x2={scale(1)} y2={SIZE - scale(0)} stroke="var(--line)" />
            <line x1={scale(0)} y1={SIZE - scale(0)} x2={scale(0)} y2={SIZE - scale(1)} stroke="var(--line)" />
            {bins.map((b) => (
              <circle key={b.low} cx={scale(b.predicted)} cy={SIZE - scale(b.recalled)}
                      r={3 + 7 * Math.sqrt(b.reviews / total)} fill="var(--accent)" fillOpacity={0.75}>
                <title>{`${b.reviews} reviews: predicted ${percent(b.predicted)}, recalled ${percent(b.recalled)}`}</title>
              </circle>
            ))}
            <text x={SIZE / 2} y={SIZE - 6} textAnchor="middle" className="axis">predicted</text>
            <text x={10} y={SIZE / 2} textAnchor="middle" className="axis"
                  transform={`rotate(-90 10 ${SIZE / 2})`}>recalled</text>
          </svg>
          <table>
            <thead>
              <tr><th>predicted</th><th>reviews</th><th>recalled</th></tr>
            </thead>
            <tbody>
              {bins.map((b) => (
                <tr key={b.low}>
                  <td>{percent(b.low)}–{percent(b.high)}</td>
                  <td>{b.reviews}</td>
                  <td>{percent(b.recalled)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {total < 30 && <p className="empty">Only {total} reviews so far; this settles with more.</p>}
        </div>
      )}
    </section>
  );
}
