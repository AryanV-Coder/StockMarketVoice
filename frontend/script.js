const API_BASE_URL = process.env.SERVER_URL || 'http://127.0.0.1:8000';

// Tab switching logic
function switchTab(tabId) {
    // Update buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.getAttribute('onclick').includes(tabId)) {
            btn.classList.add('active');
        }
    });

    // Update content
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.remove('active');
    });
    document.getElementById(tabId).classList.add('active');
}

// Toast notification logic
function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `toast show ${type}`;
    
    setTimeout(() => {
        toast.className = 'toast';
    }, 3000);
}

// Handle Orchestrate All Calls
document.getElementById('trigger-all-btn').addEventListener('click', async (e) => {
    const btn = e.target;
    btn.disabled = true;
    btn.textContent = 'Initiating...';

    try {
        const response = await fetch(`${API_BASE_URL}/orchestrate-calls`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const data = await response.json();
        
        if (data.status === 'success') {
            showToast('Automation triggered successfully!', 'success');
        } else {
            showToast(data.message || 'Error occurred', 'error');
        }
    } catch (error) {
        showToast('Failed to connect to server', 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Trigger All Calls';
    }
});

// Handle Single Call Test
document.getElementById('trigger-single-btn').addEventListener('click', async (e) => {
    const phone = document.getElementById('phone').value.trim();
    const clientName = document.getElementById('client_name').value.trim();

    if (!phone || !clientName) {
        showToast('Please fill all fields', 'error');
        return;
    }

    const btn = e.target;
    btn.disabled = true;
    btn.textContent = 'Calling...';

    try {
        const response = await fetch(`${API_BASE_URL}/test-single-call`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                phone_number: phone,
                client_name: clientName
            })
        });
        
        const data = await response.json();
        
        if (response.ok && data.status === 'success') {
            showToast(`Call initiated! SID: ${data.call_sid.substring(0, 8)}...`, 'success');
            // Clear inputs on success
            document.getElementById('phone').value = '';
            document.getElementById('client_name').value = '';
        } else {
            showToast(data.detail || data.message || 'Error occurred', 'error');
        }
    } catch (error) {
        showToast('Failed to connect to server', 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Initiate Call';
    }
});
