// Global variables
let dischargeChart = null;
let energyChart = null;
let dischargeNavChart = null;
let energyNavChart = null;
let map = null;
let currentStation = null;
let refreshInterval = null;
let lastUpdateTime = null;
let allChartPredictionData = [];

// Navigator state: startPct / endPct are fractions [0,1] of allChartPredictionData
const navState = {
    discharge: { startPct: 0, endPct: 1 },
    energy:    { startPct: 0, endPct: 1 }
};

// AbortControllers so old listeners are fully removed on each re-init
const navAbort = { discharge: null, energy: null };

// Pagination variables for table
let allTableData = [];    // Store all prediction data
let currentTablePage = 0; // Current page (0-based)
let rowsPerPage = 10;     // Number of rows per page

// Auto-refresh every 5 minutes for chart, every 60s for table
const REFRESH_INTERVAL = 5 * 60 * 1000; // 5 minutes
const TABLE_REFRESH_INTERVAL = 60 * 1000; // 60 second
let tableRefreshTimer = null;

// Initialize default dates for observations
function initializeDates() {
    const today = new Date();
    const weekAgo = new Date(today.getTime() - 7 * 24 * 60 * 60 * 1000);
    document.getElementById('endDate').value = today.toISOString().split('T')[0];
    document.getElementById('startDate').value = weekAgo.toISOString().split('T')[0];
}

// (navigator replaces slider — no-op kept for safety)
function updateSliderVisibility() {}

// Show chart error
function showChartError(message) {
    const containers = document.querySelectorAll('.chart-container');
    containers.forEach(container => {
        container.innerHTML = `<div class="error" style="margin: 2rem; text-align: center;">${message}</div>`;
    });
}

// Populate observations table with pagination
function populateObservationsTable(predictions) {
    // Store all data for pagination
    allTableData = predictions || [];
    
    // Calculate total pages
    const totalPages = Math.ceil(allTableData.length / rowsPerPage);
    
    // Ensure current page is valid
    if (currentTablePage >= totalPages) {
        currentTablePage = Math.max(0, totalPages - 1);
    }
    
    // Get data for current page (showing latest data first)
    const reversedData = [...allTableData].reverse(); // Show newest first
    const startIndex = currentTablePage * rowsPerPage;
    const endIndex = startIndex + rowsPerPage;
    const pageData = reversedData.slice(startIndex, endIndex);
    
    const tbody = document.getElementById('observationsTableBody');
    const tableContainer = document.querySelector('.water-level-table');
    tbody.innerHTML = '';
    
    if (pageData.length === 0) {
        tbody.innerHTML = '<tr><td colspan="3" class="loading">No available data.</td></tr>';
        updatePaginationControls(0, 0);
        return;
    }
    
    // Always show exactly rowsPerPage rows, no scrolling needed
    tableContainer.classList.remove('scrollable-table');
    
    pageData.forEach(point => {
        const date = new Date(point.date);
        const dateStr = date.toLocaleDateString();
        const discharge = point.discharge !== undefined ? point.discharge.toFixed(3) : 'N/A';
        const energy = point.energy !== undefined ? point.energy.toFixed(3) : 'N/A';
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${dateStr}</td>
            <td>${discharge}</td>
            <td>${energy}</td>
        `;
        tbody.appendChild(row);
    });
    
    // Add empty rows if necessary to maintain consistent table height
    if (pageData.length < rowsPerPage) {
        const emptyRowsNeeded = rowsPerPage - pageData.length;
        for (let i = 0; i < emptyRowsNeeded; i++) {
            const spacerRow = document.createElement('tr');
            spacerRow.className = 'spacer-row';
            spacerRow.innerHTML = `<td colspan="3">&nbsp;</td>`;
            tbody.appendChild(spacerRow);
        }
    }
    
    // Update pagination controls
    updatePaginationControls(currentTablePage + 1, totalPages);
}

// Update pagination controls display
function updatePaginationControls(currentPage, totalPages) {
    // Try to find existing pagination controls
    let paginationContainer = document.getElementById('tablePagination');
    
    if (!paginationContainer) {
        // Create pagination controls if they don't exist
        paginationContainer = document.createElement('div');
        paginationContainer.id = 'tablePagination';
        paginationContainer.className = 'table-pagination';
        
        // Insert after the table
        const tableContainer = document.querySelector('.water-level-table');
        if (tableContainer && tableContainer.parentNode) {
            tableContainer.parentNode.insertBefore(paginationContainer, tableContainer.nextSibling);
        }
    }
    
    if (totalPages <= 1) {
        paginationContainer.style.display = 'none';
        return;
    }
    
    paginationContainer.style.display = 'flex';
    paginationContainer.innerHTML = `
        <button onclick="previousTablePage()" ${currentPage <= 1 ? 'disabled' : ''} class="pagination-btn">
            ← Previous
        </button>
        <span class="pagination-info">
            Page ${currentPage} of ${totalPages} (${allTableData.length} total records)
        </span>
        <button onclick="nextTablePage()" ${currentPage >= totalPages ? 'disabled' : ''} class="pagination-btn">
            Next →
        </button>
    `;
}

// Navigate to previous page
function previousTablePage() {
    if (currentTablePage > 0) {
        currentTablePage--;
        populateObservationsTable(allTableData);
    }
}

// Navigate to next page  
function nextTablePage() {
    const totalPages = Math.ceil(allTableData.length / rowsPerPage);
    if (currentTablePage < totalPages - 1) {
        currentTablePage++;
        populateObservationsTable(allTableData);
    }
}

// Show latest predictions in table (no date filter)
function showLatestPredictions(stationId) {
    const tbody = document.getElementById('observationsTableBody');
    tbody.innerHTML = '<tr><td colspan="3" class="loading">Loading latest predictions...</td></tr>';
    let apiUrl = `/discharge-prediction/api/stations/${stationId}/telemetry/?predictions_only=true`;
    fetch(apiUrl)
        .then(response => response.json())
        .then(data => {
            if (data.success && data.telemetry_data && data.telemetry_data.predictions && data.telemetry_data.predictions.length > 0) {
                // Load all predictions but display with pagination
                const allPreds = data.telemetry_data.predictions;
                // Sort by date ascending (oldest to newest)
                allPreds.sort((a, b) => new Date(a.date) - new Date(b.date));
                // Reset to first page and populate table with all data
                currentTablePage = 0;
                populateObservationsTable(allPreds);
            } else {
                tbody.innerHTML = '<tr><td colspan="3" class="loading">No available data.</td></tr>';
            }
        })
        .catch(error => {
            // console.error('Error fetching latest predictions:', error);
            tbody.innerHTML = '<tr><td colspan="3" class="loading">Error loading latest predictions</td></tr>';
        });
}

// Auto-refresh disabled — pipeline runs once daily
function startAutoRefresh() {
    // Disabled: data updates once per day at 10:00 AM NPT
}

// Stop auto refresh
function stopAutoRefresh() {
    if (refreshInterval) {
        clearInterval(refreshInterval);
        refreshInterval = null;
    }
    if (tableRefreshTimer) {
        clearInterval(tableRefreshTimer);
        tableRefreshTimer = null;
    }
}

// Calculate scrollbar width and set as CSS variable for responsive tables
function setScrollbarWidthVariable() {
    // Create a temporary div with scrollbar
    const outer = document.createElement('div');
    outer.style.visibility = 'hidden';
    outer.style.overflow = 'scroll';
    document.body.appendChild(outer);
    
    // Create inner div
    const inner = document.createElement('div');
    outer.appendChild(inner);
    
    // Calculate scrollbar width (outer width - inner width)
    const scrollbarWidth = outer.offsetWidth - inner.offsetWidth;
    
    // Remove temporary elements
    document.body.removeChild(outer);
    
    // Set CSS variable
    document.documentElement.style.setProperty('--scrollbar-width', scrollbarWidth + 'px');
    
    return scrollbarWidth;
}

document.addEventListener('DOMContentLoaded', function() {
    // Set scrollbar width variable for responsive tables
    setScrollbarWidthVariable();
    
    // Handle window resize for responsive tables
    window.addEventListener('resize', function() {
        setScrollbarWidthVariable();
    });
    
    initializeMap();
    loadStations();
    startAutoRefresh();
    initializeDates();
    
    // Set up export button
    const exportBtn = document.getElementById('exportDataBtn');
    if (exportBtn) {
        // Remove any existing event listeners to prevent duplicates
        exportBtn.replaceWith(exportBtn.cloneNode(true));
        const newExportBtn = document.getElementById('exportDataBtn');
        
        // Add single click event listener
        newExportBtn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            exportToExcel();
        });
    }
    
    // Show latest predictions if station is selected
    if (window.currentStation) {
        showLatestPredictions(window.currentStation.station_id);
    }

    // Periodic table refresh disabled — data updates once per day
});

// Initialize Leaflet map
function initializeMap() {
    map = L.map('map').setView([28.3949, 84.1240], 6); // Nepal center
    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
    }).addTo(map);
}

// Load available stations
async function loadStations() {
    try {
        const response = await fetch('/discharge-prediction/api/stations/');
        const data = await response.json();
        let stations = [];
        if (Array.isArray(data)) {
            stations = data;
        } else if (data.success && Array.isArray(data.stations)) {
            stations = data.stations;
        }
        if (stations.length > 0) {
            window.stationsData = stations;
            displayStations(stations);
        } else {
            document.getElementById('stationList').innerHTML = 
                '<div class="error">Failed to load stations</div>';
        }
    } catch (error) {
        // console.error('Error loading stations:', error);
        document.getElementById('stationList').innerHTML = 
            '<div class="error">Error loading stations</div>';
    }
}

// Display stations list
function displayStations(stations) {
    const stationList = document.getElementById('stationList');
    
    // Clear existing list
    stationList.innerHTML = '';
    
    stations.forEach(station => {
        // Add to station list (left panel)
        const stationItem = document.createElement('div');
        stationItem.className = 'station-item';
        stationItem.innerHTML = `
            <div class="station-name">${station.name}</div>
            <div class="station-river">${station.river_name}</div>
        `;
        stationItem.addEventListener('click', () => selectStation(station, stationItem));
        stationList.appendChild(stationItem);
    });
    
    // Auto-select first station
    if (stations.length > 0) {
        const firstItem = stationList.querySelector('.station-item');
        selectStation(stations[0], firstItem);
    }
}



// Select a station
async function selectStation(station, element) {
    currentStation = station;
    window.currentStation = station;   // expose to inline scripts

    // Reset calculator whenever station changes
    const calcStart  = document.getElementById('calcStartDate');
    const calcEnd    = document.getElementById('calcEndDate');
    const calcHead   = document.getElementById('calcNetHead');
    const calcHours  = document.getElementById('calcOperatingHours');
    const calcResult = document.getElementById('calcResultCard');
    const calcErr    = document.getElementById('calcError');
    if (calcStart)  calcStart.value  = '';
    if (calcEnd)    calcEnd.value    = '';
    if (calcHead)   calcHead.value   = '';
    if (calcHours)  calcHours.value  = '100';
    if (calcResult) calcResult.style.display = 'none';
    if (calcErr)    calcErr.style.display    = 'none';
    
    // Update UI
    document.querySelectorAll('.station-item').forEach(item => {
        item.classList.remove('active');
    });
    if (element) {
        element.classList.add('active');
    }
    
    // Update title
    document.getElementById('stationTitle').textContent = 
        `${station.name.toUpperCase()} - PREDICTIONS`;
    // Load station details and map (fast/synchronous)
    await loadStationDetails(station);
    updateMapLocation(station);

    // Load chart and monthly forecast in parallel — one fetch each
    const [predictions] = await Promise.all([
        loadPredictionData(station.station_id),
        window.loadMonthlyForecast ? window.loadMonthlyForecast(station.station_id) : Promise.resolve()
    ]);

    // Set date pickers and populate table from already-loaded data (no extra fetches)
    if (predictions && predictions.length > 0) {
        const sorted = [...predictions].sort((a, b) => new Date(a.date) - new Date(b.date));
        document.getElementById('startDate').value = sorted[0].date.split('T')[0];
        document.getElementById('endDate').value = sorted[sorted.length - 1].date.split('T')[0];
        currentTablePage = 0;
        populateObservationsTable(sorted);
    } else {
        initializeDates();
        document.getElementById('observationsTableBody').innerHTML =
            '<tr><td colspan="3" class="loading">No available data.</td></tr>';
    }

    // Load weather summary (non-blocking)
    if (typeof window.loadWeatherSummary === 'function') {
        window.loadWeatherSummary(station);
    }
}

// Load station details
async function loadStationDetails(station) {
    const detailsDiv = document.getElementById('stationDetails');
    detailsDiv.innerHTML = `
        <div class="info-row">
            <span class="info-label">Station ID:</span>
            <span class="info-value">${station.station_id}</span>
        </div>
        <div class="info-row">
            <span class="info-label">River:</span>
            <span class="info-value">${station.river_name}</span>
        </div>
        <div class="info-row">
            <span class="info-label">Coordinates:</span>
            <span class="info-value">${station.coordinates ? 
                `${station.coordinates[0].toFixed(4)}, ${station.coordinates[1].toFixed(4)}` : 
                'N/A'}</span>
        </div>
        <div class="info-row">
            <span class="info-label">Status:</span>
            <span class="info-value">Active</span>
        </div>
    `;
}

// Update map location
function updateMapLocation(station) {
    if (station.coordinates && map) {
        const [lat, lng] = station.coordinates;
        
        // Clear existing markers
        map.eachLayer(layer => {
            if (layer instanceof L.Marker) {
                map.removeLayer(layer);
            }
        });
        
        // Add new marker
        L.marker([lat, lng])
            .addTo(map)
            .bindPopup(`<b>${station.name}</b><br>${station.river_name}`)
            .openPopup();
        
        // Center map on station
        map.setView([lat, lng], 10);
    }
}

// Load prediction data for chart
async function loadPredictionData(stationId) {
    try {
        const refreshIndicator = document.getElementById('refreshIndicator');
        refreshIndicator.textContent = 'Updating...';
        refreshIndicator.classList.add('updating');
        
        // Include explicit date parameters to get all available data
        // Use a wide date range to capture all predictions
        const startDate = '2024-01-01'; // This will cover all historical data from January 2024
        const endDate = '2026-12-31';   // Future date to capture all predictions
        
        const response = await fetch(`/discharge-prediction/api/stations/${stationId}/telemetry/?predictions_only=true&start_date=${startDate}&end_date=${endDate}`);
        const data = await response.json();
        
        if (data.success) {
            createPredictionsChart(data.telemetry_data);
            return data.telemetry_data.predictions || [];
        } else {
            console.error('Error loading prediction data:', data.error);
            showChartError('Failed to load prediction data');
        }
    } catch (error) {
        console.error('Error loading prediction data:', error);
        showChartError('Error loading prediction data');
    } finally {
        const refreshIndicator = document.getElementById('refreshIndicator');
        refreshIndicator.textContent = 'Updated daily at 10:00 AM NPT';
        refreshIndicator.classList.remove('updating');
    }
}

// Create predictions chart
function createPredictionsChart(telemetryData) {
    const dischargeCanvas = document.getElementById('dischargeChart');
    const energyCanvas = document.getElementById('energyChart');
    
    // console.debug('createPredictionsChart: discharge canvas element:', dischargeCanvas);
    // console.debug('createPredictionsChart: energy canvas element:', energyCanvas);
    
    if (!dischargeCanvas || !energyCanvas) {
        showChartError('Chart canvas not found.');
        // console.error('Chart canvas elements not found in DOM.');
        return;
    }
    
    // Process the incoming data regardless of chart state
    // Store all predictions data for slider functionality
    allChartPredictionData = (telemetryData.predictions || []).map(p => {
        // Ensure consistent date format (YYYY-MM-DD)
        const dateStr = p.date.split('T')[0];
        return {
            ...p,
            date: dateStr, // Use string date format consistently
            originalDate: p.date // Keep original for debugging
        };
    });
    
    if (allChartPredictionData.length === 0) {
        showChartError('No prediction data available');
        return;
    }
    
    // Common chart configuration - Define this before any chart operations
    const commonOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                labels: {
                    padding: 20 // Add padding around legend items
                }
            }
        },
        scales: {
            x: {
                type: 'time',
                time: {
                    unit: 'day',
                    displayFormats: {
                        day: 'MMM dd, yyyy'
                    },
                    parser: 'yyyy-MM-dd'
                },
                title: {
                    display: true,
                    text: 'Date',
                    font: {
                        size: 14,
                        weight: 'bold'
                    },
                    color: '#2c3e50',
                    padding: {
                        top: 20,
                        bottom: 0
                    },
                    position: 'end',
                    align: 'center'
                },
                grid: {
                    color: 'rgba(0, 0, 0, 0.1)'
                },
                ticks: {
                    color: '#2c3e50',
                    source: 'data',
                    // Enable autoSkip when many points are displayed
                    autoSkip: true,
                    maxRotation: 0,
                    minRotation: 0,
                    padding: 8, // Add padding to tick labels for better spacing
                    // Ensure the first and last labels are always displayed
                    callback: function(value, index, ticks) {
                        // Format month and date on first line, year on second line
                        const date = new Date(value);
                        const monthDay = date.toLocaleDateString('en-US', {
                            month: 'short',
                            day: 'numeric'
                        });
                        const year = date.getFullYear();
                        return [monthDay, year];
                    },
                    // Always show the first and last ticks
                    afterBuildTicks: function(scale) {
                        if (scale.ticks.length > 0) {
                            // Get the current ticks
                            const ticks = scale.ticks;
                            
                            // Get the first and last data points
                            const dataMin = scale.min;
                            const dataMax = scale.max;
                            
                            // Check if the first and last ticks are already included
                            const firstTickExists = ticks.some(t => t.value === dataMin);
                            const lastTickExists = ticks.some(t => t.value === dataMax);
                            
                            // If not, add them
                            if (!firstTickExists) {
                                ticks.unshift({ value: dataMin });
                            }
                            if (!lastTickExists) {
                                ticks.push({ value: dataMax });
                            }
                            
                            scale.ticks = ticks;
                        }
                    }
                }
            }
        },
        animation: {
            duration: 1000,
            easing: 'easeInOutQuart'
        },
        interaction: {
            intersect: false,
            mode: 'index'
        },
        layout: {
            padding: {
                bottom: 20 // Add extra padding at the bottom to position the Date label properly
            }
        }
    };
    
    // Only get context and create new charts if we need to
    let dischargeCtx, energyCtx;
    try {
        dischargeCtx = dischargeCanvas.getContext('2d');
        energyCtx = energyCanvas.getContext('2d');
    } catch (e) {
        showChartError('Error accessing canvas context.');
        // console.error('Error getting 2d context for charts:', e);
        return;
    }
    if (!dischargeCtx || !energyCtx) {
        showChartError('Canvas context is null.');
        // console.error('Canvas context for charts is null.');
        return;
    }
    
    // Sort predictions by date (ascending)
    allChartPredictionData.sort((a, b) => a.date.localeCompare(b.date));

    // Default navigator window: show the latest 25 points
    const n = allChartPredictionData.length;
    const defaultWindow = Math.min(25, n);
    navState.discharge.startPct = (n - defaultWindow) / n;
    navState.discharge.endPct   = 1;
    navState.energy.startPct    = (n - defaultWindow) / n;
    navState.energy.endPct      = 1;

    // Derive initial visible slice from navigator state
    const startIdx = Math.floor(navState.discharge.startPct * n);
    const endIdx   = Math.min(n, Math.ceil(navState.discharge.endPct * n));
    const predictionData = allChartPredictionData.slice(startIdx, endIdx);

    // Generate arrays of data to ensure all points are included
    const dateLabels = predictionData.map(d => d.date);
    const dischargeValues = predictionData.map(d => d.discharge);
    const energyValues = predictionData.map(d => d.energy);
    
    // Debug log all points being plotted
    // console.log('Plotting data points:');
    // dateLabels.forEach((date, i) => {
    //     console.log(`${date}: discharge=${dischargeValues[i]}, energy=${energyValues[i]}`);
    // });
    
    // Set tick limits based on number of data points
    if (predictionData.length > 20) {
        commonOptions.scales.x.ticks.maxTicksLimit = 12;
    } else if (predictionData.length > 14) {
        commonOptions.scales.x.ticks.maxTicksLimit = 14;
    } else {
        commonOptions.scales.x.ticks.maxTicksLimit = predictionData.length;
    }
    
    // Ensure the afterBuildTicks function is properly set to always show first and last labels
    commonOptions.scales.x.ticks.afterBuildTicks = function(scale) {
        if (scale.ticks.length > 0) {
            // Get the current ticks
            const ticks = scale.ticks;
            
            // Get the first and last data points
            const dataMin = scale.min;
            const dataMax = scale.max;
            
            // Check if the first and last ticks are already included
            const firstTickExists = ticks.some(t => t.value === dataMin);
            const lastTickExists = ticks.some(t => t.value === dataMax);
            
            // If not, add them
            if (!firstTickExists) {
                ticks.unshift({ value: dataMin });
            }
            if (!lastTickExists) {
                ticks.push({ value: dataMax });
            }
            
            scale.ticks = ticks;
        }
    };
    
    // Instead of always destroying and recreating the charts, update them if they exist
    if (dischargeChart) {
        // Update existing discharge chart data
        dischargeChart.data.labels = dateLabels;
        dischargeChart.data.datasets[0].data = dischargeValues;
        dischargeChart.update('none');
    } else {
        // Create new discharge chart
        dischargeChart = new Chart(dischargeCtx, {
            type: 'line',
            data: {
                labels: dateLabels,
                datasets: [
                    {
                        label: 'Predicted Discharge',
                        data: dischargeValues,
                        borderColor: '#e74c3c',
                        backgroundColor: 'rgba(231, 76, 60, 0.1)',
                        borderWidth: 3,
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        pointBackgroundColor: '#e74c3c',
                        pointBorderColor: '#ffffff',
                        pointBorderWidth: 2,
                        fill: true,
                        tension: 0,
                        spanGaps: false
                    }
                ]
            },
            options: {
                ...commonOptions,
                plugins: {
                    legend: {
                        display: false // Hide legend since there's only one dataset
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        backgroundColor: 'rgba(0, 0, 0, 0.8)',
                        titleColor: '#ffffff',
                        bodyColor: '#ffffff',
                        borderColor: '#e74c3c',
                        borderWidth: 1,
                        callbacks: {
                            label: function(context) {
                                const point = predictionData[context.dataIndex];
                                return [
                                    `Discharge: ${context.parsed.y.toFixed(3)} m³/s`,
                                    // `Confidence: ${((point.confidence || 0.9) * 100).toFixed(1)}%`
                                ];
                            }
                        }
                    }
                },
                scales: {
                    ...commonOptions.scales,
                    y: {
                        title: {
                            display: true,
                            text: 'Discharge (m³/s)',
                            font: {
                                size: 14,
                                weight: 'bold'
                            },
                            color: '#2c3e50',
                            padding: {
                                right: 10
                            }
                        },
                        grid: {
                            color: 'rgba(0, 0, 0, 0.1)'
                        },
                        ticks: {
                            color: '#2c3e50'
                        },
                        beginAtZero: true
                    }
                }
            }
        });
    }
    
    // Create or update energy chart
    if (energyChart) {
        // Update existing energy chart data
        energyChart.data.labels = dateLabels;
        energyChart.data.datasets[0].data = energyValues;
        energyChart.update('none');
    } else {
        // Create new energy chart
        energyChart = new Chart(energyCtx, {
            type: 'line',
            data: {
                labels: dateLabels,
                datasets: [
                    {
                        label: 'Predicted Energy',
                        data: energyValues,
                        borderColor: '#2980b9',
                        backgroundColor: 'rgba(41, 128, 185, 0.1)',
                        borderWidth: 3,
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        pointBackgroundColor: '#2980b9',
                        pointBorderColor: '#ffffff',
                        pointBorderWidth: 2,
                        fill: true,
                        tension: 0,
                        spanGaps: false
                    }
                ]
            },
            options: {
                ...commonOptions,
                plugins: {
                    legend: {
                        display: false // Hide legend since there's only one dataset
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        backgroundColor: 'rgba(0, 0, 0, 0.8)',
                        titleColor: '#ffffff',
                        bodyColor: '#ffffff',
                        borderColor: '#2980b9',
                        borderWidth: 1,
                        callbacks: {
                            label: function(context) {
                                return `Energy: ${context.parsed.y.toFixed(3)} MWh`;
                            }
                        }
                    }
                },
                scales: {
                    ...commonOptions.scales,
                    y: {
                        title: {
                            display: true,
                            text: 'Energy (MWh)',
                            font: {
                                size: 14,
                                weight: 'bold'
                            },
                            color: '#2980b9',
                            padding: {
                                right: 10
                            }
                        },
                        grid: {
                            color: 'rgba(0, 0, 0, 0.1)'
                        },
                        ticks: {
                            color: '#2980b9'
                        },
                        beginAtZero: true
                    }
                }
            }
        });
    }

    // Initialise/reinitialise both navigators with current data
    initNavigators();
}

// Refresh observations data
function refreshObservations() {
    if (!currentStation) {
        alert('Please select a station first');
        return;
    }
    const startDate = document.getElementById('startDate').value;
    const endDate = document.getElementById('endDate').value;
    const tbody = document.getElementById('observationsTableBody');
    // Show loading only until valid data is received
    tbody.innerHTML = '<tr><td colspan="3" class="loading">Loading predictions data...</td></tr>';
    if (!startDate || !endDate) {
        // If no dates selected, show latest predictions
        showLatestPredictions(currentStation.station_id);
        return;
    }
    // Use the same API and structure as the graph
    let apiUrl = `/discharge-prediction/api/stations/${currentStation.station_id}/telemetry/?predictions_only=true&start_date=${startDate}&end_date=${endDate}`;
    fetch(apiUrl)
        .then(response => response.json())
        .then(data => {
            // Only render table if valid, non-empty prediction data is received
            if (data.success && data.telemetry_data && Array.isArray(data.telemetry_data.predictions) && data.telemetry_data.predictions.length > 0) {
                // Filter out any predictions with missing or invalid date
                const validPreds = data.telemetry_data.predictions.filter(p => p.date && !isNaN(Date.parse(p.date)));
                if (validPreds.length > 0) {
                    // Sort by date ascending and load all data with pagination
                    validPreds.sort((a, b) => new Date(a.date) - new Date(b.date));
                    // Reset to first page and populate table with all data
                    currentTablePage = 0;
                    populateObservationsTable(validPreds);
                } else {
                    tbody.innerHTML = '<tr><td colspan="3" class="loading">No available data.</td></tr>';
                }
            } else {
                tbody.innerHTML = '<tr><td colspan="3" class="loading">No available data.</td></tr>';
            }
        })
        .catch(error => {
            // console.error('Error fetching predictions:', error);
            tbody.innerHTML = '<tr><td colspan="3" class="loading">Error loading predictions data</td></tr>';
        });
}

// ─── Navigator (Highcharts-style mini chart + draggable window) ───────────────

// Create a small overview Chart.js instance inside a navigator canvas
function createNavigatorChart(canvasId, data, valueKey, borderColor, bgColor) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;
    const existing = Chart.getChart(canvas);
    if (existing) existing.destroy();
    return new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
            labels: data.map(d => d.date),
            datasets: [{
                data: data.map(d => d[valueKey]),
                borderColor: borderColor,
                backgroundColor: bgColor,
                borderWidth: 1.5,
                pointRadius: 0,
                fill: true,
                tension: 0.3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            onResize: () => updateNavWindowUI(valueKey),
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
            scales: {
                x: { display: false },
                y: { display: false, beginAtZero: true }
            },
            animation: false
        }
    });
}

// Apply the current navigator window to the main chart
function applyNavWindow(chartType) {
    const state = navState[chartType];
    const chart = chartType === 'discharge' ? dischargeChart : energyChart;
    if (!chart || !allChartPredictionData.length) return;
    const n        = allChartPredictionData.length;
    const startIdx = Math.max(0, Math.floor(state.startPct * n));
    const endIdx   = Math.min(n, Math.ceil(state.endPct * n));
    const visible  = allChartPredictionData.slice(startIdx, endIdx);
    if (visible.length === 0) return;
    chart.data.labels           = visible.map(d => d.date);
    chart.data.datasets[0].data = visible.map(d => d[chartType]);
    const ticks = chart.options.scales.x.ticks;
    ticks.maxTicksLimit = visible.length > 20 ? 12 : visible.length > 14 ? 14 : visible.length;
    chart.update('none');
    updateNavWindowUI(chartType);
}

// Reposition the navigator window overlay
function updateNavWindowUI(chartType) {
    const prefix    = chartType === 'discharge' ? 'discharge' : 'energy';
    const state     = navState[chartType];
    const navEl     = document.getElementById(prefix + 'Navigator');
    const winEl     = document.getElementById(prefix + 'NavWindow');
    const maskLeft  = document.getElementById(prefix + 'NavMaskLeft');
    const maskRight = document.getElementById(prefix + 'NavMaskRight');
    const labelEl   = document.getElementById(prefix + 'NavLabel');
    if (!navEl || !winEl) return;

    // Always use the container's full offsetWidth so overlays span the entire strip.
    // (Chart.js may set canvas.style.width to a stale px value; navEl is always correct.)
    const W = navEl.offsetWidth;
    // Guard: element not yet rendered — retry after layout
    if (W === 0) { setTimeout(() => updateNavWindowUI(chartType), 50); return; }

    // Clamp state to [0,1] to prevent any float drift
    const sp = Math.max(0, Math.min(state.startPct, 1));
    const ep = Math.max(sp + 0.01, Math.min(state.endPct, 1));
    const left  = sp * W;
    const width = Math.max(20, Math.min((ep - sp) * W, W - left));

    winEl.style.left  = left + 'px';
    winEl.style.width = width + 'px';
    if (maskLeft)  { maskLeft.style.left  = '0';                   maskLeft.style.width  = left + 'px'; }
    if (maskRight) { maskRight.style.left = (left + width) + 'px'; maskRight.style.width = Math.max(0, W - left - width) + 'px'; }
    const n        = allChartPredictionData.length;
    const startIdx = Math.max(0, Math.floor(sp * n));
    const endIdx   = Math.min(n - 1, Math.ceil(ep * n) - 1);
    if (n > 0 && labelEl) {
        const fmt = d => new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
        labelEl.textContent = fmt(allChartPredictionData[startIdx].date) + '  \u2013  ' + fmt(allChartPredictionData[endIdx].date);
    }
}

// Attach drag + wheel-zoom interactions to one navigator
function setupNavigatorDrag(chartType) {
    // Abort & remove all previous listeners for this chartType before re-registering
    if (navAbort[chartType]) { navAbort[chartType].abort(); }
    navAbort[chartType] = new AbortController();
    const signal = navAbort[chartType].signal;

    const prefix      = chartType === 'discharge' ? 'discharge' : 'energy';
    const navEl       = document.getElementById(prefix + 'Navigator');
    const winEl       = document.getElementById(prefix + 'NavWindow');
    const leftHandle  = document.getElementById(prefix + 'NavHandleLeft');
    const rightHandle = document.getElementById(prefix + 'NavHandleRight');
    const mainCanvas  = document.getElementById(prefix + 'Chart');
    if (!navEl || !winEl) return;

    const state = navState[chartType];
    let dragType = null, dragStartX = 0, dragStartState = null;

    function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

    // Mouse-wheel zoom on navigator bar and main chart canvas
    function onWheel(e) {
        e.preventDefault();
        const factor = e.deltaY < 0 ? 0.8 : 1.25;
        let winW = (state.endPct - state.startPct) * factor;
        winW = Math.max(0.04, Math.min(1.0, winW));
        // Anchor to the right edge (latest data) so zoom always focuses on newest points
        const newStart = clamp(state.endPct - winW, 0, 1 - winW);
        state.startPct = newStart;
        state.endPct   = newStart + winW;
        applyNavWindow(chartType);
    }
    navEl.addEventListener('wheel', onWheel, { passive: false, signal });
    if (mainCanvas) mainCanvas.addEventListener('wheel', onWheel, { passive: false, signal });

    function startDrag(e, type) {
        dragType       = type;
        dragStartX     = (e.touches ? e.touches[0] : e).clientX;
        dragStartState = { startPct: state.startPct, endPct: state.endPct };
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup',   onUp);
        document.addEventListener('touchmove', onMove, { passive: false });
        document.addEventListener('touchend',  onUp);
        e.preventDefault();
    }

    function onMove(e) {
        if (!dragType) return;
        const clientX = (e.touches ? e.touches[0] : e).clientX;
        const dx      = (clientX - dragStartX) / navEl.offsetWidth;
        const winW    = dragStartState.endPct - dragStartState.startPct;
        if (dragType === 'body') {
            const ns = clamp(dragStartState.startPct + dx, 0, 1 - winW);
            state.startPct = ns;
            state.endPct   = ns + winW;
        } else if (dragType === 'left') {
            state.startPct = clamp(dragStartState.startPct + dx, 0, dragStartState.endPct - 0.04);
        } else {
            state.endPct   = clamp(dragStartState.endPct + dx, dragStartState.startPct + 0.04, 1);
        }
        applyNavWindow(chartType);
        if (e.cancelable) e.preventDefault();
    }

    function onUp() {
        dragType = null;
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup',   onUp);
        document.removeEventListener('touchmove', onMove);
        document.removeEventListener('touchend',  onUp);
    }

    winEl.addEventListener('mousedown', e => {
        if (e.target === leftHandle || e.target === rightHandle) return;
        startDrag(e, 'body');
    }, { signal });
    winEl.addEventListener('touchstart', e => {
        if (e.target === leftHandle || e.target === rightHandle) return;
        startDrag(e, 'body');
    }, { passive: false, signal });

    if (leftHandle)  leftHandle.addEventListener('mousedown',  e => { e.stopPropagation(); startDrag(e, 'left');  }, { signal });
    if (leftHandle)  leftHandle.addEventListener('touchstart', e => { e.stopPropagation(); startDrag(e, 'left');  }, { passive: false, signal });
    if (rightHandle) rightHandle.addEventListener('mousedown',  e => { e.stopPropagation(); startDrag(e, 'right'); }, { signal });
    if (rightHandle) rightHandle.addEventListener('touchstart', e => { e.stopPropagation(); startDrag(e, 'right'); }, { passive: false, signal });
}

// Initialise (or re-initialise) both navigators with current data
function initNavigators() {
    if (!allChartPredictionData.length) return;

    // Force-reset navigator state so station switch never inherits old position
    const n = allChartPredictionData.length;
    // Use at least 20% of the data as the default window so it's clearly visible
    const defaultWindow = Math.max(Math.ceil(n * 0.2), Math.min(25, n));
    navState.discharge.startPct = (n - defaultWindow) / n;
    navState.discharge.endPct   = 1;
    navState.energy.startPct    = (n - defaultWindow) / n;
    navState.energy.endPct      = 1;

    const dChart = createNavigatorChart(
        'dischargeNavCanvas', allChartPredictionData, 'discharge',
        'rgba(231, 76, 60, 0.9)', 'rgba(231, 76, 60, 0.15)'
    );
    const eChart = createNavigatorChart(
        'energyNavCanvas', allChartPredictionData, 'energy',
        'rgba(41, 128, 185, 0.9)', 'rgba(41, 128, 185, 0.15)'
    );
    dischargeNavChart = dChart;
    energyNavChart    = eChart;

    setupNavigatorDrag('discharge');
    setupNavigatorDrag('energy');

    // Disconnect any previous ResizeObserver before creating a new one
    if (window._navResizeObserver) { window._navResizeObserver.disconnect(); }

    // ResizeObserver fires whenever the container reaches its final layout width,
    // immediately repositioning the nav-window/masks to match the true pixel width.
    const ro = new ResizeObserver(() => {
        // Force Chart.js to remeasure to the new container width
        dChart?.resize();
        eChart?.resize();
        updateNavWindowUI('discharge');
        updateNavWindowUI('energy');
    });
    const dNav = document.getElementById('dischargeNavigator');
    const eNav = document.getElementById('energyNavigator');
    if (dNav) ro.observe(dNav);
    if (eNav) ro.observe(eNav);
    window._navResizeObserver = ro;

    // Initial positioning — run after a RAF so DOM reflow has settled
    requestAnimationFrame(() => {
        dChart?.resize();
        eChart?.resize();
        updateNavWindowUI('discharge');
        updateNavWindowUI('energy');
    });
}

// Export data to Excel
function exportToExcel() {
    // console.log('Export to Excel function called');
    
    if (!currentStation) {
        alert('Please select a station first');
        // For All Data mode: Use actual data displayed on the chart (fixed window of 25 points)
        const allDataWindowSize = 25;
        const startIdx = parseInt(slider.value);
        const endIdx = Math.min(startIdx + allDataWindowSize, allChartPredictionData.length);
        
        if (startIdx >= allChartPredictionData.length) {
            sliderLabel.textContent = 'No data available';
            return;
        }
        
        startDate = new Date(allChartPredictionData[startIdx].date).toLocaleDateString();
        endDate = new Date(allChartPredictionData[endIdx - 1].date).toLocaleDateString();
    } else {
        // For Zoom In-Out mode: Check if we're showing all data (zoom level 0)
        if (chartWindowSize >= allChartPredictionData.length) {
            // At zoom level 0, we're showing all data points
            startDate = new Date(allChartPredictionData[0].date).toLocaleDateString();
            endDate = new Date(allChartPredictionData[allChartPredictionData.length - 1].date).toLocaleDateString();
        } else {
            // Normal behavior with specific window size
            const startIdx = parseInt(slider.value);
            const endIdx = Math.min(startIdx + chartWindowSize, allChartPredictionData.length);
            
            if (startIdx >= allChartPredictionData.length) {
                sliderLabel.textContent = 'No data available';
                return;
            }
            
            startDate = new Date(allChartPredictionData[startIdx].date).toLocaleDateString();
            endDate = new Date(allChartPredictionData[endIdx - 1].date).toLocaleDateString();
        }
    }
    
    sliderLabel.innerHTML = `${startDate} - ${endDate} <span style="opacity:0.7;"></span>`;
}

// Update chart based on slider position
function updateChartWithSlider() {
    if (!allChartPredictionData || allChartPredictionData.length === 0) {
        return;
    }
    
    // In All Data mode, use the slider to navigate through all data points
    // In Zoom In-Out mode, use the normal slider behavior
    
    // Update the slider's maximum value based on current window size
    const slider = document.querySelector('#chartWindowSlider');
    if (!slider) {
        console.error('Slider element not found');
        return;
    }
    
    // Set slider configuration based on mode
    if (viewAllData) {
        // For All Data mode: Use fixed window of 25 points
        const allDataWindowSize = 25;
        const maxSliderValue = Math.max(0, allChartPredictionData.length - allDataWindowSize);
        slider.max = maxSliderValue;
        // Ensure the slider value is within valid range
        slider.value = Math.min(parseInt(slider.value), maxSliderValue);
    } else {
        // For Zoom In-Out mode: Check if we're at zoom level 0 (showing all data)
        if (chartWindowSize >= allChartPredictionData.length) {
            // At zoom level 0, no sliding needed
            slider.max = 0;
            slider.value = 0;
        } else {
            // Normal behavior
            const maxSliderValue = Math.max(0, allChartPredictionData.length - chartWindowSize);
            slider.max = maxSliderValue;
            // Ensure the slider value is within valid range
            slider.value = Math.min(parseInt(slider.value), maxSliderValue);
        }
    }
    
    let visibleData;
    
    // Select the appropriate window size based on current mode
    if (viewAllData) {
        // For All Data mode: Use fixed window of 25 points
        const allDataWindowSize = 25;
        const startIdx = parseInt(slider.value);
        const endIdx = Math.min(startIdx + allDataWindowSize, allChartPredictionData.length);
        visibleData = allChartPredictionData.slice(startIdx, endIdx);
    } else {
        // For Zoom In-Out mode: Check if we're at zoom level 0 (showing all data)
        if (chartWindowSize >= allChartPredictionData.length) {
            // At zoom level 0, show all data points
            visibleData = allChartPredictionData.slice(0);
            // console.log(`Zoom level 0: Showing all ${visibleData.length} data points`);
        } else {
            // Normal behavior with specific window size
            const startIdx = parseInt(slider.value);
            const endIdx = Math.min(startIdx + chartWindowSize, allChartPredictionData.length);
            visibleData = allChartPredictionData.slice(startIdx, endIdx);
            // console.log(`Zoom In-Out mode: showing ${visibleData.length} points from index ${startIdx} to ${endIdx-1}`);
        }
    }
    
    // Update the label showing the date range
    updateSliderLabel();
    
    if (visibleData.length === 0) {
        showChartError('No prediction data available in selected range');
        return;
    }
    
    // Generate arrays of data to ensure all points are included
    const dateLabels = visibleData.map(d => d.date);
    const dischargeValues = visibleData.map(d => d.discharge);
    const energyValues = visibleData.map(d => d.energy);
    
    // Adjust tick configuration based on number of data points
    if (dischargeChart && dischargeChart.options && dischargeChart.options.scales && dischargeChart.options.scales.x && dischargeChart.options.scales.x.ticks) {
        if (visibleData.length > 20) {
            dischargeChart.options.scales.x.ticks.maxTicksLimit = 12;
        } else if (visibleData.length > 14) {
            dischargeChart.options.scales.x.ticks.maxTicksLimit = 14;
        } else {
            dischargeChart.options.scales.x.ticks.maxTicksLimit = visibleData.length;
        }
    }
    
    if (energyChart && energyChart.options && energyChart.options.scales && energyChart.options.scales.x && energyChart.options.scales.x.ticks) {
        if (visibleData.length > 20) {
            energyChart.options.scales.x.ticks.maxTicksLimit = 12;
        } else if (visibleData.length > 14) {
            energyChart.options.scales.x.ticks.maxTicksLimit = 14;
        } else {
            energyChart.options.scales.x.ticks.maxTicksLimit = visibleData.length;
        }
    }
    
    // Update discharge chart if it exists
    if (dischargeChart) {
        dischargeChart.data.labels = dateLabels;
        dischargeChart.data.datasets[0].data = dischargeValues;
        dischargeChart.update('none'); // Using 'none' animation mode for immediate update
    }
    
    // Update energy chart if it exists
    if (energyChart) {
        energyChart.data.labels = dateLabels;
        energyChart.data.datasets[0].data = energyValues;
        energyChart.update('none');
    }
    
    // If either chart doesn't exist, create them both
    if (!dischargeChart || !energyChart) {
        createPredictionsChart({
            predictions: visibleData
        });
    }
}

// Toggle between "View All Data" and "View Window Data" modes
function toggleViewMode() {
    const toggleCheckbox = document.getElementById('viewModeToggle');
    if (!toggleCheckbox) return;
    
    // For checkbox, checked = Window View (interactive mode), unchecked = All Data view
    viewAllData = !toggleCheckbox.checked;
    
    // Update chart containers cursor style
    const chartContainers = document.querySelectorAll('.chart-container');
    chartContainers.forEach(container => {
        // For Zoom In-Out mode: grab cursor, for All Data mode: default cursor
        container.style.cursor = viewAllData ? 'default' : 'grab';
    });
    
    // Update slider configuration based on the current mode
    const slider = document.getElementById('chartWindowSlider');
    if (slider && allChartPredictionData.length > 0) {
        if (viewAllData) {
            // All Data mode: Use 25 data points
            const allDataWindowSize = 25;
            
            // Set slider maximum to allow scrolling through all data
            slider.max = Math.max(0, allChartPredictionData.length - allDataWindowSize);
            
            // Reset to show the most recent data
            slider.value = slider.max;
        } else {
            // Zoom In-Out mode: Check if we're showing all data (zoom level 0)
            if (chartWindowSize >= allChartPredictionData.length) {
                // At zoom level 0, no sliding needed
                slider.max = 0;
                slider.value = 0;
            } else {
                // Normal sliding window
                const maxSliderValue = Math.max(0, allChartPredictionData.length - chartWindowSize);
                slider.max = maxSliderValue;
                slider.value = Math.min(slider.value, maxSliderValue);
            }
        }
    }
    
    // Update slider visibility
    updateSliderVisibility();
    
    // Redraw charts with appropriate data
    if (allChartPredictionData.length > 0) {
        updateChartBasedOnViewMode();
    }
}

// Update chart based on current view mode
function updateChartBasedOnViewMode() {
    // Instead of calling separate functions that might destroy and recreate the charts,
    // we'll update the chart data directly based on the view mode
    
    if (!allChartPredictionData || allChartPredictionData.length === 0) {
        return;
    }
    
    let dataToShow;
    if (viewAllData) {
        // For All Data mode: Use sliding window of 25 most recent points
        const slider = document.getElementById('chartWindowSlider');
        if (!slider) return;
        
        const allDataWindowSize = 25;
        const startIdx = parseInt(slider.value);
        const endIdx = Math.min(startIdx + allDataWindowSize, allChartPredictionData.length);
        dataToShow = allChartPredictionData.slice(startIdx, endIdx);
    } else {
        // For Zoom In-Out mode: Check if we're at zoom level 0 (showing all data)
        const slider = document.getElementById('chartWindowSlider');
        if (!slider) return;
        
        if (chartWindowSize >= allChartPredictionData.length) {
            // At zoom level 0, show all data points
            dataToShow = allChartPredictionData.slice(0);
            // console.log(`Zoom level 0: Showing all ${dataToShow.length} data points`);
        } else {
            // Normal sliding window based on chartWindowSize
            const startIdx = parseInt(slider.value);
            const endIdx = Math.min(startIdx + chartWindowSize, allChartPredictionData.length);
            dataToShow = allChartPredictionData.slice(startIdx, endIdx);
            // console.log(`Zoom In-Out mode: showing ${dataToShow.length} points from index ${startIdx} to ${endIdx-1}`);
        }
    }
    
    // Update slider visibility
    updateSliderVisibility();
    
    // Generate arrays of data for the charts
    const dateLabels = dataToShow.map(d => d.date);
    const dischargeValues = dataToShow.map(d => d.discharge);
    const energyValues = dataToShow.map(d => d.energy);
    
    // Adjust tick configuration based on number of data points
    if (dischargeChart && dischargeChart.options && dischargeChart.options.scales && dischargeChart.options.scales.x && dischargeChart.options.scales.x.ticks) {
        if (dataToShow.length > 20) {
            dischargeChart.options.scales.x.ticks.maxTicksLimit = 12;
        } else if (dataToShow.length > 14) {
            dischargeChart.options.scales.x.ticks.maxTicksLimit = 14;
        } else {
            dischargeChart.options.scales.x.ticks.maxTicksLimit = dataToShow.length;
        }
    }
    
    if (energyChart && energyChart.options && energyChart.options.scales && energyChart.options.scales.x && energyChart.options.scales.x.ticks) {
        if (dataToShow.length > 20) {
            energyChart.options.scales.x.ticks.maxTicksLimit = 12;
        } else if (dataToShow.length > 14) {
            energyChart.options.scales.x.ticks.maxTicksLimit = 14;
        } else {
            energyChart.options.scales.x.ticks.maxTicksLimit = dataToShow.length;
        }
    }
    
    // Update discharge chart if it exists
    if (dischargeChart) {
        dischargeChart.data.labels = dateLabels;
        dischargeChart.data.datasets[0].data = dischargeValues;
        dischargeChart.update('none'); // Update immediately without animation
    }
    
    // Update energy chart if it exists
    if (energyChart) {
        energyChart.data.labels = dateLabels;
        energyChart.data.datasets[0].data = energyValues;
        energyChart.update('none'); // Update immediately without animation
    }
    
    // If either chart doesn't exist, create both via the standard function
    if (!dischargeChart || !energyChart) {
        createPredictionsChart({
            predictions: dataToShow
        });
    }
}

// Set up chart interaction functionality (dragging and zooming)
function setupChartDragging() {
    // Get all chart containers
    const chartContainers = document.querySelectorAll('.chart-container');
    
    if (chartContainers.length === 0) return;
    
    // Active chart container that initiated the drag
    let activeContainer = null;
    
    // Update cursor style for all chart containers
    chartContainers.forEach(container => {
        container.style.cursor = viewAllData ? 'default' : 'grab';
    });
    
    // Mouse wheel event - zoom in and out
    chartContainers.forEach(container => {
        container.addEventListener('wheel', function(e) {
            // Only enable zooming in Zoom In-Out mode
            if (viewAllData) return;
            
            e.preventDefault(); // Prevent page scrolling
            
            // Determine zoom direction
            const zoomIn = e.deltaY < 0;
            
            // Calculate current center position of visible data
            const slider = document.querySelector('#chartWindowSlider');
            if (!slider) return;
            
            const currentStart = parseInt(slider.value);
            const currentMiddle = currentStart + (chartWindowSize / 2);
            
            // Adjust window size
            if (zoomIn) {
                // Zoom in - decrease window size
                chartWindowSize = Math.max(minChartWindowSize, chartWindowSize - 2);
            } else {
                // Zoom out - increase window size
                // Check if we're about to reach maxChartWindowSize (zoom level 0)
                if (chartWindowSize + 2 >= maxChartWindowSize) {
                    // At zoom level 0, show all data points
                    chartWindowSize = allChartPredictionData.length;
                    // console.log("Zoom level 0: Showing all data points");
                } else {
                    // Normal zoom out
                    chartWindowSize = Math.min(maxChartWindowSize, chartWindowSize + 2);
                }
            }
            
            // If at maximum window size (zoom level 0), start from the beginning to show all data
            let newStart;
            if (chartWindowSize >= allChartPredictionData.length) {
                newStart = 0; // Start from the beginning to show all data
                slider.max = 0; // No sliding needed when showing all data
            } else {
                // Normal case: recalculate slider position to maintain center point
                newStart = Math.round(currentMiddle - (chartWindowSize / 2));
                const maxSliderValue = Math.max(0, allChartPredictionData.length - chartWindowSize);
                slider.max = maxSliderValue;
                newStart = Math.max(0, Math.min(maxSliderValue, newStart));
            }
            
            slider.value = newStart;
            
            // Update chart with new window size
            updateChartWithSlider();
            
            // Show zoom level indicator
            showZoomNotification(container, zoomIn);
        }, { passive: false });
    });
    
    // Mouse down event - start tracking drag
    chartContainers.forEach(container => {
        container.addEventListener('mousedown', function(e) {
            // Only enable dragging in Zoom In-Out mode
            if (viewAllData) return;
            
            isDragging = true;
            activeContainer = container;
            dragStartX = e.clientX;
            
            // Get current slider value
            const slider = document.getElementById('chartWindowSlider');
            if (slider) {
                currentSliderValue = parseInt(slider.value);
            }
            
            // Change cursor and add dragging class for visual feedback
            chartContainers.forEach(c => c.classList.add('dragging'));
            
            // Prevent text selection during drag
            e.preventDefault();
        });
    });
    
    // Mouse move event - update chart position
    document.addEventListener('mousemove', function(e) {
        if (!isDragging) return;
        
        const slider = document.querySelector('#chartWindowSlider');
        if (!slider) return;
        
        const sliderMax = parseInt(slider.max);
        const dragDistance = e.clientX - dragStartX;
        
        // Calculate how much to move the slider
        // Negative distance (drag left) → move forward in time
        // Positive distance (drag right) → move backward in time
        const moveAmount = Math.round(-dragDistance / 10); // Adjust sensitivity
        
        // Calculate new slider value with boundaries
        let newValue = currentSliderValue + moveAmount;
        newValue = Math.max(0, Math.min(sliderMax, newValue));
        
        // Update slider and chart if value changed
        if (newValue !== parseInt(slider.value)) {
            slider.value = newValue;
            updateChartWithSlider();
        }
    });
    
    // Mouse up event - stop tracking drag
    document.addEventListener('mouseup', function() {
        if (!isDragging) return;
        
        isDragging = false;
        activeContainer = null;
        chartContainers.forEach(container => {
            container.classList.remove('dragging');
        });
    });
    
    // Mouse leave event - stop tracking drag if cursor leaves the window
    document.addEventListener('mouseleave', function() {
        if (!isDragging) return;
        
        isDragging = false;
        activeContainer = null;
        chartContainers.forEach(container => {
            container.classList.remove('dragging');
        });
    });
    
    // Add touch support for mobile devices
    chartContainers.forEach(container => {
        container.addEventListener('touchstart', function(e) {
            // Only enable touch dragging in Zoom In-Out mode
            if (viewAllData) return;
            
            isDragging = true;
            activeContainer = container;
            dragStartX = e.touches[0].clientX;
            
            const slider = document.getElementById('chartWindowSlider');
            if (slider) {
                currentSliderValue = parseInt(slider.value);
            }
            
            e.preventDefault();
        });
    });
    
    document.addEventListener('touchmove', function(e) {
        if (!isDragging) return;
        
        const slider = document.querySelector('#chartWindowSlider');
        if (!slider) return;
        
        const sliderMax = parseInt(slider.max);
        const dragDistance = e.touches[0].clientX - dragStartX;
        
        const moveAmount = Math.round(-dragDistance / 10);
        let newValue = currentSliderValue + moveAmount;
        newValue = Math.max(0, Math.min(sliderMax, newValue));
        
        if (newValue !== parseInt(slider.value)) {
            slider.value = newValue;
            updateChartWithSlider();
        }
        
        e.preventDefault();
    });
    
    document.addEventListener('touchend', function() {
        isDragging = false;
        activeContainer = null;
        chartContainers.forEach(container => {
            container.classList.remove('dragging');
        });
    });
    
    // Show hint tooltip about drag functionality when in window mode
    const toggleCheckbox = document.querySelector('#viewModeToggle');
    if (toggleCheckbox) {
        toggleCheckbox.addEventListener('change', function() {
            if (this.checked) {
                // Show tooltip when switching to window mode
                const tooltip = document.createElement('div');
                tooltip.className = 'drag-hint';
                tooltip.innerHTML = 'Click and drag left/right to navigate through time<br>Use mouse wheel to zoom in/out';
                tooltip.style.position = 'absolute';
                tooltip.style.bottom = '40px';
                tooltip.style.left = '50%';
                tooltip.style.transform = 'translateX(-50%)';
                tooltip.style.backgroundColor = 'rgba(0,0,0,0.7)';
                tooltip.style.color = 'white';
                tooltip.style.padding = '8px 16px';
                tooltip.style.borderRadius = '4px';
                tooltip.style.zIndex = '1000';
                tooltip.style.fontSize = '14px';
                tooltip.style.textAlign = 'center';
                
                // Add tooltip to the first chart container
                if (chartContainers.length > 0) {
                    chartContainers[0].appendChild(tooltip);
                    
                    // Remove tooltip after a delay
                    setTimeout(() => {
                        if (tooltip.parentNode) {
                            tooltip.parentNode.removeChild(tooltip);
                        }
                    }, 5000);
                }
            }
        });
    }
    
    // Function to show zoom level notification
    function showZoomNotification(container, zoomingIn) {
        // Create notification element if it doesn't exist
        let zoomNotification = container.querySelector('.zoom-notification');
        if (!zoomNotification) {
            zoomNotification = document.createElement('div');
            zoomNotification.className = 'zoom-notification';
            zoomNotification.style.position = 'absolute';
            zoomNotification.style.top = '10px';
            zoomNotification.style.right = '10px';
            zoomNotification.style.backgroundColor = 'rgba(0,0,0,0.6)';
            zoomNotification.style.color = 'white';
            zoomNotification.style.padding = '5px 10px';
            zoomNotification.style.borderRadius = '4px';
            zoomNotification.style.zIndex = '1000';
            zoomNotification.style.fontSize = '12px';
            zoomNotification.style.transition = 'opacity 0.3s';
            container.appendChild(zoomNotification);
        }
        
        // Calculate zoom percentage (inverse of window size)
        const zoomPercentage = Math.round((1 - ((chartWindowSize - minChartWindowSize) / 
                                          (maxChartWindowSize - minChartWindowSize))) * 100);
        
        // Update notification content
        zoomNotification.innerHTML = `<strong>${zoomingIn ? '🔍+' : '🔍-'}</strong> Zoom: ${zoomPercentage}%`;
        zoomNotification.style.opacity = '1';
        
        // Hide notification after delay
        clearTimeout(zoomNotification.fadeTimeout);
        zoomNotification.fadeTimeout = setTimeout(() => {
            zoomNotification.style.opacity = '0';
        }, 1500);
    }
}

// Export data to Excel
function exportToExcel() {
    // console.log('Export to Excel function called');
    
    if (!currentStation) {
        alert('Please select a station first');
        return;
    }
    
    // Use the current date range from the inputs
    const startDate = document.getElementById('startDate').value;
    const endDate = document.getElementById('endDate').value;
    
    if (!startDate || !endDate) {
        alert('Please select both start and end dates');
        return;
    }
    
    // Show loading state by changing button text
    const exportBtn = document.getElementById('exportDataBtn');
    if (!exportBtn) {
        alert('Export button not found');
        return;
    }
    
    const originalText = exportBtn.innerHTML;
    exportBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Exporting...';
    exportBtn.disabled = true;
    
    // Fetch data from API using the selected date range
    const apiUrl = `/discharge-prediction/api/stations/${currentStation.station_id}/telemetry/?predictions_only=true&start_date=${startDate}&end_date=${endDate}`;
    
    fetch(apiUrl)
        .then(response => response.json())
        .then(data => {
            if (!data.success || !data.telemetry_data || !data.telemetry_data.predictions || data.telemetry_data.predictions.length === 0) {
                throw new Error('No data available for selected date range');
            }
            
            // Process the data for export
            const predictions = data.telemetry_data.predictions;
            
            // Create CSV content
            let csvContent = 'Date,Discharge (m³/s),Energy (MWh)\n';
            
            predictions.forEach(item => {
                const date = new Date(item.date).toLocaleDateString();
                const discharge = item.discharge || 0;
                const energy = item.energy || 0;
                
                csvContent += `${date},${discharge.toFixed(3)},${energy.toFixed(3)}\n`;
            });
            
            // Create download link for CSV file
            const encodedUri = encodeURI('data:text/csv;charset=utf-8,' + csvContent);
            const link = document.createElement('a');
            link.setAttribute('href', encodedUri);
            const filename = `${currentStation.name.replace(/ /g, '_')}_discharge_forecast_${startDate}_to_${endDate}.csv`;
            link.setAttribute('download', filename);
            link.style.display = 'none';
            document.body.appendChild(link);
            
            // Trigger download
            link.click();
            
            // Clean up immediately
            setTimeout(() => {
                document.body.removeChild(link);
            }, 100);
        })
        .catch(error => {
            // console.error('Error downloading data:', error);
            alert('Error: ' + (error.message || 'Failed to download data'));
        })
        .finally(() => {
            // Reset button state with a small delay to ensure download started
            setTimeout(() => {
                if (exportBtn) {
                    exportBtn.innerHTML = originalText;
                    exportBtn.disabled = false;
                }
            }, 500);
        });
}

// Make pagination functions globally accessible
window.previousTablePage = previousTablePage;
window.nextTablePage = nextTablePage;

// Cleanup on page unload
window.addEventListener('beforeunload', stopAutoRefresh);
window.addEventListener('beforeunload', function() {
    if (tableRefreshTimer) {
        clearInterval(tableRefreshTimer);
    }
});
