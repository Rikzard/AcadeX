document.addEventListener("DOMContentLoaded", () => {
    const savedTheme = localStorage.getItem('theme');
    const systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    
    let currentTheme = savedTheme;
    if (!currentTheme) {
        currentTheme = systemDark ? 'dark' : 'light';
    }
    
    document.documentElement.setAttribute('data-theme', currentTheme);
    updateThemeIcon(currentTheme);
});

function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
    
    updateThemeIcon(newTheme);
}

function updateThemeIcon(theme) {
    const btn = document.getElementById('themeToggleBtn');
    if (btn) {
        btn.innerText = theme === 'dark' ? '☀️' : '🌙'; // If dark, show sun to toggle light. If light, show moon.
    }
}

async function analyzePYQ() {
    const semester = document.getElementById("semester").value;
    const syllabus = document.getElementById("syllabus").value;
    const btn = document.getElementById("analyzeBtn");

    if (!syllabus.trim()) {
        alert("Please enter syllabus topics.");
        return;
    }

    try {
        btn.classList.add("loading");
        btn.disabled = true;
        
        let analyzeResponse = await fetch("/analyze_semester", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                semester: semester,
                syllabus: syllabus
            })
        });

        let result = await analyzeResponse.json();

        if (result.error) {
            document.getElementById("result").innerHTML = `<p>${result.error}</p>`;
            return;
        }

        let output = result.top_questions.map(r =>
            `<p><b>Topic:</b> ${r.topic} <br>
             <b>Relevance Score:</b> ${r.score} (Found ${r.frequency} time${r.frequency > 1 ? 's' : ''})<br>
             ${r.question}</p>`
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

        let formData = new FormData();
        formData.append("image", fileInput.files[0]);

        let response = await fetch("/extract_image", {
            method: "POST",
            body: formData
        });

        let data = await response.json();

        document.getElementById("ocrResult").innerText = data.text;
    } catch (e) {
        document.getElementById("ocrResult").innerText = "Failed to scan image. Please try again.";
    } finally {
        btn.classList.remove("loading");
        btn.disabled = false;
    }
}