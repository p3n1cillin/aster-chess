"use strict";

const $ = id => document.getElementById(id);

const ns = "http://www.w3.org/2000/svg";

const symbols = {p:"pawn",n:"knight",b:"bishop",r:"rook",q:"queen",k:"king"};

const shapes = {

 p:'<circle cx="32" cy="17" r="8"/><path d="M25 28h14l-2 11 8 10H19l8-10z"/><path d="M18 49h28l3 7H15z"/>',

 n:'<path d="M18 49c1-9 7-14 15-17l-4-5-9 9-7-5 6-16 10-6 2-5 5 8c11 6 16 18 10 37z"/><path d="M17 49h30l3 7H14z"/><circle cx="28" cy="21" r="1.9" fill="var(--piece-stroke)" stroke="none"/><path d="M17 29l6 1" fill="none"/>',

 b:'<path d="M32 6c-18 12-14 25 0 28 14-3 18-16 0-28z"/><path d="M35 12l-9 13" fill="none"/><path d="M27 34h10l-2 7 10 8H19l10-8z"/><path d="M18 49h28l3 7H15z"/>',

 r:'<path d="M17 11h8v8h5v-8h5v8h5v-8h8v16H17z"/><path d="M23 27h18l-2 16 7 7H18l7-7z"/><path d="M17 50h30l3 6H14z"/>',

 q:'<path d="M16 19l9 9 7-15 7 15 9-9-7 23H23z"/><circle cx="15" cy="17" r="3"/><circle cx="32" cy="11" r="3"/><circle cx="49" cy="17" r="3"/><path d="M24 42h16l7 8H17z"/><path d="M17 50h30l3 6H14z"/>',

 k:'<path d="M32 5v13m-6-7h12" fill="none" stroke-width="4"/><path d="M32 23c-15-13-23 4-11 14l4 8h14l4-8c12-10 4-27-11-14z"/><path d="M24 44h16l7 6H17z"/><path d="M17 50h30l3 6H14z"/>'

};

function pieceSvg(piece){if(!piece)return "";const white=piece===piece.toUpperCase();return `<svg class="piece" viewBox="0 0 64 64" aria-hidden="true" style="--piece-stroke:${white?"#485747":"#d7e2c7"}"><g fill="${white?"#f8f8e9":"#203b2d"}" stroke="${white?"#485747":"#b5caaa"}" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round">${shapes[piece.toLowerCase()]}</g></svg>`;}

function fenPieces(fen){const pieces=Array(64).fill(null);let rank=7;for(const row of fen.split(" ")[0].split("/")){let file=0;for(const char of row){if(/[1-8]/.test(char))file+=+char;else pieces[rank*8+file++]=char;}rank--;}return pieces;}

function squareName(index){return "abcdefgh"[index%8]+(Math.floor(index/8)+1);}

function squareIndex(name){return "abcdefgh".indexOf(name[0])+(+name[1]-1)*8;}

function cp(value){if(value==null)return "—";if(Math.abs(value)>29000){const mate=Math.ceil((30000-Math.abs(value))/2);return `${value<0?"−":""}M${mate}`;}return `${value>0?"+":value<0?"−":""}${(Math.abs(value)/100).toFixed(2)}`;}

function compact(value){return value==null?"—":new Intl.NumberFormat("en",{notation:"compact",maximumFractionDigits:1}).format(value);}

let state=null,analysis=null,trace=null,flipped=false,selected=null,lens="none",review=-1,preview=null,samples=[],pending=false,toastTimer,lastSequence=-1;

const squares=[];

for(let i=0;i<64;i++){const button=document.createElement("button");button.className="square";button.addEventListener("click",()=>selectSquare(button.dataset.square));$("board").append(button);squares.push(button);}

function toast(message){$("toast").textContent=message;$("toast").classList.add("visible");clearTimeout(toastTimer);toastTimer=setTimeout(()=>$("toast").classList.remove("visible"),4200);}

async function post(path,body={}){pending=true;renderBoard();try{const response=await fetch("/api/"+path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});const value=await response.json();if(!response.ok)throw new Error(value.error||"Request failed");acceptState(value);return value;}catch(error){toast(error.message);throw error;}finally{pending=false;renderBoard();if(state)renderLabels();}}

function acceptState(value){if(value.revision<lastSequence)return;lastSequence=value.revision;if(!state)flipped=value.humanSide===1;if(!value.moves.length||review>=value.moves.length)review=-1;const different=!state||state.searchId!==value.searchId;state=value;selected=null;if(different){samples=[];preview=null;}analysis=value.depths.at(-1)||null;trace=value.trace||null;render();if(state.error)toast(state.error);}

function gameFen(){return review>=0&&state.moves[review]?state.moves[review].fen:state.fen;}

function renderBoard(){if(!state)return;const pieces=fenPieces(gameFen());const last=review>=0?state.moves[review]:state.moves.at(-1);const enabled=!pending&&!state.thinking&&state.side===state.humanSide&&!state.result&&review<0;const max=Math.max(1,...(trace?.view.destinationVisits||[]));for(let cell=0;cell<64;cell++){const index=flipped?(Math.floor(cell/8)*8+7-cell%8):((7-Math.floor(cell/8))*8+cell%8);const name=squareName(index),piece=pieces[index],button=squares[cell];button.dataset.square=name;button.className="square"+(((index%8+Math.floor(index/8))%2===0)?" dark":"")+(piece?" occupied":"")+(selected===name?" selected":"")+(last&&(last.uci.slice(0,2)===name||last.uci.slice(2,4)===name)?" last":"");if(enabled&&selected&&state.legal.some(move=>move.startsWith(selected+name)))button.classList.add("legal");button.disabled=!enabled;button.setAttribute("aria-label",name+(piece?", "+(piece===piece.toUpperCase()?"White ":"Black ")+symbols[piece.toLowerCase()]:", empty"));let heat=0,color="#70b5e4";if(review<0&&lens==="search")heat=Math.log1p(trace?.view.destinationVisits[index]||0)/Math.log1p(max)*.65;else if(review<0&&(lens==="white"||lens==="black")){heat=Math.min(.68,(lens==="white"?state.whiteAttacks:state.blackAttacks)[index]*.18);color=lens==="white"?"#99f0cf":"#b893e0";}button.style.setProperty("--heat-alpha",heat);button.style.setProperty("--heat-color",color);button.innerHTML='<span class="heat"></span>'+pieceSvg(piece)+(cell>=56?`<span class="coordinate file">${name[0]}</span>`:"")+(cell%8===0?`<span class="coordinate rank">${name[1]}</span>`:"");}drawArrow(review<0&&analysis?.rootFen===state.fen?analysis.pv[0]?.uci:null);}

function drawArrow(move){const arrow=$("move-arrow");if(!move){arrow.style.display="none";return;}const point=name=>{const i=squareIndex(name),f=i%8,r=Math.floor(i/8);return flipped?[(7-f)*100+50,r*100+50]:[f*100+50,(7-r)*100+50];};const [x1,y1]=point(move.slice(0,2)),[x2,y2]=point(move.slice(2,4));for(const [key,value] of Object.entries({x1,y1,x2,y2}))arrow.setAttribute(key,value);arrow.style.display="block";}

function selectSquare(name){if(!state||state.thinking||pending||review>=0||state.result)return;const candidates=selected?state.legal.filter(move=>move.startsWith(selected+name)):[];if(candidates.length){if(candidates.some(move=>move.length===5)){const options=$("promotion-choices");options.replaceChildren();for(const move of candidates){const button=document.createElement("button");button.setAttribute("aria-label","Promote to "+symbols[move[4]]);button.innerHTML=pieceSvg(state.humanSide===0?move[4].toUpperCase():move[4]);button.addEventListener("click",()=>{$("promotion-dialog").close();sendMove(move);});options.append(button);}$("promotion-dialog").showModal();}else sendMove(candidates[0]);return;}const piece=fenPieces(state.fen)[squareIndex(name)];selected=piece&&(piece===piece.toUpperCase()?0:1)===state.humanSide?name:null;renderBoard();}

function sendMove(move){selected=null;post("move",{move}).catch(()=>{});}

function renderMini(){if(!state)return;const value=preview||{fen:trace?.view.fen||analysis?.rootFen||state.fen,line:trace?.view.line||[],kind:trace?.view.finished?"Last search root":"Live sampled branch"};const pieces=fenPieces(value.fen);$("mini-board").replaceChildren();for(let cell=0;cell<64;cell++){const index=flipped?(Math.floor(cell/8)*8+7-cell%8):(7-Math.floor(cell/8))*8+cell%8;const square=document.createElement("div");square.className="mini-square"+((index%8+Math.floor(index/8))%2===0?" dark":"");square.innerHTML=pieceSvg(pieces[index]);$("mini-board").append(square);}$("preview-title").textContent=preview?"Inspecting a position":"Live searched position";$("branch-kind").textContent=value.kind.toUpperCase();$("branch-path").textContent=value.line.length?value.line.join(" → "):state.thinking?"At the search root":analysis?"The position Aster last analyzed.":"Play a move to watch Aster search.";}

function renderChart(){const data=state?.depths||[];const points=data.map((item,i)=>[8+(data.length<2?0:i/(data.length-1)*424),42-Math.tanh(item.scoreWhite/350)*34]);$("chart-path").setAttribute("d",points.map((p,i)=>(i?"L":"M")+p.join(",")).join(" "));$("chart-dots").replaceChildren();points.forEach((p,i)=>{const circle=document.createElementNS(ns,"circle");circle.setAttribute("cx",p[0]);circle.setAttribute("cy",p[1]);circle.setAttribute("r",2.5);circle.setAttribute("fill","#a5dfbd");const title=document.createElementNS(ns,"title");title.textContent=`Depth ${data[i].depth}: ${cp(data[i].scoreWhite)}`;circle.append(title);$("chart-dots").append(circle);});$("depth-caption").textContent=data.length?`Depth ${data[0].depth} → ${data.at(-1).depth}`:"Awaiting search";}

function renderPv(){const container=$("pv");container.replaceChildren();if(!analysis?.pv.length){const text=document.createElement("span");text.className="muted";text.textContent="Aster's predicted line will appear here.";container.append(text);return;}analysis.pv.forEach((move,i)=>{const button=document.createElement("button");const number=document.createElement("small");number.textContent=(i+1)+".";button.append(number,document.createTextNode(move.san));if(preview?.pvIndex===i)button.classList.add("active");button.addEventListener("click",()=>{preview={fen:move.fen,line:analysis.pv.slice(0,i+1).map(m=>m.san),kind:`Predicted line · ply ${i+1}`,pvIndex:i};renderMini();renderPv();});container.append(button);});$("pv-caption").textContent=`Depth ${analysis.depth}`;}

function renderRoots(){const container=$("root-moves");container.replaceChildren();const rootRows=trace?.view.rootMoves||[];if(!rootRows.length){const row=document.createElement("tr"),cell=document.createElement("td");cell.colSpan=4;cell.className="muted";cell.textContent="Root moves will appear during search.";row.append(cell);container.append(row);return;}const best=analysis?.pv[0]?.uci;const ordered=[...rootRows].sort((a,b)=>(b.searching-a.searching)||(b.move===best)-(a.move===best)||(b.score??-Infinity)-(a.score??-Infinity));for(const move of ordered){const row=document.createElement("tr");row.className=(move.searching?"root-active ":"")+(move.move===best?"root-selected":"");const label=document.createElement("td");label.textContent=move.move.slice(0,2)+" → "+move.move.slice(2);const score=document.createElement("td");score.textContent=(move.bound==="upper"?"≤ ":move.bound==="lower"?"≥ ":"")+cp(move.score);const nodes=document.createElement("td");nodes.textContent=compact(move.nodes);const status=document.createElement("td");status.textContent=move.searching?"searching":move.bound==="unfinished"?"unfinished":move.move===best?"latest PV":move.bound==="exact"?"window exact":"bound";row.append(label,score,nodes,status);container.append(row);}$("root-caption").textContent=`Depth ${trace.view.depth} · ${trace.rootSide===0?"White":"Black"} to move`;}

function renderMetrics(){const view=trace?.view;const score=state.result==="1-0"?30000:state.result==="0-1"?-30000:state.result==="1/2-1/2"?0:analysis?.scoreWhite??state.scoreWhite;$("score").textContent=cp(score);$("rail-label").textContent=review>=0?"—":cp(score);const fill=review>=0?50:state.result==="1-0"?100:state.result==="0-1"?0:state.result==="1/2-1/2"?50:50+Math.tanh(score/400)*45;$("eval-fill").style.height=fill+"%";$("score-description").textContent=state.result?state.status:!analysis?"Static evaluation; no search has completed yet.":Math.abs(score)>29000?`Aster's search reports a mate for ${score>0?"White":"Black"}.`:Math.abs(score)<30?"Aster sees a roughly balanced position.":`${score>0?"White":"Black"} is favoured in Aster's current line.`;$("depth").textContent=analysis?`${analysis.depth} / ${analysis.selectiveDepth}`:view?`${view.depth} / —`:"—";const nodes=view?.nodes??analysis?.nodes,ms=view?.milliseconds??analysis?.milliseconds;$("nodes").textContent=compact(nodes);$("speed").textContent=ms>0?compact(Math.round(nodes*1000/ms)):"—";$("elapsed").textContent=ms!=null?(ms/1000).toFixed(2)+"s":"—";$("search-state").textContent=state.thinking?(state.mode==="analyze"?"ANALYZING":"SEARCHING"):analysis?"LAST SEARCH":"WAITING";$("thinking-lamp").className="lamp"+(state.thinking?" thinking":analysis?" connected":"");for(const [id,key] of [["main-count","mainNodes"],["q-count","quiescenceNodes"],["beta-count","betaCutoffs"],["tt-count","tableCutoffs"]])$(id).textContent=compact(view?.[key]);$("probe-count").textContent=view?`${compact(view.nullProbes)} / ${compact(view.reducedMoves)}`:"—";}

function renderHistory(){const target=$("move-history");target.replaceChildren();if(!state.moves.length){const text=document.createElement("p");text.className="muted";text.textContent="Your story starts with the first move.";target.append(text);return;}state.moves.forEach((move,i)=>{if(move.side===0||i===0){const number=document.createElement("span");number.className="number";number.textContent=move.number+".";target.append(number);if(move.side===1)target.append(document.createElement("span"));}const button=document.createElement("button");button.textContent=move.san;button.className=(review===i||review<0&&i===state.moves.length-1)?"active":"";button.addEventListener("click",()=>{review=i;selected=null;renderBoard();renderHistory();renderLabels();renderMetrics();});target.append(button);});if(review<0)target.scrollTop=target.scrollHeight;}

function renderLabels(){$("lens-note").textContent=review>=0?"Lenses paused during replay":"Click a piece, then a destination";const canMove=state.side===state.humanSide&&!state.thinking&&!state.result;const bottomSide=flipped?1:0,bottomHuman=bottomSide===state.humanSide;$("top-avatar").textContent=bottomHuman?"✳":"Y";$("bottom-avatar").textContent=bottomHuman?"Y":"✳";$("top-avatar").className="avatar "+(bottomHuman?"engine-avatar":"human-avatar");$("bottom-avatar").className="avatar "+(bottomHuman?"human-avatar":"engine-avatar");$("top-name").textContent=bottomHuman?"Aster":"You";$("bottom-name").textContent=bottomHuman?"You":"Aster";const humanCaption=state.humanSide===0?"White pieces":"Black pieces",engineCaption="Classical evaluation · one thread";$("top-caption").textContent=bottomHuman?engineCaption:humanCaption;$("bottom-caption").textContent=bottomHuman?humanCaption:engineCaption;$("turn-badge").textContent=state.result?"GAME OVER":review>=0?"REVIEWING":state.thinking?"ASTER SEARCHING":canMove?"YOUR TURN":"ASTER'S TURN";$("game-status").textContent=review>=0?"Reviewing move "+state.moves[review]?.san:state.result?state.status:state.thinking?(state.mode==="analyze"?"Analyzing your position":"Thinking…"):state.inCheck?"You're in check":state.moves.length?"Your move":"Choose a piece to begin";$("undo").disabled=pending||!state.moves.some(m=>m.side===state.humanSide);$("analyze").disabled=pending||state.thinking||!!state.result;$("move-now").hidden=!state.thinking;$("move-now").textContent=state.mode==="analyze"?"■ Stop analysis":"■ Move now";$("history-prev").disabled=!state.moves.length||review===0;$("history-next").disabled=review<0;$("material").textContent=cp(state.materialWhite);$("piece-value").textContent=cp(state.pieceSquareWhite);$("activity-value").textContent=cp(state.structureActivityWhite);$("tempo-value").textContent=cp(state.tempoWhite);$("phase-label").textContent=`Phase ${state.phase}/24 · ${state.phase<=8?"endgame":state.phase<20?"transition":"middlegame"}`;}

function renderSamples(){const target=$("sample-paths");target.replaceChildren();$("sample-count").textContent=samples.length+" retained samples";for(const sample of samples.slice(-12).reverse()){const button=document.createElement("button");button.textContent=`d${sample.view.depth} · ${sample.view.line.join(" → ")||"root"}`;button.addEventListener("click",()=>{preview={fen:sample.view.fen,line:sample.view.line,kind:"Recorded search sample"};renderMini();});target.append(button);}}

function render(){if(!state)return;renderBoard();renderLabels();renderMetrics();renderChart();renderPv();renderMini();renderRoots();renderHistory();renderSamples();}

$("new-game").onclick=()=>{$("side").value=state?.humanSide===1?"black":"white";$("budget").value=String(state?.milliseconds||3000);$("new-dialog").showModal();};

$("new-form").onsubmit=async event=>{event.preventDefault();try{await post("new",{side:$("side").value,milliseconds:+$("budget").value});review=-1;flipped=state.humanSide===1;$("new-dialog").close();render();}catch{}};

document.querySelectorAll("[data-close]").forEach(button=>button.onclick=()=>$(button.dataset.close).close());

$("undo").onclick=()=>{review=-1;post("undo").catch(()=>{});};$("flip").onclick=()=>{flipped=!flipped;render();};$("analyze").onclick=()=>post("analyze").catch(()=>{});$("move-now").onclick=()=>post("stop").catch(()=>{});

$("resume-preview").onclick=()=>{preview=null;renderMini();renderPv();};

document.querySelectorAll("[data-lens]").forEach(button=>button.onclick=()=>{lens=button.dataset.lens;document.querySelectorAll("[data-lens]").forEach(b=>b.classList.toggle("active",b===button));$("lens-description").textContent=lens==="search"?"Intensity counts searched nodes by the destination of the last move, including repeated visits.":lens==="none"?"Dots show legal destinations. Last move is highlighted.":"Geometric attacks per square. Pinned pieces and friendly slider blockers are included; this is not a legal-capture map.";renderBoard();});

$("history-prev").onclick=()=>{review=review<0?Math.max(0,state.moves.length-2):Math.max(0,review-1);renderBoard();renderLabels();renderHistory();renderMetrics();};$("history-next").onclick=()=>{review=review>=state.moves.length-2?-1:review+1;renderBoard();renderLabels();renderHistory();renderMetrics();};$("history-live").onclick=()=>{review=-1;render();};

$("copy-fen").onclick=async()=>{try{await navigator.clipboard.writeText(gameFen());toast("Position copied.");}catch{toast("Clipboard unavailable. Use Load position to view and copy the FEN.");$("fen-input").value=gameFen();$("fen-dialog").showModal();}};

$("load-position").onclick=()=>{$("fen-input").value=state.fen;$("fen-dialog").showModal();};$("fen-form").onsubmit=async event=>{event.preventDefault();try{await post("new",{side:state.humanSide===0?"white":"black",milliseconds:state.milliseconds,fen:$("fen-input").value.trim()});review=-1;$("fen-dialog").close();render();}catch{}};

const events=new EventSource("/api/events");events.onopen=()=>{$("connection").className="lamp connected";$("connection-text").textContent="Connected locally";};events.onerror=()=>{$("connection").className="lamp";$("connection-text").textContent="Reconnecting…";};

function freshEvent(event){const seq=Number(event.lastEventId);if(seq<lastSequence)return false;lastSequence=seq;return true;}

events.addEventListener("state",event=>{if(freshEvent(event))acceptState(JSON.parse(event.data));});

events.addEventListener("analysis",event=>{if(!freshEvent(event))return;const value=JSON.parse(event.data);if(!state||value.searchId!==state.searchId)return;analysis=value;state.depths=state.depths.filter(d=>d.depth!==value.depth);state.depths.push(value);renderMetrics();renderChart();renderPv();renderBoard();});

events.addEventListener("trace",event=>{if(!freshEvent(event))return;const value=JSON.parse(event.data);if(!state||value.searchId!==state.searchId)return;trace=value;state.trace=value;if(value.view.line.length){samples.push(value);if(samples.length>48)samples.shift();}renderMetrics();renderMini();renderRoots();renderSamples();if(lens==="search")renderBoard();});

fetch("/api/state").then(response=>response.json()).then(acceptState).catch(()=>toast("Cannot connect to Aster. Start the local server and refresh."));

