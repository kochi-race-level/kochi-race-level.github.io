function previewAnalysis(D,key,target){
 const R=D.races,day=k=>k.split('_')[0],L={C3:1,C2:2,C1:3,B:4,A:5},days=(a,b)=>(Date.parse(a+'T00:00:00Z')-Date.parse(b+'T00:00:00Z'))/86400000;
 const points=(a,b,n)=>{if(!(a in L)||!(b in L))return 0;const d=L[b]-L[a];return n===1?({0:1,1:3,2:6,3:9,4:12}[d]||0):n<=3?({1:2,2:4,3:6,4:8}[d]||0):0};
 const time=t=>t!=null&&t!==''&&Number.isFinite(+t)&&+t>0;
 const hist=(D.hist[key]||[]).filter(f=>R[f[0]]&&day(f[0])<target&&day(f[0])<=D.last).sort((a,b)=>day(b[0]).localeCompare(day(a[0]))||Number(b[0].split('_')[1])-Number(a[0].split('_')[1]));
 const runs=hist.filter((f,i)=>i<5||days(target,day(f[0]))<=180).map((f,i)=>{
 const k=f[0],r=R[k],h=r.horses.find(h=>h[1]+'|'+h[2]===key);if(!h)return null;
 const late=time(h[4])?1+r.horses.filter(o=>time(o[4])&&+o[4]<+h[4]).length:null,front=+h[6]>0?+h[6]:null,strong=[];
 for(const o of r.horses){const id=o[1]+'|'+o[2];if(id===key)continue;let best=null;for(const z of D.hist[id]||[]){const rr=R[z[0]],delta=days(day(z[0]),day(k));if(!rr||delta<=0||delta>180||day(z[0])>=target||day(z[0])>D.last)continue;const p=points(r.class,rr.class,+z[1]);if(p>=2&&(!best||p>best.p))best={n:o[1],p,k:z[0],cls:rr.class,fin:+z[1],beat:time(h[4])&&time(o[4])&&+h[4]<+o[4]}}if(best)strong.push(best)}
 strong.sort((a,b)=>b.p-a.p);return {k,i:i+1,grade:target>D.last?r.grade:'保留',finish:h[3],late,front,strong,max:strong[0]?.p||0,days:days(target,day(k)),name:r.name};
 }).filter(Boolean);
 const sa=runs.filter(z=>z.i<=5&&['S','A'].includes(z.grade)),recent=runs.filter(z=>z.days<=180);
 return {runs,count:hist.length,sa:sa.length,late:sa.filter(z=>z.late!=null&&z.late<=3).length,front:sa.filter(z=>z.front!=null&&z.front<=3).length,max:Math.max(0,...recent.map(z=>z.max)),strongLate:recent.filter(z=>z.max>=3&&z.late!=null&&z.late<=3).length};
}


function weeklyRank(D,card){
 const map=new Map();for(const key of Object.keys(D.hist)){const name=key.split('|')[0].normalize('NFKC');if(!map.has(name))map.set(name,[]);map.get(name).push(key)}
 return card.horses.filter(h=>!h.withdrawn).map(h=>{
  const keys=map.get(h.name.normalize('NFKC'))||[],a=keys.length===1?previewAnalysis(D,keys[0],card.date):null;
  if(!a||!a.count||card.date<=D.last)return {...h,a:null,score:null};
  const relevant=a.runs.filter(z=>z.i<=5||z.days<=180&&z.max>=3&&z.late!=null&&z.late<=3);
  // Single run combines grade and content; repetition is a capped bonus.
  const evidence=relevant.map(z=>{
   const sa=z.grade==='S'||z.grade==='A',late=z.late!=null&&z.late<=3,front=z.front!=null&&z.front<=3,strong=z.max>=3;
   const base=z.grade==='S'?4:z.grade==='A'?3:0;
   const points=(z.i<=5?base:0)+(z.i<=5&&sa&&late?3:0)+(z.i<=5&&sa&&front?2:0)+(strong&&late&&z.days<=180?4+Math.min(z.max,9)/3:0);
   return {z,points:Math.round(points*10)/10};
  }).filter(e=>e.points>0).sort((a,b)=>b.points-a.points||a.z.days-b.z.days);
  const score=evidence.length?Math.round((evidence[0].points+Math.min(2,(evidence.length-1)*0.5))*10)/10:0;
  return {...h,a,score,evidence};
 }).sort((a,b)=>(b.score??-1)-(a.score??-1)||(b.a?.strongLate??-1)-(a.a?.strongLate??-1)||(b.a?.max??-1)-(a.a?.max??-1)||a.n-b.n);
}


const fs=require('node:fs');
const ledger=JSON.parse(fs.readFileSync('prediction_history.json','utf8'));
const D=JSON.parse(fs.readFileSync('kochi_data.json','utf8'));
const W=JSON.parse(fs.readFileSync('week_cards.json','utf8'));
const now=new Date(), jst=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
const existing=new Set(ledger.races.map(r=>r.date+'_'+r.r));
let added=0;
for(const c of W.races){
 const id=c.date+'_'+c.r;
 // Conservative cutoff: no new predictions once the race day has started.
 if(existing.has(id)||!c.count||c.horses.length!==c.count||c.date<=jst||c.date<=D.last||!c.source||!c.time)continue;
 if(new Set(c.horses.map(h=>h.n)).size!==c.count||c.horses.some(h=>!h.name))continue;
 const a=weeklyRank(D,c);
 const picks=a.filter(h=>h.score>0).slice(0,2).map((h,i)=>({rank:i+1,n:h.n,name:h.name,score:h.score,evidence:{race:h.evidence[0].z.k,grade:h.evidence[0].z.grade,late:h.evidence[0].z.late,front:h.evidence[0].z.front,strong:h.evidence[0].z.max}}));
 ledger.races.push({date:c.date,r:c.r,name:c.name,final:c.name.includes('ファイナル'),scheduled:c.date+'T'+c.time+':00+09:00',lockedDate:jst,lockedAt:now.toISOString(),model:'0.9',dataThrough:D.last,source:c.source,entryCount:c.count,matched:a.filter(h=>h.a).length,picks,result:null});
 existing.add(id);added++;
}
if(added)fs.writeFileSync('prediction_history.json',JSON.stringify(ledger,null,2)+'\n');
console.log('New immutable race snapshots:',added);
