/* Shared Leaflet base layers for every map in GSTSync.
   Call gstMapLayers(map[, {default:'street'|'satellite'}]) after creating the map.
   Default layer is Google Maps; also offers Esri Satellite, OpenStreetMap,
   OpenTopoMap terrain and OSM Humanitarian. No CartoDB Light/Dark. */
(function (w) {
    w.gstMapLayers = function (map, opts) {
        opts = opts || {};
        var google = L.tileLayer('https://{s}.google.com/vt/lyrs=m&x={x}&y={y}&z={z}',
            { maxZoom: 20, subdomains: ['mt0', 'mt1', 'mt2', 'mt3'], attribution: '&copy; Google Maps' });
        var osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            { maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' });
        var sat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            { maxZoom: 19, attribution: 'Tiles &copy; Esri, Maxar, Earthstar Geographics' });
        var topo = L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
            { maxZoom: 17, attribution: '&copy; OpenTopoMap (CC-BY-SA)' });
        var hot = L.tileLayer('https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png',
            { maxZoom: 19, attribution: '&copy; OpenStreetMap contributors, HOT' });
        // Google is the default; pass {default:'satellite'|'street'} to override.
        var def = google;
        if (opts.default === 'satellite') def = sat;
        else if (opts.default === 'street') def = osm;
        def.addTo(map);
        L.control.layers({
            '🗺️ Google': google,
            '🛰️ Satellite': sat,
            '🛣️ Street': osm,
            '⛰️ Terrain': topo,
            '🌍 Humanitarian': hot
        }, opts.overlays || undefined, { collapsed: opts.collapsed !== false }).addTo(map);
        return { google: google, osm: osm, sat: sat, topo: topo, hot: hot };
    };
})(window);
