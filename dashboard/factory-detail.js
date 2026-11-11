/* Node page (approved mock v15): one box per sensor with its own history chart; the sensor at fault gets the ring.
   Uses the existing live adapters and commands only. */
(function(root){
 'use strict';
 const words={
  th:{back:'ภาพรวม',signals:'สัญญาณเซ็นเซอร์',diagnostics:'ข้อมูลสำหรับช่าง',issues:'รหัสปัญหาที่รายงาน',care:'ตะแกรง',lastChange:'เปลี่ยนล่าสุด',careHistory:'ประวัติการดูแล',record:'บันทึกเปลี่ยน',unloaded:'ยังไม่ได้โหลดประวัติ',noCare:'ยังไม่มีบันทึกการเปลี่ยน',timeline:'เหตุการณ์ของเครื่องนี้',allEvents:'ประวัติทั้งหมด',range:'ช่วงเวลากราฟ',noNode:'ยังไม่มี Node',slotHistory:'ประวัติผูกกับช่องเครื่อง ไม่ย้ายตาม MAC',used:'ใช้ไปแล้ว',fresh:'ข้อมูลล่าสุด',chA:'ช่อง A',chB:'ช่อง B',ratio:'อัตราส่วนเทียบค่าฐาน ไม่ใช่ dB'},
  en:{back:'Overview',signals:'Sensor signals',diagnostics:'Technician details',issues:'Reported codes',care:'Screen',lastChange:'Last replacement',careHistory:'Care history',record:'Record replacement',unloaded:'History not loaded yet',noCare:'No replacement recorded',timeline:'Machine events',allEvents:'All events',range:'Chart time range',noNode:'No Node assigned',slotHistory:'History belongs to the machine slot, not the MAC',used:'used',fresh:'Last sample',chA:'Channel A',chB:'Channel B',ratio:'Ratio to baseline, not dB'}
 };
 const pad=n=>String(n).padStart(2,'0');
 const LEVEL={alarm:'alarm',fault:'fault',warning:'fault',offline:'offline',unknown:'unknown',learning:'learning',normal:'normal',rest:'rest',empty:'empty'};
 function render(c){
  const {node:n,lang='th',t,esc,icon,name,age,assess,range='30m',commandPending=false,events=[],life,when,sensorState,sensorChart,feedRows,nodes=[],wearOf,statusIcon,isAdmin}=c;
  if(!n)return `<div class="gg-chart-msg">${esc(t('empty'))}</div>`;
  const l=words[lang]||words.th,id=Number(n.id),a=assess(n),issues=Array.isArray(a.issues)?a.issues:[];
  const lvl=a.level==='normal'&&n.status==='rest'?'rest':LEVEL[a.level]||'unknown';
  const attrs=`data-id="${id}"`,isAlarm=a.level==='alarm'&&Boolean(n.raw?.alarm_active)&&n.mode==='ALARM_ON';
  const ack=isAlarm&&isAdmin?`<button type="button" class="gg-btn gg-pri" data-action="ack" ${attrs} ${n.ack||commandPending?'disabled':''}>${icon('check')}${esc(t('ack'))}</button>`:'';
  const settings=isAdmin?`<button type="button" class="gg-btn" data-action="machine-settings" ${attrs}>${icon('settings')}${esc(t('machineSettings'))}</button>`:'';
  const careBtn=`<button type="button" class="gg-btn" data-action="maintenance-select" ${attrs}>${icon('screen')}${esc(l.careHistory)}</button>`;
  // Never show retained raw readings as current after a disconnect; numeric zero stays visible.
  const currentNumber=(v,suffix)=>typeof v==='number'&&Number.isFinite(v)?`${v.toFixed(1)} ${suffix}`:'—';
  const info=[['MAC',n.mac||l.noNode],[t('nodeState'),['offline','unknown','empty'].includes(n.status)?a.title:n.raw?.state||'—'],[t('mode'),n.mode||'—'],[t('supply'),currentNumber(n.vin,'V')],[t('boardTemp'),currentNumber(n.tc,'°C')],[t('firmware'),n.fw||n.raw?.fw||'—']];
  const switcher=`<div class="gg-switch"><button type="button" class="gg-btn" data-action="nav" data-page="overview">${icon('arrow')}${esc(l.back)}</button>${nodes.map(x=>{const xa=assess(x),xl=xa.level==='normal'&&x.status==='rest'?'rest':LEVEL[xa.level]||'unknown';return `<button type="button" class="gg-pill" data-action="detail" data-id="${x.id}" data-level="${xl}" ${x.id===id?'aria-current="true"':''}><i class="gg-pdot"></i><span class="num">${pad(x.id)}</span>${esc(name(x))}</button>`;}).join('')}</div>`;
  const box=ch=>{const x=sensorState(n,ch);return `<section class="gg-card gg-sbox${x.hot?' hot':''}${x.fault?' f':''}"><div class="gg-sl"><b>${ch==='a'?'Pickup':'Piezo'}</b>${x.hot?`<span class="gg-tagc">${esc(x.tag)}</span>`:''}<span class="gg-st"><i class="gg-sd ${x.led}"></i>${esc(x.label)}</span><strong class="gg-v num${x.val==null?' gg-dim':''}">${x.val==null?'—':Number(x.val).toFixed(2)}</strong><span class="gg-hint">${ch==='a'?l.chA:l.chB}</span></div><div class="gg-chw">${sensorChart(n,ch)}</div></section>`;};
  const ranges=['30m','1h','8h'].map(value=>`<button type="button" data-action="range" data-value="${value}" aria-pressed="${range===value}">${value==='30m'?(lang==='th'?'30 นาที':'30 min'):value==='1h'?(lang==='th'?'1 ชั่วโมง':'1 h'):(lang==='th'?'8 ชั่วโมง':'8 h')}</button>`).join('');
  const machineEvents=(Array.isArray(events)?events:[]).filter(e=>Number(e.n)===id).slice().sort((x,y)=>(Number(y.ts)||0)-(Number(x.ts)||0)).slice(0,5);
  const maintenance=root.GGMaintenanceView,careModel=maintenance?.model?maintenance.model(life,n):null,last=careModel?.latest;
  const lastText=last?(maintenance.dateLabel?maintenance.dateLabel(last.ts,last.date,lang):last.ts&&when?when(last.ts):last.date||'—'):careModel?.loaded?l.noCare:l.unloaded;
  const wear=wearOf?wearOf(n):null;
  return `${switcher}<div class="gg-mgrid"><div class="gg-mcol">
   <section class="gg-card gg-mhead" data-level="${lvl}"><h1><span class="num">${pad(id)}</span>${esc(name(n))}<span class="gg-chip" data-level="${lvl}">${icon(statusIcon?statusIcon(lvl):'check')}${esc(a.title)}</span></h1><div class="gg-acts">${ack}${settings}${careBtn}</div>
    <p class="gg-adv">${esc(a.needsAttention?a.action||a.summary:a.summary)} <span class="gg-muted">· ${esc(l.fresh)} ${esc(age(n))}</span></p></section>
   <div class="gg-shd"><h3 class="gg-h3">${esc(l.signals)}</h3><span class="gg-muted">${esc(l.ratio)}</span><div class="gg-seg" role="group" aria-label="${esc(l.range)}">${ranges}</div></div>
   <div class="gg-sgrid">${box('a')}${box('b')}</div></div>
  <div class="gg-mcol">
   <section class="gg-card gg-feedcard gg-pad"><div class="gg-rhd"><h3 class="gg-h3">${esc(l.timeline)}</h3><button type="button" class="gg-lnk" data-action="nav" data-page="history">${esc(l.allEvents)}${icon('chevron')}</button></div><ol class="gg-feed">${feedRows(machineEvents)}</ol></section>
   ${issues.length?`<section class="gg-card gg-pad"><h3 class="gg-h3">${esc(l.issues)}</h3><div class="gg-codes">${issues.map(i=>`<div><code class="gg-code">${esc(i.code)}</code><b>${esc(i.title)}</b><small>${esc(i.action||a.action||'')}</small></div>`).join('')}</div></section>`:''}
   <section class="gg-card gg-pad gg-care"><div class="gg-rhd"><h3 class="gg-h3">${esc(l.care)}</h3>${isAdmin?`<button type="button" class="gg-btn gg-sm" data-action="record" ${attrs}>${icon('plus')}${esc(l.record)}</button>`:''}</div>
    <div class="gg-care-big"><b class="num${wear>=90?' hi':''}">${wear==null?'—':Math.round(wear)+'%'}</b><span>${esc(l.used)} · ${esc(l.lastChange)} ${esc(lastText)}</span></div><div class="gg-wear${wear>=90?' hi':''}"><span class="gg-bar"><i style="width:${wear==null?0:Math.min(100,Math.max(0,wear))}%"></i></span></div><small class="gg-muted">${esc(l.slotHistory)}</small></section>
   <section class="gg-card gg-pad"><h3 class="gg-h3">${esc(l.diagnostics)}</h3><div class="gg-kvg">${info.map(([k,v])=>`<div>${esc(k)}<b class="num">${esc(v)}</b></div>`).join('')}</div></section>
  </div></div>`;
 }
 const api={render};root.GGFactoryDetail=api;
 if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
