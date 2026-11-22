import type { HistoricalFlightItem } from '../../services/flightsService';

export function DelayReasons({ row }: { row: HistoricalFlightItem }) {
  const reasons = row.delay_reasons ?? [];
  const total = reasons.reduce((sum, r) => sum + r.minutes, 0);
  return <section className="ops-reasons"><h3>Why was this flight late?</h3>
    <p className="ops-note">{row.cancelled ? 'Cancelled in the BTS record.' : row.diverted ? 'Diverted in the BTS record.' : row.arrival_delay_minutes == null ? 'Arrival delay was not reported.' : `Recorded arrival: ${row.arrival_delay_minutes > 0 ? row.arrival_delay_minutes + ' minutes late' : Math.abs(row.arrival_delay_minutes) + ' minutes early / on schedule'}.`}</p>
    {reasons.length ? <><div className="ops-cause-bar" aria-hidden="true">{reasons.map((r, i) => <span key={r.label} className={'cause-'+i} style={{width:100*r.minutes/total+'%'}}/>)}</div>
      {reasons.map((r, i) => <div className="ops-cause" key={r.label}><span><i className={'cause-'+i}/>{r.label}</span><b>{r.minutes} min · {Math.round(100*r.minutes/total)}%</b></div>)}
      <small>{total} total reported cause minutes · BTS record dated {row.flight_date} · {row.source_file}, row {row.source_row_number}. These retrospective causes are separate from the forecast.</small></> : <p className="ops-note">No specific delay cause was reported in the BTS record. Schedule and model scores cannot establish a weather, mechanical, or airspace cause.</p>}
  </section>;
}
