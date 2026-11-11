'use strict';
// Focused behavior tests. These stubs do not render WebGL or prove real NASA alignment.
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm'), crypto = require('node:crypto');
const source = fs.readFileSync(path.join(__dirname, '../assets/globe_view.js'), 'utf8');
const fixtures = require('./fixtures/globe-synthetic.json');
const contractBytes = fs.readFileSync(path.join(__dirname, 'fixtures/globe-provider-contract.json'));
const contract = JSON.parse(contractBytes);
const plain = x => JSON.parse(JSON.stringify(x));
class Events {
  constructor() { this.events = new Map(); }
  on(t, fn) { if (!this.events.has(t)) this.events.set(t, new Set()); this.events.get(t).add(fn); }
  un(t, fn) { this.events.get(t)?.delete(fn); }
  addEventListener(t, fn) { this.on(t, fn); }
  removeEventListener(t, fn) { this.un(t, fn); }
  dispatchEvent(e) { const event = typeof e === 'string' ? {type:e} : e; for (const f of [...(this.events.get(event.type)||[])]) if (f(event) === false) return false; return true; }
  count() { return [...this.events.values()].reduce((n, s) => n + s.size, 0); }
}
class CesiumEvent {
  constructor() { this.listeners = new Set(); }
  addEventListener(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
  removeEventListener(fn) { this.listeners.delete(fn); }
  raise(...args) { for (const fn of [...this.listeners]) fn(...args); }
}
class El extends Events {
  constructor(tag='div') { super(); this.tagName=tag;this.children=[];this.dataset={};this.attrs={};this.hidden=false;this.textContent='';this.parentElement=null;this.offsetWidth=200;this.offsetHeight=100;
    this.style={visibility:'',setProperty(k,v){this[k]=v;},removeProperty(k){delete this[k];}};
    const classes=new Set();this.classList={add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x)}; }
  set className(s) { s.split(/\s+/).forEach(x=>this.classList.add(x)); }
  append(...nodes) { for (const n of nodes) { n.remove();this.children.push(n);n.parentElement=this;this.onAppend?.(n); } }
  replaceChildren(...nodes) { this.children.forEach(x=>{x.parentElement=null;});this.children=[];this.append(...nodes); }
  prepend(n) { n.remove();this.children.unshift(n);n.parentElement=this; }
  remove() { if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(x=>x!==this);this.parentElement=null; }
  setAttribute(k,v) { this.attrs[k]=v; }
  getBoundingClientRect() { return {left:20,top:40,width:800,height:600}; }
  closest(s) { return s==='.'+this.testClass ? this : null; }
  contains(n) { for(let x=n;x;x=x.parentElement)if(x===this)return true;return false; }
  querySelector() { return null; }
  getContext() { return Object.fromEntries(['scale','translate','beginPath','moveTo','lineTo','closePath','fill','stroke'].map(x=>[x,()=>{}])); }
}
class Collection extends Events {
  constructor(items=[]) { super();this.items=items; }
  getArray(){return this.items;}
  add(item){this.items.push(item);this.dispatchEvent({type:'add',element:item});return item;}
}
class Geometry {
  constructor(type,coordinates){this.type=type;this.coordinates=coordinates;}
  clone(){return new Geometry(this.type,structuredClone(this.coordinates));}
  getType(){return this.type;}
  getCoordinates(){return this.coordinates;}
  getCenter(){return this.coordinates.center;}
  getRadius(){return this.coordinates.radius;}
  getGeometries(){return this.coordinates;}
}
class Feature {
  constructor(id,type='Point',coords=[25,-85],props={}){this.id=id;this.geometry=new Geometry(type,coords);this.props={flight:'125',dataset_id:'synthetic-a',...props};}
  getId(){return this.id;}get(k){return this.props[k];}getProperties(){return {...this.props,geometry:this.geometry};}getGeometry(){return this.geometry;}
}
const fill = c => ({getColor:()=>c});
const stroke = (c='#123456',w=2,d=null) => ({getColor:()=>c,getWidth:()=>w,getLineDash:()=>d});
function style({line=null,area=null,point=null,text=null,geom=null}={}) {
  return {getStroke:()=>line,getFill:()=>area,getImage:()=>point,getText:()=>text,
    getGeometryFunction:()=>geom || (f=>f.getGeometry())};
}
const circle = (c='#22c55e') => ({getRadius:()=>4.5,getFill:()=>fill(c),getStroke:()=>null,getOpacity:()=>1});
class Layer extends Events {
  constructor(id,features=[],fn=()=>style({point:circle()})){super();this.id=id;this.features=features;this.fn=fn;this.visible=true;this.source=new Events();this.source.getFeatures=()=>this.features;}
  get(k){return k==='id'?this.id:undefined;}getVisible(){return this.visible;}getOpacity(){return 1;}getSource(){return this.source;}getStyleFunction(){return this.fn;}
}
// Vector math is real here; WebGL, camera events and collections are mocks.
class Vector {
  constructor(x=0,y=0,z=0){this.x=x;this.y=y;this.z=z;}
  static fromDegrees(lon,lat,height){return {lon,lat,height};}
  static clone(p){return {...p};}
  static add(a,b,r){r.x=a.x+b.x;r.y=a.y+b.y;r.z=a.z+b.z;return r;}
  static subtract(a,b,r){r.x=a.x-b.x;r.y=a.y-b.y;r.z=a.z-b.z;return r;}
  static multiplyByScalar(a,k,r){r.x=a.x*k;r.y=a.y*k;r.z=a.z*k;return r;}
  static magnitude(a){return Math.hypot(a.x,a.y,a.z);}
  static normalize(a,r){return Vector.multiplyByScalar(a,1/Vector.magnitude(a),r);}
  static cross(a,b,r){const x=a.y*b.z-a.z*b.y,y=a.z*b.x-a.x*b.z,z=a.x*b.y-a.y*b.x;r.x=x;r.y=y;r.z=z;return r;}
}
function cesiumStub() {
  const made={viewers:[],providers:[],resources:[],handlers:[]};
  class Bag { constructor(options){this.options=options;this.items=[];this.destroyed=false;} get length(){return this.items.length;} get(i){return this.items[i];} add(x){this.items.push(x);return x;} remove(x,destroy=this.destroyPrimitives!==false){this.items=this.items.filter(v=>v!==x);if(destroy)x.destroy?.();} destroy(){this.items.forEach(x=>x.destroy?.());this.items=[];this.destroyed=true;} }
  class Color { constructor(r=0,g=0,b=0,a=1){this.red=r;this.green=g;this.blue=b;this.alpha=a;}
    static fromCssColorString(s){const rgba=/rgba\([^,]+,[^,]+,[^,]+,\s*([\d.]+)/.exec(s);const c=new Color(0,0,0,s==='transparent'?0:rgba?Number(rgba[1]):1);c.css=s;return c;}
    withAlpha(a){const c=new Color(this.red,this.green,this.blue,a);c.css=this.css;return c;}toCssColorString(){return this.css||'black';} }
  Color.TRANSPARENT=new Color(0,0,0,0);
  const C={VERSION:'1.147',Color,SceneMode:{SCENE3D:3},Ellipsoid:{WGS84:{cartesianToCartographic:p=>({height:Math.hypot(p.x,p.y,p.z)-6378137})}},Rectangle:{MAX_VALUE:{}},
    EllipsoidTerrainProvider:class{constructor(options){this.options=options;}},
    GeographicTilingScheme:class{constructor(options){this.options=options;}},
    Resource:class{constructor(options){this.options=options;made.resources.push(this);}},
    WebMapTileServiceImageryProvider:class{constructor(options){this.options=options;this.errorEvent=new CesiumEvent();made.providers.push(this);}},
    PrimitiveCollection:Bag,PointPrimitiveCollection:Bag,PolylineCollection:Bag,LabelCollection:Bag,BillboardCollection:Bag,
    GroundPrimitive:class extends Bag { static initializeTerrainHeights(){made.groundInit=(made.groundInit||0)+1;return Promise.resolve();} static isSupported(){return C.groundSupported!==false;} static supportsMaterials(){return C.groundMaterials!==false;} },ClassificationType:{TERRAIN:0},
    Primitive:class extends Bag{},PolygonHierarchy:class{constructor(positions,holes=[]){this.positions=positions;this.holes=holes;}},
    PolygonGeometry:class{constructor(options){this.options=options;}},GeometryInstance:class{constructor(options){Object.assign(this,options);}},
    PerInstanceColorAppearance:class{constructor(options){this.options=options;}},ColorGeometryInstanceAttribute:{fromColor:x=>x},
    Material:{fromType:(type,uniforms)=>({type,uniforms})},LabelStyle:{FILL_AND_OUTLINE:2},
    Cartesian3:Vector,Cartesian2:class{constructor(x,y){this.x=x;this.y=y;}},
    HeadingPitchRange:class{constructor(h,p,r){this.heading=h;this.pitch=p;this.range=r;}},
    BoundingSphere:{fromPoints:points=>({points,radius:100000})},
    Cartographic:{fromCartesian:x=>({longitude:x.lon*Math.PI/180,latitude:x.lat*Math.PI/180})},Math:{toDegrees:x=>x*180/Math.PI},
    SceneTransforms:{worldToWindowCoordinates:()=>({x:400,y:300})},
    EllipsoidalOccluder:class{isPointVisible(){return C.frontSide!==false;}},
    CameraEventType:{WHEEL:3,RIGHT_DRAG:1,PINCH:4},ScreenSpaceEventType:{LEFT_CLICK:0,MOUSE_MOVE:1},
    ScreenSpaceEventHandler:class{constructor(canvas){this.canvas=canvas;this.actions={};made.handlers.push(this);}setInputAction(fn,type){this.actions[type]=fn;}destroy(){this.destroyed=true;}},
    Viewer:class {
      constructor(surface,options){this.surface=surface;this.options=options;made.viewers.push(this);this.useDefaultRenderLoop=true;
        this.scene={screenSpaceCameraController:{zoomEventTypes:[1,3,4],enableInputs:true,enableZoom:true},canvas:new El('canvas'),primitives:new Bag(),requestRender:()=>{this.requests=(this.requests||0)+1;},
          globe:{tilesLoaded:false,tileLoadProgressEvent:new CesiumEvent()},renderError:new CesiumEvent(),postRender:new CesiumEvent(),pick:()=>this.pickResult};
        this.camera={cancelFlight(){},positionWC:new Vector(0,0,17378137),directionWC:new Vector(0,0,-1),upWC:new Vector(0,1,0),direction:new Vector(0,0,-1),up:new Vector(0,1,0),right:new Vector(1,0,0),worldToCameraCoordinatesVector:(v,r)=>Object.assign(r,v),positionCartographic:{height:11000000},setView:x=>{this.lastView=x;},zoomIn:()=>this.zoomed='in',zoomOut:()=>this.zoomed='out',flyToBoundingSphere:x=>this.flown=x,pickEllipsoid:()=>this.coordinate===undefined?{lon:25,lat:-85}:this.coordinate};
        this.clock={};this.imageryLayers=new Bag();this.imageryLayers.addImageryProvider=p=>this.imageryLayers.add({provider:p});
      }
      resize(){this.resized=true;} render(){if(C.throwRender)throw Error('WebGL');this.rendered=true;}
      destroy(){this.destroyed=true;this.scene.primitives.destroy();this.imageryLayers.destroy();}
    }};
  C.PerInstanceColorAppearance.VERTEX_FORMAT={};
  return {C,made};
}
function harness({autoLoad=true,features=[new Feature('obs-1')],layers=null,nasa=false,withCesium=true}={}) {
  const {C,made}=cesiumStub(),doc=new Events();doc.head=new El('head');doc.body=new El('body');doc.body.dataset.flMode='map';doc.createElement=t=>new El(t);
  const shell=new El(),host=new El(),readout=new El();shell.append(host);readout.textContent='2D coordinates';doc.getElementById=id=>id==='fl-map-coordinate'?readout:id==='fl-observation-popup'?h.popup:null;
  const timers=new Set(),sandbox=new Events();Object.assign(sandbox,{console,document:doc,URL,Map,Set,Promise,Infinity,
    setTimeout:(fn,ms)=>{const t=setTimeout(()=>{timers.delete(t);fn();},ms);if(ms>5)t.unref();timers.add(t);return t;},clearTimeout:t=>{clearTimeout(t);timers.delete(t);}});
  sandbox.window=sandbox;if(withCesium)sandbox.Cesium=C;
  const mutations=[];sandbox.MutationObserver=class{constructor(fn){this.fn=fn;mutations.push(this);}observe(){}disconnect(){this.disconnected=true;}};
  sandbox.ResizeObserver=class{constructor(fn){this.fn=fn;}observe(){}disconnect(){this.disconnected=true;}};
  let scriptLoads=0;
  doc.head.onAppend=n=>{if(n.tagName==='script')scriptLoads++;if(autoLoad)queueMicrotask(()=>{sandbox.Cesium=C;n.onload?.();});};
  vm.runInNewContext(source,sandbox);const G=sandbox.FrozenLegaciesGlobe;
  // Load test helpers in the same realm without changing the production API.
  sandbox.module={exports:{}};vm.runInNewContext(source,sandbox);const api=sandbox.module.exports;
  const interactions=new Collection([{active:true,getActive(){return this.active;},setActive(v){this.active=v;}},{active:false,getActive(){return this.active;},setActive(v){this.active=v;}}]);
  const list=new Collection(layers||[new Layer('frozen-observations',features)]),map=new Events();
  const camera={center:[1,2],resolution:5000,rotation:0.3};let writes=0;
  const view={getResolution:()=>camera.resolution,getZoom:()=>3,getCenter:()=>camera.center,getRotation:()=>camera.rotation,setCenter(){writes++;},setResolution(){writes++;},fit(){writes++;}};
  Object.assign(map,{getLayers:()=>list,getView:()=>view,getTargetElement:()=>host,getInteractions:()=>interactions});
  const imageryListeners=new Set(),storeListeners=new Set(),calls=[];
  const imagery={state:{enabled:nasa},subscribe(fn){imageryListeners.add(fn);fn(this.state);return()=>imageryListeners.delete(fn);},setEnabled(v){this.state.enabled=v;[...imageryListeners].forEach(fn=>fn(this.state));}};
  const store={subscribe(fn){storeListeners.add(fn);return()=>storeListeners.delete(fn);}};
  let transforms=0;const context={app:{map,view,projection:'EPSG:3031',ui:{state:{}}},ol:{proj:{transform:p=>{transforms++;return p;}}},imagery,store,visibility:{featureVisible:f=>!f.hidden},
    select:{...Object.fromEntries(['observation','flight','riggs','coverage'].map(k=>[k,f=>calls.push([k,f])])),user(){},reviewed(){},radarCoverage(){}}};
  const h={api,G,doc,host,shell,readout,sandbox,context,map,list,features,interactions,imagery,imageryListeners,storeListeners,calls,mutations,C,made,
    get timerCount(){return timers.size;},get scriptLoads(){return scriptLoads;},get transforms(){return transforms;},get writes(){return writes;},get camera(){return camera;},
    finishLoad(){sandbox.Cesium=C;for(const n of doc.head.children)n.onload?.();},
    mount(){return api.mount(context);},cleanup(){api.controllerFor(map)?.dispose();timers.forEach(clearTimeout);timers.clear();}};
  return h;
}
function primitiveLeaves(group, out=[]) {
 for(const item of group.items||[]){if(item.options?.geometryInstances)out.push(item);else if(item.items)primitiveLeaves(item,out);else out.push(item);}return out;
}
const wait = ms=>new Promise(resolve=>setTimeout(resolve,ms));

test('provider fixture hash and exact pinned options, semantic Cesium version',()=>{
  const h=harness();const T=h.api.testing;
  assert.equal(crypto.createHash('sha256').update(contractBytes).digest('hex'),'11427f34757753923ca31f7a0414f02f718fc5d960ea78a45fcc4daef9eb0982');
  assert.equal(T.CONTRACT.base,contract.release.base_url);assert.equal(T.CONTRACT.scriptIntegrity,contract.release.script.integrity);assert.equal(T.CONTRACT.cssIntegrity,contract.release.css.integrity);
  for(const version of ['1.147','1.147.0'])assert.ok(T.validVersion({VERSION:version}));for(const version of ['1.146','1.147.1','1.147evil'])assert.equal(T.validVersion({VERSION:version}),false);
  const opts=T.viewerOptions(h.C);assert.equal(opts.baseLayer,false);assert.equal(opts.baseLayerPicker,false);assert.equal(opts.sceneMode,3);assert.equal(opts.maximumRenderTimeChange,Infinity);assert.equal(opts.requestRenderMode,true);
  assert.equal(opts.terrainProvider.options.ellipsoid,h.C.Ellipsoid.WGS84);for(const key of ['geocoder','animation','timeline','homeButton','fullscreenButton','infoBox','shadows'])assert.equal(opts[key],false);
  const nasa=T.nasaOptions(h.C);for(const [key,value]of Object.entries(contract.NASA_provider.options))if(key!=='url')assert.deepEqual(plain(nasa[key]),value,key);
  assert.deepEqual(plain(nasa.url.options),{url:contract.NASA_provider.options.url,headers:{}});
  assert.equal(nasa.tilingScheme.options.numberOfLevelZeroTilesX,10);assert.equal(nasa.tilingScheme.options.numberOfLevelZeroTilesY,5);
  for(let level=0;level<=4;level++){assert.equal(nasa.tileMatrixLabels[level],String(level+3));assert.equal(360/(10*2**level),36/2**level);}
  assert.ok(!('referrerPolicy'in nasa.url.options));assert.ok(!/TrustedServers|\b(?:C|Cesium)\.Ion\b/.test(source));h.cleanup();
});

test('mount and module evaluation have zero library/provider loads',()=>{
  const h=harness();const ctl=h.mount();assert.equal(h.scriptLoads,0);assert.equal(h.made.viewers.length,0);assert.equal(h.made.providers.length,0);assert.equal(h.api.mount(h.context),ctl);assert.equal(ctl.isActive(),false);assert.equal(h.host.dataset.flActiveView,'2d');ctl.dispose();assert.equal(h.imageryListeners.size,0);assert.equal(h.storeListeners.size,0);h.cleanup();
});
test('shared cached loader, concurrent enables and exact SRI/referrer metadata',async()=>{
  const h=harness({autoLoad:false});const ctl=h.mount();const a=ctl.setEnabled(true),b=ctl.setEnabled(true);
  assert.equal(h.scriptLoads,1);assert.equal(h.made.viewers.length,0);assert.equal(h.host.classList.contains('fl-globe-active'),false);
  for(const node of h.doc.head.children){assert.equal(node.crossOrigin,'anonymous');assert.equal(node.referrerPolicy,'no-referrer');assert.ok(node.integrity.startsWith('sha256-'));assert.ok((node.href||node.src).startsWith(contract.release.base_url));}
  assert.equal(h.sandbox.CESIUM_BASE_URL,contract.release.base_url);h.finishLoad();assert.equal(await a,false);assert.equal(await b,true);assert.equal(h.made.viewers.length,1);assert.ok(h.made.viewers[0].rendered);
  await ctl.setEnabled(false);await ctl.setEnabled(true);assert.equal(h.scriptLoads,1);assert.equal(h.made.viewers.filter(x=>!x.destroyed).length,1);h.cleanup();
});
test('late load after OFF or disposal cannot activate/hide 2D',async()=>{
  for(const dispose of [false,true]){const h=harness({autoLoad:false}),ctl=h.mount();const pending=ctl.setEnabled(true);dispose?ctl.dispose():await ctl.setEnabled(false);h.finishLoad();assert.equal(await pending,false);assert.equal(h.made.viewers.length,0);assert.equal(h.host.dataset.flActiveView,'2d');assert.equal(h.interactions.items[0].active,true);h.cleanup();}
});
test('script/CSS failure stays in 2D and explicit retry reloads pinned pair',async()=>{
  const h=harness({autoLoad:false});const ctl=h.mount();const a=ctl.setEnabled(true);h.doc.head.children[0].onerror();assert.equal(await a,false);assert.equal(h.host.dataset.flGlobeStatus,'error');assert.equal(ctl.isActive(),false);
  const b=ctl.setEnabled(true);assert.equal(h.scriptLoads,2);h.finishLoad();assert.equal(await b,true);h.cleanup();
});
test('unexpected library global fails closed with no fallback/version rewrite',async()=>{
  const h=harness();h.C.VERSION='1.146';const ctl=h.mount();assert.equal(await ctl.setEnabled(true),false);assert.equal(h.made.viewers.length,0);assert.equal(h.host.dataset.flActiveView,'2d');h.cleanup();
});
test('WebGL/render failure preserves controls and exact 2D interaction flags',async()=>{
  const h=harness();h.C.throwRender=true;const original=h.map.dispatchEvent,ctl=h.mount();assert.equal(await ctl.setEnabled(true),false);assert.equal(h.host.dataset.flGlobeStatus,'error');assert.deepEqual(h.interactions.items.map(x=>x.active),[true,false]);assert.equal(h.map.dispatchEvent,original);assert.equal(h.readout.textContent,'2D coordinates');h.cleanup();
});
test('context loss destroys viewer, disposes events, restores 2D, allows retry',async()=>{
  const h=harness(),ctl=h.mount();await ctl.setEnabled(true);const v=h.made.viewers[0];let prevented=false;v.scene.canvas.dispatchEvent({type:'webglcontextlost',preventDefault(){prevented=true;}});assert.equal(prevented,true);assert.equal(ctl.isActive(),false);assert.equal(v.destroyed,true);assert.equal(v.scene.postRender.listeners.size,0);assert.equal(v.scene.canvas.count(),0);assert.equal(h.made.handlers[0].destroyed,true);await ctl.setEnabled(true);assert.equal(ctl.isActive(),true);h.cleanup();
});
test('2D dispatch capture precedes old listeners; interactions/camera/URL restore',async()=>{
  const h=harness(),old=h.map.dispatchEvent;let hits=0;h.map.on('singleclick',()=>hits++);const before=JSON.stringify(h.camera),ctl=h.mount();await ctl.setEnabled(true);
  h.map.dispatchEvent('singleclick');assert.equal(hits,0);assert.deepEqual(h.interactions.items.map(x=>x.active),[false,false]);
  const added={active:true,getActive(){return this.active;},setActive(v){this.active=v;}};h.interactions.add(added);assert.equal(added.active,false);
  h.made.viewers[0].camera.zoomIn();assert.equal(h.writes,0);assert.equal(JSON.stringify(h.camera),before);
  await ctl.setEnabled(false);h.map.dispatchEvent('singleclick');assert.equal(hits,1);assert.equal(h.map.dispatchEvent,old);assert.deepEqual(h.interactions.items.map(x=>x.active),[true,false,true]);assert.equal(h.writes,0);h.cleanup();
});
test('mode or document hiding during load cannot resurrect globe',async()=>{
  for(const mode of ['manual','terra','automatic','hidden']){const h=harness({autoLoad:false}),ctl=h.mount(),pending=ctl.setEnabled(true);if(mode==='hidden'){h.doc.hidden=true;h.doc.dispatchEvent('visibilitychange');}else{h.doc.body.dataset.flMode=mode;h.mutations[0].fn();}h.finishLoad();assert.equal(await pending,false);assert.equal(ctl.isRequested(),false);assert.equal(h.made.viewers.length,0);h.cleanup();}
});
test('leaving map mode destroys active viewer and does not auto-enable on return',async()=>{
  const h=harness(),ctl=h.mount();await ctl.setEnabled(true);h.doc.body.dataset.flMode='terra';h.mutations[0].fn();assert.equal(ctl.isActive(),false);assert.ok(h.made.viewers[0].destroyed);h.doc.body.dataset.flMode='map';h.mutations[0].fn();assert.equal(ctl.isActive(),false);h.cleanup();
});

test('clone transform ignores source Z and preserves disconnected geometry, holes and IDs',()=>{
  const h=harness(),T=h.api.testing;for(const key of ['disconnected','holes','point']){const f=fixtures[key],g=new Geometry(f.type,structuredClone(f.coordinates)),before=JSON.stringify(g.coordinates),out=T.convertGeometry(g,p=>{p[0]+=1;return p;});assert.equal(JSON.stringify(g.coordinates),before);if(key==='disconnected'){assert.equal(out.lines.length,2);assert.deepEqual(plain(out.lines[1]),[[11,-75],[12,-75]]);}if(key==='holes')assert.equal(out.polygons[0].length,2);if(key==='point')assert.deepEqual(plain(out.points),[[26,-85]]);}h.cleanup();
});
test('dateline splits at exact seam and invalid points never bridge gaps',()=>{
  const h=harness(),T=h.api.testing;
  let f=fixtures.dateline,out=T.convertGeometry(new Geometry(f.type,f.coordinates),x=>x);assert.equal(out.lines.length,2);assert.equal(out.lines[0].at(-1)[0],180);assert.equal(out.lines[1][0][0],-180);
  f=fixtures.invalidGap;out=T.convertGeometry(new Geometry(f.type,f.coordinates),x=>x);assert.equal(out.lines.length,2);assert.deepEqual(plain(out.lines[1]),[[10,-75],[11,-75]]);
  const bad=structuredClone(fixtures.holes.coordinates);bad[1][2]=[NaN,NaN];out=T.convertGeometry(new Geometry('Polygon',bad),x=>x);assert.equal(out.polygons.length,0);h.cleanup();
});
test('long projected segments densify before transform without data mutation',()=>{
  const h=harness(),T=h.api.testing;let n=0;const out=T.convertGeometry(new Geometry('LineString',[[0,0],[200000,0]]),p=>{n++;return[p[0]/10000,-80];});assert.equal(n,6);assert.equal(out.lines[0].length,6);h.cleanup();
});
test('actual visibility, feature-specific style, layer ranges and geometry function are honored',()=>{
  const a=new Feature('a'),b=new Feature('b'),c=new Feature('c');b.hidden=true;a.getStyleFunction=()=>()=>style({point:circle('#ff0000')});
  const layer=new Layer('frozen-observations',[a,b,c],f=>f===c?null:style({point:circle()}));const h=harness({layers:[layer]}),snap=h.api.testing.snapshot(h.context,'off');assert.equal(snap.rows.length,1);assert.equal(snap.rows[0].feature,a);assert.equal(snap.rows[0].featureId,'a');assert.equal(snap.rows[0].style.getImage().getFill().getColor(),'#ff0000');
  layer.getMinResolution=()=>6000;assert.equal(h.api.testing.snapshot(h.context,'off').rows.length,0);layer.getMinResolution=()=>0;layer.visible=false;assert.equal(h.api.testing.snapshot(h.context,'off').rows.length,0);layer.visible=true;layer.fn=()=>style({geom:()=>null});a.getStyleFunction=()=>null;assert.equal(h.api.testing.snapshot(h.context,'off').rows.length,0);h.cleanup();
});
test('render-stack regression: solid land/shelf fallback never washes out usable NASA',()=>{
  const polygon=new Feature('land','Polygon',fixtures.holes.coordinates);const landStyle=()=>style({area:fill('#f6f8f8'),line:stroke()});
  const fallback=new Layer('quantarctica-fallback',[polygon],landStyle),boundary=new Layer('quantarctica-basemap',[polygon],()=>style({line:stroke()})),basin=new Layer('antarctic-drainage-basins',[polygon],()=>style({area:fill('rgba(0,0,0,0.035)'),line:stroke()}));
  const ocean=new Layer('antarctic-polar-ocean',[polygon],landStyle);const h=harness({layers:[fallback,boundary,basin,ocean]});
  for(const mode of ['off','loading','unavailable','ready']){const snap=h.api.testing.snapshot(h.context,mode);assert.ok(snap.rows.every(r=>r.layerId!=='antarctic-polar-ocean'));assert.equal(snap.rows.find(r=>r.layerId==='quantarctica-fallback').fills,!['loading','ready'].includes(mode));assert.equal(snap.rows.find(r=>r.layerId==='antarctic-drainage-basins').fills,true);const batch=h.api.testing.createBatches(h.C,{primitives:new h.C.PrimitiveCollection()},snap,h.doc);assert.equal(batch.counts.polygons,['loading','ready'].includes(mode)?1:2);assert.equal(batch.counts.lines,6);batch.group.destroy();}h.cleanup();
});
test('polygons pass holes to Cesium hierarchy; point batches retain identity and scientific color',async()=>{
  const h=harness(),ctl=h.mount();await ctl.setEnabled(true);const v=h.made.viewers[0],point=v.scene.primitives.items[0].items[0].items[0];assert.equal(point.id.feature,h.features[0]);assert.equal(point.id.featureId,'obs-1');assert.equal(point.color.css,'#22c55e');assert.equal(point.position.height,200);assert.equal(point.disableDepthTestDistance,undefined);
  const polygon=new Feature('p','Polygon',fixtures.holes.coordinates),layer=new Layer('quantarctica-fallback',[polygon],()=>style({area:fill('white')}));h.list.add(layer);await ctl.whenComplete();
  const group=v.scene.primitives.items[0],primitive=primitiveLeaves(group).find(x=>x.options?.geometryInstances);assert.equal(primitive.options.geometryInstances[0].geometry.options.polygonHierarchy.holes.length,1);h.cleanup();
});
test('3D picks dispatch original features through real selection adapters, never pixel hits',async()=>{
  const features=['observations','flights','riggs','coverage'].map((x,i)=>new Feature('f'+i));
  const layers=[new Layer('frozen-observations',[features[0]]),new Layer('frozen-flights',[features[1]]),new Layer('riggs-reference-stations',[features[2]]),new Layer('antarctic-image-navigation',[features[3]])];
  const h=harness({layers}),ctl=h.mount();await ctl.setEnabled(true);const v=h.made.viewers[0],points=primitiveLeaves(v.scene.primitives.items[0]).filter(x=>x.position&&!x.image&&x.text===undefined);
  for(const point of points){v.pickResult={id:point.id};h.made.handlers[0].actions[0]({position:{x:0,y:0}});}assert.deepEqual(h.calls.map(x=>x[0]),['observation','flight','riggs','coverage']);for(let i=0;i<4;i++)assert.equal(h.calls[i][1],features[i]);assert.equal(h.writes,0);h.cleanup();
});
test('shared NASA OFF makes no provider, ON uses own pending/failure/retry, OFF removes it',async()=>{
  const h=harness(),ctl=h.mount();await ctl.setEnabled(true);assert.equal(h.made.providers.length,0);assert.equal(h.host.dataset.flGlobeImagery,'off');
  h.imagery.setEnabled(true);assert.equal(h.made.providers.length,1);assert.equal(h.host.dataset.flGlobeImagery,'loading');const v=h.made.viewers[0];v.scene.globe.tileLoadProgressEvent.raise(4);assert.equal(h.host.dataset.flGlobeImagery,'loading');v.scene.globe.tilesLoaded=true;v.scene.globe.tileLoadProgressEvent.raise(0);assert.equal(h.host.dataset.flGlobeImagery,'ready');
  h.made.providers[0].errorEvent.raise({});assert.equal(h.host.dataset.flGlobeImagery,'unavailable');assert.equal(v.imageryLayers.items.length,0);assert.equal(h.imagery.state.enabled,true);h.imagery.setEnabled(false);assert.equal(h.host.dataset.flGlobeImagery,'off');assert.equal(h.made.providers.length,1);h.cleanup();
});
test('off before NASA tile completion drops callbacks and cannot change active view',async()=>{
  const h=harness({nasa:true}),ctl=h.mount();await ctl.setEnabled(true);const v=h.made.viewers[0],provider=h.made.providers[0];await ctl.setEnabled(false);provider.errorEvent.raise({});v.scene.globe.tileLoadProgressEvent.raise(0);assert.equal(v.scene.globe.tileLoadProgressEvent.listeners.size,0);assert.equal(provider.errorEvent.listeners.size,0);assert.equal(h.host.dataset.flActiveView,'2d');assert.equal(v.useDefaultRenderLoop,false);h.cleanup();
});
test('14k points are batched; bursts coalesce; camera frames never resnapshot',async()=>{
  const features=Array.from({length:14000},(_,i)=>new Feature(String(i))),h=harness({features}),ctl=h.mount();await ctl.setEnabled(true);assert.equal(h.host.dataset.flGlobeUpdates,'1');assert.equal(JSON.parse(h.host.dataset.flGlobePrimitiveCounts).points,14000);const transforms=h.transforms,v=h.made.viewers[0];
  for(let i=0;i<20;i++){v.scene.postRender.raise();v.camera.zoomIn();}assert.equal(h.transforms,transforms);assert.equal(h.host.dataset.flGlobeUpdates,'1');
  for(let i=0;i<30;i++){h.list.items[0].source.dispatchEvent('change');h.doc.dispatchEvent('fl-map-visibility-change');}await ctl.whenComplete();assert.equal(h.host.dataset.flGlobeUpdates,'2');assert.equal(v.scene.primitives.items.length,1);await ctl.setEnabled(false);h.doc.dispatchEvent('fl-map-visibility-change');await ctl.whenComplete();assert.equal(h.host.dataset.flGlobeUpdates,'2');h.cleanup();
});
test('active zoom/reset/fit and true pointer coordinates never write 2D camera',async()=>{
  const h=harness(),ctl=h.mount();assert.equal(ctl.zoom(1),false);await ctl.setEnabled(true);const v=h.made.viewers[0];ctl.zoom(1);assert.equal(v.zoomed,'in');ctl.resetView();assert.equal(v.lastView.destination.lat,-90);ctl.fitFeature(h.features[0]);assert.ok(v.flown);assert.equal(h.writes,0);
  const plus=new El();plus.testClass='ol-zoom-in';let stopped=false;h.host.dispatchEvent({type:'click',target:plus,preventDefault(){},stopImmediatePropagation(){stopped=true;}});assert.ok(stopped);h.made.handlers[0].actions[1]({endPosition:{x:1,y:1}});assert.match(h.readout.textContent,/85.000° S · 25.000° E/);v.coordinate=null;h.made.handlers[0].actions[1]({endPosition:{}});assert.equal(h.readout.textContent,'Outside the globe');await ctl.setEnabled(false);assert.equal(h.readout.textContent,'2D coordinates');h.cleanup();
});
test('popup anchors to 3D location, horizon occlusion and restores original host',async()=>{
  const h=harness(),ctl=h.mount();await ctl.setEnabled(true);const original=new El(),popup=new El();original.append(popup);popup.hidden=false;h.popup=popup;let syncs=0;popup._flSyncPresentation=()=>syncs++;
  assert.equal(ctl.syncPopup(popup,h.features[0]),true);assert.equal(popup.parentElement,h.shell);assert.equal(popup.dataset.presentation,'globe');assert.ok(popup.style.left.endsWith('px'));const left=popup.style.left;ctl.movePopup(popup,20,0);assert.notEqual(popup.style.left,left);
  h.C.frontSide=false;h.made.viewers[0].scene.postRender.raise();assert.equal(popup.style.visibility,'hidden');await ctl.setEnabled(false);assert.equal(popup.parentElement,original);assert.equal(popup.style.visibility,'');assert.equal(syncs,1);h.cleanup();
});
test('disposal clears mount/source/DOM callbacks and repeated mount creates one new controller',async()=>{
  const h=harness(),before=h.doc.count(),ctl=h.mount();await ctl.setEnabled(true);assert.ok(h.list.items[0].source.count()>0);ctl.dispose();ctl.dispose();assert.equal(h.doc.count(),before);assert.equal(h.list.items[0].source.count(),0);assert.equal(h.map.count(),0);assert.equal(h.imageryListeners.size,0);assert.equal(h.storeListeners.size,0);assert.equal(h.api.controllerFor(h.map),undefined);const next=h.mount();assert.notEqual(next,ctl);h.cleanup();
});

// Optional reviewed-snippet checks against the owned patched copy. Set this to
// an app root after applying both review patches; never point it at Source.
const integrationRoot = process.env.GLOBE_INTEGRATION_ROOT;
function launcherHarness() {
  const h=harness({autoLoad:false});h.doc.querySelector=()=>null;h.doc.querySelectorAll=()=>[];
  h.sandbox.sessionStorage={getItem:()=> 'false',setItem(){}};
  h.sandbox.ol={source:{TileImage:class{}},tilegrid:{TileGrid:class{}},layer:{Tile:class{}}};
  const calls=[],controller={setEnabled:v=>{calls.push(['enabled',v]);return Promise.resolve(v);},dispose:()=>calls.push(['dispose'])};
  h.sandbox.FrozenLegaciesGlobe={mount:context=>{calls.push(['mount',context]);return controller;}};
  h.context.app.ui={showObservation:f=>calls.push(['observation',f]),selectFlight:(f,o)=>calls.push(['flight',f,o])};h.context.app.data={riggs:{metadata:{citation_pending:true}}};
  h.sandbox.FrozenLegaciesUI={showRiggsStation:(f,m)=>calls.push(['riggs',f,m])};h.sandbox.FrozenLegaciesCatalog={selectMapAsset:f=>calls.push(['coverage',f]),selectFeature:f=>calls.push(['radarCoverage',f])};h.sandbox.FrozenLegaciesUserLayer={selectFeature:f=>calls.push(['user',f])};h.sandbox.FrozenLegaciesPublishedLayer={selectFeature:f=>calls.push(['reviewed',f])};
  vm.runInNewContext(fs.readFileSync(path.join(integrationRoot,'assets/map_explorer.js'),'utf8'),h.sandbox);
  const launcher=h.sandbox.FrozenLegaciesMapExplorer.mountGlobeButton(h.context.app),button=h.shell.children.find(x=>x.tagName==='button');
  return Object.assign(h,{calls,launcher,button,click:()=>[...button.events.get('click')][0]()});
}
test('reviewed loader is lazy, same-origin SRI pinned, cancel-safe and uses actual adapters',{skip:!integrationRoot},async()=>{
  const h=launcherHarness();assert.equal(h.scriptLoads,0);assert.equal(h.calls.length,0);
  const first=h.click();assert.equal(h.scriptLoads,1);const second=h.click();await second;h.finishLoad();await first;assert.equal(h.calls.length,0);
  await h.click();assert.equal(h.calls[0][0],'mount');assert.deepEqual(h.calls[1],['enabled',true]);assert.equal(h.scriptLoads,1);
  const context=h.calls[0][1],f=h.features[0];for(const key of ['observation','flight','riggs','coverage','user','reviewed','radarCoverage'])context.select[key](f);
  assert.equal(h.calls.find(x=>x[0]==='observation')[1],f);const flight=h.calls.find(x=>x[0]==='flight');assert.equal(flight[1],'125');assert.deepEqual(plain(flight[2]),{datasetId:'synthetic-a',zoom:false});assert.equal(h.calls.find(x=>x[0]==='riggs')[2],h.context.app.data.riggs.metadata);assert.equal(context.imagery.state.enabled,false);for(const key of ['user','reviewed','radarCoverage'])assert.equal(h.calls.find(x=>x[0]===key)[1],f);
  assert.equal(h.doc.head.children.find(n=>n.tagName==='script').src,'/frozen-legacies/assets/globe_view.js?v=sha256-'+crypto.createHash('sha256').update(fs.readFileSync(path.join(integrationRoot,'assets/globe_view.js'))).digest('hex').slice(0,12));
  for(const n of h.doc.head.children){assert.ok((n.src||n.href).startsWith('/frozen-legacies/assets/globe_view.'));assert.equal(n.referrerPolicy,'no-referrer');assert.equal(n.crossOrigin,'anonymous');const file=(n.src||n.href).split('?')[0].split('/').at(-1);assert.equal(n.integrity,'sha256-'+crypto.createHash('sha256').update(fs.readFileSync(path.join(integrationRoot,'assets',file))).digest('base64'));}
  h.launcher.dispose();assert.equal(h.calls.at(-1)[0],'dispose');h.cleanup();
});
test('reviewed loader mode changes and teardown cancel pending activation',{skip:!integrationRoot},async()=>{
  for(const action of ['mode','hidden','dispose']){const h=launcherHarness(),pending=h.click();if(action==='mode'){h.doc.body.dataset.flMode='terra';h.mutations.at(-1).fn();assert.equal(h.button.hidden,true);h.doc.body.dataset.flMode='map';h.mutations.at(-1).fn();}else if(action==='hidden'){h.doc.hidden=true;h.doc.dispatchEvent('visibilitychange');h.doc.hidden=false;}else h.launcher.dispose();h.finishLoad();await pending;assert.equal(h.calls.filter(x=>x[0]==='mount').length,0);h.launcher.dispose();h.cleanup();}
});
test('reviewed loader failure leaves an explicit retry and releases listeners',{skip:!integrationRoot},async()=>{
  const h=launcherHarness();const pending=h.click();h.doc.head.children[0].onerror();await pending;assert.equal(h.button.textContent,'3D unavailable · retry');assert.equal(h.calls.length,0);const retry=h.click();h.finishLoad();await retry;assert.equal(h.calls.filter(x=>x[0]==='mount').length,1);h.launcher.dispose();assert.equal(h.doc.count(),2); // original MapExplorer segment listeners only
  h.cleanup();
});
test('reviewed map helper seams route reset/fit solely to active globe',{skip:!integrationRoot},()=>{
  let resets=0,fits=0,writes=0;const map={getView:()=>({fit(){writes++;}}),getSize:()=>[800,600]},ctx={console,window:null};ctx.window=ctx;ctx.FrozenLegaciesGlobe={controllerFor:m=>{assert.equal(m,map);return{resetView:()=>{resets++;return true;},fitFeature:f=>{fits++;return true;}};}};
  vm.runInNewContext(fs.readFileSync(path.join(integrationRoot,'assets/map.js'),'utf8'),ctx);ctx.FrozenLegaciesMap.resetView(map);ctx.FrozenLegaciesMap.fitToFeature(map,{});assert.equal(resets,1);assert.equal(fits,1);assert.equal(writes,0);
});
test('reviewed UI seam sends original feature to popup anchor without 2D position',{skip:!integrationRoot},()=>{
  const doc={addEventListener(){},getElementById(){return null;}},ctx={document:doc,window:null,requestAnimationFrame:fn=>fn(),FrozenLegaciesScopeMedia:{load(){}}};ctx.window=ctx;
  vm.runInNewContext(fs.readFileSync(path.join(integrationRoot,'assets/ui.js'),'utf8'),ctx);
  let anchored=null,positions=0;const map={},feature=new Feature('p'),el=new El();el.hidden=false;el._flSyncPresentation=()=>{};el._flKeepPopupInMap=()=>{};el._flOverlay={setPosition(){positions++;}};ctx.ensureObservationPopup=()=>el;ctx.observationPopupHtml=()=>'<p>Real actions mocked</p>';ctx.bindPreviewFallbacks=()=>{};
  ctx.FrozenLegaciesGlobe={controllerFor:m=>({syncPopup:(element,f)=>{assert.equal(m,map);assert.equal(element,el);anchored=f;return true;}})};
  ctx.showObservationPopup(map,feature,{});assert.equal(anchored,feature);assert.equal(el._flGlobeFeature,feature);assert.equal(positions,0);assert.equal(ctx.FrozenLegaciesUI.showRiggsStation,ctx.renderRiggsStation);
});
test('DPR changes resize owned viewer and do not add a permanent render loop',async()=>{
  const h=harness(),media=[];h.sandbox.devicePixelRatio=1.5;h.sandbox.matchMedia=()=>{const m=new Events();media.push(m);return m;};const ctl=h.mount();await ctl.setEnabled(true);const v=h.made.viewers[0];assert.equal(v.resolutionScale,1);h.sandbox.devicePixelRatio=3;media[0].dispatchEvent('change');assert.equal(v.resolutionScale,1);assert.equal(media[0].count(),0);assert.equal(media.length,2);ctl.dispose();assert.equal(media[1].count(),0);h.cleanup();
});
test('2D imagery counter notifications never retry failed 3D imagery; own retry does',async()=>{
  const h=harness({nasa:true}),ctl=h.mount();await ctl.setEnabled(true);h.made.providers[0].errorEvent.raise({});assert.equal(h.made.providers.length,1);
  for(let i=0;i<5;i++){h.imagery.state.loaded=i;h.imagery.state.pending=4-i;h.imageryListeners.forEach(fn=>fn(h.imagery.state));}assert.equal(h.made.providers.length,1);assert.equal(h.host.dataset.flGlobeImagery,'unavailable');
  const toolbar=h.shell.children.find(x=>x.classList.contains('fl-globe-toolbar')),retry=toolbar.children.find(x=>x.classList.contains('fl-globe-retry'));retry.dispatchEvent('click');assert.equal(h.made.providers.length,2);assert.equal(h.host.dataset.flGlobeImagery,'loading');assert.equal(h.imagery.state.enabled,true);h.cleanup();
});
test('synthetic 177 RIGGS shapes retain seismic/radar symbols, colors and original IDs',async()=>{
  const features=Array.from({length:177},(_,i)=>new Feature('riggs-'+i,'Point',[25,-85],{measurement_method:i<80?'seismic':'radar'}));
  const layer=new Layer('riggs-reference-stations',features,f=>style({point:{getRadius:()=>4.5,getPoints:()=>f.get('measurement_method')==='seismic'?4:3,getAngle:()=>f.get('measurement_method')==='seismic'?Math.PI/4:0,getFill:()=>fill(f.get('measurement_method')==='seismic'?'#9b3653':'#7a4fb3'),getOpacity:()=>1}}));
  const h=harness({layers:[layer]}),ctl=h.mount();await ctl.setEnabled(true);const group=h.made.viewers[0].scene.primitives.items[0],shapes=primitiveLeaves(group).filter(x=>x.image);assert.equal(shapes.length,177);assert.equal(shapes[0].id.feature,features[0]);assert.equal(shapes[176].id.featureId,'riggs-176');assert.equal(shapes[0].image,shapes[79].image);assert.notEqual(shapes[0].image,shapes[80].image);assert.ok(shapes.every(x=>x.disableDepthTestDistance===undefined));layer.visible=false;layer.dispatchEvent('change');await ctl.whenComplete();assert.equal(JSON.parse(h.host.dataset.flGlobePrimitiveCounts).points,0);h.cleanup();
});
test('selected flight multi-style halo and orange line remain separate with original feature',()=>{
  const f=new Feature('selected','MultiLineString',fixtures.disconnected.coordinates),layer=new Layer('frozen-selected-flight',[f],()=>[style({line:stroke('rgba(255,255,255,0.94)',6.5)}),style({line:stroke('#ff8a1f',3.4)})]);
  const h=harness({layers:[layer]}),snap=h.api.testing.snapshot(h.context,'ready'),batch=h.api.testing.createBatches(h.C,{primitives:new h.C.PrimitiveCollection()},snap,h.doc),lines=batch.group.items[1].items;assert.equal(lines.length,4);assert.deepEqual(lines.map(x=>x.width),[6.5,6.5,3.4,3.4]);assert.equal(lines[2].material.uniforms.color.css,'#ff8a1f');assert.ok(lines.every(x=>x.id.feature===f));batch.group.destroy();h.cleanup();
});
test('source/layer rebuild failure falls back accessibly without a blank map',async()=>{
  const h=harness(),ctl=h.mount();await ctl.setEnabled(true);h.list.items[0].fn=()=>{throw Error('bad style');};h.list.items[0].dispatchEvent('change');await ctl.whenComplete();assert.equal(ctl.isActive(),false);assert.equal(h.host.dataset.flGlobeStatus,'error');assert.equal(h.interactions.items[0].active,true);assert.ok(h.made.viewers[0].destroyed);const toolbar=h.shell.children.find(x=>x.classList.contains('fl-globe-toolbar')),status=toolbar.children.find(x=>x.classList.contains('fl-globe-status'));assert.equal(status.attrs.role,'status');assert.match(status.textContent,/2D map is available/);h.cleanup();
});
test('reviewed real popup presentation restores selected source coordinate on 2D exit',{skip:!integrationRoot},async()=>{
  const h=harness(),ctl=h.mount();await ctl.setEnabled(true);const element=new El('section');element.hidden=true;h.popup=element;h.shell.append(element);
  h.sandbox.ol={...h.context.ol,Overlay:class{constructor(options){this.element=options.element;this.offset=options.offset;}setPosition(p){this.position=p;}getPosition(){return this.position;}setOffset(p){this.offset=p;}getOffset(){return this.offset;}}};
  h.map.addOverlay=o=>{const overlayHost=new El();h.host.append(overlayHost);overlayHost.append(o.element);};
  h.sandbox.matchMedia=()=>{const m=new Events();m.matches=false;return m;};h.sandbox.requestAnimationFrame=()=>0;h.sandbox.cancelAnimationFrame=()=>{};
  vm.runInNewContext(fs.readFileSync(path.join(integrationRoot,'assets/ui.js'),'utf8'),h.sandbox);h.sandbox.observationPopupHtml=()=>'';h.sandbox.bindPreviewFallbacks=()=>{};
  h.sandbox.showObservationPopup(h.map,h.features[0],{});assert.equal(element.dataset.presentation,'globe');assert.equal(element._flOverlay.getPosition(),undefined);
  await ctl.setEnabled(false);assert.equal(element.dataset.presentation,'map');assert.deepEqual(element._flOverlay.getPosition(),h.features[0].getGeometry().getCoordinates());assert.equal(h.writes,0);h.cleanup();
});

for (const [layerId, adapter] of [['frozen-my-picks','user'],['frozen-reviewed-results','reviewed'],['frozen-radar-coverage','radarCoverage']]) {
  test(`parity witness: ${layerId} renders and routes the same source feature`, async () => {
    const feature = new Feature('same-id', 'Point', [25,-85], {kind:'observations', layerId:'frozen-observations'});
    const layer = new Layer(layerId, [feature]);
    const h = harness({layers:[layer]}), routed=[];
    for (const key of ['user','reviewed','radarCoverage']) h.context.select[key]=f=>routed.push([key,f]);
    const ctl=h.mount();await ctl.setEnabled(true);
    const v=h.made.viewers[0], point=v.scene.primitives.items[0].items[0].items[0];
    assert.equal(point.id.feature, feature, 'rendered original feature');
    assert.equal(point.id.layerId,layerId,'namespace comes from actual layer');
    v.pickResult={id:point.id};
    const handled=h.made.handlers[0].actions[0]({position:{x:0,y:0}});
    assert.equal(routed.find(([key])=>key===adapter)?.[1],feature,'same feature callback');
    assert.equal(handled,true);
    assert.equal(h.calls.length,0,'feature properties cannot route as static observation');
    v.pickResult=undefined;h.made.handlers[0].actions[0]({position:{x:0,y:0}});
    assert.equal(routed.at(-3)[1],null);assert.equal(routed.at(-2)[1],null);assert.equal(routed.at(-1)[1],null);
    h.cleanup();
  });
}

test('OpenLayers propertychange alone refreshes RIGGS visibility without generic or source change',async()=>{
 const layer=new Layer('riggs-reference-stations',[new Feature('riggs-1')]);layer.visible=false;
 // BaseObject property setters emit property-specific/propertychange events, not Observable.change.
 layer.setVisible=function(visible){if(this.visible===visible)return;const oldValue=this.visible;this.visible=visible;this.dispatchEvent({type:'change:visible',key:'visible',oldValue});this.dispatchEvent({type:'propertychange',key:'visible',oldValue});};
 let generic=0,sourceChanges=0;layer.on('change',()=>generic++);layer.source.on('change',()=>sourceChanges++);
 const h=harness({layers:[layer]}),ctl=h.mount();await ctl.setEnabled(true);await ctl.whenComplete();
 assert.equal(JSON.parse(h.host.dataset.flGlobeFeatureCounts)['riggs-reference-stations'],undefined);
 const before=Number(h.host.dataset.flGlobeUpdates);layer.setVisible(true);await ctl.whenComplete();
 assert.equal(JSON.parse(h.host.dataset.flGlobeFeatureCounts)['riggs-reference-stations'],1);
 assert.ok(Number(h.host.dataset.flGlobeUpdates)>before,'visibility alone schedules a fresh snapshot');
 const shown=Number(h.host.dataset.flGlobeUpdates);layer.setVisible(false);await ctl.whenComplete();
 assert.equal(JSON.parse(h.host.dataset.flGlobeFeatureCounts)['riggs-reference-stations'],undefined);
 assert.ok(Number(h.host.dataset.flGlobeUpdates)>shown,'hide alone also refreshes');
 assert.equal(generic,0);assert.equal(sourceChanges,0);assert.equal(h.writes,0);
 h.cleanup();assert.equal(layer.events.get('propertychange')?.size||0,0,'property listener disposed');
});

test('dynamic sources, visibility, filters and removal keep flowing through the debounced traversal',async()=>{
 const h=harness({layers:[]}),ctl=h.mount();await ctl.setEnabled(true);
 const feature=new Feature('live'),layer=new Layer('frozen-my-picks',[feature]);h.list.add(layer);await ctl.whenComplete();
 assert.equal(JSON.parse(h.host.dataset.flGlobePrimitiveCounts).points,1);
 layer.visible=false;layer.dispatchEvent('change');await ctl.whenComplete();assert.equal(JSON.parse(h.host.dataset.flGlobePrimitiveCounts).points,0);
 layer.visible=true;layer.features=[new Feature('replacement')];for(let i=0;i<10;i++)layer.source.dispatchEvent('change');await ctl.whenComplete();
 assert.equal(JSON.parse(h.host.dataset.flGlobePrimitiveCounts).points,1);
 layer.fn=()=>null;h.doc.dispatchEvent('fl-map-visibility-change');await ctl.whenComplete();assert.equal(JSON.parse(h.host.dataset.flGlobePrimitiveCounts).points,0);
 layer.fn=()=>style({point:circle()});layer.source=new Events();layer.source.getFeatures=()=>layer.features;layer.dispatchEvent('change:source');await ctl.whenComplete();
 assert.equal(JSON.parse(h.host.dataset.flGlobePrimitiveCounts).points,1);
 h.list.items=[];h.list.dispatchEvent('remove');await ctl.whenComplete();assert.equal(JSON.parse(h.host.dataset.flGlobePrimitiveCounts).points,0);assert.equal(layer.source.count(),0);h.cleanup();
});
for(const width of [1440,750,320])for(const open of [false,true])test(`measured globe controls: ${width}px, Layers ${open?'open':'collapsed'}`,{skip:!integrationRoot},async()=>{
 const h=launcherHarness(),G=h.sandbox.FrozenLegaciesMapExplorer;
 const rect=(left,top,w,height)=>({left,top,width:w,height,right:left+w,bottom:top+height});
 const box=rect(20,40,width,650),empty=new El(),zoom=new El(),layers=new El(),key=new El(),readout=new El();
 empty.className='fl-empty-flight-control';zoom.className='ol-zoom';layers.className='fl-map-data-controls';key.className='fl-map-legend';readout.className='fl-map-readout';
 let emptyHeight=width===320?54:32,layersWidth=open?(width===320?220:260):128;
 empty.getBoundingClientRect=()=>rect(28,48,Math.min(260,width-64),emptyHeight);
 zoom.getBoundingClientRect=()=>rect(20+width-48,54,32,64);
 layers.getBoundingClientRect=()=>rect(20+width-layersWidth-16,40+(width===320?80:94),layersWidth,open?310:42);
 key.getBoundingClientRect=()=>rect(36,440,Math.min(220,width-32),180);readout.getBoundingClientRect=()=>rect(36,640,220,30);
 const nodes={'.fl-empty-flight-control':empty,'.ol-zoom':zoom,'.fl-map-data-controls':layers,'.fl-map-legend':key,'.fl-map-readout':readout};
 h.shell.getBoundingClientRect=()=>box;h.shell.querySelector=s=>nodes[s];
 const stop=G.positionGlobeControls(h.button,h.shell,h.doc);
 const check=node=>{const top=box.top+parseFloat(node.style.top),left=box.left+parseFloat(node.style.left),right=left+parseFloat(node.style.maxWidth),bottom=top+parseFloat(node.style.maxHeight);
  assert.ok(top>=empty.getBoundingClientRect().bottom+8);assert.ok(right<=layers.getBoundingClientRect().left-8);assert.ok(bottom<=key.getBoundingClientRect().top-8);assert.ok(left>=box.left);assert.equal(node.style.overflow,'auto');};
 check(h.button);
 h.context.positionControls=G.positionGlobeControls;const ctl=h.mount();const pending=ctl.setEnabled(true);h.finishLoad();await pending;
 const toolbar=h.shell.children.find(n=>n.classList.contains('fl-globe-toolbar'));const stopToolbar=()=>ctl.dispose();check(toolbar);assert.equal(toolbar.style.top,h.button.style.top);assert.equal(toolbar.style.width,h.button.style.width);
 // A wrapped empty-flight label and an open/close disclosure must reflow both controls.
 emptyHeight+=20;layersWidth=open?128:220;h.shell.dispatchEvent('toggle');check(h.button);check(toolbar);
 stop();stopToolbar();h.launcher.dispose();h.cleanup();
});


test('ground fills drape without elevation and retain hierarchy, colors, IDs and outlines',()=>{
  const h=harness(),f=new Feature('basin-ground','Polygon',[[[0,-80],[10,-80],[5,-85],[0,-80]],[[3,-81],[4,-81],[3,-82],[3,-81]]]);
  const rings=f.getGeometry().getCoordinates();
  const row={feature:f,featureId:f.getId(),layerId:'antarctic-drainage-basins',kind:'reference',opacity:0.4,style:style({line:stroke('#123456',2),area:fill('#abcdef')}),fills:true,offset:240,fillOffset:60,geometry:{points:[],lines:[],polygons:[rings]}};
  const before=JSON.stringify(rings),batch=h.api.testing.createBatches(h.C,{primitives:new h.C.PrimitiveCollection()},{rows:[row]},h.doc);
  assert.deepEqual(plain(batch.counts),{points:0,lines:2,polygons:1,labels:0,billboards:0});
  const ground=batch.group.items.at(-1);assert.ok(ground instanceof h.C.GroundPrimitive);assert.equal(ground.options.classificationType,h.C.ClassificationType.TERRAIN);assert.equal(ground.options.asynchronous,false);assert.equal(ground.options.appearance.options.flat,true);
  const instance=ground.options.geometryInstances[0],p=instance.geometry.options;
  assert.equal(instance.id.feature,f);assert.equal(instance.id.featureId,'basin-ground');assert.equal(p.height,0);assert.equal(p.polygonHierarchy.holes.length,1);assert.ok(p.polygonHierarchy.positions.every(p=>p.height===0));assert.ok(p.polygonHierarchy.holes[0].positions.every(p=>p.height===0));
  assert.equal(instance.attributes.color.alpha,0.4);assert.equal(instance.attributes.color.css,'#abcdef');assert.equal(JSON.stringify(rings),before);batch.group.destroy();h.cleanup();
});

test('ground initialization is awaited before Viewer and cancelled enable stays 2D',async()=>{
  const h=harness();let resolve;h.C.GroundPrimitive.initializeTerrainHeights=()=>new Promise(r=>{resolve=r;});const ctl=h.mount(),pending=ctl.setEnabled(true);await wait(0);
  assert.equal(typeof resolve,'function');assert.equal(h.made.viewers.length,0);assert.equal(h.interactions.items[0].getActive(),true);
  await ctl.setEnabled(false);resolve();assert.equal(await pending,false);assert.equal(h.made.viewers.length,0);assert.equal(ctl.isActive(),false);assert.equal(h.writes,0);h.cleanup();
});

test('ground capability or bound-table failure restores usable 2D',async()=>{
  for(const failure of ['table','supported','materials']){
    const h=harness();if(failure==='table')h.C.GroundPrimitive.initializeTerrainHeights=()=>Promise.reject(Error('asset unavailable'));
    if(failure==='supported')h.C.groundSupported=false;if(failure==='materials')h.C.groundMaterials=false;
    const ctl=h.mount();assert.equal(await ctl.setEnabled(true),false);assert.equal(ctl.isActive(),false);assert.equal(h.host.dataset.flGlobeStatus,'error');assert.equal(h.interactions.items[0].getActive(),true);assert.equal(h.writes,0);assert.ok(h.made.viewers.every(v=>v.destroyed));h.cleanup();
  }
});

test('ground batches are destroyed on refresh, off, dispose and failed refresh',async()=>{
  for(const end of ['off','dispose','error']){
    const f=new Feature('surface-ground','Polygon',[[[0,-80],[10,-80],[0,-85],[0,-80]]]),layer=new Layer('antarctic-drainage-basins',[f],()=>style({area:fill('#abcdef')})),h=harness({layers:[layer]}),ctl=h.mount();
    await ctl.setEnabled(true);const v=h.made.viewers[0],oldGroup=v.scene.primitives.items[0],oldGround=oldGroup.items.at(-1);assert.ok(oldGround instanceof h.C.GroundPrimitive);
    ctl.refresh();await ctl.whenComplete();assert.equal(oldGroup.destroyed,true);assert.equal(oldGround.destroyed,true);assert.equal(v.scene.primitives.items.length,1);
    const current=v.scene.primitives.items[0],ground=current.items.at(-1);
    if(end==='off')await ctl.setEnabled(false);else if(end==='dispose')ctl.dispose();else{layer.fn=()=>{throw Error('style failure');};ctl.refresh();await ctl.whenComplete();}
    assert.equal(current.destroyed,true);assert.equal(ground.destroyed,true);assert.equal(v.destroyed,true);assert.equal(ctl.isActive(),false);assert.equal(h.interactions.items[0].active,true);h.cleanup();
  }
});

test('ground batch partial construction failure destroys its only owner',()=>{
  const h=harness(),made=[],Original=h.C.GroundPrimitive;h.C.GroundPrimitive=class extends Original{constructor(o){super(o);made.push(this);}};
  const row={feature:new Feature('owned'),featureId:'owned',layerId:'basin',kind:'reference',opacity:1,style:style({area:fill('#abc')}),fills:true,geometry:{points:[],lines:[],polygons:[[[[0,-80],[1,-80],[0,-81],[0,-80]]]]}};
  assert.throws(()=>h.api.testing.createBatches(h.C,{primitives:{add(){throw Error('collection add failure');}}},{rows:[row]},h.doc),/collection add failure/);
  assert.equal(made.length,1);assert.equal(made[0].destroyed,true);h.cleanup();
});

test('ground metadata is not fetched after cancelled deferred engine load',async()=>{
  const h=harness({withCesium:false,autoLoad:false}),ctl=h.mount(),pending=ctl.setEnabled(true);await ctl.setEnabled(false);h.finishLoad();assert.equal(await pending,false);assert.equal(h.made.groundInit||0,0);assert.equal(h.made.viewers.length,0);h.cleanup();
});

const globeStatus = h => h.shell.children.find(n=>n.classList.contains('fl-globe-toolbar')).children.find(n=>n.classList.contains('fl-globe-status'));
test('quiet ready status retains truthful loading, pending, failure and retry feedback without resnapshot',async()=>{
 const h=harness({nasa:true,layers:[new Layer('frozen-observations',[new Feature('obs')]),new Layer('quantarctica-fallback',[new Feature('land','Polygon',[[[0,-80],[1,-80],[1,-81],[0,-80]]])],()=>style({area:fill('#ffffff')}))]}),ctl=h.mount(),opening=ctl.setEnabled(true);
 assert.match(globeStatus(h).textContent,/Loading 3D globe/);await opening;
 assert.match(globeStatus(h).textContent,/NASA imagery loading/);assert.doesNotMatch(globeStatus(h).textContent,/3D globe/);
 await ctl.whenComplete();assert.equal(h.host.dataset.flGlobeUpdates,'1','no redundant setup timer');
 const v=h.made.viewers[0],progress=v.scene.globe.tileLoadProgressEvent;
 for(let n=10;n>0;n--)progress.raise(n);assert.equal(h.host.dataset.flGlobeImagery,'loading');
 v.scene.globe.tilesLoaded=true;progress.raise(0);await ctl.whenComplete();
 assert.equal(globeStatus(h).textContent,'');assert.equal(h.host.dataset.flGlobeImageryTilesReady,'true');assert.equal(h.host.dataset.flGlobeUpdates,'1');assert.equal(h.host.dataset.flGlobeSnapshotCount,'1');
 const transforms=h.transforms;for(let i=0;i<20;i++){progress.raise(4);assert.match(globeStatus(h).textContent,/NASA tiles loading/);assert.equal(h.host.dataset.flGlobeImageryTilesReady,'false');assert.equal(h.host.dataset.flGlobeImageryPending,'4');progress.raise(0);}
 for(const fn of h.imageryListeners)fn({enabled:true,pending:99});await ctl.whenComplete();
 assert.equal(h.host.dataset.flGlobeUpdates,'1');assert.equal(h.transforms,transforms);
 h.made.providers[0].errorEvent.raise({});assert.match(globeStatus(h).textContent,/unavailable/);await ctl.whenComplete();
 assert.equal(h.host.dataset.flGlobeUpdates,'2');assert.equal(h.host.dataset.flGlobeSnapshotCount,'1');
 const retry=h.shell.children.find(n=>n.classList.contains('fl-globe-toolbar')).children.find(n=>n.classList.contains('fl-globe-retry'));
 assert.equal(retry.hidden,false);retry.dispatchEvent('click');assert.match(globeStatus(h).textContent,/loading/);assert.equal(h.made.providers.length,2);
 h.cleanup();
});
test('warm CPU snapshot reuses projection; inactive changes and view resolution invalidate safely',async()=>{
 const h=harness(),ctl=h.mount();await ctl.setEnabled(true);const first=h.transforms;
 await ctl.setEnabled(false);await ctl.setEnabled(true);assert.equal(h.transforms,first);assert.equal(h.host.dataset.flGlobeSnapshotReused,'true');assert.equal(h.scriptLoads,1);
 await ctl.setEnabled(false);h.features[0].geometry.coordinates=[30,-80];h.list.items[0].source.dispatchEvent('change');await ctl.setEnabled(true);
 assert.equal(h.host.dataset.flGlobeSnapshotCount,'2');assert.ok(h.transforms>first);
 await ctl.setEnabled(false);h.camera.resolution=2500;await ctl.setEnabled(true);assert.equal(h.host.dataset.flGlobeSnapshotCount,'3');
 assert.equal(h.made.viewers.filter(v=>!v.destroyed).length,1);h.cleanup();assert.ok(h.made.viewers.every(v=>v.destroyed));
});
test('geometry, style, filter, layer properties and unknown invalidation coalesce; replaced sources detach',async()=>{
 const h=harness(),ctl=h.mount();await ctl.setEnabled(true);const layer=h.list.items[0],old=layer.source;
 h.features[0].geometry.coordinates=[40,-75];layer.fn=()=>style({point:circle('#ff0000')});
 for(let i=0;i<12;i++){old.dispatchEvent('change');layer.dispatchEvent('propertychange');h.doc.dispatchEvent('fl-image-scope-filter-change');for(const fn of h.storeListeners)fn({unknown:true});}
 await ctl.whenComplete();assert.equal(h.host.dataset.flGlobeSnapshotCount,'2');assert.equal(h.host.dataset.flGlobeUpdates,'2');
 const point=h.made.viewers[0].scene.primitives.items[0].items[0].items[0];assert.equal(point.position.lon,40);assert.equal(point.color.css,'#ff0000');assert.equal(point.id.feature,h.features[0]);
 layer.source=new Events();layer.features=[new Feature('new')];layer.source.getFeatures=()=>layer.features;layer.dispatchEvent('change:source');await ctl.whenComplete();assert.equal(old.count(),0);
 const before=h.host.dataset.flGlobeUpdates;old.dispatchEvent('change');await ctl.whenComplete();assert.equal(h.host.dataset.flGlobeUpdates,before);
 h.features[0].hidden=true;layer.features[0].hidden=true;h.doc.dispatchEvent('fl-map-visibility-change');await ctl.whenComplete();assert.equal(JSON.parse(h.host.dataset.flGlobePrimitiveCounts).points,0);
 h.list.items=[];h.list.dispatchEvent('remove');await ctl.whenComplete();assert.equal(layer.source.count(),0);assert.deepEqual(JSON.parse(h.host.dataset.flGlobeFeatureCounts),{});h.cleanup();
});
function geometricCamera(C,height=11000000,target={}) {
 const R=6378137,camera=Object.assign(target,{positionWC:new Vector(0,0,R+height),directionWC:new Vector(0,0,-1),upWC:new Vector(0,1,0),positionCartographic:{height},cancelFlight(){this.cancelled=(this.cancelled||0)+1;}});
 camera.setView=({destination,orientation})=>{camera.positionWC=destination;camera.positionCartographic.height=Math.hypot(destination.x,destination.y,destination.z)-R;camera.orientation=orientation;};
 camera.worldToCameraCoordinatesVector=(v,r)=>{camera.referenceConversions=(camera.referenceConversions||0)+1;return Object.assign(r,v);};
 camera.move=(direction,distance)=>{camera.positionWC=Vector.add(camera.positionWC,Vector.multiplyByScalar(direction,distance,new Vector()),new Vector());camera.positionCartographic.height=Vector.magnitude(camera.positionWC)-R;};
 camera.pickEllipsoid=p=>{
  const d=new Vector((p.x-400)/1000,(p.y-300)/1000,-1),o=camera.positionWC;
  const a=d.x*d.x+d.y*d.y+d.z*d.z,b=2*(o.x*d.x+o.y*d.y+o.z*d.z),c=o.x*o.x+o.y*o.y+o.z*o.z-R*R,disc=b*b-4*a*c;
  if(disc<0)return undefined;const t=(-b-Math.sqrt(disc))/(2*a);if(t<0)return undefined;
  return new Vector(o.x+d.x*t,o.y+d.y*t,o.z+d.z*t);
 };return camera;
}
test('picked-ray wheel zoom preserves perspective anchor, orientation and ellipsoid height limits',()=>{
 const h=harness(),T=h.api.testing,camera=geometricCamera(h.C),pixel={x:520,y:350},anchor=camera.pickEllipsoid(pixel);
 assert.ok(anchor);const project=()=>[(anchor.x-camera.positionWC.x)/(anchor.z-camera.positionWC.z),(anchor.y-camera.positionWC.y)/(anchor.z-camera.positionWC.z)];const expected=project();
 for(const delta of [-40,-120,-10000,120,10000]){assert.equal(T.anchoredZoom(h.C,camera,pixel,delta),true);const hgt=camera.positionCartographic.height;assert.ok(hgt>=1000&&hgt<=40000000);project().forEach((v,i)=>assert.ok(Math.abs(v-expected[i])<1e-9));assert.deepEqual(plain(camera.directionWC),{x:0,y:0,z:-1});assert.deepEqual(plain(camera.upWC),{x:0,y:1,z:0});}
 const outside=geometricCamera(h.C),initial=outside.positionWC.z;outside.pickEllipsoid=()=>undefined;
 assert.equal(T.anchoredZoom(h.C,outside,pixel,-120),true);assert.ok(outside.positionWC.z<initial);assert.equal(outside.positionWC.x,0,'off-globe fallback follows camera direction');h.cleanup();
});
test('wheel delta modes are normalized and bounded, invalid input is ignored',()=>{
 const h=harness(),norm=h.api.testing.wheelPixels;
 assert.equal(norm({deltaMode:0,deltaY:1},600),1);assert.equal(norm({deltaMode:1,deltaY:1},600),16);
 assert.equal(norm({deltaMode:2,deltaY:-1},600),-120);assert.equal(norm({deltaY:999999},600),120);assert.equal(norm({deltaY:NaN},600),0);h.cleanup();
});
test('single wheel owner preserves native touch/drag; smoothing, cancel and OFF clean up all inputs',async()=>{
 const h=harness(),ctl=h.mount();await ctl.setEnabled(true);const v=h.made.viewers[0],inputs=v.scene.screenSpaceCameraController,canvas=v.scene.canvas;
 assert.deepEqual(plain(inputs.zoomEventTypes),[1,4]);assert.equal(inputs.minimumZoomDistance,1000);assert.equal(inputs.maximumZoomDistance,40000000);assert.ok(inputs.maximumTiltAngle<Math.PI/2);assert.ok(inputs.inertiaSpin<0.9);
 const current=v,target=canvas,navCamera=geometricCamera(h.C,11000000,v.camera);
 const z=navCamera.positionWC.z;let prevented=0;
 target.dispatchEvent({type:'wheel',deltaMode:2,deltaY:-1,clientX:420,clientY:340,preventDefault(){prevented++;}});
 assert.equal(prevented,1);assert.equal(navCamera.positionWC.z,z,'movement is smoothed, not an immediate page jump');await wait(35);assert.ok(navCamera.positionWC.z<z);assert.equal(h.writes,0);
 target.dispatchEvent('pointerdown');const stopped=navCamera.positionWC.z;await wait(50);assert.equal(navCamera.positionWC.z,stopped);
 target.dispatchEvent({type:'wheel',deltaY:120,clientX:420,clientY:340,preventDefault(){prevented++;}});await ctl.setEnabled(false);const off=navCamera.positionWC.z;await wait(40);assert.equal(navCamera.positionWC.z,off);assert.equal(target.count(),0);assert.deepEqual(plain(current.scene.screenSpaceCameraController.zoomEventTypes),[1,3,4]);assert.equal(current.destroyed,true);assert.equal(canvas.count(),0);assert.equal(h.writes,0);h.cleanup();
});
test('wheel pending work cannot survive tab hiding, context loss or dispose across repeat visits',async()=>{
 for(const exit of ['hide','loss','dispose']){
  const h=harness(),ctl=h.mount();await ctl.setEnabled(true);const v=h.made.viewers[0];
  v.scene.canvas.dispatchEvent({type:'wheel',deltaY:-100,clientX:420,clientY:340,preventDefault(){}});
  if(exit==='hide'){h.doc.hidden=true;h.doc.dispatchEvent('visibilitychange');}
  else if(exit==='loss')v.scene.canvas.dispatchEvent({type:'webglcontextlost',preventDefault(){}});else ctl.dispose();
  await wait(40);assert.equal(ctl.isActive(),false);assert.equal(v.destroyed,true);assert.equal(v.scene.canvas.count(),0);assert.equal(v.scene.postRender.listeners.size,0);assert.equal(h.timerCount,0);
  if(exit!=='dispose'){h.doc.hidden=false;await ctl.setEnabled(true);assert.equal(h.made.viewers.filter(x=>!x.destroyed).length,1);}h.cleanup();assert.ok(h.made.viewers.every(x=>x.destroyed));
 }
});
test('NASA status transitions without fallback land never rebuild any scientific primitives',async()=>{
 const h=harness({nasa:true}),ctl=h.mount();await ctl.setEnabled(true);const v=h.made.viewers[0],transforms=h.transforms;
 v.scene.globe.tileLoadProgressEvent.raise(1);v.scene.globe.tilesLoaded=true;
 for(let i=0;i<20;i++)v.scene.globe.tileLoadProgressEvent.raise(0);h.imagery.setEnabled(false);await ctl.whenComplete();
 assert.equal(h.host.dataset.flGlobeUpdates,'1');assert.equal(h.transforms,transforms);h.cleanup();
});
test('replacing nested layer collections rebinds future properties and detaches old layers',async()=>{
 const a=new Layer('riggs-reference-stations',[new Feature('old')]),b=new Layer('riggs-reference-stations',[new Feature('new')]);
 const group=new Events();let children=new Collection([a]);group.getLayers=()=>children;group.getVisible=()=>true;
 const h=harness({layers:[group]}),ctl=h.mount();await ctl.setEnabled(true);children=new Collection([b]);group.dispatchEvent('change:layers');await ctl.whenComplete();
 assert.equal(a.count(),0);assert.equal(a.source.count(),0);assert.equal(JSON.parse(h.host.dataset.flGlobeFeatureCounts)['riggs-reference-stations'],1);
 b.visible=false;b.dispatchEvent('propertychange');await ctl.whenComplete();assert.equal(JSON.parse(h.host.dataset.flGlobePrimitiveCounts).points,0);h.cleanup();assert.equal(b.count(),0);
});
test('oversized CPU snapshots render every feature but are not retained for repeat visits',async()=>{
 const features=Array.from({length:50001},(_,i)=>new Feature(String(i))),h=harness({features}),ctl=h.mount();await ctl.setEnabled(true);
 assert.equal(JSON.parse(h.host.dataset.flGlobePrimitiveCounts).points,50001);await ctl.setEnabled(false);await ctl.setEnabled(true);
 assert.equal(h.host.dataset.flGlobeSnapshotReused,'false');assert.equal(h.host.dataset.flGlobeSnapshotCount,'2');assert.equal(JSON.parse(h.host.dataset.flGlobePrimitiveCounts).points,50001);h.cleanup();
});
test('transient ready then OFF cancels a no-op policy rebuild; unknown false notifications invalidate',async()=>{
 const layer=new Layer('quantarctica-fallback',[new Feature('land')]),h=harness({layers:[layer],nasa:true}),ctl=h.mount();await ctl.setEnabled(true);const v=h.made.viewers[0];
 v.scene.globe.tileLoadProgressEvent.raise(1);v.scene.globe.tilesLoaded=true;v.scene.globe.tileLoadProgressEvent.raise(0);h.imagery.setEnabled(false);await ctl.whenComplete();assert.equal(h.host.dataset.flGlobeUpdates,'1');
 for(const fn of h.storeListeners)fn(false);await ctl.whenComplete();assert.equal(h.host.dataset.flGlobeSnapshotCount,'2');h.cleanup();
});
test('warm snapshot retains actual polar stereographic coordinates, scientific values and identity',async()=>{
 const projection=require('./fixtures/globe_projection.cjs'),expected=[-55.377,-78.905],xy=projection.forward(expected),feature=new Feature('projected','Point',xy,{thickness:1345.6});
 const h=harness({features:[feature]});let transforms=0;h.context.ol.proj.transform=(p,from,to)=>{assert.equal(from,'EPSG:3031');assert.equal(to,'EPSG:4326');transforms++;return projection.inverse(p);};
 const before=JSON.stringify(feature.getProperties()),ctl=h.mount();await ctl.setEnabled(true);
 const point=()=>h.made.viewers.at(-1).scene.primitives.items[0].items[0].items[0];
 assert.ok(Math.abs(point().position.lon-expected[0])<1e-8);assert.ok(Math.abs(point().position.lat-expected[1])<1e-8);assert.equal(point().id.feature,feature);
 await ctl.setEnabled(false);await ctl.setEnabled(true);assert.equal(transforms,1);assert.equal(point().id.feature,feature);assert.equal(JSON.stringify(feature.getProperties()),before);h.cleanup();
});


test('anchored wheel translates through camera reference frame without an HPR orientation round trip',()=>{
 const h=harness(),camera=geometricCamera(h.C);camera.setView=()=>{throw Error('setView must not rotate near-nadir basis');};
 assert.equal(h.api.testing.anchoredZoom(h.C,camera,{x:520,y:350},-120),true);
 assert.equal(camera.referenceConversions,1);assert.deepEqual(plain(camera.directionWC),{x:0,y:0,z:-1});assert.deepEqual(plain(camera.upWC),{x:0,y:1,z:0});h.cleanup();
});

test('NASA loading keeps context outlines and basin fills; ready reuses batches and failure/OFF restore fallback',async()=>{
 const polygon=new Feature('land','Polygon',fixtures.holes.coordinates),land=new Layer('quantarctica-fallback',[polygon],()=>style({area:fill('white'),line:stroke()}));
 const basin=new Layer('antarctic-drainage-basins',[new Feature('basin','Polygon',fixtures.holes.coordinates)],()=>style({area:fill('rgba(0,0,0,0.035)'),line:stroke()}));
 const h=harness({layers:[land,basin],nasa:true}),ctl=h.mount();await ctl.setEnabled(true);const v=h.made.viewers[0];
 const counts=()=>JSON.parse(h.host.dataset.flGlobePrimitiveCounts),initial=counts(),transforms=h.transforms;
 assert.equal(initial.polygons,1);assert.equal(initial.lines,4);assert.deepEqual(JSON.parse(h.host.dataset.flGlobeFeatureCounts),{'quantarctica-fallback':1,'antarctic-drainage-basins':1});
 v.scene.globe.tileLoadProgressEvent.raise(1);v.scene.globe.tilesLoaded=true;for(let i=0;i<10;i++)v.scene.globe.tileLoadProgressEvent.raise(0);await ctl.whenComplete();
 assert.equal(h.host.dataset.flGlobeUpdates,'1');assert.equal(h.transforms,transforms);assert.deepEqual(counts(),initial);
 h.made.providers[0].errorEvent.raise({});await ctl.whenComplete();assert.equal(counts().polygons,2);assert.equal(counts().lines,initial.lines);assert.equal(h.host.dataset.flGlobeSnapshotReused,'true');assert.equal(h.transforms,transforms);
 h.imagery.setEnabled(false);await ctl.whenComplete();assert.equal(h.host.dataset.flGlobeUpdates,'2');
 h.imagery.setEnabled(true);await ctl.whenComplete();assert.equal(counts().polygons,1);assert.equal(counts().lines,initial.lines);
 h.imagery.setEnabled(false);await ctl.whenComplete();assert.equal(counts().polygons,2);assert.equal(counts().lines,initial.lines);assert.equal(h.transforms,transforms);h.cleanup();
});


test('saved world pose restores through the current reference frame without direction/up HPR conversion',()=>{
 const h=harness(),saved={destination:new Vector(1,2,3),orientation:{direction:new Vector(0,0,-1),up:new Vector(1,0,0)}};
 let calls=0;const camera={direction:new Vector(),up:new Vector(),right:new Vector(),
  setView(options){calls++;assert.deepEqual(Object.keys(options),['destination']);assert.equal(options.destination,saved.destination);},
  worldToCameraCoordinatesVector(v,r){return Object.assign(r,{x:v.y,y:-v.x,z:v.z});}
 };
 const before=JSON.stringify(saved);h.api.testing.restoreCamera(h.C,camera,saved);
 assert.equal(calls,1);assert.equal(Vector.magnitude(Vector.subtract(camera.direction,new Vector(0,0,-1),new Vector())),0);assert.equal(Vector.magnitude(Vector.subtract(camera.up,new Vector(0,-1,0),new Vector())),0);assert.equal(Vector.magnitude(Vector.subtract(camera.right,new Vector(-1,0,0),new Vector())),0);assert.equal(JSON.stringify(saved),before);h.cleanup();
});
