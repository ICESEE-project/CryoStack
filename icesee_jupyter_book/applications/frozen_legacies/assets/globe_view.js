/* Optional, display-only WGS84 globe. No data fetches, projection writes or Ion.
 * Root integration is separate: see INTEGRATION.md. Cesium is loaded only by
 * setEnabled(true), never by script evaluation or mount(). */
(function (root) {
  'use strict';
  const BASE = 'https://cdn.jsdelivr.net/npm/cesium@1.147.0/Build/Cesium/';
  const CONTRACT = Object.freeze({
    base: BASE, version: '1.147',
    scriptIntegrity: 'sha256-yhgDlvB+DJb19TtNGNlf+reoorXMEVqppv5wN6BDwsc=',
    cssIntegrity: 'sha256-cCxa3z0W7H8cA8xft+y4I69sWfoZJ4n7LIWax6EfSgw=',
    nasaUrl: 'https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/BlueMarble_ShadedRelief_Bathymetry/default/{TileMatrixSet}/{TileMatrix}/{TileRow}/{TileCol}.jpeg',
    credit: 'NASA GIBS · Blue Marble Shaded Relief and Bathymetry (MODIS)'
  });
  const controllers = new WeakMap();
  let libraryPromise = null;
  const validVersion = C => /^1\.147(?:\.0)?$/.test(String(C?.VERSION));

  function loadCesium(documentRef = root.document) {
    if (libraryPromise) return libraryPromise;
    libraryPromise = new Promise((resolve, reject) => {
      if (root.Cesium && !validVersion(root.Cesium)) {
        reject(new Error('Unexpected Cesium version')); return;
      }
      // Even an existing matching global is not proof of pinned script/CSS.
      // Load the reviewed pair once; retry also repairs a failed stylesheet.
      root.CESIUM_BASE_URL = BASE;
      const script = documentRef.createElement('script'), css = documentRef.createElement('link');
      script.src = BASE + 'Cesium.js'; script.integrity = CONTRACT.scriptIntegrity;
      css.rel = 'stylesheet'; css.href = BASE + 'Widgets/widgets.css'; css.integrity = CONTRACT.cssIntegrity;
      for (const node of [script, css]) { node.crossOrigin = 'anonymous'; node.referrerPolicy = 'no-referrer'; }
      let jsReady = false, cssReady = false, settled = false;
      const timer = root.setTimeout(() => fail(), 25000);
      function cleanup() { root.clearTimeout(timer); script.onload = script.onerror = css.onload = css.onerror = null; }
      function fail() {
        if (settled) return;
        settled = true; cleanup(); script.remove(); css.remove();
        reject(new Error('Globe resources unavailable'));
      }
      function finish() {
        if (settled || !jsReady || !cssReady) return;
        if (!validVersion(root.Cesium)) { fail(); return; }
        settled = true; cleanup(); resolve(root.Cesium);
      }
      script.onload = () => { jsReady = true; finish(); }; css.onload = () => { cssReady = true; finish(); };
      script.onerror = css.onerror = fail;
      documentRef.head.append(css, script);
    }).catch(error => { libraryPromise = null; throw error; });
    return libraryPromise;
  }

  function viewerOptions(C) {
    return {baseLayer: false, baseLayerPicker: false,
      terrainProvider: new C.EllipsoidTerrainProvider({ellipsoid: C.Ellipsoid.WGS84}),
      sceneMode: C.SceneMode.SCENE3D, scene3DOnly: true, geocoder: false,
      animation: false, timeline: false, sceneModePicker: false, navigationHelpButton: false,
      homeButton: false, fullscreenButton: false, infoBox: false, selectionIndicator: false,
      skyBox: false, shadows: false, requestRenderMode: true, maximumRenderTimeChange: Infinity,
      useBrowserRecommendedResolution: true, automaticallyTrackDataSourceClocks: false};
  }
  function nasaOptions(C) {
    return {url: new C.Resource({url: CONTRACT.nasaUrl, headers: {}}),
      layer: 'BlueMarble_ShadedRelief_Bathymetry', style: 'default', format: 'image/jpeg',
      tileMatrixSetID: '500m', tileMatrixLabels: ['3', '4', '5', '6', '7'],
      tilingScheme: new C.GeographicTilingScheme({numberOfLevelZeroTilesX: 10,
        numberOfLevelZeroTilesY: 5, rectangle: C.Rectangle.MAX_VALUE}),
      tileWidth: 512, tileHeight: 512, minimumLevel: 0, maximumLevel: 4,
      enablePickFeatures: false, credit: CONTRACT.credit};
  }

  // Every transform receives a fresh coordinate. No transformed geometry or
  // source values are ever written back. Densify in the source projection so
  // polar straight segments/rings do not turn into invented geodesic chords.
  // Read only public OL arrays; no source coordinates are mutated. Real OL
  // getCoordinates()/clone() copies an entire long geometry synchronously.
  function* readCoordinates(g) {
    const type = g.getType();
    if (type === 'Circle' || type === 'GeometryCollection') return null;
    const flat = g.getFlatCoordinates?.();
    if (!flat) return g.getCoordinates?.(); // small compatibility adapters
    const stride = g.getStride(), point = i => [flat[i], flat[i + 1]];
    if (type === 'Point') return point(0);
    function* ring(start, end) { const out = []; for (let i = start; i < end; i += stride) { out.push(point(i)); yield; } return out; }
    if (type === 'MultiPoint' || type === 'LineString') return yield* ring(0, flat.length);
    let offset = 0;
    function* rings(ends) { const out = []; for (const end of ends) { out.push(yield* ring(offset, end)); offset = end; yield; } return out; }
    if (type === 'Polygon' || type === 'MultiLineString') return yield* rings(g.getEnds());
    if (type === 'MultiPolygon') { const out = []; for (const ends of g.getEndss()) { out.push(yield* rings(ends)); yield; } return out; }
    return null;
  }
  function drain(iterator) { let next; do { next = iterator.next(); } while (!next.done); return next.value; }
  function convertGeometry(geometry, transform) { return drain(convertGeometrySteps(geometry, transform)); }
  function* convertGeometrySteps(geometry, transform) {
    if (!geometry) return null;
    const g = geometry, type = g.getType();
    const ll = p => {
      if (!Array.isArray(p) || !p.slice(0, 2).every(Number.isFinite)) return null;
      const q = transform(p.slice(0, 2));
      if (!q || !q.slice(0, 2).every(Number.isFinite) || Math.abs(q[1]) > 90) return null;
      return [((q[0] + 180) % 360 + 360) % 360 - 180, q[1]];
    };
    const sample = function* (coords) {
      const out = [];
      for (let i = 0; i < coords.length; i++) {
        const a = coords[i - 1], b = coords[i];
        if (a && a.slice(0, 2).every(Number.isFinite) && b?.slice(0, 2).every(Number.isFinite)) {
          const n = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / 40000));
          for (let j = 1; j < n; j++) { out.push(ll([a[0] + (b[0] - a[0]) * j / n, a[1] + (b[1] - a[1]) * j / n])); yield; }
        }
        out.push(ll(b)); yield;
      }
      return out;
    };
    const split = function* (points) {
      const paths = []; let path = [];
      const flush = () => { if (path.length > 1) paths.push(path); path = []; };
      for (const b of points) {
        yield;
        if (!b) { flush(); continue; }
        const a = path[path.length - 1];
        if (a && Math.abs(b[0] - a[0]) > 180) {
          const bx = b[0] + (b[0] < a[0] ? 360 : -360), edge = bx > 180 ? 180 : -180;
          const lat = a[1] + (b[1] - a[1]) * (edge - a[0]) / (bx - a[0]);
          path.push([edge, lat]); flush(); path.push([-edge, lat]);
        }
        path.push(b);
      }
      flush(); return paths;
    };
    const polygon = function* (rings) {
      const converted = [];
      for (const ring of rings) converted.push(yield* sample(ring));
      // Invalid navigation must not become a closing chord or lose a hole.
      let valid = !!converted.length;
      for (const ring of converted) { if (ring.length < 4) valid = false; for (const p of ring) { if (!p) valid = false; yield; } }
      return valid ? converted : null;
    };
    const coords = yield* readCoordinates(g);
    const result = {points: [], lines: [], polygons: []};
    if (type === 'Point' || type === 'MultiPoint') {
      for (const p of type === 'Point' ? [coords] : coords) { const q = ll(p); if (q) result.points.push(q); yield; }
      return result;
    }
    if (type === 'LineString' || type === 'MultiLineString') {
      for (const c of type === 'LineString' ? [coords] : coords) {
        const paths = yield* split(yield* sample(c));
        for (const path of paths) { result.lines.push(path); yield; }
      }
      return result;
    }
    if (type === 'Polygon' || type === 'MultiPolygon') {
      for (const rings of type === 'Polygon' ? [coords] : coords) { const p = yield* polygon(rings); if (p) result.polygons.push(p); yield; }
      return result;
    }
    if (type === 'Circle') {
      const c = g.getCenter(), r = g.getRadius(), ring = [];
      for (let i = 0; i <= 240; i++) { const a = i / 240 * Math.PI * 2; ring.push([c[0] + r * Math.cos(a), c[1] + r * Math.sin(a)]); yield; }
      result.lines = yield* split(yield* sample(ring)); return result;
    }
    if (type === 'GeometryCollection') {
      for (const child of g.getGeometriesArray?.() || g.getGeometries()) {
        const row = yield* convertGeometrySteps(child, transform);
        if (row) for (const key of ['points', 'lines', 'polygons']) for (const x of row[key]) { result[key].push(x); yield; }
      }
      return result;
    }
    return null;
  }

  function collectLayers(map) {
    const rows = [];
    const visit = (layer, opacity = 1, visible = true) => {
      opacity *= layer.getOpacity?.() ?? 1; visible = visible && layer.getVisible?.() !== false;
      if (layer.getLayers) layer.getLayers().getArray().forEach(x => visit(x, opacity, visible));
      else rows.push({layer, opacity, visible, order: rows.length});
    };
    map.getLayers().getArray().forEach(x => visit(x));
    return rows.sort((a, b) => (a.layer.getZIndex?.() ?? 0) - (b.layer.getZIndex?.() ?? 0) || a.order - b.order);
  }
  const DYNAMIC_SELECTION = Object.freeze({'frozen-my-picks':'user',
    'frozen-reviewed-results':'reviewed', 'frozen-radar-coverage':'radarCoverage'});
  const FILL_CONTEXT = new Set(['quantarctica-fallback', 'quantarctica-basemap', 'antarctic-land']);
  function renderPolicy(id, imageryState) {
    return {skip: id === 'antarctic-polar-ocean',
      fills: !(FILL_CONTEXT.has(id) && (imageryState === 'loading' || imageryState === 'ready'))};
  }
  const LAYER_PRIORITY = Object.freeze({'frozen-observations':0, 'frozen-my-picks':1,
    'frozen-reviewed-results':2, 'riggs-reference-stations':3, 'frozen-selected-flight':4});
  const layerPriority = id => LAYER_PRIORITY[id] ?? 10;
  function snapshot(context, imageryState) {
    const {app, ol} = context, view = app.map.getView();
    const resolution = view.getResolution(), zoom = view.getZoom?.() ?? 0;
    const mapLayers = collectLayers(app.map), rows = [], counts = {}, seen = new Set();
    let skipped = 0;
    for (const [layerOrder, {layer, opacity, visible}] of mapLayers.entries()) {
      const id = layer.get?.('id') || '', policy = renderPolicy(id, imageryState);
      // The polar ocean disc is presentation only. Raster imagery is provided
      // independently by the exact EPSG4326 WMTS contract.
      if (!visible || !opacity || policy.skip || !layer.getSource?.()?.getFeatures) continue;
      if (resolution < (layer.getMinResolution?.() ?? 0) || resolution >= (layer.getMaxResolution?.() ?? Infinity) ||
          zoom <= (layer.getMinZoom?.() ?? -Infinity) || zoom > (layer.getMaxZoom?.() ?? Infinity)) continue;
      // Unattached antarcticLand is deliberately absent: traverse the map,
      // never the entire bundle or data.full* collections.
      for (const feature of layer.getSource().getFeatures()) {
        const kind = id === 'frozen-observations' ? 'observations' :
          ['frozen-flights', 'frozen-selected-flight'].includes(id) ? 'flights' :
          id === 'antarctic-image-navigation' ? 'coverage' : DYNAMIC_SELECTION[id] || null;
        if (kind && !DYNAMIC_SELECTION[id] && context.visibility?.featureVisible(feature, kind) === false) continue;
        const styleFn = feature.getStyleFunction?.() || layer.getStyleFunction?.();
        const raw = styleFn ? styleFn(feature, resolution) : layer.getStyle?.();
        if (!raw) continue;
        const styles = Array.isArray(raw) ? raw : [raw];
        let included = false;
        for (const [styleOrder, style] of styles.entries()) {
          const geom = style.getGeometryFunction ? style.getGeometryFunction()(feature) : feature.getGeometry();
          if (!geom) continue;
          const converted = convertGeometry(geom, p => ol.proj.transform(p, app.projection, 'EPSG:4326'));
          if (!converted) { skipped++; continue; }
          // Basins keep their supplied translucent fill. Suppress only solid
          // land/shelf fallback fills while NASA loads or is ready, preserving outlines.
          rows.push({feature, featureId: feature.getId?.(), layer, layerId: id, kind, layerOrder, rowOrder:rows.length,
            opacity, style, geometry: converted, fills: policy.fills,
            // Tiny stack offsets preserve OL order between batched primitive
            // kinds; these are display separation, never supplied elevations.
            offset: 200 + layerOrder * 2 + styleOrder * 0.25, fillOffset: 30 + layerOrder * 2});
          included = true;
        }
        if (included) {
          if (!seen.has(layer)) { counts[id || 'reference'] ||= 0; seen.add(layer); }
          counts[id || 'reference']++;
        }
      }
    }
    return {rows, counts, skipped};
  }

  function* describeSnapshot(context, imageryState) {
    const {app, ol} = context, view = app.map.getView();
    const resolution = view.getResolution(), zoom = view.getZoom?.() ?? 0;
    const mapLayers = collectLayers(app.map).map((entry, layerOrder) => ({...entry, layerOrder}))
      .sort((a, b) => layerPriority(a.layer.get?.('id')) - layerPriority(b.layer.get?.('id')) || a.layerOrder - b.layerOrder), rows = [], counts = {}, seen = new Set();
    let skipped = 0;
    for (const {layerOrder, layer, opacity, visible} of mapLayers) {
      const id = layer.get?.('id') || '', policy = renderPolicy(id, imageryState);
      // The polar ocean disc is presentation only. Raster imagery is provided
      // independently by the exact EPSG4326 WMTS contract.
      if (!visible || !opacity || policy.skip || !layer.getSource?.()?.getFeatures) continue;
      if (resolution < (layer.getMinResolution?.() ?? 0) || resolution >= (layer.getMaxResolution?.() ?? Infinity) ||
          zoom <= (layer.getMinZoom?.() ?? -Infinity) || zoom > (layer.getMaxZoom?.() ?? Infinity)) continue;
      // Unattached antarcticLand is deliberately absent: traverse the map,
      // never the entire bundle or data.full* collections.
      for (const feature of layer.getSource().getFeatures()) {
        yield;
        const kind = id === 'frozen-observations' ? 'observations' :
          ['frozen-flights', 'frozen-selected-flight'].includes(id) ? 'flights' :
          id === 'antarctic-image-navigation' ? 'coverage' : DYNAMIC_SELECTION[id] || null;
        if (kind && !DYNAMIC_SELECTION[id] && context.visibility?.featureVisible(feature, kind) === false) continue;
        const styleFn = feature.getStyleFunction?.() || layer.getStyleFunction?.();
        const raw = styleFn ? styleFn(feature, resolution) : layer.getStyle?.();
        if (!raw) continue;
        const styles = Array.isArray(raw) ? raw : [raw];
        let included = false;
        for (const [styleOrder, style] of styles.entries()) {
          const geom = style.getGeometryFunction ? style.getGeometryFunction()(feature) : feature.getGeometry();
          if (!geom) continue;
          const converted = geom; yield;
          if (!converted) { skipped++; continue; }
          // Basins keep their supplied translucent fill. Suppress only solid
          // land/shelf fallback fills while NASA loads or is ready, preserving outlines.
          rows.push({feature, featureId: feature.getId?.(), layer, layerId: id, kind, layerOrder, rowOrder:rows.length,
            opacity, style, geometry: converted, fills: policy.fills,
            // Tiny stack offsets preserve OL order between batched primitive
            // kinds; these are display separation, never supplied elevations.
            offset: 200 + layerOrder * 2 + styleOrder * 0.25, fillOffset: 30 + layerOrder * 2});
          yield rows[rows.length - 1];
          included = true;
        }
        if (included) {
          if (!seen.has(layer)) { counts[id || 'reference'] ||= 0; seen.add(layer); }
          counts[id || 'reference']++;
        }
      }
    }
    return {rows, counts, skipped};
  }

  function color(C, value, opacity = 1) {
    let result;
    if (Array.isArray(value)) result = new C.Color(value[0] / 255, value[1] / 255, value[2] / 255, value[3] ?? 1);
    else result = C.Color.fromCssColorString(String(value || 'transparent'));
    if (!result) throw new Error('Unsupported map color');
    return result.withAlpha(result.alpha * opacity);
  }
  const position = (C, p, offset = 200) => C.Cartesian3.fromDegrees(p[0], p[1], offset);
  function dashMaterial(C, stroke, opacity) {
    const c = color(C, stroke.getColor(), opacity), dash = stroke.getLineDash?.();
    if (!dash?.length) return C.Material.fromType('Color', {color: c});
    const total = dash.reduce((a, b) => a + b, 0); let pattern = 0;
    for (let bit = 0; bit < 16; bit++) {
      let t = (bit + 0.5) / 16 * total, part = 0;
      while (part < dash.length - 1 && t >= dash[part]) { t -= dash[part]; part++; }
      if (part % 2 === 0) pattern |= 1 << bit;
    }
    return C.Material.fromType('PolylineDash', {color: c, gapColor: C.Color.TRANSPARENT,
      dashLength: total, dashPattern: pattern});
  }

  function* batchSteps(C, snap, documentRef, owner) {
    const group = new C.PrimitiveCollection(), points = new C.PointPrimitiveCollection(),
      lines = new C.PolylineCollection(), labels = new C.LabelCollection(), shapes = new C.BillboardCollection();
    if (owner) owner.group = group;
    group.add(points); group.add(lines); group.add(labels); group.add(shapes);
    const polygons = [], shapeCache = new Map(); let pointCount = 0, lineCount = 0, polygonCount = 0, labelCount = 0, billboardCount = 0;
    const positions = function* (path, offset) { const out = []; for (const p of path) { out.push(position(C, p, offset)); yield; } return out; };
    const addLine = function* (path, stroke, row, pick) {
      if (!stroke || path.length < 2) return;
      lines.add({positions: yield* positions(path, row.offset ?? 200), width: stroke.getWidth?.() || 1,
        material: dashMaterial(C, stroke, row.opacity), id: pick}); lineCount++;
    };
    const shapeImage = (image, row) => {
      const n = image.getPoints(), radius = image.getRadius(), angle = image.getAngle?.() || 0;
      const fill = image.getFill?.()?.getColor(), stroke = image.getStroke?.();
      const key = JSON.stringify([n, radius, angle, fill, stroke?.getColor(), row.opacity]);
      if (shapeCache.has(key)) return shapeCache.get(key);
      const canvas = documentRef.createElement('canvas'), size = Math.ceil(radius * 2 + 6);
      canvas.width = canvas.height = size * 2;
      const ctx = canvas.getContext('2d'); ctx.scale(2, 2); ctx.translate(size / 2, size / 2); ctx.beginPath();
      for (let i = 0; i < n; i++) {
        const a = angle - Math.PI / 2 + i * Math.PI * 2 / n;
        const p = [radius * Math.cos(a), radius * Math.sin(a)];
        i ? ctx.lineTo(...p) : ctx.moveTo(...p);
      }
      ctx.closePath();
      if (fill) { ctx.fillStyle = color(C, fill, row.opacity).toCssColorString(); ctx.fill(); }
      if (stroke) { ctx.strokeStyle = color(C, stroke.getColor(), row.opacity).toCssColorString(); ctx.lineWidth = stroke.getWidth?.() || 1; ctx.stroke(); }
      shapeCache.set(key, canvas); return canvas;
    };
    try {
      for (const row of snap.rows) {
        yield;
        const {style, geometry} = row, stroke = style.getStroke?.(), fill = style.getFill?.();
        const image = style.getImage?.(), text = style.getText?.();
        const pick = {flGlobe: true, feature: row.feature, featureId: row.featureId, layerId: row.layerId, kind: row.kind};
        for (const p of geometry.points) {
          yield;
          if (image && image.getOpacity?.() !== 0) {
            const imageOpacity = row.opacity * (image.getOpacity?.() ?? 1);
            if (Number.isFinite(image.getPoints?.())) {
              shapes.add({position: position(C, p, row.offset ?? 200), image: shapeImage(image, row), scale: 0.5, id: pick}); billboardCount++;
            } else {
              points.add({position: position(C, p), pixelSize: (image.getRadius?.() || 4) * 2,
                color: color(C, image.getFill?.()?.getColor(), imageOpacity),
                outlineColor: color(C, image.getStroke?.()?.getColor(), imageOpacity),
                outlineWidth: image.getStroke?.()?.getWidth?.() || 0, id: pick});
            }
            pointCount++;
          }
          if (text?.getText?.()) { labelCount++; labels.add({position: position(C, p), text: String(text.getText()),
            font: text.getFont?.() || '12px sans-serif', fillColor: color(C, text.getFill?.()?.getColor(), row.opacity),
            outlineColor: color(C, text.getStroke?.()?.getColor(), row.opacity),
            outlineWidth: text.getStroke?.()?.getWidth?.() || 0, style: C.LabelStyle.FILL_AND_OUTLINE,
            pixelOffset: new C.Cartesian2(text.getOffsetX?.() || 0, text.getOffsetY?.() || 0), id: pick}); }
        }
        for (const path of geometry.lines) yield* addLine(path, stroke, row, pick);
        for (const rings of geometry.polygons) {
          for (const ring of rings) yield* addLine(ring, stroke, row, pick);
          if (fill && row.fills) {
            const holes = [];
            for (let i = 1; i < rings.length; i++) { holes.push(new C.PolygonHierarchy(yield* positions(rings[i], 0))); yield; }
            const hierarchy = new C.PolygonHierarchy(yield* positions(rings[0], 0), holes);
            polygons.push(new C.GeometryInstance({geometry: new C.PolygonGeometry({polygonHierarchy: hierarchy,
              height: 0, vertexFormat: C.PerInstanceColorAppearance.VERTEX_FORMAT}), id: pick,
              attributes: {color: C.ColorGeometryInstanceAttribute.fromColor(color(C, fill.getColor(), row.opacity))}}));
            polygonCount++;
          }
        }
      }
      // Ground classification drapes fills on the ellipsoid; elevated chord
      // triangles intersected the globe mesh and produced concentric banding.
      if (polygons.length) group.add(new C.GroundPrimitive({geometryInstances: polygons,
        classificationType: C.ClassificationType.TERRAIN,
        appearance: new C.PerInstanceColorAppearance({flat: true, closed: false, translucent: true}), asynchronous: false}));

    } catch (error) { group.destroy(); if (owner) owner.group = null; throw error; }
    return {group, counts: {points: pointCount, lines: lineCount, polygons: polygonCount, labels: labelCount, billboards: billboardCount}};
  }

  // Bound new GPU collection uploads by real geometry/symbol work, retaining
  // contiguous rows. A single oversized row stays intact (dash joins/holes).
  const BATCH_BUDGETS = Object.freeze({rows: 3584, points: 1024, vertices: 8192, glyphs: 4096});
  function planBatches(rows) {
    const chunks = []; let chunk = null;
    for (const row of rows) {
      const {geometry, style} = row, stroke = style.getStroke?.(), fill = style.getFill?.();
      const text = String(style.getText?.()?.getText?.() || '');
      const cost = {rows: 1, points: geometry.points.length, vertices: 0, glyphs: geometry.points.length * text.length};
      if (stroke) for (const path of geometry.lines) cost.vertices += path.length;
      for (const rings of geometry.polygons) for (const ring of rings)
        if (stroke || (fill && row.fills)) cost.vertices += ring.length * (stroke && fill && row.fills ? 2 : 1);
      const oversized = Object.keys(cost).some(key => cost[key] > BATCH_BUDGETS[key]);
      if (chunk && (chunk.layerOrder !== (row.layerOrder ?? 0) || oversized || Object.keys(cost).some(key => chunk.cost[key] + cost[key] > BATCH_BUDGETS[key]))) chunk = null;
      if (!chunk) { chunk = {rows: [], layerOrder:row.layerOrder ?? 0, cost: {rows:0, points:0, vertices:0, glyphs:0}, oversized}; chunks.push(chunk); }
      chunk.rows.push(row); for (const key of Object.keys(cost)) chunk.cost[key] += cost[key];
      if (oversized) chunk = null;
    }
    return chunks;
  }

  function createBatches(C, scene, snap, documentRef) {
    const next = drain(batchSteps(C, snap, documentRef));
    try { scene.primitives.add(next.group); } catch (error) { next.group.destroy(); throw error; }
    return next;
  }
  // Browser-recommended resolution uses CSS pixels. Both active and idle
  // policies bound TOTAL drawing pixels, including large desktop/4k canvases.
  function preserveClientAspect(camera, canvas) {
    const frustum = camera.frustum;
    if (frustum && 'aspectRatio' in frustum && canvas.clientWidth > 0 && canvas.clientHeight > 0)
      frustum.aspectRatio = canvas.clientWidth / canvas.clientHeight;
  }
  function qualityScale(width, height, dpr, idle) {
    if (!(width > 0 && height > 0) || !Number.isFinite(width * height)) return null;
    const density = Number.isFinite(dpr) && dpr > 0 ? dpr : 1;
    return Math.min(idle ? Math.max(density, 1.25) : density, idle ? 1.5 : 1,
      Math.sqrt((idle ? 4500000 : 3000000) / (width * height)));
  }

  const MIN_HEIGHT = 1000, MAX_HEIGHT = 40000000;
  const now = () => root.performance?.now?.() ?? Date.now();
  function wheelPixels(event, pageHeight) {
    const units = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? pageHeight : 1;
    const pixels = event.deltaY * units;
    return Number.isFinite(pixels) ? Math.max(-120, Math.min(120, pixels)) : 0;
  }
  // Translation along the actual picked ray preserves its perspective screen
  // coordinate without rotating the camera or approximating a map projection.
  function anchoredZoom(C, camera, pixel, delta) {
    const anchor = camera.pickEllipsoid(pixel, C.Ellipsoid.WGS84);
    const start = C.Cartesian3.clone(camera.positionWC);
    const ray = anchor ? C.Cartesian3.subtract(anchor, start, new C.Cartesian3()) :
      C.Cartesian3.multiplyByScalar(camera.directionWC, Math.max(MIN_HEIGHT, camera.positionCartographic.height), new C.Cartesian3());
    const amount = 1 - Math.exp(delta * 0.0015);
    const candidate = t => C.Cartesian3.add(start,
      C.Cartesian3.multiplyByScalar(ray, amount * t, new C.Cartesian3()), new C.Cartesian3());
    const height = p => C.Ellipsoid.WGS84.cartesianToCartographic(p)?.height;
    const valid = p => { const h = height(p); return Number.isFinite(h) && h >= MIN_HEIGHT && h <= MAX_HEIGHT; };
    let destination = candidate(1);
    if (!valid(destination)) {
      // Limit on the same ray, preserving the anchor even at either bound.
      if (!valid(start)) return false;
      let low = 0, high = 1;
      for (let i = 0; i < 24; i++) { const mid = (low + high) / 2; if (valid(candidate(mid))) low = mid; else high = mid; }
      destination = candidate(low);
    }
    // setView converts direction/up through HPR and loses near-nadir roll.
    // Move in the current reference frame without changing the camera basis.
    const travel = C.Cartesian3.subtract(destination, start, new C.Cartesian3());
    const distance = C.Cartesian3.magnitude(travel);
    if (distance) camera.move(camera.worldToCameraCoordinatesVector(
      C.Cartesian3.normalize(travel, travel), new C.Cartesian3()), distance);
    return true;
  }

  function restoreCamera(C, camera, saved) {
    // Restore world-space basis directly; setView(direction/up) loses roll
    // through Cesium's near-nadir HPR conversion.
    camera.setView({destination: saved.destination});
    C.Cartesian3.normalize(camera.worldToCameraCoordinatesVector(
      saved.orientation.direction, camera.direction), camera.direction);
    C.Cartesian3.normalize(camera.worldToCameraCoordinatesVector(
      saved.orientation.up, camera.up), camera.up);
    C.Cartesian3.normalize(C.Cartesian3.cross(
      camera.direction, camera.up, camera.right), camera.right);
  }

  function mount(context) {
    const {app, ol, imagery, select} = context;
    if (controllers.has(app?.map)) return controllers.get(app.map);
    if (!app?.map || !ol?.proj?.transform || !imagery?.state || typeof imagery.subscribe !== 'function' ||
        typeof select?.observation !== 'function' || typeof select?.flight !== 'function' || typeof select?.riggs !== 'function' || typeof select?.coverage !== 'function' ||
        Object.values(DYNAMIC_SELECTION).some(key => typeof select?.[key] !== 'function')) {
      throw new Error('Globe requires the real map, shared imagery and selection adapters');
    }
    const doc = context.documentRef || root.document, host = context.host || app.map.getTargetElement();
    const controlsHost = context.controlsHost || host.parentElement;
    const disposers = [], viewerDisposers = [], interactionStates = new Map(), popups = new Map();
    const make = (tag, cls, parent) => { const n = doc.createElement(tag); n.className = cls; parent.append(n); return n; };
    const surface = make('div', 'fl-globe-surface', host); host.prepend(surface); surface.hidden = true;
    surface.setAttribute('aria-label', '3D Antarctic globe');
    const toolbar = make('div', 'fl-globe-toolbar', controlsHost);
    const positionControls = context.positionControls || root.FrozenLegaciesMapExplorer?.positionGlobeControls;
    if (positionControls) disposers.push(positionControls(toolbar, controlsHost, doc));
    const toggle = make('button', 'fl-globe-toggle', toolbar); toggle.type = 'button'; toggle.textContent = '3D globe';
    toggle.setAttribute('aria-pressed', 'false');
    const about = make('details', 'fl-globe-about', toolbar), summary = make('summary', '', about);
    summary.textContent = 'About view';
    const note = make('p', '', about); note.textContent = 'Rotate, tilt and zoom a WGS84 ellipsoid with shaded imagery. No measured terrain elevation is shown. Map data and scientific values are unchanged.';
    const reset = make('button', 'fl-globe-reset', toolbar); reset.type = 'button'; reset.textContent = 'Reset view'; reset.hidden = true;
    const status = make('span', 'fl-globe-status', toolbar); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    const retry = make('button', 'fl-globe-retry', toolbar); retry.type = 'button'; retry.textContent = 'Retry globe'; retry.hidden = true;
    let C, viewer = null, batches = null, desired = false, active = false, disposed = false, epoch = 0;
    let savedCamera = null, snapshotTimer = null, dataDirty = false, updateCount = 0, imageryLayer = null, imageryState = 'off';
    let imageryTimer = null, imageryLoaded = false, pending = 0, imageryFailed = false, imageDisposers = [];
    let priorReadout = null, restoreCapture = null;
    let generation = 0, build = null, completion = Promise.resolve(false), qualityTimer = null;
    let sizeKey = '', dimensionKey = '', qualityMoving = false, qualityInputHeld = false;
    const emptyCounts = () => ({points:0, lines:0, polygons:0, labels:0, billboards:0});
    function cancelBuild() {
      generation++;
      if (build) {
        const old = build; build = null;
        root.clearTimeout(old.timer); old.timer = null; const wake = old.wake; old.wake = null; wake?.(false);
        old.owner.group?.destroy(); old.owner.group = null;
      }
    }
    function retire() {
      if (batches && viewer) viewer.scene.primitives.remove(batches.group);
      batches = null;
      host.dataset.flGlobeComplete = 'false'; host.dataset.flGlobeStage = 'pending';
      host.dataset.flGlobeRenderedPrimitiveCounts = JSON.stringify(emptyCounts());
      host.dataset.flGlobeFeatureCounts = '{}';
      host.dataset.flGlobePrimitiveCounts = JSON.stringify(emptyCounts());
    }
    // One bounded CPU snapshot; no Viewer or GPU resources survive OFF.
    let cachedSnapshot = null, snapshotKey = null, batchPolicy = null, snapshotCount = 0, batchHasContext = false;
    const invalidate = () => { cachedSnapshot = null; snapshotKey = null; };
    const policy = () => imageryState === 'loading' || imageryState === 'ready';
    const readout = context.coordinateReadout || doc.getElementById('fl-map-coordinate');
    const onDOM = (target, type, fn, options, bucket = disposers) => {
      target?.addEventListener(type, fn, options); bucket.push(() => target?.removeEventListener(type, fn, options));
    };
    const onOL = (target, type, fn, bucket = disposers) => {
      if (!target?.on) return;
      target.on(type, fn); bucket.push(() => target.un?.(type, fn));
    };
    const onC = (event, fn, bucket = viewerDisposers) => {
      const remove = event.addEventListener(fn); bucket.push(() => { if (typeof remove === 'function') remove(); else event.removeEventListener(fn); });
    };
    const request = () => { if (viewer && active) viewer.scene.requestRender(); };
    function stateAttrs(state) {
      host.dataset.flActiveView = active && restoreCapture ? '3d' : '2d'; host.dataset.flGlobeStatus = state;
      host.dataset.flCesiumVersion = C?.VERSION || '';
      toggle.setAttribute('aria-pressed', String(desired)); reset.hidden = !active;
      retry.hidden = state !== 'error' && !imageryFailed;
    }
    function schedule() {
      invalidate(); dataDirty = true; cancelQuality(); cancelBuild(); retire();
      if (active) { stateAttrs('loading'); imageryMessage(); request(); }
      queueRefresh();
    }
    function queueRefresh() {
      if (!active || snapshotTimer !== null) return;
      snapshotTimer = root.setTimeout(() => { snapshotTimer = null; refresh(); }, 60);
    }
    function refresh() {
      if (!active || !viewer) return Promise.resolve(false);
      cancelBuild(); retire();
      const localViewer = viewer, token = epoch, serial = generation;
      const job = {timer:null, wake:null, owner:{group:null}, steps:0, slices:0, maxSteps:0,
        maxSlice:0, cpu:0, snapshotCPU:0, batchCPU:0, stageCPU:[], fillPolicy:policy(), started:now()};
      build = job;
      host.dataset.flGlobeQualityReason = 'building';
      cancelQuality(); applyQuality(false);
      const valid = () => build === job && serial === generation && token === epoch &&
        viewer === localViewer && desired && active && !disposed && modeIsMap() && !doc.hidden;
      // A task boundary allows input and browser rendering, unlike a microtask.
      const pause = () => new Promise(resolve => {
        if (!valid()) { resolve(false); return; }
        job.wake = resolve;
        const resume = () => { if (job.wake !== resolve) return; job.timer = null; job.wake = null; resolve(valid()); };
        const fallbackTask = () => { if (job.wake === resolve) job.timer = root.setTimeout(resume, 0); };
        if (typeof root.scheduler?.yield === 'function') {
          try { Promise.resolve(root.scheduler.yield()).then(resume, fallbackTask); }
          catch (_) { fallbackTask(); }
        } else fallbackTask();
      });
      async function run(iterator) {
        while (valid()) {
          const at = now(); let step, count = 0;
          do { step = iterator.next(); count++; } while (!step.done && count < 8192 && (count % 16 !== 0 || now() - at < 5) && valid());
          const elapsed = now() - at;
          job.cpu += elapsed; job.steps += count; job.slices++;
          job.maxSlice = Math.max(job.maxSlice, elapsed); job.maxSteps = Math.max(job.maxSteps, count);
          if (!valid()) { iterator.return?.(); return null; }
          if (step.done) return step.value;
          if (!await pause()) { iterator.return?.(); return null; }
        }
        iterator.return?.(); return null;
      }
      completion = (async () => {
        try {
          root.clearTimeout(snapshotTimer); snapshotTimer = null; dataDirty = false;
          stateAttrs('loading'); imageryMessage();
          host.dataset.flGlobeComplete = 'false'; host.dataset.flGlobeGeneration = String(serial);
          delete host.dataset.flGlobeFirstObservationMs; delete host.dataset.flGlobeFirstPointMs;
          host.dataset.flGlobeStage = 'preparing';
          const key = [app.map.getView().getResolution(), app.map.getView().getZoom?.(), app.projection];
          const reused = cachedSnapshot && snapshotKey?.every((v, i) => v === key[i]);
          function* cachedRows() { for (const row of cachedSnapshot.priorityRows || cachedSnapshot.rows) yield row; }
          const descriptions = reused ? cachedRows() : describeSnapshot(context, 'off');
          let descriptionDone = false, pendingDescriptor = null;
          function* readStage(limit) {
            const out = [];
            if (pendingDescriptor) { out.push(pendingDescriptor); pendingDescriptor = null; }
            while (out.length < limit) {
              const next = descriptions.next();
              if (next.done) { descriptionDone = true; return out; }
              if (next.value) {
                if (out.length && next.value.layerOrder !== out[0].layerOrder) { pendingDescriptor = next.value; return out; }
                out.push(next.value);
              }
              yield;
            }
            return out;
          }
          let descriptors = await run(readStage(128));
          if (!valid()) return false;
          job.snapshotCPU = job.cpu;
          const rows = [], counts = {}, seen = new Map(), convertedGeometries = new WeakMap(); let coordinates = 0, skipped = 0, geometryConversions = 0, geometryCacheHits = 0;
          const layerCount = collectLayers(app.map).length;
          let group = !descriptionDone || layerCount > 1 ? new C.PrimitiveCollection() : null;
          let ordered = null;
          const prepareBuckets = () => {
            const kinds = Array.from({length:5}, () => group.add(new C.PrimitiveCollection()));
            return kinds.map(kind => layerCount > 1
              ? Array.from({length:layerCount}, () => kind.add(new C.PrimitiveCollection())) : [kind]);
          };
          if (group) { ordered = prepareBuckets(); localViewer.scene.primitives.add(group); batches = {group, counts:emptyCounts()}; }
          // Stream bounded descriptor windows, then cap each immutable GPU batch.
          // Source/style traversal itself streams, so initial interaction does
          // not wait for archive-path traversal, cloning or projection.
          let first = true, hasContext = false;
          for (let stage = 0; ; stage++) {
            if (stage) {
              if (descriptionDone) break;
              const readAt = job.cpu;
              descriptors = await run(readStage(3584));
              job.snapshotCPU += job.cpu - readAt;
              if (!valid()) return false;
              if (!descriptors.length) break;
            }
            const prepared = [];
            function* prepare() {
              for (const descriptor of descriptors) {
                let geometry;
                const cacheable = descriptor.geometry && typeof descriptor.geometry === 'object';
                if (reused) geometry = descriptor.geometry;
                else if (cacheable && convertedGeometries.has(descriptor.geometry)) { geometry = convertedGeometries.get(descriptor.geometry); geometryCacheHits++; }
                else {
                  geometry = yield* convertGeometrySteps(descriptor.geometry, p => ol.proj.transform(p, app.projection, 'EPSG:4326'));
                  geometryConversions++;
                  if (cacheable) convertedGeometries.set(descriptor.geometry, geometry);
                }
                if (!geometry) { skipped++; yield; continue; }
                const row = {...descriptor, geometry}; rows.push(row);
                prepared.push({...row, fills:renderPolicy(row.layerId, imageryState).fills});
                if (!seen.has(row.layer)) seen.set(row.layer, new Set());
                if (!seen.get(row.layer).has(row.feature)) {
                  counts[row.layerId || 'reference'] = (counts[row.layerId || 'reference'] || 0) + 1;
                  seen.get(row.layer).add(row.feature);
                }
                hasContext ||= FILL_CONTEXT.has(row.layerId) && geometry.polygons.length && row.style.getFill?.();
                coordinates += geometry.points.length;
                for (const line of geometry.lines) { coordinates += line.length; yield; }
                for (const polygon of geometry.polygons) for (const ring of polygon) { coordinates += ring.length; yield; }
                yield;
              }
              return true;
            }
            const prepAt = job.cpu;
            await run(prepare()); job.snapshotCPU += job.cpu - prepAt; if (!valid()) return false;
            const chunks = planBatches(prepared);
            if (!chunks.length) chunks.push({rows:[], layerOrder:0, cost:{rows:0,points:0,vertices:0,glyphs:0}, oversized:false});
            if (!group && chunks.length > 1) {
              group = new C.PrimitiveCollection();
              ordered = prepareBuckets();
              localViewer.scene.primitives.add(group); batches = {group, counts:emptyCounts()};
            }
            for (const chunk of chunks) {
            const batchAt = job.cpu;
            const next = await run(batchSteps(C, {rows:chunk.rows}, doc, job.owner));
            if (!valid()) return false;
            job.batchCPU += job.cpu - batchAt;
            if (group) {
              // Keep the baseline primitive-kind order AND original row/style
              // order within each kind, independently of stage attachment.
              next.group.destroyPrimitives = false;
              let kind = 0;
              while (next.group.length) {
                const child = next.group.get(0); next.group.remove(child); next.group.destroyPrimitives = true;
                try { ordered[kind++][layerCount > 1 ? chunk.layerOrder : 0].add(child); } catch (error) { child.destroy(); throw error; }
                next.group.destroyPrimitives = false;
              }
              next.group.destroyPrimitives = true; next.group.destroy();
            }
            else { localViewer.scene.primitives.add(next.group); batches = {group:next.group, counts:emptyCounts()}; }
            job.owner.group = null;
            for (const name of Object.keys(next.counts)) batches.counts[name] += next.counts[name];
            // Render each immutable stage once. The initial successful stage is
            // interactive while remaining overlays retain truthful loading UI.
            const renderAt = now(); localViewer.render();
            if (!valid()) return false;
            job.stageCPU.push({stage:job.stageCPU.length, descriptorStage:stage, rows:chunk.rows.length, cost:chunk.cost, oversized:chunk.oversized, cpuMs:job.cpu-batchAt, renderMs:now()-renderAt});
            host.dataset.flGlobeRenderedPrimitiveCounts = JSON.stringify(batches.counts);
            host.dataset.flGlobeStage = String(job.stageCPU.length);
            if (first) {
              first = false;
              if (!restoreCapture) {
                freeze2D(); stateAttrs('loading');
                const openPopup = doc.getElementById('fl-observation-popup');
                if (openPopup && !openPopup.hidden) openPopup._flSyncPresentation?.();
                context.onActiveChange?.(true);
                if (!valid()) return false;
              }
              host.dataset.flGlobeFirstUsableMs = String(now()-job.started);
              host.dataset.flGlobeInitialRenderMs = String(now()-renderAt);
            }
            if (next.counts.points && host.dataset.flGlobeFirstPointMs === undefined)
              host.dataset.flGlobeFirstPointMs = String(now() - job.started);
            if (host.dataset.flGlobeFirstObservationMs === undefined && chunk.rows.some(row => {
              const image = row.style.getImage?.();
              return row.layerId === 'frozen-observations' && row.geometry.points.length && image && image.getOpacity?.() !== 0;
            })) host.dataset.flGlobeFirstObservationMs = String(now() - job.started);
            request();
            // Always yield after attachment, even if this was a tiny stage.
            if (!await pause()) return false;
            }
            if (descriptionDone) break;
          }
          if (!valid()) return false;
          const snap = {rows:rows.slice().sort((a,b) => a.layerOrder - b.layerOrder || a.rowOrder - b.rowOrder), priorityRows:rows, counts, skipped:reused ? cachedSnapshot.skipped : skipped};
          if (!reused) {
            snapshotCount++;
            cachedSnapshot = rows.length <= 50000 && coordinates <= 500000 ? snap : null;
            snapshotKey = cachedSnapshot ? key : null;
          }
          batchPolicy = policy(); batchHasContext = !!hasContext; updateCount++;
          host.dataset.flGlobeSnapshotMs = String(job.snapshotCPU);
          host.dataset.flGlobeBatchMs = String(job.batchCPU);
          host.dataset.flGlobeSnapshotCount = String(snapshotCount);
          host.dataset.flGlobeSnapshotReused = String(!!reused);
          host.dataset.flGlobeFeatureCounts = JSON.stringify(counts);
          host.dataset.flGlobePrimitiveCounts = JSON.stringify(batches.counts);
          host.dataset.flGlobeSkipped = String(snap.skipped);
          host.dataset.flGlobeUpdates = String(updateCount);
          host.dataset.flGlobeBuildMetrics = JSON.stringify({steps:job.steps, slices:job.slices, maxSteps:job.maxSteps,
            maxSliceMs:job.maxSlice, cpuMs:job.cpu, geometryConversions, geometryCacheHits, stages:job.stageCPU});
          host.dataset.flGlobeAllCompleteMs = String(now()-job.started);
          host.dataset.flGlobeComplete = 'true'; host.dataset.flGlobeStage = 'complete';
          build = null; stateAttrs('ready'); imageryMessage(); request(); scheduleQuality(); return true;
        } catch (_) {
          if (valid()) fallback('3D data could not be drawn. The 2D map is available.');
          return false;
        } finally {
          job.owner.group?.destroy(); job.owner.group = null;
          if (build === job) {
            build = null;
            if (viewer === localViewer && (doc.hidden || !modeIsMap())) {
              desired = false; epoch++; deactivate(); status.textContent = ''; stateAttrs('off');
            }
          }
        }
      })();
      return completion;
    }
    function schedulePolicy() {
      // Loading and ready share outline context. Only explicit OFF/failure
      // changes fallback fills; the rebuild reuses projected geometry.
      if (build) { if (build.fillPolicy !== policy()) { cancelBuild(); retire(); queueRefresh(); } }
      else if (batches && batchHasContext && batchPolicy !== policy()) queueRefresh();
      else if (!dataDirty) { root.clearTimeout(snapshotTimer); snapshotTimer = null; }
    }
    function imageryMessage() {
      if (!active) return;
      if (imageryState === 'off') status.textContent = 'NASA imagery off · vector context';
      else if (imageryFailed) status.textContent = 'NASA imagery unavailable · vector context';
      else if (imageryState === 'loading') status.textContent = 'NASA imagery loading · vector context';
      else status.textContent = pending ? 'NASA tiles loading' : '';
      if (build || dataDirty || snapshotTimer !== null) status.textContent = '3D overlays loading… ' + status.textContent;
      host.dataset.flGlobeImagery = imageryState;
      host.dataset.flGlobeImageryPending = String(pending);
      host.dataset.flGlobeImageryTilesReady = String(imageryState === 'ready' && pending === 0 && viewer?.scene.globe.tilesLoaded === true);
      retry.hidden = !imageryFailed;
    }
    function removeImagery() {
      root.clearTimeout(imageryTimer); imageryTimer = null;
      imageDisposers.splice(0).forEach(fn => fn());
      if (viewer && imageryLayer) viewer.imageryLayers.remove(imageryLayer, true);
      imageryLayer = null; imageryLoaded = false; pending = 0;
    }
    function startImagery() {
      if (!viewer || !active) return;
      const enabled = imagery.state.enabled === true;
      if (!enabled) {
        removeImagery(); imageryFailed = false; imageryState = 'off'; imageryMessage(); schedulePolicy(); request(); return;
      }
      if (imageryLayer) return;
      imageryState = 'loading'; imageryFailed = false;
      try {
        const provider = new C.WebMapTileServiceImageryProvider(nasaOptions(C));
        imageryLayer = viewer.imageryLayers.addImageryProvider(provider);
        const fail = () => {
          if (!active || !imagery.state.enabled) return;
          imageryFailed = true; imageryState = 'unavailable'; removeImagery(); imageryMessage(); schedulePolicy(); request();
        };
        onC(provider.errorEvent, fail, imageDisposers);
        // These are THIS viewer's events; no 2D tile counters are reused.
        onC(viewer.scene.globe.tileLoadProgressEvent, count => {
          if (!active || !imageryLayer || !imagery.state.enabled) return;
          pending = count;
          // A zero event is accepted only after real tile activity. Inspect
          // globe.tilesLoaded as well: provider creation is not tile success.
          if (count > 0) imageryLoaded = true;
          if (imageryLoaded && count === 0 && viewer.scene.globe.tilesLoaded) {
            root.clearTimeout(imageryTimer); imageryState = 'ready'; schedulePolicy();
          }
          imageryMessage();
        }, imageDisposers);
        imageryTimer = root.setTimeout(fail, 25000);
      } catch (_) {
        removeImagery(); imageryFailed = true; imageryState = 'unavailable';
      }
      imageryMessage(); schedulePolicy(); request();
    }
    function freeze2D() {
      if (restoreCapture) return;
      // Capture at Observable dispatch, before existing OL listeners, including
      // handlers that were bound before this module was mounted.
      const original = app.map.dispatchEvent;
      const blocked = new Set(['singleclick', 'click', 'dblclick', 'pointerdrag', 'pointermove', 'pointerdown', 'pointerup', 'keydown', 'keypress']);
      const capture = function (event) {
        if (active && blocked.has(typeof event === 'string' ? event : event.type)) return false;
        return original.call(this, event);
      };
      app.map.dispatchEvent = capture;
      restoreCapture = () => { if (app.map.dispatchEvent === capture) app.map.dispatchEvent = original; };
      for (const i of app.map.getInteractions().getArray()) {
        if (!interactionStates.has(i)) interactionStates.set(i, i.getActive());
        i.setActive(false);
      }
      priorReadout = readout?.textContent;
      if (readout) readout.textContent = 'Move across the globe for coordinates';
      host.classList.add('fl-globe-active'); controlsHost.classList.add('fl-globe-mode');
    }
    function restore2D() {
      restoreCapture?.(); restoreCapture = null;
      interactionStates.forEach((value, i) => i.setActive(value)); interactionStates.clear();
      host.classList.remove('fl-globe-active'); controlsHost.classList.remove('fl-globe-mode');
      if (readout && priorReadout !== null) readout.textContent = priorReadout;
      priorReadout = null;
      for (const [element, entry] of popups) {
        entry.host?.append(element); element.classList.remove('fl-globe-popup');
        element.style.visibility = entry.visibility; element._flSyncPresentation?.();
      }
      popups.clear();
    }
    function cancelQuality() { root.clearTimeout(qualityTimer); qualityTimer = null; }
    function applyQuality(idle, force = false) {
      if (!viewer || !active || !desired || doc.hidden) return;
      const bounds = surface.getBoundingClientRect(), next = qualityScale(bounds.width, bounds.height, root.devicePixelRatio, idle);
      if (next === null) return;
      const key = bounds.width + ':' + bounds.height;
      const current = viewer.resolutionScale;
      // Upscale only beyond hysteresis; decreases always honor the pixel cap.
      const changed = !Number.isFinite(current) || next < current - 0.001 || next > current * 1.08;
      if (changed) viewer.resolutionScale = next;
      if (changed || key !== sizeKey || force) {
        sizeKey = key; viewer.resize();
        preserveClientAspect(viewer.camera, viewer.scene.canvas);
        request(); updatePopups();
      }
      host.dataset.flGlobeResolutionScale = String(viewer.resolutionScale);
    }
    function qualityPose() {
      const camera = viewer?.camera;
      if (!camera) return null;
      return [camera.positionWC, camera.directionWC, camera.upWC].flatMap(v => [v.x,v.y,v.z]);
    }
    function stablePose(a, b) {
      return a && b && a.every((v,i) => Number.isFinite(v) && Math.abs(v-b[i]) <= (i < 3 ? 0.00001 : 1e-12));
    }
    function scheduleQuality() {
      cancelQuality();
      const reason = !active || !desired || doc.hidden ? 'inactive' : build ? 'building' : qualityInputHeld ? 'input-held' : 'settling';
      host.dataset.flGlobeQualityReason = reason;
      host.dataset.flGlobeQualityMoving = String(qualityMoving);
      host.dataset.flGlobeQualityInputHeld = String(qualityInputHeld);
      if (reason !== 'settling') return;
      const localViewer = viewer, token = epoch, pose = qualityPose();
      qualityTimer = root.setTimeout(() => {
        qualityTimer = null;
        if (viewer !== localViewer || token !== epoch || !active || !desired || build || qualityInputHeld || doc.hidden) return;
        if (!stablePose(pose, qualityPose())) { qualityMoving = true; scheduleQuality(); return; }
        qualityMoving = false; host.dataset.flGlobeQualityMoving = 'false';
        host.dataset.flGlobeQualityReason = 'idle'; applyQuality(true);
      }, 240);
    }
    function movementQuality() { cancelQuality(); applyQuality(false); }
    function resizeViewer() {
      if (!viewer) return;
      const bounds = surface.getBoundingClientRect();
      const key = [bounds.width, bounds.height, root.devicePixelRatio || 1].join(':');
      if (key === dimensionKey) return;
      dimensionKey = key; movementQuality(); scheduleQuality();
    }
    function resetView() {
      if (!active || !viewer) return false;
      viewer.camera.setView({destination: C.Cartesian3.fromDegrees(0, -90, 11000000),
        orientation: {heading: 0, pitch: -Math.PI / 2, roll: 0}}); request(); return true;
    }
    function zoom(delta) {
      if (!active || !viewer) return false;
      const height = viewer.camera.positionCartographic.height;
      const distance = delta > 0 ? Math.max(0, height - Math.max(MIN_HEIGHT, height * 0.7)) : Math.max(0, Math.min(MAX_HEIGHT, height * 1.3) - height);
      delta > 0 ? viewer.camera.zoomIn(distance) : viewer.camera.zoomOut(distance);
      request(); return true;
    }
    function fitFeature(feature) {
      if (!active || !viewer) return false;
      const g = convertGeometry(feature?.getGeometry?.(), p => ol.proj.transform(p, app.projection, 'EPSG:4326'));
      if (!g) return true;
      const coords = [...g.points, ...g.lines.flat(), ...g.polygons.flat(2)];
      if (!coords.length) return true;
      const sphere = C.BoundingSphere.fromPoints(coords.map(p => position(C, p)));
      viewer.camera.flyToBoundingSphere(sphere, {duration: 0.4, offset: new C.HeadingPitchRange(0, -Math.PI / 2, Math.max(50000, sphere.radius * 3))});
      request(); return true;
    }
    function pick(position2D) {
      if (!active || !viewer) return false;
      // A depth-tested scene pick carries the actual OL feature reference.
      const raw = viewer.scene.pick(position2D), item = raw?.id;
      // Match each old singleclick listener's null/clear behavior as well as hits.
      for (const [layerId, adapter] of Object.entries(DYNAMIC_SELECTION))
        select[adapter](item?.flGlobe && item.layerId === layerId ? item.feature : null);
      if (!item?.flGlobe) return false;
      if (DYNAMIC_SELECTION[item.layerId]) { schedule(); return true; }
      if (item.layerId === 'riggs-reference-stations') select.riggs(item.feature);
      else if (item.kind === 'coverage') select.coverage(item.feature);
      else if (item.kind === 'observations') select.observation(item.feature);
      else if (item.kind === 'flights') select.flight(item.feature);
      else return false;
      schedule(); return true;
    }
    function coordinates(p) {
      if (!active || !viewer || !readout) return;
      const cart = viewer.camera.pickEllipsoid(p, C.Ellipsoid.WGS84);
      if (!cart) { readout.textContent = 'Outside the globe'; return; }
      const ll = C.Cartographic.fromCartesian(cart), lat = C.Math.toDegrees(ll.latitude), lon = C.Math.toDegrees(ll.longitude);
      readout.textContent = `${Math.abs(lat).toFixed(3)}° ${lat < 0 ? 'S' : 'N'} · ${Math.abs(lon).toFixed(3)}° ${lon < 0 ? 'W' : 'E'}`;
    }
    function syncPopup(element, feature) {
      if (!active || !viewer || !element) return false;
      if (!popups.has(element)) popups.set(element, {host: element.parentElement, visibility: element.style.visibility, offset: [0, 0]});
      const entry = popups.get(element), geometry = feature?.getGeometry?.();
      if (feature && (entry.feature !== feature || entry.geometry !== geometry || entry.revision !== geometry?.getRevision?.())) {
        entry.feature = feature; entry.geometry = geometry; entry.revision = geometry?.getRevision?.();
        const coords = geometry?.getCoordinates?.();
        entry.position = coords && Number.isFinite(coords[0])
          ? position(C, ol.proj.transform(coords.slice(0, 2), app.projection, 'EPSG:4326')) : null;
      }
      // Reparent once; repeatedly appending would drop focused popup actions.
      if (element.parentElement !== controlsHost) controlsHost.append(element);
      const bounds = host.getBoundingClientRect();
      element.style.setProperty('--fl-map-width', bounds.width + 'px');
      element.style.setProperty('--fl-map-height', bounds.height + 'px');
      element.classList.add('fl-globe-popup');
      element.dataset.presentation = 'globe'; updatePopups(); return true;
    }
    function movePopup(element, dx, dy) {
      const p = popups.get(element); if (!active || !p) return false;
      p.offset[0] += dx; p.offset[1] += dy; updatePopups(); return true;
    }
    function updatePopups() {
      if (!active || !viewer) return;
      for (const [element, entry] of popups) {
        if (element.hidden || !entry.feature) continue;
        const cart = entry.position;
        if (!cart) continue;
        const screen = C.SceneTransforms.worldToWindowCoordinates(viewer.scene, cart);
        const occluder = new C.EllipsoidalOccluder(C.Ellipsoid.WGS84, viewer.camera.positionWC);
        const visible = !!screen && occluder.isPointVisible(cart);
        element.style.visibility = visible ? '' : 'hidden';
        if (!visible) continue;
        const bounds = host.getBoundingClientRect(), shell = controlsHost.getBoundingClientRect();
        const w = element.offsetWidth, h = element.offsetHeight;
        const left = Math.max(8, Math.min(bounds.width - w - 8, screen.x - w / 2 + entry.offset[0]));
        const top = Math.max(8, Math.min(bounds.height - h - 8, screen.y - h - 14 + entry.offset[1]));
        Object.assign(element.style, {left: `${bounds.left - shell.left + left}px`, top: `${bounds.top - shell.top + top}px`, right: 'auto', bottom: 'auto'});
      }
    }
    function installNavigation() {
      const camera = viewer.camera, canvas = viewer.scene.canvas, inputs = viewer.scene.screenSpaceCameraController;
      const originalZoomEvents = inputs.zoomEventTypes;
      const events = Array.isArray(originalZoomEvents) ? originalZoomEvents : [originalZoomEvents];
      inputs.zoomEventTypes = events.filter(event => (event?.eventType ?? event) !== C.CameraEventType.WHEEL);
      inputs.inertiaSpin = 0.55; inputs.inertiaZoom = 0.15;
      inputs.maximumMovementRatio = 0.05; inputs.zoomFactor = 2;
      inputs.minimumZoomDistance = MIN_HEIGHT; inputs.maximumZoomDistance = MAX_HEIGHT;
      inputs.maximumTiltAngle = Math.PI / 2 - 0.02; inputs.enableCollisionDetection = true;
      let timer = null, remaining = 0, pixel = null;
      const cancel = () => { root.clearTimeout(timer); timer = null; remaining = 0; };
      const step = () => {
        timer = null;
        if (!active || !viewer || !inputs.enableInputs || !inputs.enableZoom) { cancel(); return; }
        const delta = Math.abs(remaining) < 0.5 ? remaining : remaining * 0.35;
        remaining -= delta;
        if (delta) { anchoredZoom(C, camera, pixel, delta); request(); }
        if (Math.abs(remaining) >= 0.01) timer = root.setTimeout(step, 16);
        else scheduleQuality();
      };
      onDOM(canvas, 'wheel', event => {
        if (!active || !inputs.enableInputs || !inputs.enableZoom) return;
        const bounds = canvas.getBoundingClientRect(), delta = wheelPixels(event, bounds.height);
        if (!delta) return;
        event.preventDefault(); movementQuality(); camera.cancelFlight();
        pixel = new C.Cartesian2(event.clientX - bounds.left, event.clientY - bounds.top);
        remaining = Math.max(-240, Math.min(240, remaining + delta));
        if (timer === null) timer = root.setTimeout(step, 16);
      }, {passive: false}, viewerDisposers);
      for (const event of ['pointerdown', 'touchstart', 'keydown']) onDOM(canvas, event, () => { qualityInputHeld = true; cancel(); movementQuality(); scheduleQuality(); }, false, viewerDisposers);
      for (const event of ['pointerup','pointercancel','touchend','touchcancel','keyup','blur']) onDOM(root, event, () => { qualityInputHeld = false; scheduleQuality(); }, false, viewerDisposers);
      viewerDisposers.push(() => { cancel(); inputs.zoomEventTypes = originalZoomEvents; });
    }
    function stopViewer() {
      cancelBuild(); cancelQuality(); qualityMoving = false; qualityInputHeld = false; sizeKey = ''; dimensionKey = '';
      host.dataset.flGlobeComplete = 'false'; host.dataset.flGlobeStage = 'off';
      root.clearTimeout(snapshotTimer); snapshotTimer = null;
      if (viewer) {
        savedCamera = {destination: C.Cartesian3.clone(viewer.camera.positionWC),
          orientation: {direction: C.Cartesian3.clone(viewer.camera.directionWC), up: C.Cartesian3.clone(viewer.camera.upWC)}};
        viewer.useDefaultRenderLoop = false;
        removeImagery();
        viewerDisposers.splice(0).forEach(fn => fn());
        viewer.destroy(); viewer = null; batches = null;
      }
    }
    function deactivate() {
      const wasActive = active; active = false; stopViewer(); surface.replaceChildren(); surface.hidden = true; restore2D();
      host.dataset.flGlobeFeatureCounts = '{}';
      host.dataset.flGlobePrimitiveCounts = JSON.stringify(emptyCounts());
      host.dataset.flGlobeImagery = 'off';
      host.dataset.flGlobeImageryPending = '0'; host.dataset.flGlobeImageryTilesReady = 'false';
      if (wasActive) context.onActiveChange?.(false);
    }
    function fallback(message) {
      desired = false; epoch++; deactivate(); status.textContent = message;
      stateAttrs('error');
    }
    function modeIsMap() { return !doc.body?.dataset.flMode || doc.body.dataset.flMode === 'map'; }
    async function setEnabled(value) {
      if (disposed) return false;
      if (value && active && desired) return controller.whenComplete();
      desired = !!value; const token = ++epoch, setupStarted = now();
      if (!desired) { deactivate(); status.textContent = ''; stateAttrs('off'); return false; }
      if (!modeIsMap() || doc.hidden) { desired = false; stateAttrs('off'); return false; }
      if (active) { stateAttrs('ready'); return true; }
      status.textContent = 'Loading 3D globe… The 2D map remains available.'; stateAttrs('loading');
      try {
        C = await loadCesium(doc);
        if (disposed || !desired || token !== epoch || !modeIsMap() || doc.hidden) return false;
        host.dataset.flGlobeEngineMs = String(now() - setupStarted);
        // A small bundled height-bound table is required for synchronous
        // ground classification. This does not enable a measured terrain service.
        const groundStarted = now();
        await C.GroundPrimitive.initializeTerrainHeights();
        if (disposed || !desired || token !== epoch || !modeIsMap() || doc.hidden) return false;
        host.dataset.flGlobeGroundInitMs = String(now() - groundStarted);
        // No hidden 2D state is changed during any asynchronous load.
        surface.hidden = false;
        const viewerStarted = now();
        viewer = new C.Viewer(surface, viewerOptions(C));
        host.dataset.flGlobeViewerMs = String(now() - viewerStarted);
        if (!C.GroundPrimitive.isSupported(viewer.scene) || !C.GroundPrimitive.supportsMaterials(viewer.scene))
          throw new Error('Ground overlay rendering unsupported');
        viewer.scene.globe.enableLighting = false;
        viewer.scene.globe.depthTestAgainstTerrain = true;
        viewer.scene.backgroundColor = C.Color.fromCssColorString('#142a39');
        viewer.scene.globe.baseColor = C.Color.fromCssColorString('#42677b');
        viewer.clock.shouldAnimate = false;
        const handler = new C.ScreenSpaceEventHandler(viewer.scene.canvas);
        handler.setInputAction(e => pick(e.position), C.ScreenSpaceEventType.LEFT_CLICK);
        handler.setInputAction(e => coordinates(e.endPosition), C.ScreenSpaceEventType.MOUSE_MOVE);
        viewerDisposers.push(() => handler.destroy());
        onC(viewer.scene.renderError, () => fallback('3D rendering stopped. The 2D map is available.'));
        onC(viewer.scene.postRender, updatePopups);
        onDOM(viewer.scene.canvas, 'webglcontextlost', e => {
          e.preventDefault(); fallback('3D graphics were interrupted. The 2D map is available.');
        }, false, viewerDisposers);
        if (viewer.camera.moveStart) onC(viewer.camera.moveStart, () => { qualityMoving = true; movementQuality(); scheduleQuality(); });
        if (viewer.camera.moveEnd) onC(viewer.camera.moveEnd, () => { qualityMoving = false; scheduleQuality(); });
        if (root.ResizeObserver) {
          const observer = new root.ResizeObserver(resizeViewer);
          observer.observe(host); viewerDisposers.push(() => observer.disconnect());
        }
        active = true;
        installNavigation();
        if (savedCamera) restoreCamera(C, viewer.camera, savedCamera); else resetView();
        startImagery();
        resizeViewer();
        const enablingViewer = viewer, setupBuild = refresh(), setupGeneration = generation;
        const rendered = await setupBuild;
        if (!rendered || token !== epoch || setupGeneration !== generation || viewer !== enablingViewer ||
            !desired || !active || disposed || doc.hidden || !modeIsMap()) return false;
        if (!active) return false;
        // Complete an actual synchronous render before hiding the 2D canvas.
        resizeViewer();

        if (!active || !viewer) return false;
        stateAttrs('ready'); request();
        host.dataset.flGlobeSetupMs = String(now() - setupStarted);
        const openPopup = doc.getElementById('fl-observation-popup');
        if (openPopup && !openPopup.hidden) openPopup._flSyncPresentation?.();
        return true;
      } catch (_) {
        if (!disposed && desired && token === epoch) fallback('3D globe unavailable. Continue with the 2D map or retry.');
        return false;
      }
    }
    onOL(app.map.getInteractions(), 'add', e => {
      if (active && restoreCapture && e.element) { interactionStates.set(e.element, e.element.getActive()); e.element.setActive(false); }
    });
    const layerDisposers = [];
    function bindLayers() {
      layerDisposers.splice(0).forEach(fn => fn());
      const seen = new Set();
      const visit = collection => {
        onOL(collection, 'add', () => { bindLayers(); schedule(); }, layerDisposers);
        onOL(collection, 'remove', () => { bindLayers(); schedule(); }, layerDisposers);
        for (const layer of collection.getArray()) {
          onOL(layer, 'change', schedule, layerDisposers);
          onOL(layer, 'propertychange', schedule, layerDisposers);
          onOL(layer, 'change:layers', () => { bindLayers(); schedule(); }, layerDisposers);
          onOL(layer, 'change:source', () => { bindLayers(); schedule(); }, layerDisposers);
          const source = layer.getSource?.();
          if (source && !seen.has(source)) { seen.add(source); onOL(source, 'change', schedule, layerDisposers); }
          if (layer.getLayers) visit(layer.getLayers());
        }
      };
      visit(app.map.getLayers());
    }
    onOL(app.map, 'change:layerGroup', () => { bindLayers(); schedule(); });
    const viewDisposers = [];
    function bindView() {
      viewDisposers.splice(0).forEach(fn => fn());
      onOL(app.map.getView(), 'change', schedule, viewDisposers);
    }
    bindView(); disposers.push(() => viewDisposers.splice(0).forEach(fn => fn()));
    onOL(app.map, 'change:view', () => { bindView(); schedule(); });
    bindLayers(); disposers.push(() => layerDisposers.splice(0).forEach(fn => fn()));
    for (const event of ['fl-map-visibility-change', 'fl-map-products-changed', 'frozen-legacies:observation', 'fl-image-scope-filter-change'])
      onDOM(doc, event, schedule);
    const unsub = context.store?.subscribe?.(schedule); if (typeof unsub === 'function') disposers.push(unsub);
    let lastSharedEnabled = imagery.state.enabled === true;
    const unsubscribeImagery = imagery.subscribe(state => {
      const enabled = state.enabled === true;
      if (enabled === lastSharedEnabled) return; // Ignore 2D tile counts/errors.
      lastSharedEnabled = enabled;
      if (active) startImagery();
    });
    if (typeof unsubscribeImagery !== 'function') {
      // This is a required reviewed adapter, rather than leaking callbacks.
      disposers.splice(0).forEach(fn => fn()); toolbar.remove(); surface.remove();
      throw new Error('Shared imagery.subscribe must return its disposer');
    }
    disposers.push(unsubscribeImagery);
    onDOM(toggle, 'click', () => { void setEnabled(!desired); });
    onDOM(reset, 'click', resetView);
    onDOM(retry, 'click', () => {
      if (!active) { void setEnabled(true); return; }
      removeImagery(); imageryFailed = false; startImagery();
    });
    // Capture navigation controls before their OL target listeners can run.
    onDOM(host, 'click', e => {
      if (!active) return;
      const plus = e.target.closest?.('.ol-zoom-in'), minus = e.target.closest?.('.ol-zoom-out');
      if (plus || minus) { e.preventDefault(); e.stopImmediatePropagation(); zoom(plus ? 1 : -1); }
    }, true);
    onDOM(root, 'resize', resizeViewer);
    let dprMedia = null;
    const dprChanged = () => { resizeViewer(); watchDPR(); };
    function watchDPR() {
      dprMedia?.removeEventListener?.('change', dprChanged);
      dprMedia = root.matchMedia?.('(resolution: ' + (root.devicePixelRatio || 1) + 'dppx)');
      dprMedia?.addEventListener?.('change', dprChanged);
    }
    watchDPR(); disposers.push(() => dprMedia?.removeEventListener?.('change', dprChanged));
    onDOM(doc, 'visibilitychange', () => { if (doc.hidden && desired) void setEnabled(false); });
    if (root.MutationObserver && doc.body) {
      const observer = new root.MutationObserver(() => { if (!modeIsMap() && desired) void setEnabled(false); });
      observer.observe(doc.body, {attributes: true, attributeFilter: ['data-fl-mode']});
      disposers.push(() => observer.disconnect());
    }
    const controller = Object.freeze({setEnabled, isActive: () => active && !!restoreCapture, isRequested: () => desired,
      resetView, zoom, fitFeature, syncPopup, movePopup,
      refresh: schedule,
      // Resolves the explicitly current generation, including debounced refresh.
      async whenComplete() {
        if (snapshotTimer !== null && active) { root.clearTimeout(snapshotTimer); snapshotTimer = null; refresh(); }
        const current = completion, result = await current;
        return current === completion ? result : false;
      },
      dispose() {
        if (disposed) return;
        desired = false; epoch++; deactivate(); disposed = true;
        invalidate();
        disposers.splice(0).forEach(fn => fn()); toolbar.remove(); surface.remove(); controllers.delete(app.map);
        host.dataset.flActiveView = '2d'; host.dataset.flGlobeStatus = 'disposed';
      }});
    controllers.set(app.map, controller); stateAttrs('off'); return controller;
  }
  const api = Object.freeze({mount, controllerFor: map => controllers.get(map)});
  root.FrozenLegaciesGlobe = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = {...api,
    testing: {CONTRACT, loadCesium, validVersion, viewerOptions, nasaOptions, convertGeometry, convertGeometrySteps, readCoordinates, describeSnapshot, batchSteps, planBatches, BATCH_BUDGETS, layerPriority, preserveClientAspect, qualityScale, snapshot, renderPolicy, createBatches, wheelPixels, anchoredZoom, restoreCamera}};
})(typeof window !== 'undefined' ? window : globalThis);
