const subjectMap = {
    "semester_1": ["Physics Dummy", "Maths Dummy", "Chemistry Dummy"],
    "semester_2": ["BEE Dummy", "Mechanics Dummy", "Graphics Dummy"],
    "semester_3": ["Maths", "DBMS", "DS", "COA", "DSGT"],
    "semester_4": ["Maths", "AOA", "CTD", "MDM", "OS"],
    "semester_5": ["TCS Dummy", "SE Dummy", "CN Dummy"],
    "semester_6": ["SPCC Dummy", "CSS Dummy", "AI Dummy"],
    "semester_7": ["DSIP Dummy", "MCC Dummy"],
    "semester_8": ["HMI Dummy", "DC Dummy"]
};

document.addEventListener("DOMContentLoaded", () => {
    // Always dark mode
    document.documentElement.removeAttribute('data-theme');
    const themeBtn = document.getElementById('themeToggleBtn');
    if (themeBtn) themeBtn.style.display = 'none';

    const savedSidebar = localStorage.getItem('sidebar-state');
    if (savedSidebar === 'collapsed') {
        const sidebar = document.getElementById('mainSidebar');
        if (sidebar) sidebar.classList.add('collapsed');
    }

    // Initialize Dashboard Features
    renderHeatmap();
    animateChart();
    
    // Auto-populate logic for all views
    initLibrary();
    initMockTest();

    // Subject Population logic
    const semesterSelect = document.getElementById("semester");
    const subjectSelect = document.getElementById("subject");

    function populateSubjects() {
        if (!semesterSelect || !subjectSelect) return;
        const selectedSem = semesterSelect.value;
        const subjects = subjectMap[selectedSem] || ["Dummy Subject"];
        
        subjectSelect.innerHTML = "";
        subjects.forEach(sub => {
            const opt = document.createElement("option");
            opt.value = sub; 
            opt.textContent = sub;
            subjectSelect.appendChild(opt);
        });
    }

    if (semesterSelect) {
        semesterSelect.addEventListener("change", populateSubjects);
        populateSubjects();
    }
});

function switchView(viewId) {
    // Update Views
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.getElementById(viewId).classList.add('active');

    // Update Sidebar
    document.querySelectorAll('.nav-item').forEach(btn => {
        btn.classList.remove('active');
        if (btn.getAttribute('onclick').includes(viewId)) {
            btn.classList.add('active');
        }
    });

    // Update Title
    const titleMap = {
        'dashboard-view':   'Dashboard Overview',
        'pyq-view':         'PYQ Predictor',
        'books-view':       'Reference Books',
        'mock-test-view':   'Mock Test',
        'tabulator-view':   'Marks Tabulator',
        'submissions-view': 'Student Submissions'
    };
    document.getElementById('activeViewTitle').innerText = titleMap[viewId] || 'AcadeX';

    if (viewId === 'books-view') loadLibrary();
    if (viewId === 'mock-test-view') initMockTest();
    if (viewId === 'submissions-view') loadSubmissions();
}

// --- Sidebar Logic ---
function toggleSidebar() {
    const sidebar = document.getElementById('mainSidebar');
    sidebar.classList.toggle('collapsed');
    const state = sidebar.classList.contains('collapsed') ? 'collapsed' : 'expanded';
    localStorage.setItem('sidebar-state', state);
}

// --- Library Logic ---

function initLibrary() {
    const libSem = document.getElementById("libSemester");
    if (libSem) {
        populateLibrarySubjects();
        libSem.addEventListener("change", populateLibrarySubjects);
    }
}

function populateLibrarySubjects() {
    const sem = document.getElementById("libSemester").value;
    const subSelect = document.getElementById("libSubject");
    if (!subSelect) return;

    const subjects = subjectMap[sem] || [];
    subSelect.innerHTML = "";
    subjects.forEach(sub => {
        const opt = document.createElement("option");
        opt.value = sub;
        opt.textContent = sub;
        subSelect.appendChild(opt);
    });
    loadLibrary(); // Load books for the first subject
}

async function loadLibrary() {
    const sem = document.getElementById("libSemester").value;
    const sub = document.getElementById("libSubject").value;
    const shelf = document.getElementById("booksShelf");
    if (!shelf) return;

    shelf.innerHTML = '<div class="loader-small"></div>';

    try {
        const response = await fetch(`/api/books?semester=${sem}&subject=${sub}`);
        const books = await response.json();

        if (books.length === 0) {
            shelf.innerHTML = '<p class="msg-empty">No reference books listed for this subject yet.</p>';
            return;
        }

        shelf.innerHTML = books.map((book) => `
            <div class="book-card fade-in" onclick="openBook('${book.url}')" data-book-id="${book.id}">
                <div class="book-info">
                    <div class="book-title">${book.title}</div>
                    <div class="book-author">by ${book.author}</div>
                </div>
                <div class="book-badge">PDF</div>
                <!-- Delete Button (uses book.id — safe against race conditions) -->
                ${document.querySelector('.btn-add-small') ? `
                    <button class="btn-delete-book" onclick="event.stopPropagation(); deleteBook(${book.id})" title="Delete Book">×</button>
                ` : ''}
            </div>
        `).join("");

    } catch (e) {
        shelf.innerHTML = '<p>Error loading books.</p>';
    }
}

function openBook(url) {
    if (!url) {
        alert("No PDF available for this book.");
        return;
    }
    window.open(url, '_blank');
}

async function addBook() {
    const sem = document.getElementById("libSemester").value;
    const sub = document.getElementById("libSubject").value;
    const title = document.getElementById("newBookTitle").value;
    const author = document.getElementById("newBookAuthor").value;
    const file = document.getElementById("newBookFile").files[0];

    if (!title || !author || !file) {
        alert("Please fill in all fields and select a PDF file.");
        return;
    }

    const formData = new FormData();
    formData.append("semester", sem);
    formData.append("subject", sub);
    formData.append("title", title);
    formData.append("author", author);
    formData.append("book_file", file);

    try {
        const response = await fetch('/api/books/add', {
            method: 'POST',
            body: formData
        });
        const result = await response.json();
        
        if (result.success) {
            document.getElementById("newBookTitle").value = "";
            document.getElementById("newBookAuthor").value = "";
            document.getElementById("newBookFile").value = "";
            document.getElementById("addBookForm").classList.add("hidden");
            loadLibrary();
        } else {
            alert(result.error || "Failed to add book.");
        }
    } catch (e) {
        alert("Error connecting to server.");
    }
}

async function deleteBook(bookId) {
    if (!confirm("Are you sure you want to delete this book?")) return;

    try {
        const response = await fetch('/api/books/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            // Send the DB primary key — stable across concurrent requests
            body: JSON.stringify({ book_id: bookId })
        });
        const result = await response.json();

        if (result.success) {
            loadLibrary();
        } else {
            alert(result.error);
        }
    } catch (e) {
        alert("Error connecting to server.");
    }
}

// --- Mock Test Logic ---

function initMockTest() {
    const mockSem = document.getElementById("mockSemester");
    if (mockSem) {
        populateMockSubjects();
        mockSem.addEventListener("change", populateMockSubjects);
    }
}

function populateMockSubjects() {
    const sem = document.getElementById("mockSemester").value;
    const subSelect = document.getElementById("mockSubject");
    if (!subSelect) return;

    const subjects = subjectMap[sem] || [];
    subSelect.innerHTML = "";
    subjects.forEach(sub => {
        const opt = document.createElement("option");
        opt.value = sub;
        opt.textContent = sub;
        subSelect.appendChild(opt);
    });
}

async function generateMockTest() {
    const sub = document.getElementById("mockSubject").value;
    const paperArea = document.getElementById("mockPaperArea");
    const questionsList = document.getElementById("mockQuestionsList");
    const displaySub = document.getElementById("displaySub");
    const uploadPanel = document.getElementById("answerUploadPanel");

    try {
        const response = await fetch(`/api/static_mock_test?subject=${sub}`);
        const questions = await response.json();

        displaySub.innerText = `Subject: ${sub}`;
        questionsList.innerHTML = questions.map((q, i) => `
            <div class="paper-question">
                <span class="q-num">Q${i+1}.</span>
                <span class="q-text">${q}</span>
            </div>
        `).join("");

        paperArea.classList.remove("hidden");
        uploadPanel.classList.remove("hidden");
        // Scroll to paper
        paperArea.scrollIntoView({ behavior: 'smooth' });

    } catch (e) {
        alert("Error generating mock test.");
    }
}

async function submitTestAnswers() {
    const sub  = document.getElementById("mockSubject").value;
    const sem  = document.getElementById("mockSemester").value;
    const file = document.getElementById("answerFile").files[0];

    if (!file) {
        alert("Please attach your answer file before submitting.");
        return;
    }

    const formData = new FormData();
    formData.append("semester", sem);
    formData.append("subject", sub);
    formData.append("answer_file", file);

    try {
        const response = await fetch("/api/submit_test", {
            method: "POST",
            body: formData
        });
        const result = await response.json();

        if (result.success) {
            // ✅ Reset the view completely — student sees no history
            document.getElementById("mockPaperArea").classList.add("hidden");
            document.getElementById("answerUploadPanel").classList.add("hidden");
            document.getElementById("answerFile").value = "";
            document.getElementById("mockQuestionsList").innerHTML = "";

            // Show a short success toast
            const toast = document.createElement("div");
            toast.style.cssText = `
                position: fixed; bottom: 30px; right: 30px; z-index: 9999;
                background: #16A34A; color: white; padding: 16px 24px;
                border-radius: 14px; font-weight: 600; font-size: 0.95rem;
                box-shadow: 0 8px 24px rgba(22,163,74,0.3);
                animation: slideUpFade 0.4s ease;
            `;
            toast.innerText = "✅ Answers submitted successfully!";
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), 3000);
        } else {
            alert(result.error || "Failed to submit.");
        }
    } catch (e) {
        alert("Error submitting answers.");
    }
}

async function loadSubmissions() {
    const container = document.getElementById("submissionsTable");
    if (!container) return;

    container.innerHTML = '<p style="color: var(--text-muted); padding: 20px;">Loading submissions...</p>';

    try {
        const response = await fetch("/api/submissions");
        const submissions = await response.json();

        if (!submissions.length) {
            container.innerHTML = `
                <div class="empty-state">
                    📭 No submissions yet. Students will appear here after submitting their tests.
                </div>`;
            return;
        }

        container.innerHTML = `
            <table class="submissions-table">
                <thead>
                    <tr>
                        <th>Student</th>
                        <th>Subject</th>
                        <th>Semester</th>
                        <th>Submitted At</th>
                        <th>Answer File</th>
                    </tr>
                </thead>
                <tbody>
                    ${submissions.map(s => `
                        <tr>
                            <td><strong>${s.student}</strong></td>
                            <td><span class="sub-badge">${s.subject}</span></td>
                            <td>${s.semester.replace('_', ' ')}</td>
                            <td>${s.submitted_at}</td>
                            <td>
                                <a class="btn-download" href="/api/submissions/download/${s.filename}" download>
                                    ⬇ Download
                                </a>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>`;
    } catch (e) {
        container.innerHTML = '<p style="color: darkred; padding: 20px;">Error loading submissions.</p>';
    }
}

function renderHeatmap() {
    const container = document.getElementById('consistencyHeatmap');
    if (!container) return;

    container.innerHTML = '';
    // Generate 60 mock days (roughly 2 months)
    for (let i = 0; i < 60; i++) {
        const intensity = Math.floor(Math.random() * 4); // 0 to 3
        const cell = document.createElement('div');
        cell.className = 'heatmap-cell';
        cell.style.backgroundColor = `var(--heatmap-${intensity})`;
        cell.title = `Activity Level: ${intensity}`;
        container.appendChild(cell);
    }
}

function animateChart() {
    const path = document.querySelector('.chart-line');
    if (!path) return;
    
    // Simple drawing animation
    const length = path.getTotalLength();
    path.style.strokeDasharray = length;
    path.style.strokeDashoffset = length;
    
    setTimeout(() => {
        path.style.transition = 'stroke-dashoffset 2s ease-in-out';
        path.style.strokeDashoffset = '0';
    }, 500);
}

function toggleTheme() { /* dark mode always on */ }
function updateThemeIcon(theme) { /* no-op */ }

async function analyzePYQ() {
    const semester = document.getElementById("semester").value;
    const subject = document.getElementById("subject").value;
    const syllabusFile = document.getElementById("syllabusFile").files[0];
    const btn = document.getElementById("analyzeBtn");

    if (!subject.trim()) {
        alert("Please enter a subject name.");
        return;
    }

    if (!syllabusFile) {
        alert("Please upload your syllabus file.");
        return;
    }

    try {
        btn.classList.add("loading");
        btn.disabled = true;
        const btnText = btn.querySelector('.btn-text');
        const originalText = btnText.innerText;
        btnText.innerText = "Analyzing...";
        
        let formData = new FormData();
        formData.append("semester", semester);
        formData.append("subject", subject);
        formData.append("syllabus", syllabusFile);

        let analyzeResponse = await fetch("/analyze_semester", {
            method: "POST",
            body: formData
        });

        let result = await analyzeResponse.json();

        if (result.error) {
            document.getElementById("result").innerHTML = `<p>${result.error}</p>`;
            return;
        }

        let output = result.top_questions.map(r =>
            `<div class="result-card">
               <p><b>Topic:</b> ${r.topic}</p>
               <p><b>Repeated:</b> ${r.frequency} time${r.frequency > 1 ? 's' : ''}</p>
               <p style="margin-top: 10px;">${r.question}</p>
             </div>`
        ).join("");

        if (!output) {
            output = "<p>No matching questions found.</p>";
        }

        document.getElementById("result").innerHTML = output;
    } catch (e) {
        document.getElementById("result").innerHTML = `<p>Something went wrong: ${e.message}</p>`;
    } finally {
        btn.classList.remove("loading");
        btn.disabled = false;
        const btnText = btn.querySelector('.btn-text');
        btnText.innerText = "✨ Predict Questions";
    }
}


async function scanImage() {
    const fileInput = document.getElementById("imageFile");
    const btn = document.getElementById("scanBtn");

    if (!fileInput.files[0]) {
        alert("Please upload an image first.");
        return;
    }

    try {
        btn.classList.add("loading");
        btn.disabled = true;
        const btnText = btn.querySelector('.btn-text');
        const originalText = btnText.innerText;
        btnText.innerText = "Extracting...";

        let formData = new FormData();
        formData.append("image", fileInput.files[0]);

        let response = await fetch("/extract_image", {
            method: "POST",
            body: formData
        });

        let data = await response.json();

        if (data.error) {
            document.getElementById("ocrResult").innerHTML = `<p style="color: darkred;">Error: ${data.error}</p>`;
            return;
        }

        const extracted = data.extracted_data;
        let tableHtml = `<table style="width:100%; border-collapse: collapse; margin-top: 10px;">
                            <tr style="border-bottom: 2px solid var(--input-border); text-align: left;">
                                <th style="padding: 8px;">Section / Question</th>
                                <th style="padding: 8px;">Marks Obtained</th>
                            </tr>`;
                            
        for (const [key, value] of Object.entries(extracted)) {
            tableHtml += `<tr style="border-bottom: 1px solid var(--input-border);">
                            <td style="padding: 8px; font-weight: 500; color: var(--text-heading);">${key}</td>
                            <td style="padding: 8px;">${value}</td>
                          </tr>`;
        }
        tableHtml += `</table>
                      <div style="margin-top: 15px; padding: 10px; border-radius: 8px; background: rgba(22, 163, 74, 0.1); border: 1px solid var(--accent);">
                        <p style="margin: 0; font-weight: 600; color: var(--accent); text-align: center;">✅ Appended to Excel Successfully</p>
                      </div>`;

        document.getElementById("ocrResult").innerHTML = tableHtml;

    } catch (e) {
        document.getElementById("ocrResult").innerHTML = `<p style="color: darkred;">Failed to scan image. Please try again or check API keys.</p>`;
    } finally {
        btn.classList.remove("loading");
        btn.disabled = false;
        const btnText = btn.querySelector('.btn-text');
        btnText.innerText = "📝 Extract to Excel";
        fileInput.value = ""; // Reset file loader
    }
}