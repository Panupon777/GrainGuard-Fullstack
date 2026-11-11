/* Read-only adapters for the real GrainGuard Hub API. No sample telemetry. */
(function (root) {
  'use strict';
  const finite = value => typeof value === 'number' && Number.isFinite(value) ? value : null;
  const list = value => Array.isArray(value) ? value : [];
  const safeSlots = slots => [...new Set(list(slots).filter(n => Number.isInteger(n) && n > 0))];
  function classify(raw, connected) {
    if (!connected) return 'unknown';
    if (!raw || !raw.mac || raw.cls === 'empty' || raw.state === 'EMPTY') return 'empty';
    if (raw.cls === 'offline' || raw.state === 'OFFLINE') return 'offline';
    if (raw.cls === 'alarm') return 'alarm';
    if (raw.cls === 'warn') return 'warn';
    if (['cal', 'learn', 'shadow'].includes(raw.cls)) return 'learn';
    if (raw.cls === 'rest') return 'rest';
    if (raw.cls === 'ok' || raw.cls === 'run') {
      const machineState = raw.last_state || raw.state;
      if (machineState === 'REST') return 'rest';
      if (machineState === 'RUN') return 'run';
      if (machineState === 'CAL' || machineState === 'SHADOW') return 'learn';
    }
    return 'unknown';
  }
  /** lastFetchMs is browser receipt time. The Hub remains status authority. */
  function normalizeSnapshot(snapshot, visibleSlots = [1], lastFetchMs = Date.now(), connected = true) {
    const received = finite(lastFetchMs);
    const elapsed = received === null ? 0 : Math.max(0, (Date.now() - received) / 1000);
    const bySlot = new Map(list(snapshot && snapshot.nodes).map(n => [n.n, n]));
    return safeSlots(visibleSlots).map(id => {
      const raw = bySlot.get(id) || null;
      const status = classify(raw, connected);
      const current = connected && !['offline', 'empty', 'unknown'].includes(status);
      const baseAge = finite(raw && raw.last_seen_s);
      const label = raw && typeof raw.label === 'string' ? raw.label : '';
      const chb = Boolean(raw && raw.chb);
      return {
        id, n:id, mac:raw && raw.mac || null, name:label, label,
        place:'', status, state:raw && raw.state || null,
        reason:!connected ? 'hub_lost' : !raw ? 'not_configured' : status === 'unknown' ? 'awaiting_data' : null,
        a:current ? finite(raw.ratio) : null,
        b:current && chb ? finite(raw.ratio_b) : null,
        chb, channelBEnabled:chb, age:baseAge === null ? null : Math.max(0,baseAge) + elapsed,
        ack:Boolean(raw && raw.ack), mode:raw && raw.mode || null,
        since:finite(raw && raw.since), fw:raw && raw.fw || null,
        vin:current ? finite(raw.vin) : null, tc:current ? finite(raw.tc) : null,
        codes:list(raw && raw.codes), errors:list(raw && raw.errors),
        health:list(raw && raw.health), health_text:list(raw && raw.health_text),
        spark:current ? list(raw.spark).map(finite) : [],
        sparkB:current && chb ? list(raw.spark_b).map(finite) : [],
        alarmCh:raw && raw.alarm_active && ['A','B','AB'].includes(raw.alarm_ch) ? raw.alarm_ch : null,
        alarm_active:Boolean(raw && raw.alarm_active), alarm_shadow:Boolean(raw && raw.alarm_shadow),
        dataAvailable:current && (finite(raw.ratio)!==null || (chb && finite(raw.ratio_b)!==null)), raw
      };
    });
  }
  function counts(value) {
    const nodes = Array.isArray(value) ? value : list(value && value.nodes);
    const count = status => nodes.filter(n => n.status === status).length;
    return {
      total:nodes.length, registered:nodes.filter(n => Boolean(n.mac)).length,
      run:count('run'), rest:count('rest'), alarm:count('alarm'), warn:count('warn'),
      attention:nodes.filter(n => n.status === 'alarm' || n.status === 'warn').length,
      offline:count('offline'), empty:count('empty'), learn:count('learn'), unknown:count('unknown')
    };
  }
  /** Real history buckets; null gaps remain null and no curve is fabricated. */
  function normalizeHistory(payload) {
    return list(payload && payload.points)
      .filter(point => point && finite(point.t) !== null)
      .map(point => ({
        ts:point.t, a:finite(point.ratio), b:finite(point.ratio_b),
        aMax:finite(point.ratio_max), bMax:finite(point.ratio_b_max),
        vin:finite(point.vin), tc:finite(point.tc), count:finite(point.cnt),
        alarm:finite(point.alarm), run:finite(point.run), raw:point
      }))
      .sort((a,b) => a.ts-b.ts);
  }
  function visible(value, query = '') {
    const nodes = Array.isArray(value) ? value : list(value && value.nodes);
    const policy = !Array.isArray(value) && value && value.policy || {};
    const q = String(query).trim().toLowerCase();
    return nodes.filter(n => !(policy.offline === 'group' && n.status === 'offline'))
      .filter(n => `${n.name || ''} ${n.label || ''} ${n.mac || ''} ${n.id} เครื่องขัด ${n.id} Whitener ${n.id}`.toLowerCase().includes(q));
  }
  root.GGModel = {normalizeSnapshot,normalizeHistory,counts,visible,classify};
  if (typeof module !== 'undefined') module.exports=root.GGModel;
})(globalThis);
