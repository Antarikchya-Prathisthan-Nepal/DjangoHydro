// Initialize map with Nepal center coordinates

// Initialize map with Nepal center coordinates

// Define street and satellite layers
var streetLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
});

// Esri World Imagery Satellite layer
var satelliteLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 18,
    attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community'
});

// Initialize map with street layer as default
var map = L.map('map', {
    center: [28.5, 84],
    zoom: 7,
    layers: [streetLayer]
});

// Dedicated pane so key points always render above watershed polygons.
if (!map.getPane('hydro-points-pane')) {
    map.createPane('hydro-points-pane');
    map.getPane('hydro-points-pane').style.zIndex = 700;
}

// Add layer control to switch between street and satellite
var baseMaps = {
    "Street Map": streetLayer,
    "Satellite": satelliteLayer
};
L.control.layers(baseMaps).addTo(map);

// Guard against Leaflet popup zoom animation errors when popup is removed mid-transition.
if (window.L && L.Popup && !L.Popup.prototype._hydroZoomGuardPatched) {
    var originalPopupAnimateZoom = L.Popup.prototype._animateZoom;
    L.Popup.prototype._animateZoom = function(e) {
        if (!this._map || !this._latlng) {
            return;
        }
        return originalPopupAnimateZoom.call(this, e);
    };
    L.Popup.prototype._hydroZoomGuardPatched = true;
}

if (window.ol && window.ol.proj && typeof window.ol.proj.useGeographic === 'function') {
    window.ol.proj.useGeographic();
}


// ====== MAP LEGEND FOR ELEVATION BANDS & POINTS (only after catchment) ======
function showElevationLegendOnMap() {
    if (window.elevationLegendControl) {
        map.removeControl(window.elevationLegendControl);
    }
    window.elevationLegendControl = L.control({ position: 'topright' });
    window.elevationLegendControl.onAdd = function (map) {
        var div = L.DomUtil.create('div', 'info legend elevation-legend');
        div.innerHTML = `
            <div style="background: rgba(255,255,255,0.75); border-radius: 6px; box-shadow: 0 2px 8px rgba(0,0,0,0.10); padding: 5px 8px; min-width: 110px; font-size: 12px; line-height: 1.2;">
                <b>Elevation Bands</b><br>
                <i style="display:inline-block;width:12px;height:12px;background:#fdae61;border:1.5px solid #b36b00;margin-right:4px;vertical-align:middle;"></i>
                <span style="vertical-align:middle;">Below 3000m</span><br>
                <i style="display:inline-block;width:12px;height:12px;background:#dfabe9ff;border:1.5px solid #4b006e;margin-right:4px;vertical-align:middle;"></i>
                <span style="vertical-align:middle;">Below 5000m</span><br>
                <hr style="margin:5px 0;">
                <b>Points</b><br>
                <svg width="12" height="12" style="vertical-align:middle;margin-right:4px;"><circle cx="6" cy="6" r="5" fill="#0074D9" stroke="#003366" stroke-width="1.5"/></svg>
                <span style="vertical-align:middle;">Requested Point</span><br>
                <svg width="12" height="12" style="vertical-align:middle;margin-right:4px;"><circle cx="6" cy="6" r="5" fill="red" stroke="#900" stroke-width="1.5"/></svg>
                <span style="vertical-align:middle;">Snapped Point</span>
            </div>
        `;
        return div;
    };
    window.elevationLegendControl.addTo(map);
}
L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
});

var watershedLayer;
var elevationBandLayers = [];
var outletMarker;
var requestedPointMarker;
var visibleRequestedPointMarker;
var visibleSnappedPointMarker;

function clearVisiblePointMarkers() {
    if (visibleRequestedPointMarker && map.hasLayer(visibleRequestedPointMarker)) {
        map.removeLayer(visibleRequestedPointMarker);
    }
    if (visibleSnappedPointMarker && map.hasLayer(visibleSnappedPointMarker)) {
        map.removeLayer(visibleSnappedPointMarker);
    }
    visibleRequestedPointMarker = null;
    visibleSnappedPointMarker = null;
}

function renderVisiblePointMarkers(requestLat, requestLng, snappedLat, snappedLng) {
    clearVisiblePointMarkers();

    if (isValidCoordinatePair(requestLat, requestLng)) {
        visibleRequestedPointMarker = L.circleMarker([requestLat, requestLng], {
            pane: 'hydro-points-pane',
            color: '#003366',
            weight: 2,
            radius: 7,
            fillColor: '#0074D9',
            fillOpacity: 1
        }).addTo(map);
    }

    if (isValidCoordinatePair(snappedLat, snappedLng)) {
        visibleSnappedPointMarker = L.circleMarker([snappedLat, snappedLng], {
            pane: 'hydro-points-pane',
            color: '#660000',
            weight: 2,
            radius: 7,
            fillColor: '#ff0000',
            fillOpacity: 1
        }).addTo(map);
    }
}

// Function to update map location info in sidebar
function updateMapLocationInfo() {
    document.getElementById('pointer-info').innerHTML =
        '<div class="location-item">' +
        '<span class="location-icon">📍</span> <strong>Mouse Position (lat, lon):</strong> 0, 0' +
        '</div>' +
        '<div class="location-item">' +
        '<span class="location-icon">🔍</span> <strong>Zoom level:</strong> ' + map.getZoom() +
        '</div>';
}

// Update location info when map loads (show 0, 0 initially)
map.whenReady(function() {
    updateMapLocationInfo();
});

// Update zoom level when map is zoomed (but keep coordinates as they are)
map.on('zoomend', function() {
    // Only update zoom level, preserve current coordinate display
    var currentContent = document.getElementById('pointer-info').innerHTML;
    var zoomMatch = currentContent.match(/<strong>Zoom level:<\/strong>\s*\d+/);
    if (zoomMatch) {
        document.getElementById('pointer-info').innerHTML = currentContent.replace(
            /<strong>Zoom level:<\/strong>\s*\d+/,
            '<strong>Zoom level:</strong> ' + map.getZoom()
        );
    }
});

// Track mouse movement over the map
map.on('mousemove', function(e) {
    // Don't update coordinates if watershed info is displayed
    if (watershedInfoDisplayed) return;
    
    var lat = e.latlng.lat;
    var lng = e.latlng.lng;
    
    document.getElementById('pointer-info').innerHTML =
        '<div class="location-item">' +
        '<span class="location-icon">📍</span> <strong>Mouse Position (lat, lon):</strong> ' + lat.toFixed(4) + ', ' + lng.toFixed(4) +
        '</div>' +
        '<div class="location-item">' +
        '<span class="location-icon">🔍</span> <strong>Zoom level:</strong> ' + map.getZoom() +
        '</div>';
});

// Reset coordinates when mouse leaves the map
map.on('mouseout', function() {
    // Don't update coordinates if watershed info is displayed
    if (watershedInfoDisplayed) return;
    
    document.getElementById('pointer-info').innerHTML =
        '<div class="location-item">' +
        '<span class="location-icon">📍</span> <strong>Mouse Position (lat, lon):</strong> 0, 0' +
        '</div>' +
        '<div class="location-item">' +
        '<span class="location-icon">🔍</span> <strong>Zoom level:</strong> ' + map.getZoom() +
        '</div>';
});

function closeAnyOpenPopup() {
    try {
        map.closePopup();
    } catch (e) {
        // no-op: defensive cleanup
    }
}


map.on('click', function(e) {
    // If delineation is in progress, do NOT move the popup or marker, just keep it at the initial point
    if (isDelineationInProgress) {
        // If the popup somehow closed, reopen it at the original marker
        if (requestedPointMarker && !requestedPointMarker.isPopupOpen()) {
            var processingContent = '<div class="custom-popup">' +
                '<div class="processing-text">' +
                '<div class="spinner"></div>' +
                'Delineating...' +
                '</div>' +
                '<button class="cancel-btn" onclick="event.stopPropagation(); cancelDelineation(); return false;">Cancel</button>' +
                '</div>';
            var processingPopupOptions = {
                closeButton: false,
                closeOnClick: false,
                autoClose: false,
                closeOnEscapeKey: false
            };
            var popup = requestedPointMarker.getPopup();
            if (!popup) {
                requestedPointMarker.bindPopup(processingContent, processingPopupOptions);
                popup = requestedPointMarker.getPopup();
            } else {
                popup.options.closeButton = false;
                popup.options.closeOnClick = false;
                popup.options.autoClose = false;
                popup.options.closeOnEscapeKey = false;
                popup.setContent(processingContent);
                popup.update();
            }
            requestedPointMarker.openPopup();
            popup.off('remove');
        }
        return;
    }

    var lat = e.latlng.lat;
    var lng = e.latlng.lng;

    // Show requested point marker
    if (requestedPointMarker) {
        clearRequestedPointMarker();
    }
    showRequestedPoint(lat, lng);
    var markerForPopup = requestedPointMarker;

    // Show first popup with "Upstream watershed" and "Delineate!" button
    var popupContent = '<div class="custom-popup">' +
        '<h4>Upstream watershed</h4>' +
        '<button class="delineate-btn" onclick="event.stopPropagation(); startDelineation(' + lat + ', ' + lng + '); return false;">Delineate!</button>' +
        '</div>';

    markerForPopup.bindPopup(popupContent).openPopup();
    // Remove marker if popup is closed (cross icon)
    var popup = markerForPopup.getPopup();
    if (popup) {
        popup.off('remove'); // Remove any previous handler
        var removeHandler = function() {
            if (currentDelineationRequest || abortController) {
                popup.off('remove', removeHandler);
                return;
            }
            setTimeout(function() {
                clearRequestedPointMarker(markerForPopup);
            }, 0);
            popup.off('remove', removeHandler);
        };
        popup.on('remove', removeHandler);
    }
});

// Global variable to track current delineation request
var currentDelineationRequest = null;
var abortController = null;
var delineationTimeoutId = null;
var delineationAbortReason = null;
var DELINEATION_REQUEST_TIMEOUT_MS = 5 * 60 * 1000;
var isDelineationInProgress = false;
var currentClickedLat = null;
var currentClickedLng = null;
var watershedInfoDisplayed = false;
var currentWatershedGeojson = null;

function clearDelineationTimeout() {
    if (delineationTimeoutId) {
        clearTimeout(delineationTimeoutId);
        delineationTimeoutId = null;
    }
}

function clearRequestedPointMarker(expectedMarker) {
    var markerToClear = expectedMarker || requestedPointMarker;
    if (!markerToClear) {
        return;
    }

    // If an expected marker is provided, avoid clearing a newer active marker.
    if (expectedMarker && requestedPointMarker && requestedPointMarker !== expectedMarker) {
        if (map.hasLayer(expectedMarker)) {
            try {
                expectedMarker.unbindPopup();
            } catch (e) {
                // no-op: defensive cleanup
            }
            map.removeLayer(expectedMarker);
        }
        return;
    }

    if (requestedPointMarker === markerToClear) {
        requestedPointMarker = null;
    }

    try {
        markerToClear.unbindPopup();
    } catch (e) {
        // no-op: defensive cleanup
    }

    if (map.hasLayer(markerToClear)) {
        map.removeLayer(markerToClear);
    }
}


function isValidCoordinatePair(lat, lng) {
    return Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180;
}

function startDelineation(lat, lng, isAutomatic = false) {
    if (!isValidCoordinatePair(lat, lng)) {
        // document.getElementById('result').innerHTML = "<span style='color:red;'>Invalid coordinates for delineation.</span>";
        console.error('Invalid coordinates for delineation.');
        return;
    }

    if (isDelineationInProgress) {
        return;
    }
    isDelineationInProgress = true;

    // Store the clicked coordinates for later use
    currentClickedLat = lat;
    currentClickedLng = lng;

    closeAnyOpenPopup();
    
    // Immediately remove previous catchment, overlays, and markers before new delineation
    if (watershedLayer) {
        map.removeLayer(watershedLayer);
        watershedLayer = null;
    }
    if (outletMarker) {
        map.removeLayer(outletMarker);
        outletMarker = null;
    }
    if (elevationBandLayers && elevationBandLayers.length > 0) {
        elevationBandLayers.forEach(function(layer) {
            map.removeLayer(layer);
        });
        elevationBandLayers = [];
    }
    clearVisiblePointMarkers();
    watershedInfoDisplayed = false;
    currentWatershedGeojson = null;
    if (window.elevationLegendControl) {
        map.removeControl(window.elevationLegendControl);
    }
    var legendGroup = document.getElementById('legend-group');
    if (legendGroup) legendGroup.style.display = 'none';
    
    // We'll no longer show "Processing..." in the result div since we have it in the popup
    // document.getElementById('result').innerHTML = "";

    // Ensure clicked-point marker always exists before popup operations
    if (!requestedPointMarker || !map.hasLayer(requestedPointMarker)) {
        requestedPointMarker = L.circleMarker([lat, lng], {
            color: 'blue',
            radius: 8,
            fillColor: 'blue',
            fillOpacity: 0.8
        }).addTo(map);
    } else {
        requestedPointMarker.setLatLng([lat, lng]);
    }
    
    // Update popup to show "Delineating..." with cancel button
    var processingContent = '<div class="custom-popup">' +
        '<div class="processing-text">' +
        '<div class="spinner"></div>' +
        'Delineating...' +
        '</div>' +
        '<button class="cancel-btn" onclick="event.stopPropagation(); cancelDelineation(); return false;">Cancel</button>' +
        '</div>';
    var processingPopupOptions = {
        closeButton: false,
        closeOnClick: false,
        autoClose: false,
        closeOnEscapeKey: false
    };
    
    // Get the popup element and update its content directly
    var popup = requestedPointMarker.getPopup();
    if (!popup) {
        // If no popup exists (automatic mode), create one
        requestedPointMarker.bindPopup(processingContent, processingPopupOptions);
        popup = requestedPointMarker.getPopup();
    } else {
        popup.options.closeButton = false;
        popup.options.closeOnClick = false;
        popup.options.autoClose = false;
        popup.options.closeOnEscapeKey = false;
        popup.setContent(processingContent);
        popup.update();
    }
    
    // Open the popup if it's not already open
    if (!requestedPointMarker.isPopupOpen()) {
        requestedPointMarker.openPopup();
    }
    
    // During processing, cancellation is allowed only via the Cancel button.
    popup.off('remove');

    var method = 'vector'; // Default to vector method
    var precision = 'high'; // Default to high precision
    
    // Create an AbortController to cancel the request if needed
    abortController = new AbortController();
    delineationAbortReason = null;
    clearDelineationTimeout();
    delineationTimeoutId = window.setTimeout(function() {
        if (abortController) {
            delineationAbortReason = 'timeout';
            abortController.abort();
        }
    }, DELINEATION_REQUEST_TIMEOUT_MS);
    
    // Store the request so we can cancel it if needed
    currentDelineationRequest = fetch("/delineation/api/delineate/", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": window.CSRF_TOKEN
        },
        body: JSON.stringify({ latitude: lat, longitude: lng, method: method, precision: precision }),
        signal: abortController.signal
    })
    .then(async response => {
        let data;
        try {
            data = await response.json();
            // console.log('Full response data:', data); // Log full response
            // console.log('Response keys:', Object.keys(data));
            // console.log('data.success:', data.success);
            // console.log('data.watershed_geojson exists:', !!data.watershed_geojson);
            // console.log('data.outlet_coords:', data.outlet_coords);
        } catch (err) {
            // document.getElementById('result').innerHTML = `<span style='color:red;'>Server returned invalid JSON. Status: ${response.status}</span>`;
            console.error('Server returned invalid JSON. Status:', response.status);
            console.error('JSON parse error:', err);
            throw err;
        }
        
        // Check if the operation was cancelled during the request
        if (abortController && abortController.signal.aborted) {
            // console.log('Operation was cancelled, ignoring response');
            return;
        }
        
        // Clear the popup close handler immediately to prevent interference
        if (requestedPointMarker && requestedPointMarker.getPopup()) {
            requestedPointMarker.getPopup().off('remove');
            // console.log('Popup close handler removed to prevent interference');
        }
        
        if (!response.ok) {
            // document.getElementById('result').innerHTML = `<span style='color:red;'>Error ${response.status}: ${data.error || response.statusText}</span>`;
            console.error('HTTP error:', data.error);
            throw new Error(data.error || response.statusText);
        }
        
        // Log full response data for debugging
        // console.log('Complete response data:', data);
        // console.log('Response has elevation_stats?', !!data.elevation_stats);
        // if (data.elevation_stats) {
        //     console.log('elevation_stats keys:', Object.keys(data.elevation_stats));
        //     console.log('Has areas_below_threshold?', !!data.elevation_stats.areas_below_threshold);
        //     if (data.elevation_stats.areas_below_threshold) {
        //         console.log('areas_below_threshold length:', data.elevation_stats.areas_below_threshold.length);
        //     }
        // }
        

        // Clear any existing watershed layers before adding new ones
        if (watershedLayer) {
            map.removeLayer(watershedLayer);
            watershedLayer = null;
        }
        if (outletMarker) {
            map.removeLayer(outletMarker);
            outletMarker = null;
        }
        if (elevationBandLayers && elevationBandLayers.length > 0) {
            elevationBandLayers.forEach(function(layer) {
                map.removeLayer(layer);
            });
            elevationBandLayers = [];
        }

        // --- Add elevation band polygons as colored overlays ---
        if (data.elevation_band_polygons && Array.isArray(data.elevation_band_polygons) && data.elevation_band_polygons.length > 0) {
            var bandStyles = {
                3000: { color: '#e65100', weight: 3, fillColor: '#fdae61', fillOpacity: 0.75 },
                5000: { color: '#b319d2ff', weight: 2, fillColor: '#dfabe9ff', fillOpacity: 0.50 }
            };
            var sortedBands = data.elevation_band_polygons.slice().sort(function(a, b) {
                return a.threshold - b.threshold;
            });
            sortedBands.forEach(function(band) {
                if (band && band.geometry && band.threshold) {
                    var style = bandStyles[band.threshold] || { color: '#cccccc', weight: 2, fillColor: '#cccccc', fillOpacity: 0.2 };
                    var bandLayer = L.geoJSON(band.geometry, {
                        style: style,
                        interactive: false
                    });
                    bandLayer.addTo(map);
                    elevationBandLayers.push(bandLayer);
                }
            });
        }

        if (data.success === true && data.watershed_geojson) {
            try {
                if (!data.watershed_geojson.geometry) {
                    throw new Error('GeoJSON has no geometry property');
                }
                if (!data.watershed_geojson.geometry.coordinates) {
                    throw new Error('GeoJSON geometry has no coordinates');
                }
                if (!Array.isArray(data.watershed_geojson.geometry.coordinates)) {
                    throw new Error('GeoJSON coordinates is not an array');
                }

                var geoJsonData;
                if (data.watershed_geojson.type === 'Feature') {
                    geoJsonData = {
                        type: "FeatureCollection",
                        features: [data.watershed_geojson]
                    };
                } else if (data.watershed_geojson.type === 'FeatureCollection') {
                    geoJsonData = data.watershed_geojson;
                } else {
                    geoJsonData = {
                        type: "FeatureCollection",
                        features: [{
                            type: "Feature",
                            geometry: data.watershed_geojson,
                            properties: {}
                        }]
                    };
                }

                watershedLayer = L.geoJSON(geoJsonData, {
                    style: function(feature) {
                        return {
                            color: '#0066cc',
                            weight: 4,
                            opacity: 1.0,
                            fillColor: '#66ccff',
                            fillOpacity: 0.18,
                            dashArray: null
                        };
                    },
                    onEachFeature: function(feature, layer) {
                        layer.bindPopup(`
                            <div style="text-align: center;">
                                <strong>🌊 Watershed Boundary</strong><br>
                                <small>Area: ${feature.properties.area_km2 || 'N/A'} km²</small>
                            </div>
                        `);
                        layer.on('click', function(e) {
                            if (isDelineationInProgress) {
                                L.DomEvent.stopPropagation(e);
                                return;
                            }
                            L.DomEvent.stopPropagation(e);
                            if (!e || !e.latlng || !isValidCoordinatePair(e.latlng.lat, e.latlng.lng)) {
                                return;
                            }
                            var clickLat = e.latlng.lat;
                            var clickLng = e.latlng.lng;
                            closeAnyOpenPopup();
                            if (requestedPointMarker) {
                                clearRequestedPointMarker();
                            }
                            requestedPointMarker = L.circleMarker([clickLat, clickLng], {
                                color: 'blue',
                                radius: 8,
                                fillColor: 'blue',
                                fillOpacity: 0.8
                            }).addTo(map);
                            var markerForPopup = requestedPointMarker;
                            var popupContent = '<div class="custom-popup">' +
                                '<h4>Upstream watershed</h4>' +
                                '<p style="font-size: 0.9em; margin: 5px 0;">Click inside existing watershed to delineate sub-catchment</p>' +
                                '<button class="delineate-btn" onclick="event.stopPropagation(); startDelineation(' + clickLat + ', ' + clickLng + '); return false;">Delineate !</button>' +
                                '</div>';
                            markerForPopup.bindPopup(popupContent).openPopup();
                            var popup = markerForPopup.getPopup();
                            if (popup) {
                                popup.off('remove');
                                var removeHandler = function() {
                                    setTimeout(function() {
                                        clearRequestedPointMarker(markerForPopup);
                                    }, 0);
                                    popup.off('remove', removeHandler);
                                };
                                popup.on('remove', removeHandler);
                            }
                        });
                    }
                });
                if (watershedLayer.getLayers().length === 0) {
                    throw new Error('No features were created from GeoJSON');
                }
                watershedLayer.addTo(map);
                try {
                    var bounds = watershedLayer.getBounds();
                    if (bounds.isValid()) {
                        map.fitBounds(bounds, { padding: [50, 50] });
                    }
                } catch (boundsErr) {}
                setTimeout(function() {
                    map.invalidateSize();
                }, 100);
                setTimeout(function() {}, 100);
            } catch (geojsonErr) {
                // document.getElementById('result').innerHTML = `<span style='color:red;'>Error rendering GeoJSON: ${geojsonErr.message}</span>`;
                console.error('Error rendering GeoJSON:', geojsonErr);
                return;
            }

            // --- Ensure requested point marker is visible ---
            if (requestedPointMarker) {                // Move marker to currentClickedLat/lng and re-add if needed
                requestedPointMarker.setLatLng([currentClickedLat, currentClickedLng]);
                if (!map.hasLayer(requestedPointMarker)) {
                    requestedPointMarker.addTo(map);
                }
            } else {
                requestedPointMarker = L.circleMarker([currentClickedLat, currentClickedLng], {
                    color: 'blue',
                    radius: 8,
                    fillColor: 'blue',
                    fillOpacity: 0.8
                }).addTo(map);
            }

            // --- Ensure snapped outlet marker is visible ---
            if (data.outlet_coords && Array.isArray(data.outlet_coords) && data.outlet_coords.length === 2) {
                try {
                    var markerOutletLat = Number(data.outlet_coords[1]);
                    var markerOutletLng = Number(data.outlet_coords[0]);
                    if (!isValidCoordinatePair(markerOutletLat, markerOutletLng)) {
                        throw new Error('Invalid outlet coordinates');
                    }
                    if (outletMarker) {
                        outletMarker.setLatLng([markerOutletLat, markerOutletLng]);
                        if (!map.hasLayer(outletMarker)) {
                            outletMarker.addTo(map);
                        }
                    } else {
                        outletMarker = L.circleMarker([markerOutletLat, markerOutletLng], {
                            color: 'red',
                            radius: 10,
                            fillColor: 'red',
                            fillOpacity: 0.8,
                            weight: 2
                        }).addTo(map);
                    }
                } catch (outletErr) {}
            }

            // Draw persistent markers that are independent from popup lifecycle.
            var persistentOutletLat = data.outlet_coords && data.outlet_coords.length === 2 ? Number(data.outlet_coords[1]) : null;
            var persistentOutletLng = data.outlet_coords && data.outlet_coords.length === 2 ? Number(data.outlet_coords[0]) : null;
            renderVisiblePointMarkers(currentClickedLat, currentClickedLng, persistentOutletLat, persistentOutletLng);

            showElevationLegendOnMap();
            var legendGroup = document.getElementById('legend-group');
            if (legendGroup) legendGroup.style.display = 'block';

            // Success is finalized; disable cancel path before popup cleanup.
            currentDelineationRequest = null;
            abortController = null;

            if (requestedPointMarker) {
                try {
                    var popup = requestedPointMarker.getPopup();
                    if (popup) {
                        popup.off('remove');
                        requestedPointMarker.closePopup();
                        popup.off();
                    }
                    requestedPointMarker.unbindPopup();
                } catch (popupError) {}
            }

            var areaKm2 = data.area_km2 || 0;
            var outletLat = data.outlet_coords && data.outlet_coords.length === 2 ? Number(data.outlet_coords[1]) : 0;
            var outletLng = data.outlet_coords && data.outlet_coords.length === 2 ? Number(data.outlet_coords[0]) : 0;
            var formattedArea = areaKm2.toLocaleString('en-US', {maximumFractionDigits: 0});
            currentWatershedGeojson = data.watershed_geojson;
            watershedInfoDisplayed = true;
            var outletCoordsText = 'N/A';
            if (data.outlet_coords && Array.isArray(data.outlet_coords) && data.outlet_coords.length === 2) {
                if (isValidCoordinatePair(outletLat, outletLng)) {
                    outletCoordsText = outletLat.toFixed(4) + ', ' + outletLng.toFixed(4);
                }
            }
            var elevationHtml = '';
            if (data.elevation_stats && data.elevation_stats.areas_below_threshold) {
                elevationHtml = '<div class="option-group elevation-stats">';
                elevationHtml += '<h4>Elevation Analysis:</h4>';
                if (data.elevation_stats.is_fallback) {
                    var warningMessage = 'Estimated elevation values shown. ';
                    if (data.elevation_stats.dem_coverage === 'none') {
                        warningMessage += 'No DEM data available for this watershed.';
                    } else if (data.elevation_stats.dem_coverage === 'minimal') {
                        warningMessage += 'DEM data covers less than 5% of the watershed area.';
                    } else if (data.elevation_stats.dem_coverage === 'partial') {
                        warningMessage += 'DEM data covers less than 50% of the watershed area.';
                    } else if (data.elevation_stats.dem_coverage === 'substantial') {
                        warningMessage += 'DEM data covers ' + 
                            (data.elevation_stats.coverage_percent ? 
                             data.elevation_stats.coverage_percent.toFixed(1) + '%' : 
                             'a substantial portion') + 
                            ' of the watershed area.';
                    }
                    if (data.elevation_stats.dem_coverage !== 'none') {
                        warningMessage += ' For accurate elevation analysis, a complete DEM for Nepal is needed.';
                    }
                    elevationHtml += '<div class="elevation-warning" style="background-color: #fff3cd; color: #856404; padding: 8px; margin-bottom: 10px; border-radius: 4px; font-size: 0.9em;">' +
                        '<strong>⚠️ Note:</strong> ' + warningMessage + 
                        '</div>';
                }
                elevationHtml += '<table class="elevation-table">';
                elevationHtml += '<tr><th>Elevation</th><th>Area (km²)</th><th>Percentage</th></tr>';
                try {
                    if (Array.isArray(data.elevation_stats.areas_below_threshold)) {
                        data.elevation_stats.areas_below_threshold.forEach(function(item) {
                            if (item && typeof item === 'object') {
                                var threshold = item.threshold || 0;
                                var area = (item.area_km2 !== undefined) ? 
                                    parseFloat(item.area_km2).toLocaleString('en-US', {maximumFractionDigits: 1}) : 'N/A';
                                var percentage = (item.percentage !== undefined) ? 
                                    parseFloat(item.percentage).toLocaleString('en-US', {maximumFractionDigits: 1}) : 'N/A';
                                var rowStyle = (item.is_fallback === true) ? ' style="color: #856404; font-style: italic;"' : '';
                                elevationHtml += '<tr' + rowStyle + '><td>Below ' + threshold + 'm</td><td>' + area + '</td><td>' + percentage + '%</td></tr>';
                            }
                        });
                    } else {
                        elevationHtml += '<tr><td colspan="3">Error loading elevation data</td></tr>';
                    }
                } catch (e) {
                    elevationHtml += '<tr><td colspan="3">Error processing elevation data</td></tr>';
                }
                elevationHtml += '</table></div>';
            }
            var sidebarContent =
                '<div class="location-item">' +
                '<span class="location-icon">🎯</span> <strong>Clicked Point (lat, lon):</strong> ' + currentClickedLat.toFixed(4) + ', ' + currentClickedLng.toFixed(4) +
                '</div>' +
                '<div class="location-item">' +
                '<span class="location-icon">📍</span> <strong>Snapped Outlet (lat, lon):</strong> ' + outletCoordsText +
                '</div>' +
                '<div class="location-item">' +
                '<span class="location-icon">🔍</span> <strong>Zoom level:</strong> ' + map.getZoom() +
                '</div>' +
                '<div class="location-item watershed-summary" style="display: flex; align-items: flex-start; margin-top: 10px;">' +
                '<span class="location-icon" style="margin-right: 6px; margin-top: 2px;">🌊</span>' +
                '<div style="display: flex; flex-direction: column;">' +
                '<span style="font-weight: bold; color: #b3e0ff; letter-spacing: 0.5px;">Watershed Summary</span>' +
                '<span style="font-size: 0.98em; color: #fff; margin-top: 2px;">Delineated a watershed of <span style="font-weight: bold; color: #fff;">' + formattedArea + ' km²</span> with an outlet near<br>coordinates: <span style="color: #b3e0ff;">' + (isValidCoordinatePair(outletLat, outletLng) ? (outletLat.toFixed(3) + ', ' + outletLng.toFixed(3)) : 'N/A') + '</span></span>' +
                '</div>' +
                '</div>';
            if (data.elevation_stats && data.elevation_stats.areas_below_threshold) {
                sidebarContent += elevationHtml;
            } else {
                sidebarContent += '<div class="elevation-stats-missing">No elevation data available for this watershed.</div>';
            }
            sidebarContent +=
                '<div style="margin-top: 15px; padding: 10px 0;">' +
                '<button class="download-btn" onclick="downloadWatershed()" title="Download watershed as GeoJSON">' +
                '⬇️ Download GeoJSON' +
                '</button>' +
                '</div>';
            document.getElementById('pointer-info').innerHTML = sidebarContent;
            if (window.innerWidth <= 768) {
                var sidebar = document.getElementById('sidebar');
                if (sidebar) {
                    sidebar.classList.remove('collapsed');
                    sidebar.classList.add('has-watershed');
                    var sidebarToggle = document.getElementById('sidebar-toggle');
                    if (sidebarToggle) {
                        sidebarToggle.innerHTML = '▼';
                    }
                }
            }
            var pointerInfoElement = document.getElementById('pointer-info');
            if (pointerInfoElement) {
                pointerInfoElement.scrollIntoView({ behavior: 'smooth', block: 'end' });
            }
            setTimeout(function() {
                var downloadBtn = document.querySelector('.download-btn');
            }, 100);
            // document.getElementById('result').innerHTML = "";
        } else {
            // document.getElementById('result').innerHTML =
            //     `<span style='color:red;'>Error: ${data.error || 'No watershed_geojson in response'}</span>`;
            console.error('Rendering failed:', data.error);
        }
        
        // Clear request variables after processing
        currentDelineationRequest = null;
        abortController = null;
        clearDelineationTimeout();
        delineationAbortReason = null;
        isDelineationInProgress = false;
        // console.log('Request variables cleared after successful processing');
    })
    .catch(err => {
        // console.error('Fetch error:', err);
        
        // Check if the error is due to request cancellation
        if (err.name === 'AbortError') {
            if (delineationAbortReason === 'timeout') {
                console.log('Delineation timed out after 5 minutes');
            } else {
                console.log('Delineation Cancelled by user');
            }            // document.getElementById('result').innerHTML = "Delineation cancelled.";
        } else if (!err.message.includes('Error')) {
            console.log('AJAX error:', err);
            // document.getElementById('result').innerHTML = `<span style='color:red;'>AJAX error: ${err}</span>`;
        }
        
        if (requestedPointMarker) {
            try {
                clearRequestedPointMarker();
            } catch (popupError) {
                // console.warn('Error closing popup in catch block:', popupError);
            }
        }
        currentDelineationRequest = null;
        abortController = null;
        clearDelineationTimeout();
        delineationAbortReason = null;
        isDelineationInProgress = false;
    });
}

function cancelDelineation() {
    // console.log('Cancel delineation called');
    
    // Abort the current fetch request if it exists
    if (abortController) {
        delineationAbortReason = 'user';
        abortController.abort();
        // console.log('Delineation request aborted');
    }
    
    // Clear the request references and data
    currentDelineationRequest = null;
    abortController = null;
    clearDelineationTimeout();
    delineationAbortReason = null;
    isDelineationInProgress = false;
    currentWatershedGeojson = null;
    
    // Reset watershed info display flag
    watershedInfoDisplayed = false;

    closeAnyOpenPopup();
    
    // Close the popup and remove the marker from the map
    if (requestedPointMarker) {
        clearRequestedPointMarker();
        // console.log('Requested point marker removed');
    }
    
    // Also remove any existing watershed layers and outlet markers
    if (watershedLayer) {
        map.removeLayer(watershedLayer);
        watershedLayer = null;
        // console.log('Watershed layer removed');
    }
    if (outletMarker) {
        map.removeLayer(outletMarker);
        outletMarker = null;
        // console.log('Outlet marker removed');
    }
    clearVisiblePointMarkers();
    
    // Hide the legend since no markers are displayed
    var legendGroup = document.getElementById('legend-group');
    if (legendGroup) legendGroup.style.display = 'none';
    
    // Reset the sidebar to default state
    document.getElementById('pointer-info').innerHTML = 
        '<div class="location-item">' +
        '<span class="location-icon">🎯</span> <strong>Pointer (lat, lon):</strong> -' +
        '</div>' +
        '<div class="location-item">' +
        '<span class="location-icon">🔍</span> <strong>Zoom level:</strong> -' +
        '</div>';
    
    // Update the result display
    // document.getElementById('result').innerHTML = "Delineation cancelled.";\
    // console.log("Delineation cancelled.")
    
}

function enterCoords() {
    const modal = document.getElementById('coord-modal');
    const input = document.getElementById('coord-input');
    const okBtn = document.getElementById('coord-ok');
    const cancelBtn = document.getElementById('coord-cancel');
    
    // Show modal
    modal.style.display = 'block';
    input.focus();
    input.value = '';
    
    // Handle OK button
    okBtn.onclick = function() {
        const coords = input.value.trim();
        if (coords) {
            parseAndSetCoordinates(coords);
        }
        modal.style.display = 'none';
    };
    
    // Handle Cancel button
    cancelBtn.onclick = function() {
        modal.style.display = 'none';
    };
    
    // Handle Enter key
    input.onkeypress = function(e) {
        if (e.key === 'Enter') {
            okBtn.click();
        }
    };
    
    // Handle Escape key
    document.onkeydown = function(e) {
        if (e.key === 'Escape' && modal.style.display === 'block') {
            modal.style.display = 'none';
        }
    };
    
    // Close modal when clicking outside
    modal.onclick = function(e) {
        if (e.target === modal) {
            modal.style.display = 'none';
        }
    };
}

function parseAndSetCoordinates(coordString) {
    // Parse coordinates separated by comma, space, or both
    const coords = coordString.replace(/,/g, ' ').split(/\s+/).filter(c => c.length > 0);
    
    if (coords.length !== 2) {
        alert('Please enter exactly two coordinates (latitude and longitude)');
        return;
    }
    
    const lat = parseFloat(coords[0]);
    const lng = parseFloat(coords[1]);
    
    if (isNaN(lat) || isNaN(lng)) {
        alert('Please enter valid numeric coordinates');
        return;
    }
    
    // Check if coordinates are within Nepal bounds
    if (lat < 26.0 || lat > 31.0 || lng < 80.0 || lng > 89.0) {
        alert('Coordinates must be within Nepal bounds (Latitude: 26-31°N, Longitude: 80-89°E)');
        return;
    }
    
    // Set map view to the entered coordinates
    map.setView([lat, lng], 12);
    
    // Remove any existing temporary marker
    if (window.tempMarker) {
        map.removeLayer(window.tempMarker);
        window.tempMarker = null;
    }
    
    // Remove any existing requested point marker before creating new one
    if (requestedPointMarker) {
        clearRequestedPointMarker();
    }
    
    // Create the requested point marker (same as map click)
    requestedPointMarker = L.circleMarker([lat, lng], {
        color: 'blue',
        radius: 8,
        fillColor: 'blue',
        fillOpacity: 0.8
    }).addTo(map);
    
    console.log('Coordinates entered - starting automatic delineation at:', lat, lng);
    
    // Start delineation automatically after a short delay to allow map to settle
    setTimeout(function() {
        startDelineation(lat, lng, true);
    }, 500);
}
function getLocation() {
    if (navigator.geolocation) {
        // Show loading state
        // document.getElementById('result').innerHTML = "Getting your location...";
        
        navigator.geolocation.getCurrentPosition(function(pos) {
            var lat = pos.coords.latitude;
            var lng = pos.coords.longitude;
            
            // console.log('Current location obtained:', lat, lng);
            
            // Check if coordinates are within Nepal bounds
            if (lat < 26.0 || lat > 31.0 || lng < 80.0 || lng > 89.0) {
                alert('Your current location is outside Nepal bounds. This tool is designed for watersheds within Nepal (Latitude: 26-31°N, Longitude: 80-89°E)');
                console.log('Current location is outside Nepal bounds.');
                // document.getElementById('result').innerHTML = "";
                return;
            }
            
            // Set map view to current location
            map.setView([lat, lng], 12);
            
            // Remove any existing requested point marker before creating new one
            if (requestedPointMarker) {
                clearRequestedPointMarker();
            }
            
            // Create the requested point marker (same as map click and coordinate entry)
            requestedPointMarker = L.circleMarker([lat, lng], {
                color: 'blue',
                radius: 8,
                fillColor: 'blue',
                fillOpacity: 0.8
            }).addTo(map);
            
            // console.log('Current location marker created - starting automatic delineation at:', lat, lng);
            
            // Start delineation automatically after a short delay to allow map to settle
            setTimeout(function() {
                startDelineation(lat, lng, true);
            }, 500);
            
        }, function(error) {
            // Handle geolocation errors
            var errorMessage = "";
            switch(error.code) {
                case error.PERMISSION_DENIED:
                    errorMessage = "Location access denied by user. Please enable location access and try again.";
                    break;
                case error.POSITION_UNAVAILABLE:
                    errorMessage = "Location information is unavailable. Please try again or enter coordinates manually.";
                    break;
                case error.TIMEOUT:
                    errorMessage = "Location request timed out. Please try again.";
                    break;
                default:
                    errorMessage = "An unknown error occurred while getting your location.";
                    break;
            }
            
            alert(errorMessage);
            // document.getElementById('result').innerHTML = "";
            console.error('Geolocation error:', error);
        });
    } else {
        alert("Geolocation is not supported by your browser. Please enter coordinates manually.");
        // document.getElementById('result').innerHTML = "";
    }
}

function downloadWatershed() {
    // console.log('Download button clicked!');
    // console.log('currentWatershedGeojson:', currentWatershedGeojson);
    
    if (!currentWatershedGeojson) {
        alert("No watershed data available for download.");
        return;
    }
    
    try {
        // Create a more complete GeoJSON with metadata
        var downloadData = {
            type: "FeatureCollection",
            features: [
                {
                    type: "Feature",
                    geometry: currentWatershedGeojson.geometry,
                    properties: {
                        name: "Watershed",
                        area_km2: currentWatershedGeojson.properties.area_km2,
                        clicked_latitude: currentClickedLat,
                        clicked_longitude: currentClickedLng,
                        // delineation_method: "Vector Method - MERIT-Hydro",
                        // generated_by: "Nepal Watersheds Portal",
                        generated_date: new Date().toISOString(),
                        coordinate_system: "EPSG:4326 (WGS84)"
                    }
                }
            ]
        };
        
        // console.log('Download data prepared:', downloadData);
        
        // Convert to JSON string
        var jsonString = JSON.stringify(downloadData, null, 2);
        
        // Create blob and download
        var blob = new Blob([jsonString], { type: 'application/json' });
        var url = window.URL.createObjectURL(blob);
        
        // Create download link
        var link = document.createElement('a');
        link.href = url;
        
        // Generate filename with coordinates and timestamp
        var timestamp = new Date().toISOString().slice(0, 19).replace(/:/g, '-');
        var filename = `watershed_${currentClickedLat.toFixed(4)}_${currentClickedLng.toFixed(4)}_${timestamp}.geojson`;
        link.download = filename;
        
        // console.log('Downloading file:', filename);
        
        // Trigger download
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        
        // Clean up URL object
        window.URL.revokeObjectURL(url);
        
        // console.log('Watershed GeoJSON downloaded successfully');
        
    } catch (error) {
        // console.error('Error downloading watershed:', error);
        alert('Error downloading watershed file. Please try again.');
    }
}
