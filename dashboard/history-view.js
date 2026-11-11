/* Read-only presentation and filtering for the latest fetched Hub events. */
(function(root){
 'use strict';
 const CATEGORY_TYPES={alarm:['ALARM_ON','ALARM_OFF','ACK','SHADOW_ALARM','SHADOW_ALARM_END'],fault:['FAULT','FAULT_CLEAR','HEALTH'],connectivity:['NODE_OFFLINE','NODE_ONLINE','PLANT_POWER_OFF','HUB_BOOT','BOOT'],maintenance:['SCREEN_CHANGE'],admin:['CMD','ASSIGN','MODE','CAL','CAL_FORCED','RECORD']};
 const TITLES={ALARM_ON:'Alarm started',ALARM_OFF:'Alarm ended',ACK:'Acknowledged by Node',SHADOW_ALARM:'Shadow alarm observed',SHADOW_ALARM_END:'Shadow alarm ended',FAULT:'Node fault',FAULT_CLEAR:'Fault cleared',HEALTH:'Node health changed',NODE_OFFLINE:'Node offline',NODE_ONLINE:'Node online',PLANT_POWER_OFF:'Plant power unavailable',HUB_BOOT:'Hub started',BOOT:'Node restarted',SCREEN_CHANGE:'Screen replacement recorded',CMD:'Command sent',ASSIGN:'Machine assignment changed',MODE:'Node mode changed',CAL:'Baseline learning',CAL_FORCED:'Baseline learning command',RECORD:'Record mode'};
 const LABELS={
  en:{filters:'Filters',machine:'Machine / Node',allMachines:'All tracked machines + Hub',category:'Event category',all:'All events',alarm:'Process alarms & ACK',fault:'Sensor / equipment health',connectivity:'Connection & power',maintenance:'Screen maintenance',admin:'Settings & technician actions',other:'Other events',period:'Time window',allTime:'All fetched times',hour:'Last hour',day:'Last 24 hours',week:'Last 7 days',custom:'Custom range',from:'From (Bangkok, UTC+7)',to:'To (Bangkok, UTC+7)',search:'Search message, code or MAC',searchHint:'e.g. E102, Node MAC, screen',sort:'Order',newest:'Newest first',oldest:'Oldest first',reset:'Reset filters',time:'Time',event:'Event',action:'Action',view:'View Node',raw:'Original Hub message',none:'No fetched events match these filters.',scope:'Up to 100 recent Hub events, not the complete archive.',result:'events',loaded:'fetched',invalid:'Enter a valid date range; the end must be after the start.',noDate:'Time unavailable',hub:'Hub',type:'Type'},
  th:{filters:'ตัวกรอง',machine:'เครื่อง / Node',allMachines:'เครื่องที่ติดตามทั้งหมด + Hub',category:'ประเภทเหตุการณ์',all:'ทุกประเภท',alarm:'Alarm ของกระบวนการ / รับทราบ',fault:'สุขภาพเซ็นเซอร์ / อุปกรณ์',connectivity:'การเชื่อมต่อ / ไฟเลี้ยง',maintenance:'การดูแลตะแกรง',admin:'ตั้งค่า / คำสั่งช่าง',other:'เหตุการณ์อื่น',period:'ช่วงเวลา',allTime:'ทุกเวลาที่ดึงมา',hour:'1 ชั่วโมงล่าสุด',day:'24 ชั่วโมงล่าสุด',week:'7 วันล่าสุด',custom:'กำหนดช่วงเวลา',from:'ตั้งแต่ (เวลาไทย UTC+7)',to:'ถึง (เวลาไทย UTC+7)',search:'ค้นหาข้อความ รหัส หรือ MAC',searchHint:'เช่น E102, MAC ของ Node, ตะแกรง',sort:'เรียงลำดับ',newest:'ใหม่ไปเก่า',oldest:'เก่าไปใหม่',reset:'ล้างตัวกรอง',time:'เวลา',event:'เหตุการณ์',action:'ดำเนินการ',view:'ดู Node',raw:'ข้อความต้นฉบับจาก Hub',none:'ไม่พบเหตุการณ์ที่ตรงกับตัวกรองในข้อมูลที่ดึงมา',scope:'แสดงสูงสุด 100 เหตุการณ์ล่าสุดจาก Hub ไม่ใช่ประวัติทั้งหมด',result:'เหตุการณ์',loaded:'ดึงมา',invalid:'กรุณาระบุช่วงเวลาที่ถูกต้อง โดยเวลาสิ้นสุดต้องไม่น้อยกว่าเวลาเริ่มต้น',noDate:'ไม่ทราบเวลา',hub:'Hub',type:'ประเภท'}
 };
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const defaults=()=>({machine:'all',category:'all',period:'all',from:'',to:'',sort:'newest'});
 const classifyEvent=e=>Object.keys(CATEGORY_TYPES).find(k=>CATEGORY_TYPES[k].includes(String(e?.type||'').toUpperCase()))||'other';
 // datetime-local fields are explicitly Bangkok wall time, independent of browser timezone.
 function bangkokTimestamp(value){
  if(!value)return null;
  const m=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(String(value));
  if(!m)return NaN;
  const parts=m.slice(1).map(v=>v===undefined?0:Number(v)),[year,month,day,hour,minute,second]=parts;
  const check=new Date(Date.UTC(year,month-1,day,hour,minute,second));
  if(check.getUTCFullYear()!==year||check.getUTCMonth()!==month-1||check.getUTCDate()!==day||hour>23||minute>59||second>59)return NaN;
  return (check.getTime()-7*3600000)/1000;
 }
 function rangeValid(filters){
  const f={...defaults(),...filters};if(f.period!=='custom')return true;
  const from=bangkokTimestamp(f.from),to=bangkokTimestamp(f.to);
  return (from===null||Number.isFinite(from))&&(to===null||Number.isFinite(to))&&(from===null||to===null||to>=from);
 }
 function filterEvents(events,filters={},now=Date.now()/1000){
  const f={...defaults(),...filters};
  if(!rangeValid(f))return [];
  const duration={hour:3600,day:86400,week:604800}[f.period];
  const from=f.period==='custom'?bangkokTimestamp(f.from):duration?now-duration:null;
  const to=f.period==='custom'?bangkokTimestamp(f.to):duration?now:null;
  return (Array.isArray(events)?events:[]).filter(e=>{
   if(f.machine!=='all'&&(f.machine==='hub'?!!e.n:String(e.n)!==String(f.machine)))return false;
   if(f.category!=='all'&&classifyEvent(e)!==f.category)return false;
   const ts=Number(e.ts);
   if((from!==null||to!==null)&&(!Number.isFinite(ts)||e.ts==null))return false;
   if(from!==null&&ts<from||to!==null&&ts>to)return false;
   return true;
  }).sort((a,b)=>{
   const x=a.ts==null?NaN:Number(a.ts),y=b.ts==null?NaN:Number(b.ts);
   if(!Number.isFinite(x))return Number.isFinite(y)?1:0;if(!Number.isFinite(y))return -1;
   return f.sort==='oldest'?x-y:y-x;
  });
 }
 // Events page (approved mock v15): one filter bar, clean rows, fixed page size so the page never scrolls.
 const KIND={alarm:['alarm','alert'],fault:['fault','wrench'],connectivity:['','link'],maintenance:['screen','screen'],admin:['','settings'],other:['','history']};
 const MORE={th:{title:'ประวัติเหตุการณ์',prev:'หน้าก่อน',next:'หน้าถัดไป',of:'จาก'},en:{title:'Event history',prev:'Previous page',next:'Next page',of:'of'}};
 function render({events=[],nodes=[],lang='th',filters={},now=Date.now()/1000,icon=null}={}){
  const l=LABELS[lang==='en'?'en':'th'],m=MORE[lang==='en'?'en':'th'],f={...defaults(),...filters},filtered=filterEvents(events,f,now),ic=n=>icon?icon(n):'';
  const option=(value,label,selected)=>`<option value="${esc(value)}"${String(selected)===String(value)?' selected':''}>${esc(label)}</option>`;
  const select=(key,label,options)=>`<label class="gg-fsel history-field"><span>${esc(label)}</span><select data-history-filter="${key}" name="${key}">${options.map(([v,t])=>option(v,t,f[key])).join('')}</select></label>`;
  const machineOptions=[['all',l.allMachines],['hub',l.hub],...nodes.map(n=>[String(n.id??n.n),`Node ${n.id??n.n} · ${n.name||n.label||n.raw?.label||''}`])];
  const categories=[['all',l.all],...Object.keys(CATEGORY_TYPES).map(k=>[k,l[k]]),['other',l.other]];
  const dateField=(key,label)=>`<label class="gg-fsel history-field"><span>${esc(label)}</span><input type="datetime-local" name="${key}" data-history-filter="${key}" value="${esc(f[key])}"></label>`;
  const locale=lang==='en'?'en-GB':'th-TH',okTs=ts=>ts!=null&&Number.isFinite(Number(ts));
  const timeOf=ts=>okTs(ts)?new Date(Number(ts)*1000).toLocaleTimeString(locale,{timeZone:'Asia/Bangkok',hour12:false}):l.noDate;
  const dateOf=ts=>okTs(ts)?new Date(Number(ts)*1000).toLocaleDateString(locale,{timeZone:'Asia/Bangkok'}):'';
  const nodeFor=e=>nodes.find(n=>Number(n.id??n.n)===Number(e.n));
  const machineName=e=>{if(!e.n)return l.hub;const n=nodeFor(e);return n&&(!e.mac||e.mac===n.mac)?`${n.name||n.label||n.raw?.label||'Node '+e.n}`:`Node ${e.n} · ${e.label||e.mac||''}`;};
  const per=9,pages=Math.max(1,Math.ceil(filtered.length/per)),pg=Math.min(Math.max(1,Number(f.pg)||1),pages),rows=filtered.slice((pg-1)*per,pg*per);
  const row=e=>{const cat=classifyEvent(e),[cls,icn]=KIND[cat]||KIND.other,title=lang==='en'?(TITLES[e.type]||e.type):e.text||e.type;
   return `<div class="gg-erow" role="row"><span class="gg-fi ${cls}">${ic(icn)}</span><span class="num" role="cell"><b>${esc(timeOf(e.ts))}</b><small>${esc(dateOf(e.ts))}</small></span><span role="cell"><b>${esc(machineName(e))}</b>${e.n?`<small class="num">Node ${Number(e.n)}${e.mac?' · '+esc(e.mac):''}</small>`:''}</span><span role="cell"><span class="gg-typ" data-category="${cat}">${esc(l[cat])}</span></span><span class="gg-emsg" role="cell">${esc(title)}${lang==='en'&&e.text?`<small>${esc(e.text)}</small>`:''}</span><span role="cell">${e.code?`<code class="gg-code">${esc(e.code)}</code>`:'<span class="gg-muted">—</span>'}</span><span class="gg-eact" role="cell">${e.n&&nodeFor(e)?`<button type="button" class="gg-btn gg-sm history-node-link" data-action="detail" data-id="${Number(e.n)}">${esc(l.view)}</button>`:''}</span></div>`;};
  return `<div class="gg-pgh"><h1>${esc(m.title)}</h1><span class="gg-muted history-result-count" role="status" aria-live="polite"><b class="num">${filtered.length}</b> ${esc(l.result)} · ${events.length} ${esc(l.loaded)} · ${esc(l.scope)}</span></div>
   <form id="history-filter-form" class="gg-card gg-fbar history-filters" aria-label="${esc(l.filters)}">${select('machine',l.machine,machineOptions)}${select('category',l.category,categories)}${select('period',l.period,[['all',l.allTime],['hour',l.hour],['day',l.day],['week',l.week],['custom',l.custom]])}${f.period==='custom'?dateField('from',l.from)+dateField('to',l.to):''}${select('sort',l.sort,[['newest',l.newest],['oldest',l.oldest]])}<button type="button" class="gg-btn gg-right" data-action="history-reset">${esc(l.reset)}</button></form>
   ${!rangeValid(f)?`<p role="alert" class="gg-alert">${esc(l.invalid)}</p>`:''}
   <section id="history-results" class="gg-card gg-elist" role="table"><div class="gg-ehead" role="row"><span></span><span>${esc(l.time)}</span><span>${esc(l.machine)}</span><span>${esc(l.category)}</span><span>${esc(l.event)}</span><span></span><span></span></div>
    ${rows.map(row).join('')||`<div class="gg-chart-msg gg-static">${esc(l.none)}</div>`}
    <div class="gg-pager"><span class="num">${filtered.length?`${(pg-1)*per+1}–${Math.min(pg*per,filtered.length)} ${esc(m.of)} ${filtered.length}`:''}</span><button type="button" class="gg-btn gg-sm" data-action="history-page" data-value="-1" ${pg<=1?'disabled':''} aria-label="${esc(m.prev)}">${ic('left')}</button><span class="num">${pg} / ${pages}</span><button type="button" class="gg-btn gg-sm" data-action="history-page" data-value="1" ${pg>=pages?'disabled':''} aria-label="${esc(m.next)}">${ic('chevron')}</button></div></section>`;
 }
 const api={defaults,classifyEvent,filterEvents,render,bangkokTimestamp,rangeValid};
 if(typeof module!=='undefined'&&module.exports)module.exports=api;
 root.GGHistoryView=api;
})(typeof globalThis!=='undefined'?globalThis:this);
