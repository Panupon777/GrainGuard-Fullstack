/* Daily summary (approved mock v15): one card per tracked machine in the same 3 × 2 grid as the overview,
   plus mill totals and the error codes of the last 30 days. Reads /api/daily?days=14 and /api/errors only. */
(function(root){
 'use strict';
 const list=v=>Array.isArray(v)?v:[];
 const num=v=>typeof v==='number'&&Number.isFinite(v)?v:null;
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const words={
  th:{title:'สรุปรายวัน',runH:'ชม. เดินเครื่อง',alarms:'Alarm',alarmMin:'นาที Alarm',health:'เตือนเซ็นเซอร์',uptime:'ข้อมูลครบ',mill:'รวมทั้งโรงสี',codes:'รหัสปัญหา 30 วันล่าสุด',noCodes:'ไม่มีรหัสปัญหาใน 30 วัน',partial:'วันนี้ยังไม่จบ ค่าจะนับต่อจนเที่ยงคืน',noData:'ไม่มีข้อมูลวันนี้',slot:'ช่องว่าง',bars:'ชั่วโมงเดินเครื่อง 14 วัน',loading:'กำลังโหลดสรุปจาก Hub',failed:'โหลดสรุปจาก Hub ไม่ได้',prev:'วันก่อน',next:'วันถัดไป',today:'วันนี้ · ถึงตอนนี้',times:'ครั้ง'},
  en:{title:'Daily summary',runH:'run hours',alarms:'Alarms',alarmMin:'alarm min',health:'Sensor warnings',uptime:'Data coverage',mill:'Whole mill',codes:'Error codes, last 30 days',noCodes:'No error codes in 30 days',partial:'Today is still counting until midnight.',noData:'No data for this day',slot:'Empty slot',bars:'Run hours, 14 days',loading:'Loading the Hub summary',failed:'Could not load the Hub summary',prev:'Previous day',next:'Next day',today:'Today · so far',times:'times'}
 };
 // Pure helpers (tested): the day's row per machine, a 14-day run-hour series, mill totals and code counts.
 function dayRows(daily,date){const d=list(daily&&daily.days).find(x=>x.date===date);const m=new Map();for(const r of list(d&&d.rows))m.set(Number(r.node),r);return m;}
 function series(daily,node){return list(daily&&daily.days).map(d=>{const r=list(d.rows).find(x=>Number(x.node)===node);const v=num(r&&r.run_min);return v==null?null:v/60;});}
 function totals(rows,nodes){const t={run_h:0,alarm_count:0,alarm_min:0,health_incidents:0};for(const n of nodes){const r=rows.get(n);if(!r)continue;t.run_h+=(num(r.run_min)||0)/60;t.alarm_count+=num(r.alarm_count)||0;t.alarm_min+=num(r.alarm_min)||0;t.health_incidents+=num(r.health_incidents)||0;}return t;}
 // Counts come from the Hub's 30-day error history; an active code with no history row yet still counts once.
 function codeCounts(errors){const by=new Map(),hist=list(errors&&errors.history),add=(e)=>{const k=String(e.code),c=by.get(k)||{code:k,title:e.th||'',count:0,where:new Set()};c.count++;c.where.add(e.n?(e.label||'Node '+e.n):'Hub');by.set(k,c);};
  for(const e of hist)if(e&&e.code)add(e);
  for(const e of list(errors&&errors.active))if(e&&e.code&&!hist.some(h=>h.code===e.code&&Number(h.n)===Number(e.n)&&h.open))add(e);
  return [...by.values()].map(c=>({...c,where:[...c.where]})).sort((a,b)=>b.count-a.count||a.code.localeCompare(b.code));}
 function level(r){if(!r)return 'off';const has=(num(r.run_min)||0)+(num(r.rest_min)||0)+(num(r.offline_min)||0)>0;if(!has)return 'off';if((num(r.alarm_count)||0)>0)return 'bad';if((num(r.health_incidents)||0)>0||(num(r.uptime_pct)??100)<90)return 'warn';return 'ok';}
 function render({daily,errors,nodes=[],lang='th',date=null,icon=null,failed=false}={}){
  const w=words[lang==='en'?'en':'th'],ic=n=>icon?icon(n):'',days=list(daily&&daily.days).map(d=>d.date),today=daily&&daily.today;
  const current=date&&days.includes(date)?date:today||days.at(-1)||null,idx=days.indexOf(current);
  const label=current?(current===today?w.today:new Date(current+'T00:00:00+07:00').toLocaleDateString(lang==='en'?'en-GB':'th-TH',{weekday:'short',day:'numeric',month:'short',year:'numeric',timeZone:'Asia/Bangkok'})):'—';
  const head=`<div class="gg-pgh"><h1>${w.title}</h1><div class="gg-dnav gg-right"><button type="button" class="gg-btn" data-action="daily-day" data-value="-1" ${idx<=0?'disabled':''} aria-label="${w.prev}">${ic('left')}</button><span class="gg-btn gg-static-btn">${ic('cal')}${esc(label)}</span><button type="button" class="gg-btn" data-action="daily-day" data-value="1" ${idx<0||idx>=days.length-1?'disabled':''} aria-label="${w.next}">${ic('chevron')}</button></div></div>`;
  if(!daily)return head+`<div class="gg-ghost gg-wide gg-fill"><span>${ic(failed?'unlink':'clock')}${failed?w.failed:w.loading}</span></div>`;
  const rows=dayRows(daily,current),ids=nodes.map(n=>Number(n.id??n.n)),t=totals(rows,ids);
  const cards=nodes.map(n=>{const id=Number(n.id??n.n),r=rows.get(id),s=series(daily,id),max=Math.max(1,...s.filter(v=>v!=null)),lv=level(r),run=num(r&&r.run_min);
   const kv=(k,v,cls='')=>`<div><small>${k}</small><b class="num ${cls}">${v}</b></div>`;
   return `<article class="gg-dcard" data-node="${id}"><div class="gg-dc-hd"><span class="gg-nno">${String(id).padStart(2,'0')}</span><span class="gg-nm">${esc(n.name||n.label||'Node '+id)}</span><i class="gg-led ${lv}"></i></div>
    <div class="gg-dc-big"><b class="num">${run==null||lv==='off'?'—':(run/60).toFixed(1)}</b><small>${w.runH}</small></div>
    <div class="gg-mini" role="img" aria-label="${w.bars}">${lv==='off'&&!s.some(v=>v)?`<div class="gg-empty">${w.noData}</div>`:s.map((v,i)=>`<i class="${i===s.length-1?'last':''}" style="height:${v==null?2:Math.max(4,v/max*100).toFixed(0)}%"></i>`).join('')}</div>
    <div class="gg-dc-kv">${kv(w.alarms,r?num(r.alarm_count)??0:'—',r&&r.alarm_count?'bad':'')}${kv(w.alarmMin,r?(num(r.alarm_min)??0).toFixed(0):'—')}${kv(w.health,r?num(r.health_incidents)??0:'—',r&&r.health_incidents?'warn':'')}${kv(w.uptime,r&&num(r.uptime_pct)!=null?Math.round(r.uptime_pct)+'%':'—',r&&num(r.uptime_pct)!=null&&r.uptime_pct<90?'bad':'')}</div></article>`;});
  while(cards.length<6)cards.push(`<div class="gg-ghost"><span><small>${w.slot}</small></span></div>`);
  const codes=codeCounts(errors);
  return head+`<div class="gg-ov"><div class="gg-dgrid">${cards.join('')}</div>
   <aside class="gg-rail"><section class="gg-card"><h3 class="gg-h3">${w.mill}</h3><div class="gg-tot4"><div><b class="num">${t.run_h.toFixed(1)}</b><small>${w.runH}</small></div><div><b class="num bad">${t.alarm_count}</b><small>${w.alarms}</small></div><div><b class="num">${t.alarm_min.toFixed(0)}</b><small>${w.alarmMin}</small></div><div><b class="num warn">${t.health_incidents}</b><small>${w.health}</small></div></div>${current===today?`<p class="gg-hnote" style="margin-top:10px">${w.partial}</p>`:''}</section>
    <section class="gg-card gg-feedcard"><h3 class="gg-h3">${w.codes}</h3><div class="gg-dcodes">${codes.slice(0,6).map(c=>`<div><code class="gg-code">${esc(c.code)}</code><b>${esc(c.title||c.code)}</b><span class="num">${c.count}</span><small>${esc(c.where.join(', '))}</small></div>`).join('')||`<p class="gg-hnote">${w.noCodes}</p>`}</div></section></aside></div>`;
 }
 const api={render,dayRows,series,totals,codeCounts,level};root.GGDailyView=api;
 if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
