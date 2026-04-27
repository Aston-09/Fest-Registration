document.addEventListener('DOMContentLoaded', () => {
    // Set dynamic dates
    const dateEl = document.getElementById('current-date');
    if (dateEl) {
        const options = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
        dateEl.textContent = new Date().toLocaleDateString('en-US', options).toUpperCase();
    }
    
    const yearEl = document.getElementById('year');
    if (yearEl) {
        yearEl.textContent = new Date().getFullYear();
    }

    // --- Parallax Engine (60fps optimized) ---
    const parallaxElements = document.querySelectorAll('[data-parallax]');
    let ticking = false;

    // Cache speed values to avoid repeated DOM reads
    const parallaxData = Array.from(parallaxElements).map(el => ({
        el,
        speed: parseFloat(el.getAttribute('data-parallax-speed')) || 0
    }));

    // Hint the GPU to promote these layers
    parallaxData.forEach(({ el }) => {
        el.style.willChange = 'transform';
    });

    function updateParallax() {
        const scrollY = window.scrollY;
        for (let i = 0; i < parallaxData.length; i++) {
            // translate3d forces GPU compositing — no layout/paint
            parallaxData[i].el.style.transform = `translate3d(0, ${scrollY * parallaxData[i].speed}px, 0)`;
        }
        ticking = false;
    }

    window.addEventListener('scroll', () => {
        if (!ticking) {
            ticking = true;
            requestAnimationFrame(updateParallax);
        }
    }, { passive: true });

    // --- Page Routing Logic ---
    const path = window.location.pathname;

    if (path === '/' || path === '/index.html') {
        loadHomeData();
    } else if (path.includes('participants')) {
        setupForm('participant-form', '/participants');
        setupGroupForm();
    } else if (path.includes('events')) {
        loadEvents();
        setupForm('event-form', '/events');
        setupForm('register-event-form', '/register-event');
    } else if (path.includes('registrations')) {
        loadRegistrations();
    }
});

// --- Data Fetching Functions ---

async function loadHomeData() {
    try {
        const [partRes, evRes, regRes] = await Promise.all([
            fetch('/participants'),
            fetch('/events'),
            fetch('/registrations')
        ]);
        
        const partData = await partRes.json();
        const evData = await evRes.json();
        const regData = await regRes.json();
        
        document.getElementById('stat-participants').textContent = partData.participants ? partData.participants.length : 0;
        document.getElementById('stat-events').textContent = evData.events ? evData.events.length : 0;
        document.getElementById('stat-registrations').textContent = regData.registrations ? regData.registrations.length : 0;

        // Populate recent events (max 4)
        const eventsContainer = document.getElementById('recent-events-container');
        if (eventsContainer && evData.events) {
            eventsContainer.innerHTML = '';
            const recent = evData.events.slice(-4);
            recent.forEach((ev, index) => {
                const isNew = index === recent.length - 1; // Mark the very last one as NEW
                eventsContainer.innerHTML += `
                    <div class="event-card">
                        ${isNew ? '<span class="badge-new">NEW</span>' : ''}
                        <span class="event-category">${ev.category} • ${ev.type}</span>
                        <h4 class="event-title">${ev.event_name}</h4>
                        <div class="event-details">
                            <p><strong>Fee:</strong> ₹${ev.registration_fee}</p>
                            <p><strong>Prize:</strong> ₹${ev.prize_pool}</p>
                        </div>
                    </div>
                `;
            });
        }
    } catch (err) {
        console.error("Error fetching home data:", err);
    }
}

async function loadEvents() {
    const container = document.getElementById('events-container');
    if (!container) return;

    try {
        const res = await fetch('/events');
        const data = await res.json();
        
        container.innerHTML = '';
        if (data.events && data.events.length > 0) {
            data.events.forEach((ev, idx) => {
                container.innerHTML += `
                    <div class="event-card">
                        ${idx === data.events.length - 1 ? '<span class="badge-new">NEW</span>' : ''}
                        <span class="event-category">${ev.category} • ${ev.type}</span>
                        <h4 class="event-title">${ev.event_name}</h4>
                        <div class="event-details">
                            <p style="background: #e2e8f0; padding: 4px 8px; border-radius: 4px; display: inline-block; margin-bottom: 0.5rem; color: #1e293b;"><strong>Event ID: ${ev.event_id}</strong></p>
                            <p><strong>Fee:</strong> ₹${ev.registration_fee}</p>
                            <p><strong>Prize:</strong> ₹${ev.prize_pool}</p>
                        </div>
                    </div>
                `;
            });
        } else {
            container.innerHTML = '<p>No events scheduled at this time.</p>';
        }
    } catch (err) {
        container.innerHTML = '<p>Error fetching the schedule.</p>';
    }
}

async function loadRegistrations() {
    const tableBody = document.querySelector('#registrations-table tbody');
    if (!tableBody) return;

    try {
        const res = await fetch('/registrations');
        const data = await res.json();
        
        tableBody.innerHTML = '';
        if (data.registrations && data.registrations.length > 0) {
            data.registrations.forEach(r => {
                const statusClass = r.payment_status.toLowerCase() === 'paid' ? 'status-paid' : 'status-pending';
                // Handle different date formats coming from backend
                const regDate = r.reg_date ? new Date(r.reg_date).toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric'}) : 'Unknown';
                
                tableBody.innerHTML += `
                    <tr>
                        <td><strong>${r.name}</strong></td>
                        <td>${r.event_name}</td>
                        <td>${regDate}</td>
                        <td class="${statusClass}">${r.payment_status}</td>
                    </tr>
                `;
            });
        } else {
            tableBody.innerHTML = '<tr><td colspan="4">No enrollments recorded yet.</td></tr>';
        }
    } catch (err) {
        tableBody.innerHTML = '<tr><td colspan="4">Error examining the ledger.</td></tr>';
    }
}





// ==============================
// Registration Page Logic
// ==============================

let groupMemberCount = 1;

// Toggle between single and group registration
function switchRegType(type) {
    const singleContainer = document.getElementById('single-form-container');
    const groupContainer = document.getElementById('group-form-container');
    const btnSingle = document.getElementById('btn-single');
    const btnGroup = document.getElementById('btn-group');

    if (!singleContainer || !groupContainer) return;

    if (type === 'single') {
        singleContainer.classList.remove('hidden');
        groupContainer.classList.add('hidden');
        btnSingle.classList.add('active');
        btnGroup.classList.remove('active');
    } else {
        singleContainer.classList.add('hidden');
        groupContainer.classList.remove('hidden');
        btnSingle.classList.remove('active');
        btnGroup.classList.add('active');
    }
}

// Make switchRegType global
window.switchRegType = switchRegType;

// Add a new group member card
function addGroupMember() {
    groupMemberCount++;
    const idx = groupMemberCount;

    const card = document.createElement('div');
    card.className = 'group-member-card';
    card.setAttribute('data-index', idx);
    card.innerHTML = `
        <div class="member-card-header">
            <span class="member-number">Member #${idx}</span>
            <button type="button" class="btn-remove-member" onclick="removeGroupMember(this)">✕ Remove</button>
        </div>
        <div class="reg-form-grid">
            <div class="form-group">
                <label>Full Name</label>
                <input type="text" name="g_name_${idx}" placeholder="Full Name" required>
            </div>
            <div class="form-group">
                <label>College</label>
                <input type="text" name="g_college_${idx}" placeholder="College" required>
            </div>
            <div class="form-group">
                <label>Department</label>
                <input type="text" name="g_department_${idx}" placeholder="Department" required>
            </div>
            <div class="form-row">
                <div class="form-group half">
                    <label>Year</label>
                    <input type="number" name="g_year_${idx}" min="1" max="5" placeholder="1-5" required>
                </div>
                <div class="form-group half">
                    <label>Telephone</label>
                    <input type="tel" name="g_phone_${idx}" placeholder="+91..." required>
                </div>
            </div>
            <div class="form-group">
                <label>Electronic Mail</label>
                <input type="email" name="g_email_${idx}" placeholder="email@mail.com" required>
            </div>
        </div>
    `;

    document.getElementById('group-members-list').appendChild(card);
    updateMemberCount();

    // Smooth scroll to new card
    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

window.addGroupMember = addGroupMember;

// Remove a group member card
function removeGroupMember(btn) {
    const card = btn.closest('.group-member-card');
    card.style.opacity = '0';
    card.style.transform = 'scale(0.95)';
    setTimeout(() => {
        card.remove();
        updateMemberCount();
    }, 250);
}

window.removeGroupMember = removeGroupMember;

function updateMemberCount() {
    const count = document.querySelectorAll('.group-member-card').length;
    const el = document.getElementById('member-count');
    if (el) el.textContent = count;
}

// Setup group form submission
function setupGroupForm() {
    const form = document.getElementById('group-form');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const msgBox = document.getElementById('group-msg');
        msgBox.textContent = 'Dispatching telegraph for the group...';
        msgBox.className = 'form-message';

        const cards = document.querySelectorAll('.group-member-card');
        const members = [];

        cards.forEach(card => {
            const idx = card.getAttribute('data-index');
            const name = card.querySelector(`[name="g_name_${idx}"]`).value;
            const college = card.querySelector(`[name="g_college_${idx}"]`).value;
            const department = card.querySelector(`[name="g_department_${idx}"]`).value;
            const year = parseInt(card.querySelector(`[name="g_year_${idx}"]`).value);
            const phone = card.querySelector(`[name="g_phone_${idx}"]`).value;
            const email = card.querySelector(`[name="g_email_${idx}"]`).value;

            members.push({ name, college, department, year, email, phone });
        });

        try {
            const res = await fetch('/participants/group', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ members })
            });

            const result = await res.json();

            if (res.ok) {
                msgBox.innerHTML = (result.message || 'Group registered!').replace(
                    /(\d{6})/g, 
                    `<span style="background: #1e293b; color: #fff; padding: 4px 8px; border-radius: 4px; font-size: 1.2em; letter-spacing: 2px; margin: 0 5px;">$1</span>`
                );
                msgBox.classList.add('success');
                form.reset();
                // Reset to single member
                const list = document.getElementById('group-members-list');
                const firstCard = list.querySelector('.group-member-card');
                list.innerHTML = '';
                list.appendChild(firstCard);
                groupMemberCount = 1;
                updateMemberCount();
            } else {
                msgBox.textContent = result.message || 'An error occurred.';
                msgBox.classList.add('error');
            }
        } catch (err) {
            msgBox.textContent = 'Failed to communicate with the server.';
            msgBox.classList.add('error');
        }
    });
}


// --- Form Handling ---

function setupForm(formId, endpoint) {
    const form = document.getElementById(formId);
    if (!form) return;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const msgBox = form.nextElementSibling; // Assuming div.form-message is right after form
        msgBox.textContent = 'Dispatching telegraph...';
        msgBox.className = 'form-message';
        
        const formData = new FormData(form);
        const params = new URLSearchParams();
        for (const [key, value] of formData.entries()) {
            params.append(key, value);
        }
        
        try {
            // FastAPI endpoints expect query parameters
            const res = await fetch(`${endpoint}?${params.toString()}`, {
                method: 'POST'
            });
            
            const result = await res.json();
            
            if (res.ok) {
                if (result.participant_id) {
                    msgBox.innerHTML = result.message.replace(
                        result.participant_id, 
                        `<span style="background: #1e293b; color: #fff; padding: 4px 8px; border-radius: 4px; font-size: 1.2em; letter-spacing: 2px; margin: 0 5px;">${result.participant_id}</span>`
                    );
                } else {
                    msgBox.textContent = result.message || 'Success!';
                }
                msgBox.classList.add('success');
                form.reset();
                
                // Reload data dynamically
                if (endpoint === '/events') loadEvents();
                if (endpoint === '/register-event') {
                    // Nothing needed since it just registers
                }
            } else {
                msgBox.textContent = result.message || 'An error occurred.';
                msgBox.classList.add('error');
            }
        } catch (err) {
            msgBox.textContent = 'Failed to communicate with the server.';
            msgBox.classList.add('error');
        }
    });
}
