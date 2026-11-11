'use strict';
// Offline public Cesium 1.147 collection ownership and quality/camera checks.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const [sdk,core]=process.argv.slice(2),bytes=fs.readFileSync(sdk);
assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'),'ca180396f07e0c96f5f53b4d18d95ffab7a8a2b5cc115aa9a6fe7037a043c2c7');
const domTypes=Object.fromEntries(['HTMLCanvasElement','HTMLImageElement','HTMLVideoElement','ImageBitmap','OffscreenCanvas'].map(name=>[name,class{}]));
const box={...domTypes,...require('stream/web'),console,setTimeout,clearTimeout,URL,Blob,TextDecoder,TextEncoder,performance,atob,btoa};box.global=box;vm.createContext(box);vm.runInContext(bytes.toString(),box);const C=box.Cesium,T=require(core).testing;
const group=new C.PrimitiveCollection(),roots=Array.from({length:5},()=>group.add(new C.PrimitiveCollection()));
const stage=new C.PrimitiveCollection(),points=stage.add(new C.PointPrimitiveCollection()),lines=stage.add(new C.PolylineCollection()),labels=stage.add(new C.LabelCollection()),shapes=stage.add(new C.BillboardCollection());
const feature={id:'original'};points.add({position:C.Cartesian3.fromDegrees(20,-80),id:feature});
for(let i=0;i<2;i++)lines.add({positions:[C.Cartesian3.fromDegrees(20,-80),C.Cartesian3.fromDegrees(21,-81)],material:C.Material.fromType('Color',{color:C.Color.RED}),id:feature});
assert.notEqual(lines.get(0).material,lines.get(1).material);
stage.destroyPrimitives=false;let kind=0;while(stage.length){const child=stage.get(0);stage.remove(child);roots[kind++].add(child);}stage.destroyPrimitives=true;stage.destroy();
assert.equal(points.isDestroyed(),false);assert.equal(lines.get(0).id,feature);group.destroy();assert.equal(points.isDestroyed(),true);assert.equal(lines.isDestroyed(),true);assert.equal(labels.isDestroyed(),true);assert.equal(shapes.isDestroyed(),true);
const scene={canvas:{clientWidth:1334,clientHeight:1022},drawingBufferWidth:1334,drawingBufferHeight:1022,mapProjection:new C.GeographicProjection(),mode:C.SceneMode.SCENE3D,mapMode2D:C.MapMode2D.ROTATE};
const camera=new C.Camera(scene);scene.camera=camera;camera.update(C.SceneMode.SCENE3D);camera.setView({destination:C.Cartesian3.fromDegrees(-45,-90,15000000),orientation:{heading:0,pitch:-Math.PI/2,roll:0}});
const pixel=new C.Cartesian2(566.377,420.395),anchor=camera.pickEllipsoid(pixel,C.Ellipsoid.WGS84),start={destination:C.Cartesian3.clone(camera.positionWC),orientation:{direction:C.Cartesian3.clone(camera.directionWC),up:C.Cartesian3.clone(camera.upWC)}};
const project=p=>{const matrix=C.Matrix4.multiply(camera.frustum.projectionMatrix,camera.viewMatrix,new C.Matrix4()),clip=C.Matrix4.multiplyByVector(matrix,new C.Cartesian4(p.x,p.y,p.z,1),new C.Cartesian4());return [(clip.x/clip.w+1)*1334/2,(1-clip.y/clip.w)*1022/2];};
const initial=project(anchor),rows=[];
for(const dpr of [1,1.5,2,3])for(const idle of [false,true]){
 const scale=T.qualityScale(1334,1022,dpr,idle);scene.drawingBufferWidth=Math.round(1334*scale);scene.drawingBufferHeight=Math.round(1022*scale);
 assert.equal(C.Cartesian3.distance(start.destination,camera.positionWC),0);assert.equal(C.Cartesian3.distance(start.orientation.direction,camera.directionWC),0);
 T.anchoredZoom(C,camera,pixel,-20);const moved=project(anchor);assert.ok(Math.hypot(moved[0]-initial[0],moved[1]-initial[1])<1e-7);
 T.restoreCamera(C,camera,start);assert.ok(C.Cartesian3.distance(start.destination,camera.positionWC)<1e-7);assert.ok(C.Cartesian3.distance(start.orientation.direction,camera.directionWC)<1e-12);rows.push({dpr,idle,scale,pixelError:Math.hypot(moved[0]-initial[0],moved[1]-initial[1])});
}
// Execute the real public Widget.resize path with integer canvas attributes.
box.window={devicePixelRatio:1};const canvas={clientWidth:1334,clientHeight:1022};let w=1334,h=1022;
Object.defineProperties(canvas,{width:{get:()=>w,set:v=>{w=Math.trunc(v);}},height:{get:()=>h,set:v=>{h=Math.trunc(v);}}});
const widget=Object.create(C.CesiumWidget.prototype);Object.assign(widget,{_canvas:canvas,_useBrowserRecommendedResolution:true,_resolutionScale:1.25,_forceResize:true,_scene:{camera,requestRender(){}}});
T.restoreCamera(C,camera,start);camera.frustum.aspectRatio=1334/1022;const cssPixel=project(anchor);widget.resize();const roundedPixel=project(anchor);assert.notEqual(camera.frustum.aspectRatio,1334/1022);const roundingDrift=Math.hypot(cssPixel[0]-roundedPixel[0],cssPixel[1]-roundedPixel[1]);assert.ok(roundingDrift>0.001);
T.preserveClientAspect(camera,canvas);const restoredPixel=project(anchor);const correctedDrift=Math.hypot(cssPixel[0]-restoredPixel[0],cssPixel[1]-restoredPixel[1]);assert.ok(correctedDrift<1e-9);
console.log(JSON.stringify({sdk:C.VERSION,collectionOwnership:'pass; transferred collections destroyed once, distinct per-line materials',cameraQualityCases:rows.length,widgetResizeCases:1,roundingDrift,correctedDrift,rows,noGPU:true},null,2));
