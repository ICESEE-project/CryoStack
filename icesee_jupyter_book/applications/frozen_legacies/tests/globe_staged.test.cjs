'use strict';
// CPU scheduling and lifecycle tests. These do not simulate GPU latency.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{createRequire}=require('node:module');
const helper=path.join(__dirname,'globe_view.test.cjs');
const prelude=fs.readFileSync(helper,'utf8').split('const wait =')[0];
const holder={exports:{}};
new Function('require','module','__dirname',prelude+'\nmodule.exports={harness,Feature,Geometry,Layer,style,stroke,fill,circle,Events,CesiumEvent,El};')(createRequire(helper),holder,__dirname);
const {harness,Feature,Geometry,Layer,style,stroke,fill,circle,Events,CesiumEvent}=holder.exports;
const baseline=require(path.join(process.env.GLOBE_BASELINE_ROOT,'assets/globe_view.js')).testing;
const plain=x=>JSON.parse(JSON.stringify(x));
const turn=()=>new Promise(resolve=>setImmediate(resolve));
function leaves(group,out={points:[],lines:[],labels:[],billboards:[],polygons:[]}){
 for(const x of group.items||[]){
  if(x.items) {if(x.options?.geometryInstances)out.polygons.push(...x.options.geometryInstances);else leaves(x,out);}
  else if(x.positions)out.lines.push(x);
  else if(x.text!==undefined)out.labels.push(x);
  else if(x.image)out.billboards.push(x);
  else if(x.position)out.points.push(x);
 }
 return out;
}
function flatGeometry(type,coords){
 const nested=coords,flat=[],ends=[],endss=[];
 const ring=r=>{for(const p of r)flat.push(p[0],p[1],p[2]??777);return flat.length;};
 if(type==='Point')ring([coords]);
 else if(['LineString','MultiPoint'].includes(type))ring(coords);
 else if(['Polygon','MultiLineString'].includes(type))for(const r of coords)ends.push(ring(r));
 else if(type==='MultiPolygon')for(const p of coords)endss.push(p.map(ring));
 return {getType:()=>type,getFlatCoordinates:()=>flat,getStride:()=>3,getEnds:()=>ends,getEndss:()=>endss,
  getCoordinates(){throw Error('unbounded coordinate copy');},clone(){throw Error('unbounded geometry clone');},
  reference:new Geometry(type,nested)};
}
function exhaust(iterator,quantum=512){let steps=0,max=0,last;do{let n=0;do{last=iterator.next();n++;steps++;}while(!last.done&&n<quantum);max=Math.max(max,n);}while(!last.done);return {value:last.value,steps,max};}
for(const [type,coords] of [
 ['Point',[20,-80,7]],['MultiPoint',[[170,-80],[-175,-80],[NaN,-80]]],
 ['LineString',[[170,-80],[-175,-81],[NaN,NaN],[20,-80],[21,-81]]],
 ['MultiLineString',[[[0,-80],[1,-80]],[[10,-85],[11,-85]]]],
 ['Polygon',[[[0,-80],[4,-80],[4,-84],[0,-80]],[[1,-81],[2,-81],[1,-82],[1,-81]]]],
 ['MultiPolygon',[[[[0,-80],[4,-80],[4,-84],[0,-80]]],[[[20,-80],[24,-80],[24,-84],[20,-80]]]]]
])test('incremental public flat-coordinate equivalence: '+type,()=>{
 const h=harness(),g=flatGeometry(type,coords),before=JSON.stringify(g.getFlatCoordinates());
 const got=exhaust(h.api.testing.convertGeometrySteps(g,p=>p)).value;
 assert.deepEqual(plain(got),plain(baseline.convertGeometry(g.reference,p=>p)));assert.equal(JSON.stringify(g.getFlatCoordinates()),before);h.cleanup();
});
test('circle, collection, unsupported and invalid holes retain baseline output',()=>{
 const h=harness(),T=h.api.testing;
 const gs=[new Geometry('Circle',{center:[0,0],radius:200000}),new Geometry('Unsupported',[]),new Geometry('Polygon',[[[0,-80],[1,-80],[1,-81],[0,-80]],[[0,-80],[1,-80],[NaN,-81],[0,-80]]])];
 for(const g of gs)assert.deepEqual(plain(T.convertGeometry(g,p=>[p[0]/10000,-80+p[1]/100000])),plain(baseline.convertGeometry(g,p=>[p[0]/10000,-80+p[1]/100000])));
 const children=[new Geometry('Point',[20,-80]),new Geometry('LineString',[[1,-80],[2,-81]])];
 const collection={getType:()=> 'GeometryCollection',getGeometriesArray:()=>children};
 assert.deepEqual(plain(T.convertGeometry(collection,p=>p)),{points:[[20,-80]],lines:[[[1,-80],[2,-81]]],polygons:[]});h.cleanup();
});
test('single long geometry and a single huge densified segment bound iterator work without changing coordinates',()=>{
 const h=harness(),T=h.api.testing;
 for(const coords of [Array.from({length:24000},(_,i)=>[i*3,-800000]),[[0,0],[40000*24000,0]]]){
  const g=flatGeometry('LineString',coords),transform=p=>[p[0]/100000,-80];
  const out=exhaust(T.convertGeometrySteps(g,transform));
  assert.ok(out.steps>24000);assert.equal(out.max,512);
  assert.deepEqual(plain(out.value),plain(baseline.convertGeometry(g.reference,transform)));
 }
 h.cleanup();
});
test('real tasks and an interactive rendered stage precede complete data; fixed static collections retain exact identity, order, styles, labels and billboards',async()=>{
 const obs=Array.from({length:900},(_,i)=>new Feature('p'+i));
 const paths=Array.from({length:700},(_,i)=>new Feature('l'+i,'LineString',[[i/100,-80],[i/100+1,-81]]));
 const riggs=new Feature('riggs');const shape={getPoints:()=>3,getRadius:()=>8,getFill:()=>fill('#fff'),getStroke:()=>stroke('#000')};
 const text={getText:()=> 'station',getFill:()=>fill('#123456')};
 const h=harness({layers:[new Layer('frozen-observations',obs),new Layer('frozen-flights',paths,()=>style({line:stroke('#123456',3,[2,3])})),new Layer('riggs-reference-stations',[riggs],()=>style({point:shape,text}))]});
 const owned=[],Base=h.C.PointPrimitiveCollection;
 for(const name of ['PointPrimitiveCollection','PolylineCollection','LabelCollection','BillboardCollection'])h.C[name]=class extends Base{constructor(...args){super(...args);owned.push(this);}add(x){assert.ok(!this.uploaded,'no growing collection after render');return super.add(x);}};
 const expected=baseline.createBatches(h.C,{primitives:new h.C.PrimitiveCollection()},baseline.snapshot(h.context,'off'),h.doc);
 const expectedLeaves=leaves(expected.group);expected.group.destroy();owned.length=0;
 const Viewer=h.C.Viewer;let first=null,renders=0;
 h.C.Viewer=class extends Viewer{render(){super.render();renders++;const all=leaves(this.scene.primitives);if(!first)first={count:all.points.length,status:h.host.dataset.flGlobeComplete};for(const col of owned)if(all.points.some(p=>col.items.includes(p))||all.lines.some(p=>col.items.includes(p))||all.labels.some(p=>col.items.includes(p))||all.billboards.some(p=>col.items.includes(p)))col.uploaded=true;}};
 let heartbeat=0;const beat=setInterval(()=>heartbeat++,1);
 const ctl=h.mount();await ctl.setEnabled(true);clearInterval(beat);assert.ok(heartbeat>1);assert.ok(renders>1&&renders<=4);assert.equal(first.status,'false');assert.equal(first.count,128);
 assert.equal(h.host.dataset.flGlobeComplete,'true');assert.equal(h.host.dataset.flGlobeStatus,'ready');
 const actual=leaves(h.made.viewers[0].scene.primitives);
 for(const key of Object.keys(expectedLeaves)){assert.equal(actual[key].length,expectedLeaves[key].length,key);for(let i=0;i<actual[key].length;i++){assert.equal(actual[key][i].id.feature,expectedLeaves[key][i].id.feature);assert.deepEqual(plain(actual[key][i]),plain(expectedLeaves[key][i]));}}
 assert.equal(new Set(actual.lines.map(l=>l.material)).size,actual.lines.length,'each polyline owns its material');
 assert.ok(owned.length<=16);const metrics=JSON.parse(h.host.dataset.flGlobeBuildMetrics);assert.ok(metrics.maxSteps<=8192);assert.ok(metrics.slices>1);
 assert.ok(Number(h.host.dataset.flGlobeFirstUsableMs)<Number(h.host.dataset.flGlobeAllCompleteMs));
 await ctl.setEnabled(false);assert.ok(owned.every(x=>x.destroyed));h.cleanup();
});
function controlled(h){
 const realSet=h.sandbox.setTimeout,realClear=h.sandbox.clearTimeout,tasks=[];
 h.sandbox.setTimeout=(fn,ms)=>{if(ms!==0)return realSet(fn,ms);const t={fn,cancelled:false};tasks.push(t);return t;};
 h.sandbox.clearTimeout=t=>{if(t&&typeof t.fn==='function')t.cancelled=true;else realClear(t);};
 return {tasks,async step(){const task=tasks.shift();if(task&&!task.cancelled)task.fn();await turn();},async drain(){let n=0;while(tasks.length){assert.ok(++n<10000);await this.step();}}};
}
test('OFF cancellation settles at every task boundary; no pending group or stale attachment survives',async()=>{
 let count=0;
 // Determine all boundaries using a fixed fixture, then cancel each one.
 {const h=harness({features:Array.from({length:700},(_,i)=>new Feature('p'+i))}),q=controlled(h),ctl=h.mount(),p=ctl.setEnabled(true);await turn();while(q.tasks.length){count++;await q.step();}assert.equal(await p,true);h.cleanup();}
 assert.ok(count>1);
 for(let boundary=0;boundary<count;boundary++){
  const h=harness({features:Array.from({length:700},(_,i)=>new Feature('p'+i))}),q=controlled(h),ctl=h.mount(),p=ctl.setEnabled(true);await turn();for(let i=0;i<boundary;i++)await q.step();
  await ctl.setEnabled(false);await q.drain();assert.equal(await p,false);assert.ok(h.made.viewers.every(v=>v.destroyed));assert.equal(h.host.dataset.flGlobeComplete,'false');assert.equal(h.timerCount,0);h.cleanup();
 }
});
for(const action of ['dispose','hidden','contextloss','error','replacement'])test('partial build cleanup: '+action,async()=>{
 const h=harness({features:Array.from({length:1000},(_,i)=>new Feature('p'+i))}),q=controlled(h),ctl=h.mount(),p=ctl.setEnabled(true);await turn();
 while(h.host.dataset.flGlobeFirstUsableMs===undefined)await q.step();const old=h.made.viewers[0];
 if(action==='dispose')ctl.dispose();
 else if(action==='hidden'){h.doc.hidden=true;h.doc.dispatchEvent('visibilitychange');}
 else if(action==='contextloss')old.scene.canvas.dispatchEvent({type:'webglcontextlost',preventDefault(){}});
 else if(action==='error')old.scene.renderError.raise(Error('test'));
 else {await ctl.setEnabled(false);const next=ctl.setEnabled(true);await turn();await q.drain();assert.equal(await next,true);assert.notEqual(h.made.viewers.at(-1),old);assert.equal(h.made.viewers.at(-1).scene.primitives.items.length,1);}
 await q.drain();assert.equal(await p,false);assert.ok(old.destroyed);assert.equal(old.scene.primitives.items.length,0);
 h.cleanup();assert.equal(h.timerCount,0);
});
test('latest filter/source/layer/selection notifications immediately retire excluded data and RIGGS never resurrects',async()=>{
 const p=new Feature('private'),r=new Feature('riggs'),layer=new Layer('frozen-observations',[p]),riggs=new Layer('riggs-reference-stations',[r]);
 const h=harness({layers:[layer,riggs]}),ctl=h.mount();await ctl.setEnabled(true);const v=h.made.viewers[0],old=v.scene.primitives.items[0];
 p.hidden=true;h.doc.dispatchEvent('fl-map-visibility-change');assert.equal(old.destroyed,true);assert.equal(v.scene.primitives.items.length,0);assert.equal(h.host.dataset.flGlobeComplete,'false');
 layer.features=Array.from({length:900},(_,i)=>new Feature('excluded'+i));const q=controlled(h);const first=ctl.whenComplete();await turn();
 layer.features=[new Feature('latest')];const oldSource=layer.source;layer.source=new Events();layer.source.getFeatures=()=>layer.features;layer.dispatchEvent('change:source');
 riggs.visible=false;riggs.dispatchEvent('propertychange');h.list.items=[layer];h.list.dispatchEvent('remove');
 for(const fn of h.storeListeners)fn({unknown:true});const latest=ctl.whenComplete();await turn();await q.drain();assert.equal(await first,false);assert.equal(await latest,true);
 assert.equal(oldSource.count(),0);assert.deepEqual(leaves(v.scene.primitives).points.map(x=>x.id.featureId),['latest']);assert.equal(JSON.parse(h.host.dataset.flGlobePrimitiveCounts).points,1);h.cleanup();
});
for(const dpr of [0.75,1,1.5,2,3])test('quality total pixel budget and CSS units across DPR '+dpr,()=>{
 const h=harness(),scale=h.api.testing.qualityScale;
 for(const [w,ht] of [[800,600],[2560,1440],[3840,2160],[12000,4000]])for(const idle of [false,true]){const q=scale(w,ht,dpr,idle);assert.ok(Number.isFinite(q)&&q>0);assert.ok(w*ht*q*q<=(idle?4500000:3000000)+1);assert.ok(q<=Math.min(idle?1.5:1,idle?Math.max(dpr,1.25):dpr));if(idle)assert.ok(q>=scale(w,ht,dpr,false));}
 for(const [w,ht] of [[0,0],[0,600],[800,0],[Infinity,600]])assert.equal(scale(w,ht,dpr,true),null);h.cleanup();
});
test('idle sharpness debounces, uses hysteresis, has no resize feedback, preserves pose and cancels timers',async()=>{
 const h=harness();h.sandbox.devicePixelRatio=3;
 const Viewer=h.C.Viewer;h.C.Viewer=class extends Viewer{constructor(...args){super(...args);this.camera.moveStart=new CesiumEvent();this.camera.moveEnd=new CesiumEvent();}resize(){super.resize();this.resizeCount=(this.resizeCount||0)+1;}};
 const ctl=h.mount();await ctl.setEnabled(true);const v=h.made.viewers[0],pose=plain({position:v.camera.positionWC,direction:v.camera.directionWC,up:v.camera.upWC});
 await new Promise(r=>setTimeout(r,280));assert.equal(v.resolutionScale,1.5);const resizes=v.resizeCount;
 for(let i=0;i<20;i++)v.scene.postRender.raise();assert.equal(v.resizeCount,resizes);
 v.camera.moveStart.raise();assert.equal(v.resolutionScale,1);v.camera.moveEnd.raise();v.camera.moveStart.raise();const motion=setInterval(()=>{v.camera.positionWC.x+=1;},40);await new Promise(r=>setTimeout(r,280));assert.equal(v.resolutionScale,1);clearInterval(motion);v.camera.positionWC.x=pose.position.x;
 v.camera.moveEnd.raise();await ctl.setEnabled(false);assert.equal(h.timerCount,0);assert.deepEqual(plain({position:v.camera.positionWC,direction:v.camera.directionWC,up:v.camera.upWC}),pose);h.cleanup();
});

test('one long single-feature build yields during projection AND construction and preserves the complete path',async()=>{
 const h=harness(),coords=Array.from({length:24000},(_,i)=>[i/1000,-80]);
 const geometry=flatGeometry('LineString',coords),feature=new Feature('long');feature.geometry=geometry;
 const layer=new Layer('frozen-flights',[feature],()=>style({line:stroke('#fff',2)}));h.list.items=[layer];
 const ctl=h.mount();let beats=0;const heartbeat=setInterval(()=>beats++,1);
 assert.equal(await ctl.setEnabled(true),true);clearInterval(heartbeat);assert.ok(beats>2);
 const paths=leaves(h.made.viewers[0].scene.primitives).lines;assert.equal(paths.length,1);assert.equal(paths[0].id.feature,feature);assert.equal(paths[0].positions.length,coords.length);
 const metrics=JSON.parse(h.host.dataset.flGlobeBuildMetrics);assert.ok(metrics.maxSteps<=8192);assert.ok(metrics.slices>4);assert.equal(JSON.parse(h.host.dataset.flGlobePrimitiveCounts).lines,1);assert.equal(metrics.stages.length,1);assert.equal(metrics.stages[0].oversized,true);assert.ok(metrics.stages[0].cost.vertices>h.api.testing.BATCH_BUDGETS.vertices);h.cleanup();
});
test('multiple refreshes preserve the original 2D dispatch, interactions and coordinate readout exactly',async()=>{
 const h=harness(),original=h.map.dispatchEvent,ctl=h.mount();await ctl.setEnabled(true);
 for(let i=0;i<3;i++){ctl.refresh();await ctl.whenComplete();}
 await ctl.setEnabled(false);assert.equal(h.map.dispatchEvent,original);assert.equal(h.readout.textContent,'2D coordinates');assert.deepEqual(h.interactions.items.map(x=>x.active),[true,false]);h.cleanup();
});


test('large final remainder uses bounded immutable uploads and retains every point in original order',async()=>{
 const features=Array.from({length:6000},(_,i)=>new Feature('bounded'+i)),h=harness({features}),ctl=h.mount();await ctl.setEnabled(true);
 const metrics=JSON.parse(h.host.dataset.flGlobeBuildMetrics),limits=h.api.testing.BATCH_BUDGETS;
 assert.ok(metrics.stages.length>3);for(const stage of metrics.stages){assert.equal(stage.oversized,false);for(const key of Object.keys(limits))assert.ok(stage.cost[key]<=limits[key],key);}
 assert.deepEqual(leaves(h.made.viewers[0].scene.primitives).points.map(x=>x.id.featureId),features.map(x=>x.getId()));
 assert.equal(JSON.parse(h.host.dataset.flGlobePrimitiveCounts).points,features.length);assert.ok(Number(h.host.dataset.flGlobeFirstObservationMs)>=Number(h.host.dataset.flGlobeFirstUsableMs));assert.ok(Number(h.host.dataset.flGlobeFirstPointMs)>=Number(h.host.dataset.flGlobeFirstUsableMs));h.cleanup();
});
test('upload cost partitions contiguous styled rows without splitting a long path or changing pick identity',()=>{
 const h=harness(),T=h.api.testing,rows=[];
 for(let i=0;i<9;i++)rows.push({feature:new Feature('line'+i),style:style({line:stroke()}),geometry:{points:[],lines:[Array.from({length:3000},()=>[0,-80])],polygons:[]}});
 rows.splice(4,0,{feature:new Feature('oversized'),style:style({line:stroke()}),geometry:{points:[],lines:[Array.from({length:10000},()=>[0,-80])],polygons:[]}});
 const chunks=T.planBatches(rows);const flat=Array.from(chunks).flatMap(c=>Array.from(c.rows));assert.equal(flat.length,rows.length);flat.forEach((row,i)=>assert.equal(row,rows[i]));const huge=chunks.find(c=>c.oversized);assert.equal(huge.rows.length,1);assert.equal(huge.rows[0],rows[4]);assert.equal(huge.rows[0].geometry.lines[0].length,10000);
 for(const c of chunks)if(!c.oversized)assert.ok(c.cost.vertices<=T.BATCH_BUDGETS.vertices);h.cleanup();
});
test('an existing idle-sharp viewer returns to active budget during filter and NASA policy builds',async()=>{
 const land=new Layer('quantarctica-fallback',[new Feature('land','Polygon',[[[0,-80],[1,-80],[1,-81],[0,-80]]])],()=>style({area:fill('white')}));
 const h=harness({layers:[new Layer('frozen-observations',[new Feature('p')]),land],nasa:true});h.sandbox.devicePixelRatio=2;const ctl=h.mount();await ctl.setEnabled(true);const v=h.made.viewers[0];
 await new Promise(r=>setTimeout(r,280));assert.equal(v.resolutionScale,1.5);
 const q=controlled(h);ctl.refresh();let done=ctl.whenComplete();await turn();assert.equal(v.resolutionScale,1);await new Promise(r=>setTimeout(r,280));assert.equal(h.host.dataset.flGlobeComplete,'false');assert.equal(v.resolutionScale,1,'quiet camera cannot sharpen while the pipeline is held');await q.drain();assert.equal(await done,true);assert.equal(v.resolutionScale,1);
 await new Promise(r=>setTimeout(r,280));assert.equal(v.resolutionScale,1.5);
 h.imagery.setEnabled(false);done=ctl.whenComplete();await turn();assert.equal(v.resolutionScale,1);await q.drain();assert.equal(await done,true);assert.equal(v.resolutionScale,1);h.cleanup();assert.equal(h.timerCount,0);
});


test('context-first stages distinguish first usable from first actual observation and clear metrics on a no-observation generation',async()=>{
 const context=Array.from({length:600},(_,i)=>new Feature('context'+i,'LineString',[[0,-80],[1,-81]]));
 const obs=new Feature('obs'),layer=new Layer('frozen-observations',[obs]),h=harness({layers:[new Layer('quantarctica-basemap',context,()=>style({line:stroke()})),layer]}),ctl=h.mount();
 await ctl.setEnabled(true);const d=h.host.dataset;assert.ok(Number(d.flGlobeFirstUsableMs)<=Number(d.flGlobeFirstObservationMs));assert.ok(Number(d.flGlobeFirstObservationMs)<=Number(d.flGlobeAllCompleteMs));assert.ok(Number(d.flGlobeFirstPointMs)>=Number(d.flGlobeFirstUsableMs));
 layer.visible=false;layer.dispatchEvent('propertychange');await ctl.whenComplete();assert.equal(d.flGlobeFirstObservationMs,undefined);assert.equal(d.flGlobeFirstPointMs,undefined);h.cleanup();
});
test('loading feedback remains visible during debounced vector retirement after NASA is ready',async()=>{
 const h=harness({nasa:true}),ctl=h.mount();await ctl.setEnabled(true);const v=h.made.viewers[0];v.scene.globe.tileLoadProgressEvent.raise(1);v.scene.globe.tilesLoaded=true;v.scene.globe.tileLoadProgressEvent.raise(0);await ctl.whenComplete();
 ctl.refresh();const status=h.shell.children.find(x=>x.classList.contains('fl-globe-toolbar')).children.find(x=>x.classList.contains('fl-globe-status'));assert.match(status.textContent,/3D overlays loading/);await ctl.whenComplete();assert.equal(status.textContent,'');h.cleanup();
});


test('standard-DPR display gets modest idle supersampling only within the hard pixel cap',()=>{const h=harness(),scale=h.api.testing.qualityScale;assert.equal(scale(1280,720,1,false),1);assert.equal(scale(1280,720,1,true),1.25);assert.ok(3840*2160*scale(3840,2160,1,true)**2<=4500000+1);h.cleanup();});


test('heavy context-first input draws observations first but final kind/layer/row order remains canonical',async()=>{
 const context=Array.from({length:700},(_,i)=>new Feature('context'+i,'LineString',[[0,-80],[1,-81]])),obs=Array.from({length:300},(_,i)=>new Feature('priority'+i));
 const layers=[new Layer('quantarctica-basemap',context,()=>style({line:stroke()})),new Layer('frozen-observations',obs),new Layer('riggs-reference-stations',[new Feature('station')])];
 const h=harness({layers}),expected=baseline.createBatches(h.C,{primitives:new h.C.PrimitiveCollection()},baseline.snapshot(h.context,'off'),h.doc),before=leaves(expected.group);expected.group.destroy();const Viewer=h.C.Viewer;let first;
 h.C.Viewer=class extends Viewer{render(){super.render();if(!first)first=leaves(this.scene.primitives);}};const ctl=h.mount();await ctl.setEnabled(true);
 assert.ok(first.points.length>0);assert.ok(first.points.every(x=>x.id.layerId==='frozen-observations'));assert.equal(first.lines.length,0);
 let after=leaves(h.made.viewers[0].scene.primitives);for(const kind of Object.keys(before)){assert.deepEqual(after[kind].map(x=>x.id.featureId),before[kind].map(x=>x.id.featureId));}
 await ctl.setEnabled(false);await ctl.setEnabled(true);after=leaves(h.made.viewers[1].scene.primitives);for(const kind of Object.keys(before))assert.deepEqual(after[kind].map(x=>x.id.featureId),before[kind].map(x=>x.id.featureId));assert.equal(h.host.dataset.flGlobeSnapshotReused,'true');h.cleanup();
});
test('native scheduler tasks cancel before a stale uncancellable yield promise resumes',async()=>{
 const h=harness({features:Array.from({length:1200},(_,i)=>new Feature('p'+i))}),pending=[];h.sandbox.scheduler={yield:()=>new Promise(resolve=>pending.push(resolve))};const ctl=h.mount(),opening=ctl.setEnabled(true);await turn();assert.ok(pending.length);await ctl.setEnabled(false);for(const resume of pending)resume();await turn();assert.equal(await opening,false);assert.ok(h.made.viewers.every(v=>v.destroyed));assert.equal(h.timerCount,0);h.cleanup();
});
test('missing camera moveEnd cannot latch idle sharpness; held input releases outside the canvas',async()=>{
 const h=harness();h.sandbox.devicePixelRatio=2;const Viewer=h.C.Viewer;h.C.Viewer=class extends Viewer{constructor(...args){super(...args);this.camera.moveStart=new CesiumEvent();this.camera.moveEnd=new CesiumEvent();}};
 const ctl=h.mount();await ctl.setEnabled(true);const v=h.made.viewers[0];v.camera.moveStart.raise();await new Promise(r=>setTimeout(r,280));assert.equal(v.resolutionScale,1.5);assert.equal(h.host.dataset.flGlobeQualityMoving,'false');
 v.scene.canvas.dispatchEvent('pointerdown');await new Promise(r=>setTimeout(r,280));assert.equal(v.resolutionScale,1);h.sandbox.dispatchEvent('pointerup');await new Promise(r=>setTimeout(r,280));assert.equal(v.resolutionScale,1.5);v.scene.canvas.dispatchEvent('pointerdown');h.sandbox.dispatchEvent('blur');await new Promise(r=>setTimeout(r,280));assert.equal(v.resolutionScale,1.5);h.cleanup();assert.equal(h.timerCount,0);
});


test('shared source geometry converts once per build while all layer styles, counts and ordered picks remain',async()=>{
 const feature=new Feature('shared','LineString',[[10,-80],[11,-81]]),a=new Layer('quantarctica-fallback',[feature],()=>style({line:stroke('#fff',3)})),b=new Layer('quantarctica-basemap',[feature],()=>style({line:stroke('#123',1)}));
 const h=harness({layers:[a,b]}),expected=baseline.createBatches(h.C,{primitives:new h.C.PrimitiveCollection()},baseline.snapshot(h.context,'off'),h.doc),before=leaves(expected.group);expected.group.destroy();let transforms=0;h.context.ol.proj.transform=p=>{transforms++;return p;};const ctl=h.mount();await ctl.setEnabled(true);
 assert.equal(transforms,2);const after=leaves(h.made.viewers[0].scene.primitives);assert.deepEqual(plain(after.lines),plain(before.lines));assert.equal(after.lines[0].id.feature,feature);assert.equal(after.lines[1].id.feature,feature);assert.deepEqual(JSON.parse(h.host.dataset.flGlobeFeatureCounts),{'quantarctica-fallback':1,'quantarctica-basemap':1});const metrics=JSON.parse(h.host.dataset.flGlobeBuildMetrics);assert.equal(metrics.geometryConversions,1);assert.equal(metrics.geometryCacheHits,1);h.cleanup();
});
