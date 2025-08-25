// Debounce function for search
function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

// Initialize SocketIO
const socket = io({
  reconnectionAttempts: 5,
  reconnectionDelay: 1000
});

// SocketIO connection status
socket.on('connect', () => {
  console.log('SocketIO connected');
  const status = document.getElementById('connection-status');
  if (status) {
    status.innerHTML = '<small class="text-success">Connected to server</small>';
  }
});

socket.on('connect_error', (error) => {
  console.error('SocketIO connection error:', error);
  const status = document.getElementById('connection-status');
  if (status) {
    status.innerHTML = '<small class="text-danger">Connection failed</small>';
  }
});

// Toggle sidebar
function toggleSidebar() {
  const sidebar = document.querySelector('.sidebar');
  sidebar.classList.toggle('active');
}

// Search users
function initSearch() {
  const searchInput = document.getElementById('search-user');
  if (searchInput) {
    searchInput.addEventListener('input', debounce(function() {
      const query = this.value;
      fetch('/search_users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: 'query=' + encodeURIComponent(query)
      })
      .then(response => {
        if (!response.ok) throw new Error('Search failed');
        return response.json();
      })
      .then(data => {
        const results = document.getElementById('search-results');
        results.innerHTML = data.map(user => `
          <div class="list-group-item d-flex align-items-center animate__animated animate__fadeIn">
            <img src="${user.avatar}" alt="Avatar" class="avatar" />
            <div>
              <strong>${user.username}</strong><br>
              <small>${user.status}</small><br>
              <small>Terakhir: ${user.last_seen}</small>
            </div>
            <div class="ms-auto">
              <button onclick="addFriend('${user.username}')" class="btn btn-success btn-sm">Tambah Teman</button>
              <a href="/private/${user.username}" class="btn btn-primary btn-sm"><i class="fas fa-comment"></i> Chat</a>
            </div>
          </div>
        `).join('');
      })
      .catch(error => {
        console.error('Error searching users:', error);
        document.getElementById('search-results').innerHTML = '<p>Error loading users</p>';
      });
    }, 300));
  }
}

// Add friend
function addFriend(username) {
  fetch(`/add_friend/${username}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      showToast('Teman berhasil ditambahkan!');
      location.reload();
    } else {
      showToast(data.error, 'danger');
    }
  })
  .catch(error => {
    console.error('Error adding friend:', error);
    showToast('Gagal menambah teman', 'danger');
  });
}

// Show toast notification
function showToast(message, type = 'primary') {
  const toastContainer = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast align-items-center text-white bg-${type} border-0`;
  toast.setAttribute('role', 'alert');
  toast.setAttribute('aria-live', 'assertive');
  toast.setAttribute('aria-atomic', 'true');
  toast.innerHTML = `
    <div class="d-flex">
      <div class="toast-body">${message}</div>
      <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
    </div>
  `;
  toastContainer.appendChild(toast);
  const bsToast = new bootstrap.Toast(toast);
  bsToast.show();
  setTimeout(() => toast.remove(), 5000);
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
  initSearch();
  const toastContainer = document.createElement('div');
  toastContainer.id = 'toast-container';
  toastContainer.style.position = 'fixed';
  toastContainer.style.top = '80px';
  toastContainer.style.right = '10px';
  toastContainer.style.zIndex = '2000';
  document.body.appendChild(toastContainer);

  socket.on('notification', (data) => {
    showToast(data.message);
  });
});