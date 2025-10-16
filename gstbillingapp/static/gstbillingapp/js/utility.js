// Check if the internet is available by trying to load a lightweight resource from a CDN
function checkInternetConnection() {
    var xhr = new XMLHttpRequest();
    xhr.open('GET', 'https://cdnjs.cloudflare.com/ajax/libs/jquery/3.6.0/jquery.min.js', true); // A small JS file from a CDN
    xhr.onload = function() {
        if (xhr.status === 200) {
            // If the request is successful, assume the internet is available
            loadCDNFiles();
        }
    };
    xhr.onerror = function() {
        // If the request fails, assume there's no internet, use local files
        console.log('No internet connection. Using local files.');
    };
    xhr.send();
}

function loadCDNFiles() {
    // Load the CDN links for CSS and JS
    document.getElementById('remove-entry-a').innerHTML = '<i class="fas fa-trash"></i>';
}

// Run the check when the page loads
// checkInternetConnection();