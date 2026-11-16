// Logout confirmation dialog functionality
document.addEventListener('DOMContentLoaded', function() {
    // Get user button
    const userBtn = document.getElementById('userDropdown');
    
    if (userBtn) {
        // Remove Bootstrap dropdown data attributes to prevent default behavior
        userBtn.removeAttribute('data-bs-toggle');
        userBtn.removeAttribute('aria-expanded');
        
        // Create logout confirmation dialog
        const logoutDialog = document.createElement('div');
        logoutDialog.className = 'logout-dialog';
        logoutDialog.innerHTML = `
            <div class="logout-dialog-content">
                <div class="logout-icon">
                    <i class="fas fa-sign-out-alt"></i>
                </div>
                <h5 class="logout-title">Logout</h5>
                <p class="logout-message">Are you sure you want to logout?</p>
                <div class="logout-actions">
                    <button type="button" class="logout-cancel-btn">Cancel</button>
                    <a href="/users/logout/" class="logout-confirm-btn">Logout</a>
                </div>
            </div>
        `;
        
        // Append dialog to dropdown container
        userBtn.parentNode.appendChild(logoutDialog);
        
        // Toggle logout dialog on user button click
        userBtn.addEventListener('click', function(event) {
            event.preventDefault();
            event.stopPropagation();
            logoutDialog.classList.toggle('show');
        });
        
        // Close dialog when cancel button is clicked
        const cancelBtn = logoutDialog.querySelector('.logout-cancel-btn');
        if (cancelBtn) {
            cancelBtn.addEventListener('click', function() {
                logoutDialog.classList.remove('show');
            });
        }
        
        // Add event listener to the logout button to clear any session storage
        const logoutBtn = logoutDialog.querySelector('.logout-confirm-btn');
        if (logoutBtn) {
            logoutBtn.addEventListener('click', function() {
                // Set a flag to indicate this is a fresh logout
                localStorage.setItem('freshLogout', 'true');
            });
        }
        
        // Close dialog when clicking outside
        document.addEventListener('click', function(event) {
            if (!userBtn.contains(event.target) && !logoutDialog.contains(event.target)) {
                logoutDialog.classList.remove('show');
            }
        });
    }
});