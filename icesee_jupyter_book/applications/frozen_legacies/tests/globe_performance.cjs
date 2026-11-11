'use strict';
// Sequential fixed-input comparison. Real JS traversal/projection/construction;
// Cesium collections, GPU and network are mocks. No fixed ready sleeps.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),{createRequire}=require('node:module'),{performance}=require('node:perf_hooks');
const {forward,inverse}=require('./fixtures/globe_projection.cjs');
const baseline=path.resolve(process.argv[2]),candidate=path.resolve(process.argv[3]);
const helperFile=path.join(candidate,'tests/globe_view.test.cjs');
const prelude=fs.readFileSync(helperFile,'utf8').split('const wait =')[0].replace("path.join(__dirname, '../assets/globe_view.js')","path.join(runtimeRoot, 'assets/globe_view.js')");
const task=()=>new Promise(resolve=>setTimeout(resolve,0));
function summary(primitives){
 const rows={points:[],lines:[],polygons:[],labels:[],billboards:[]};
 function visit(group){for(const x of group.items||[]){if(x.options?.geometryInstances){for(const i of x.options.geometryInstances)rows.polygons.push({id:i.id.featureId,layer:i.id.layerId,geometry:i.geometry.options,color:i.attributes.color});}else if(x.items)visit(x);else {const key=x.positions?'lines':x.text!==undefined?'labels':x.image?'billboards':x.position?'points':null;if(key)rows[key].push({id:x.id.featureId,layer:x.id.layerId,position:x.position,positions:x.positions,pixelSize:x.pixelSize,width:x.width,material:x.material,color:x.color,text:x.text,scale:x.scale});}}}
 visit(primitives);return {counts:Object.fromEntries(Object.entries(rows).map(([k,v])=>[k,v.length])),orderedIDs:Object.fromEntries(Object.entries(rows).map(([k,v])=>[k,crypto.createHash('sha256').update(JSON.stringify(v.map(x=>[x.layer,x.id]))).digest('hex')])),styleGeometryHash:crypto.createHash('sha256').update(JSON.stringify(rows)).digest('hex')};
}
function renderCounts(primitives){
 const out={points:0,lines:0,labels:0,billboards:0,polygons:0};
 function visit(group){for(const x of group.items||[]){if(x.options?.geometryInstances)out.polygons+=x.options.geometryInstances.length;else if(x.items)visit(x);else if(x.positions)out.lines++;else if(x.text!==undefined)out.labels++;else if(x.image)out.billboards++;else if(x.position)out.points++;}}visit(primitives);return out;
}

async function measure(runtimeRoot){
 const holder={exports:{}};new Function('require','module','__dirname','runtimeRoot',prelude+'\nmodule.exports={harness,Feature,Layer,style,stroke,fill};')(createRequire(helperFile),holder,path.dirname(helperFile),runtimeRoot);
 const {harness,Feature,Layer,style,stroke,fill}=holder.exports;
 const points=Array.from({length:13576},(_,i)=>new Feature('p'+i,'Point',forward([-170+i%340,-89+(i%180)/10])));
 const paths=Array.from({length:10389},(_,i)=>new Feature('l'+i,'LineString',[forward([-170+i%340,-82]),forward([-169.9+i%340,-81.99])]));
 const flights=Array.from({length:95},(_,i)=>new Feature('f'+i,'MultiLineString',[[forward([-160+i,-85]),forward([-159.9+i,-84.99])],[forward([-150+i,-83]),forward([-149.9+i,-82.99])]]));
 const land=new Feature('land','Polygon',[[forward([0,-84]),forward([0.1,-84]),forward([0.1,-84.1]),forward([0,-84])]]);
 const layers=[new Layer('frozen-observations',points),new Layer('frozen-flights',flights,()=>style({line:stroke()})),new Layer('antarctic-image-navigation',paths,()=>style({line:stroke()})),new Layer('quantarctica-fallback',[land],()=>style({area:fill('#ffffff')}))];
 const h=harness({layers,nasa:true});h.sandbox.devicePixelRatio=2;h.sandbox.performance=performance;let transforms=0;h.context.ol.proj.transform=p=>{transforms++;return inverse(p);};
 let at=performance.now();const snap=h.api.testing.snapshot(h.context,'off'),snapshotMs=performance.now()-at;
 at=performance.now();const batch=h.api.testing.createBatches(h.C,{primitives:new h.C.PrimitiveCollection()},snap,h.doc),createBatchesMs=performance.now()-at;const primitiveCounts=batch.counts;batch.group.destroy();transforms=0;
 // Baseline has no completion API: observe its explicit update counter write.
 // Candidate uses whenComplete(), which includes pending debounce generations.
 let updates=0,waiters=[];
 Object.defineProperty(h.host.dataset,'flGlobeUpdates',{enumerable:true,get:()=>String(updates),set:v=>{updates=Number(v);for(const w of waiters.filter(w=>updates>=w.target))w.resolve();waiters=waiters.filter(w=>updates<w.target);}});
 const nextUpdate=target=>updates>=target?Promise.resolve():new Promise(resolve=>waiters.push({target,resolve}));
 const ctl=h.mount(),stages=[],renders=[];let phase='cold',phaseAt=0;
 const Viewer=h.C.Viewer;
 h.C.Viewer=class extends Viewer{render(){super.render();renders.push({phase,ms:performance.now()-phaseAt,counts:renderCounts(this.scene.primitives),complete:h.host.dataset.flGlobeComplete??'baseline-synchronous'});}};
 const stage=label=>stages.push({label,transforms,resolutionScale:h.made.viewers.at(-1)?.resolutionScale,updates,summary:summary(h.made.viewers.at(-1).scene.primitives),diagnostics:{...h.host.dataset}});
 let ticks=0,maxLag=0,last=performance.now();const heartbeat=setInterval(()=>{const n=performance.now();maxLag=Math.max(maxLag,n-last-5);last=n;ticks++;},5);
 await task();phaseAt=performance.now();await Promise.all([ctl.setEnabled(true),nextUpdate(1)]);if(ctl.whenComplete)await ctl.whenComplete();const coldSetupMs=performance.now()-phaseAt;await task();const coldHeartbeat={ticks,maxLagMs:maxLag};stage('cold-complete');
 const v=h.made.viewers[0];v.scene.globe.tileLoadProgressEvent.raise(1);v.scene.globe.tilesLoaded=true;v.scene.globe.tileLoadProgressEvent.raise(0);if(ctl.whenComplete)await ctl.whenComplete();stage('first-NASA-ready');
 for(let i=0;i<5;i++){v.scene.globe.tileLoadProgressEvent.raise(2);v.scene.globe.tileLoadProgressEvent.raise(0);}if(ctl.whenComplete)await ctl.whenComplete();stage('five-progress-cycles');
 await ctl.setEnabled(false);phase='warm';phaseAt=performance.now();await Promise.all([ctl.setEnabled(true),nextUpdate(2)]);if(ctl.whenComplete)await ctl.whenComplete();const warmSetupMs=performance.now()-phaseAt;stage('warm-complete');
 const refreshed=nextUpdate(3);for(let i=0;i<30;i++)layers[0].source.dispatchEvent('change');if(ctl.whenComplete)await ctl.whenComplete();await refreshed;stage('30-source-events-complete');
 clearInterval(heartbeat);h.cleanup();return {fixtureFeatures:{points:13576,flights:95,paths:10389,land:1},snapshotMs,createBatchesMs,primitiveCounts,coldSetupMs,warmSetupMs,coldHeartbeat,renders,scriptLoads:h.scriptLoads,groundInitCalls:h.made.groundInit,stages,viewersCreated:h.made.viewers.length,liveViewersAfterDispose:h.made.viewers.filter(v=>!v.destroyed).length};
}
(async()=>{const before=await measure(baseline),after=await measure(candidate);const a=before.stages[0].summary,b=after.stages[0].summary;if(JSON.stringify(a)!==JSON.stringify(b))throw Error('fixed-input counts/ordered IDs/style/geometry changed');console.log(JSON.stringify({kind:'synthetic Node; real traversal/projection/batch JS; mock GPU/render/network. No real GPU/FPS claim.',inputEquivalent:true,before,after},null,2));})().catch(error=>{console.error(error);process.exitCode=1;});
