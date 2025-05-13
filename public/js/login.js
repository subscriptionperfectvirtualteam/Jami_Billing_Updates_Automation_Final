// Load saved credentials if available
document.addEventListener('DOMContentLoaded', function() {
    const savedCredentials = localStorage.getItem('rdnCredentials');
    if (savedCredentials) {
      try {
        const credentials = JSON.parse(savedCredentials);
        document.getElementById('username').value = credentials.username || '';
        document.getElementById('password').value = credentials.password || '';
        document.getElementById('securityCode').value = credentials.securityCode || '';
        document.getElementById('saveCredentials').checked = true;
      } catch (e) {
        console.error('Error loading saved credentials:', e);
      }
    }

    // Focus on username field
    document.getElementById('username').focus();
  });

  // Handle form submission
  document.getElementById('loginForm').addEventListener('submit', function(e) {
    e.preventDefault();

    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;
    const securityCode = document.getElementById('securityCode').value;
    const saveCredentials = document.getElementById('saveCredentials').checked;

    // Save credentials if checkbox is selected
    if (saveCredentials) {
      localStorage.setItem('rdnCredentials', JSON.stringify({
        username, password, securityCode
      }));
    } else {
      localStorage.removeItem('rdnCredentials');
    }

    // Disable form and show loading message
    document.getElementById('submitBtn').disabled = true;
    document.getElementById('submitBtn').innerHTML =
      '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Logging in...';

    const statusMessage = document.getElementById('statusMessage');
    statusMessage.className = 'mt-3 alert alert-info';
    statusMessage.style.display = 'block';
    statusMessage.textContent = 'Logging in to RDN. Please wait...';

    // Submit the form
    fetch('/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'  // Make sure Content-Type is set correctly
      },
      body: JSON.stringify({
        username, password, securityCode
      })
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        console.log("Login successful, redirecting to dashboard...");
        // Always redirect to dashboard directly, never to case-form
        const redirectUrl = '/dashboard';

        // Add a slight delay to ensure the message is seen
        setTimeout(() => {
          window.location.href = redirectUrl;
        }, 500);
      } else {
        statusMessage.className = 'mt-3 alert alert-danger';
        statusMessage.textContent = data.error || 'Login failed. Please check your credentials.';
        document.getElementById('submitBtn').disabled = false;
        document.getElementById('submitBtn').textContent = 'Login to RDN';
      }
    })
    .catch(error => {
      statusMessage.className = 'mt-3 alert alert-danger';
      statusMessage.textContent = 'Error: ' + error.message;
      document.getElementById('submitBtn').disabled = false;
      document.getElementById('submitBtn').textContent = 'Login to RDN';
    });
  });